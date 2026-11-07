"""앱 아이콘(시안 B)·Play 대표 이미지·체험 모드 예시 이미지를 만든다.

사용: python tools/make_assets.py <NotoSansKR 글꼴 경로>
  글꼴: https://github.com/google/fonts/tree/main/ofl/notosanskr (SIL Open Font License 1.1)
결과는 static/ 아래에 PNG로 저장한다 (글꼴 파일 자체는 저장소에 넣지 않음).
예시 고지서의 이름·번호는 모두 지어낸 값이며, 개인정보 자리는 가림 처리한 모습으로 그린다.
"""
from __future__ import annotations

import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parent.parent
STATIC = ROOT / "static"
NAVY = "#1F4E79"
YELLOW = "#FFC53D"
WHITE = "#FFFFFF"


def font(path: str, size: int, weight: str = "Bold") -> ImageFont.FreeTypeFont:
    f = ImageFont.truetype(path, size)
    try:
        f.set_variation_by_name(weight)
    except (OSError, ValueError):
        pass
    return f


def center_text(draw: ImageDraw.ImageDraw, cx: float, cy: float, text: str, f, fill: str) -> None:
    x0, y0, x1, y1 = draw.textbbox((0, 0), text, font=f)
    draw.text((cx - (x1 - x0) / 2 - x0, cy - (y1 - y0) / 2 - y0), text, font=f, fill=fill)


def icon(fp: str, size: int, safe: float) -> Image.Image:
    """시안 B: 남색 바탕 + 흰 '고지서' + 노란 알약 '쉽게 보기'. safe: 가장자리 여백 비율(마스커블은 크게)."""
    s = 4  # 크게 그린 뒤 줄여 가장자리를 부드럽게
    W = size * s
    img = Image.new("RGB", (W, W), NAVY)
    d = ImageDraw.Draw(img)
    inner = W * (1 - 2 * safe)
    center_text(d, W / 2, W / 2 - inner * 0.13, "고지서", font(fp, int(inner * 0.30), "Black"), WHITE)
    pw, ph = inner * 0.70, inner * 0.22
    top = W / 2 + inner * 0.10
    d.rounded_rectangle([W / 2 - pw / 2, top, W / 2 + pw / 2, top + ph], radius=ph / 2, fill=YELLOW)
    center_text(d, W / 2, top + ph / 2, "쉽게 보기", font(fp, int(inner * 0.125), "ExtraBold"), NAVY)
    return img.resize((size, size), Image.LANCZOS)


def feature_graphic(fp: str) -> Image.Image:
    """Play 스토어 대표 이미지 1024×500."""
    img = Image.new("RGB", (1024, 500), NAVY)
    d = ImageDraw.Draw(img)
    img.paste(icon(fp, 300, 0.06), (70, 100))
    d.text((420, 120), "고지서 쉽게 보기", font=font(fp, 64, "Black"), fill=WHITE)
    d.text((420, 215), "사진만 찍으면", font=font(fp, 40, "Bold"), fill=YELLOW)
    d.text((420, 268), "언제까지 · 얼마 · 무엇을", font=font(fp, 40, "Bold"), fill=WHITE)
    d.text((420, 321), "쉽게 알려 드려요", font=font(fp, 40, "Bold"), fill=WHITE)
    return img


def _paper(w: int, h: int) -> tuple[Image.Image, ImageDraw.ImageDraw]:
    img = Image.new("RGB", (w, h), "#F4F1EA")
    d = ImageDraw.Draw(img)
    d.rectangle([20, 20, w - 20, h - 20], fill=WHITE, outline="#BBBBBB", width=2)
    return img, d


def _hidden(d, x, y, w, h=34):
    d.rectangle([x, y, x + w, y + h], fill="black")


def example_car_tax(fp: str) -> Image.Image:
    """가상 자동차세 고지서 (개인정보 자리는 가린 모습)."""
    img, d = _paper(820, 1040)
    f_t, f_b, f_s = font(fp, 40, "Black"), font(fp, 28, "Medium"), font(fp, 22, "Regular")
    d.rectangle([20, 20, 800, 110], fill=NAVY)
    d.text((50, 40), "자동차세 납부 고지서 (예시)", font=f_t, fill=WHITE)
    rows = [("과세 기관", "○○시 ○○구청 세무과"), ("납세자", None), ("주민등록번호", None), ("주소", None),
            ("차량", "승용차 (2,000cc)"), ("과세 기간", "2기분 (7월 ~ 12월)")]
    y = 150
    for label, value in rows:
        d.text((60, y), label, font=f_b, fill="#333333")
        if value:
            d.text((300, y), value, font=f_b, fill="#111111")
        else:
            _hidden(d, 300, y + 2, 300)
        y += 62
    d.line([60, y + 10, 760, y + 10], fill="#999999", width=2)
    y += 40
    d.text((60, y), "납부할 금액", font=f_b, fill="#333333")
    d.text((300, y - 8), "130,000원", font=font(fp, 44, "Black"), fill="#B3261E")
    y += 80
    d.text((60, y), "납부 기한", font=f_b, fill="#333333")
    d.text((300, y), "고지서를 받은 날부터 2주 안", font=f_b, fill="#111111")
    y += 80
    for line in ["• 기한이 지나면 가산금 3%가 붙습니다.",
                 "• 위택스, 은행 앱, 가상계좌, 편의점에서 낼 수 있습니다.",
                 "• 문의: ○○구청 세무과 (고지서에 적힌 대표번호)"]:
        d.text((60, y), line, font=f_s, fill="#333333")
        y += 44
    d.text((60, 960), "※ 체험용으로 만든 가짜 고지서입니다.", font=f_s, fill="#B3261E")
    return img


def example_scam_sms(fp: str) -> Image.Image:
    """가짜 과태료 문자 (사기 예시). 휴대폰·계좌 자리는 가린 모습."""
    img = Image.new("RGB", (720, 1040), "#E9EEF3")
    d = ImageDraw.Draw(img)
    f_h, f_b, f_s = font(fp, 30, "Bold"), font(fp, 27, "Regular"), font(fp, 22, "Regular")
    d.rectangle([0, 0, 720, 90], fill="#FFFFFF")
    d.text((30, 26), "문자 메시지 (예시)", font=f_h, fill="#111111")
    d.rounded_rectangle([30, 130, 690, 880], radius=28, fill=WHITE)
    lines = ["[Web발신]", "[교통법규 위반] 과태료 미납 안내", "", "고객님 차량의 과태료 64,000원이",
             "미납되었습니다. 오늘까지 내지 않으면", "차량이 압류됩니다.", "", "▶ 즉시 납부:",
             "   http://fine-pay24.example", "", "▶ 입금 계좌 (담당자 개인 계좌)", None, "", "▶ 문의 (담당 주무관)", None]
    y = 165
    for line in lines:
        if line is None:
            _hidden(d, 70, y + 2, 360)
        elif line:
            d.text((60, y), line, font=f_b, fill="#B3261E" if "압류" in line or "example" in line else "#111111")
        y += 44
    d.text((30, 940), "※ 체험용으로 만든 가짜 문자입니다.", font=f_s, fill="#B3261E")
    return img


def main(fp: str) -> None:
    (STATIC / "examples").mkdir(parents=True, exist_ok=True)
    icon(fp, 512, 0.06).save(STATIC / "icon-512.png", optimize=True)
    icon(fp, 192, 0.06).save(STATIC / "icon-192.png", optimize=True)
    icon(fp, 512, 0.16).save(STATIC / "icon-maskable-512.png", optimize=True)  # 안드로이드가 원형으로 잘라도 안전
    feature_graphic(fp).save(STATIC / "feature-graphic-1024x500.png", optimize=True)
    example_car_tax(fp).save(STATIC / "examples" / "car-tax.png", optimize=True)
    example_scam_sms(fp).save(STATIC / "examples" / "scam-sms.png", optimize=True)
    for p in sorted(STATIC.rglob("*.png")):
        print(p.relative_to(ROOT), Image.open(p).size, p.stat().st_size // 1024, "KB")


if __name__ == "__main__":
    main(sys.argv[1])
