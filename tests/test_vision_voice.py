"""개인정보 찾기·가림, 사진 보정, 음성 문장 검증 (모델 없이)."""
import os
import sys
from pathlib import Path

import numpy as np
import pytest
from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import vision  # noqa: E402
from voice import build_script, number_to_korean  # noqa: E402


# ---------- 개인정보 번호 판별 ----------

@pytest.mark.parametrize("text, kind", [
    ("주민등록번호 900101-1234567", "주민등록번호"),
    ("주민번호900101 2234567", "주민등록번호"),
    ("9001011234567", "주민등록번호"),
    ("연락처 010-1234-5678", "전화번호"),
    ("연락처 070-1234-5678", "전화번호"),     # OCR이 010을 070으로 읽는 경우
    ("O1O-1234-5678", "전화번호"),             # 0을 O로 읽은 경우
    ("가상계좌 123-456789-01-234 (농협)", "계좌번호"),
    ("계좌 110123456789", "계좌번호"),
    ("납부금액 130,000원", None),
    ("1,234,567,890원", None),
    ("문의 02-3153-8000", None),
    ("콜센터 1588-1234", None),
    ("031-123-4567", None),
    ("납부기한 2026. 11. 30.", None),
    ("과세번호 2026-11", None),
])
def test_classify_pii(text, kind):
    hit = vision.classify_pii(text)
    assert (hit[0] if hit else None) == kind


def _box(x0, y0, x1, y1):
    return [[x0, y0], [x1, y0], [x1, y1], [x0, y1]]


def test_find_pii_boxes_hides_values_not_labels():
    ocr = [
        (_box(40, 30, 400, 70), "자동차세 고지서", 0.9),
        (_box(40, 90, 220, 130), "성명: 홍길동", 0.9),
        (_box(40, 150, 480, 190), "주민등록번호 900101-1234567", 0.9),
        (_box(40, 210, 330, 250), "납부금액 130,000원", 0.9),
        (_box(40, 270, 120, 310), "주소", 0.9),                      # 라벨만 있는 상자
        (_box(140, 270, 700, 310), "서울특별시 마포구 월드컵로 212", 0.9),  # 오른쪽 값 상자
        (_box(40, 330, 160, 370), "홍길동", 0.9),
        (_box(170, 330, 240, 370), "귀하", 0.9),
        (_box(40, 390, 440, 430), "문의 마포구청 02-3153-8000", 0.9),
    ]
    boxes = vision.find_pii_boxes(ocr, width=1000)
    kinds = sorted(b["kind"] for b in boxes)
    assert kinds == sorted(["이름·주소·연락처", "주민등록번호", "이름·주소·연락처", "이름·주소·연락처"])
    by_row = {round(b["box"][1]): b["box"] for b in boxes}
    # 성명 줄: 라벨('성명:')은 남기고 이름 부분만 → 상자 왼쪽 끝보다 오른쪽에서 시작
    assert by_row[90][0] > 40 + 60
    # 주민번호 줄: 라벨 '주민등록번호'(한글 6자)는 남김
    assert by_row[150][0] > 40 + 150
    assert by_row[150][2] == pytest.approx(480)
    # 라벨만 있는 '주소' → 오른쪽 상자 통째로, '귀하' → 왼쪽 이름 상자 통째로
    assert by_row[270] == (140, 270, 700, 310)
    assert by_row[330] == (40, 330, 160, 370)
    assert 210 not in by_row and 390 not in by_row  # 금액·기관 번호는 남김


def test_redact_and_claude_boxes():
    img = Image.new("RGB", (1000, 500), "white")
    boxes = vision.boxes_from_claude(
        [{"page": 1, "box": [100, 100, 300, 200], "kind": "이름"},
         {"page": 2, "box": [0, 0, 10, 10], "kind": "이름"},       # 다른 페이지
         {"page": 1, "box": [500, 500, 400, 600], "kind": "기타"},  # 뒤집힌 좌표
         {"page": 1, "box": [1, 2, 3], "kind": "기타"},             # 좌표 개수 오류
         {"page": 1, "box": [-50, 900, 2000, 1000], "kind": "주소"}],  # 범위 밖은 잘라냄
        0, img.size)
    assert [b["box"] for b in boxes] == [(100, 50, 300, 100), (0, 450, 1000, 500)]
    out = np.asarray(vision.redact(img, boxes))
    assert out[75, 200].tolist() == [0, 0, 0]
    assert out[300, 600].tolist() == [255, 255, 255]


# ---------- 사진 보정 ----------

def _photo_of_document():
    """회색 배경 위에 기울어진 흰 문서가 찍힌 사진."""
    img = Image.new("RGB", (1200, 900), (90, 90, 90))
    d = ImageDraw.Draw(img)
    d.polygon([(250, 120), (980, 180), (930, 820), (180, 760)], fill="white")
    d.line([(320, 260), (860, 300)], fill="black", width=6)
    return img


def test_perspective_correct():
    out, warped = vision.perspective_correct(_photo_of_document())
    assert warped
    w, h = out.size
    assert 650 < w < 800 and 550 < h < 700
    arr = np.asarray(out)
    assert arr[h // 2, w // 2].mean() > 200  # 가운데가 문서(흰색)
    assert arr[5:20, 5:20].mean() > 150       # 모서리에 배경(회색)이 거의 없음


def test_perspective_skips_flat_scans():
    scan = Image.new("RGB", (800, 1100), "white")
    ImageDraw.Draw(scan).text((50, 50), "text", fill="black")
    out, warped = vision.perspective_correct(scan)
    assert not warped and out is scan


def test_cpu_enhance_skips_pdf_pages_and_flags_upscale():
    pdf_page = vision.Page(image=Image.new("RGB", (600, 800), "white"), from_pdf=True)
    assert vision.cpu_enhance(pdf_page).image is pdf_page.image
    assert vision.needs_upscale(Image.new("RGB", (900, 600)))
    assert not vision.needs_upscale(Image.new("RGB", (1500, 1000)))


def test_build_pages_pdf(tmp_path):
    p = tmp_path / "doc.pdf"
    Image.new("RGB", (600, 800), "white").save(p, "PDF", save_all=True,
                                                 append_images=[Image.new("RGB", (600, 800), "white")])
    data = p.read_bytes()
    as_img = vision.build_pages([(data, "doc.pdf")], as_images=True)
    assert len(as_img) == 2 and all(pg.image is not None and pg.from_pdf for pg in as_img)
    native = vision.build_pages([(data, "doc.pdf")], as_images=False)
    assert len(native) == 1 and native[0].pdf == data
    assert len(vision.build_pages([(data, "doc.pdf")] * 8, as_images=True)) == vision.MAX_PAGES


# ---------- 음성 문장 ----------

@pytest.mark.parametrize("n, words", [
    (0, "영"), (10, "십"), (11, "십일"), (101, "백일"), (1000, "천"), (10000, "만"), (10001, "만 일"),
    (13000, "만 삼천"), (87650, "팔만 칠천육백오십"), (130000, "십삼만"), (100000000, "일억"),
    (123456789, "일억 이천삼백사십오만 육천칠백팔십구"),
])
def test_number_to_korean(n, words):
    assert number_to_korean(n) == words


def test_build_script_short_and_safe():
    v = build_script({"voice_summary": "자동차세를 내라는 고지서예요", "doc_type": "자동차세 고지서",
                      "d_day": {"date": "2026-06-10", "days_left": 3, "label": "D-3", "status": "upcoming"},
                      "amount_krw": 130000, "scam_signals": []})
    assert v["text"] == "자동차세를 내라는 고지서예요. 6월 10일까지, 3일 남았어요. 금액은 130,000원이에요."
    assert v["speech"] == "자동차세를 내라는 고지서예요. 유월 십일까지, 삼일 남았어요. 금액은 십삼만 원이에요."
    assert not any(ch.isdigit() for ch in v["speech"])  # TTS용 문장엔 숫자가 없어야 함

    # 요약에 숫자(개인정보 가능성)가 있거나 너무 길면 안전한 대체 문장
    v = build_script({"voice_summary": "010-1234-5678로 연락하세요", "doc_type": "과태료 통지서",
                      "d_day": {"date": "2026-10-01", "days_left": -5}, "amount_krw": None, "scam_signals": ["개인 계좌"]})
    assert v["text"].startswith("과태료 통지서입니다. 사기가 의심돼요.")
    assert "5일 지났어요" in v["text"] and "010" not in v["text"]
    long = build_script({"voice_summary": "가" * 80, "doc_type": "안내문", "d_day": None, "amount_krw": None, "scam_signals": []})
    assert len(long["text"]) <= 41


# ---------- 실제 OCR 모델 (선택: RUN_MODEL_TESTS=1, 한글 글꼴 필요) ----------

FONT = r"C:\Windows\Fonts\malgun.ttf"


@pytest.mark.skipif(os.getenv("RUN_MODEL_TESTS") != "1" or not os.path.exists(FONT),
                    reason="실제 모델 테스트는 RUN_MODEL_TESTS=1에서만 (모델 다운로드·한글 글꼴 필요)")
def test_real_ocr_redaction():
    from PIL import ImageFont

    import models

    font = ImageFont.truetype(FONT, 30)
    lines = ["자동차세 고지서", "성명: 홍길동", "주민등록번호 900101-1234567", "연락처 010-1234-5678",
             "납부금액 130,000원", "문의 마포구청 02-3153-8000", "가상계좌 123-456789-01-234 (농협)",
             "주소: 서울특별시 마포구 월드컵로 212"]
    img = Image.new("RGB", (1000, 60 * len(lines) + 40), "white")
    d = ImageDraw.Draw(img)
    for i, t in enumerate(lines):
        d.text((40, 30 + 60 * i), t, fill="black", font=font)
    images, ocr_results = models.gpu_prepare([img], [False], True)
    boxes = vision.find_pii_boxes(ocr_results[0], img.width)
    rows = sorted({int(((b["box"][1] + b["box"][3]) / 2 - 30) // 60) for b in boxes})  # 상자 세로 중심 → 줄 번호
    assert rows == [1, 2, 3, 6, 7]  # 이름·주민번호·휴대폰·계좌·주소는 가리고, 금액·기관 번호는 남김
