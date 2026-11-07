"""문서 이미지 처리 (모델 없이 도는 부분).

- 페이지 준비: 사진은 EXIF 회전 보정, PDF는 개인정보 가림이 필요할 때 페이지 이미지로 변환
- CPU 보정: 문서 테두리를 찾아 원근 보정, 대비·선명도 보정 (위험하면 건너뜀)
- 개인정보 찾기: OCR 결과(글자 상자)에서 주민번호·휴대폰·계좌번호·이름/주소 칸을 골라냄
- 가림: 찾은 상자를 검게 칠함. Claude 모드에서는 Claude가 알려준 좌표(0~1000)로 칠함

OCR·초해상도 같은 모델 실행은 models.py(GPU)에서 한다. 입력 내용은 로그로 남기지 않는다.
"""
from __future__ import annotations

import io
import re
from dataclasses import dataclass, field

import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageOps, UnidentifiedImageError

from errors import ToolError

MAX_PAGES = 10          # 한 번에 처리할 최대 페이지 수 (PDF 포함)
PDF_RENDER_SCALE = 2.0  # 72dpi × 2 ≈ A4 1190×1684
PAD = 4                 # 가림 상자 여백(px)


@dataclass
class Page:
    """Claude에 보낼 한 페이지. image가 있으면 이미지, 없으면 원본 PDF 바이트를 그대로 보낸다."""
    image: Image.Image | None = None
    pdf: bytes | None = None
    from_pdf: bool = False   # PDF에서 렌더링한 페이지(깨끗하므로 화질 보정 불필요)
    name: str = ""
    notes: list[str] = field(default_factory=list)


# ---------- 페이지 준비 ----------

def open_image(data: bytes, name: str) -> Image.Image:
    try:
        img = Image.open(io.BytesIO(data))
        return ImageOps.exif_transpose(img).convert("RGB")
    except (UnidentifiedImageError, OSError) as e:
        raise ToolError(f"'{name}'을(를) 읽을 수 없습니다. JPG·PNG·WEBP 사진이나 PDF로 넣어주세요.") from e


def is_pdf(data: bytes, name: str) -> bool:
    return data[:5] == b"%PDF-" or name.lower().endswith(".pdf")


def render_pdf(data: bytes, name: str, limit: int) -> list[Image.Image]:
    import pypdfium2 as pdfium

    try:
        doc = pdfium.PdfDocument(data)
    except Exception as e:  # noqa: BLE001 - 손상된 PDF
        raise ToolError(f"'{name}' PDF를 열 수 없습니다.") from e
    try:
        n = min(len(doc), limit)
        return [doc[i].render(scale=PDF_RENDER_SCALE).to_pil().convert("RGB") for i in range(n)]
    finally:
        doc.close()


def build_pages(items: list[tuple[bytes, str]], as_images: bool) -> list[Page]:
    """(바이트, 이름) 목록 → 페이지 목록. as_images면 PDF도 페이지 이미지로 바꾼다."""
    pages: list[Page] = []
    for data, name in items:
        left = MAX_PAGES - len(pages)
        if left <= 0:
            break
        if is_pdf(data, name):
            if as_images:
                pages += [Page(image=im, from_pdf=True, name=f"{name} p{i + 1}")
                          for i, im in enumerate(render_pdf(data, name, left))]
            else:
                pages.append(Page(pdf=data, name=name))
        else:
            pages.append(Page(image=open_image(data, name), name=name))
    return pages


# ---------- CPU 화질 보정 ----------

def _order_corners(pts: np.ndarray) -> np.ndarray:
    s, d = pts.sum(axis=1), np.diff(pts, axis=1).ravel()
    return np.array([pts[np.argmin(s)], pts[np.argmin(d)], pts[np.argmax(s)], pts[np.argmax(d)]], dtype=np.float32)


def perspective_correct(img: Image.Image) -> tuple[Image.Image, bool]:
    """사진 속 문서의 네 모서리를 찾으면 정면으로 편다. 확신이 없으면 원본 그대로."""
    import cv2

    rgb = np.asarray(img)
    h, w = rgb.shape[:2]
    scale = 800 / max(h, w) if max(h, w) > 800 else 1.0
    small = cv2.resize(rgb, (int(w * scale), int(h * scale))) if scale < 1 else rgb
    gray = cv2.GaussianBlur(cv2.cvtColor(small, cv2.COLOR_RGB2GRAY), (5, 5), 0)
    edges = cv2.dilate(cv2.Canny(gray, 50, 150), np.ones((3, 3), np.uint8))
    contours, _ = cv2.findContours(edges, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    area_img = small.shape[0] * small.shape[1]
    for c in sorted(contours, key=cv2.contourArea, reverse=True)[:5]:
        approx = cv2.approxPolyDP(c, 0.02 * cv2.arcLength(c, True), True)
        if len(approx) != 4 or not cv2.isContourConvex(approx):
            continue
        ratio = cv2.contourArea(approx) / area_img
        if not 0.35 <= ratio <= 0.97:  # 너무 작으면 문서가 아니고, 거의 전체면 이미 반듯함
            return img, False
        quad = _order_corners(approx.reshape(4, 2).astype(np.float32) / scale)
        tl, tr, br, bl = quad
        width = int(max(np.linalg.norm(br - bl), np.linalg.norm(tr - tl)))
        height = int(max(np.linalg.norm(tr - br), np.linalg.norm(tl - bl)))
        if width < 200 or height < 200:
            return img, False
        dst = np.array([[0, 0], [width - 1, 0], [width - 1, height - 1], [0, height - 1]], dtype=np.float32)
        warped = cv2.warpPerspective(rgb, cv2.getPerspectiveTransform(quad, dst), (width, height))
        return Image.fromarray(warped), True
    return img, False


def cpu_enhance(page: Page) -> Page:
    """원근 보정 + 대비·선명도. PDF에서 만든 페이지는 이미 깨끗하므로 건너뛴다."""
    if page.image is None or page.from_pdf:
        return page
    img, warped = perspective_correct(page.image)
    img = ImageOps.autocontrast(img, cutoff=1)
    img = img.filter(ImageFilter.UnsharpMask(radius=2, percent=80, threshold=3))
    if warped:
        page.notes.append("원근 보정")
    page.image = img
    return page


def needs_upscale(img: Image.Image, threshold: int = 1000) -> bool:
    """긴 변이 작은(저해상도) 사진만 초해상도로 키운다."""
    return max(img.size) < threshold


# ---------- 개인정보 찾기 (OCR 결과 기반) ----------
#
# OCR은 보통 한 줄을 상자 하나로 돌려준다("주민등록번호 900101-1234567").
# 줄 전체를 칠하면 라벨까지 사라지므로, 값 부분의 글자 위치를 상자 안 가로 위치로 환산해 그 부분만 가린다.

_RRN = re.compile(r"(?<!\d)\d{6}\s*[-~–]?\s*[1-8]\d{6}(?!\d)")
# OCR이 010의 1을 7로 잘못 읽는 일이 잦아 070도 휴대폰으로 본다
_MOBILE = re.compile(r"(?<!\d)0[17][016789]\s*[-.\s]?\s*\d{3,4}\s*[-.\s]?\s*\d{4}(?!\d)")
_DIGIT_GROUPS = re.compile(r"(?<![\d,.])\d{2,8}(?:\s*-\s*\d{1,8}){1,5}(?![\d,.])|(?<![\d,.])\d{11,16}(?![\d,.])")
_LANDLINE = re.compile(r"^(?:0\d{1,3}|1[5-9]\d{2})-?\d{3,4}(?:-?\d{4})?$")
# 값이 개인정보인 라벨 (기관 연락처용 '문의', '전화번호'는 넣지 않는다)
_LABELS = ("성명", "이름", "주소", "납세자", "납부자", "수신", "받는분", "소유자", "주민번호", "주민등록번호",
           "생년월일", "연락처", "휴대폰", "핸드폰", "휴대전화")
_HONORIFICS = ("귀하",)

# OCR이 숫자 사이 O·o를 0으로, l·I를 1로 잘못 읽는 경우가 많다 (글자 수는 그대로 유지)
_OCR_FIX = str.maketrans({"O": "0", "o": "0", "l": "1", "I": "1", "|": "1"})


def _normalize_ocr(text: str) -> str:
    return re.sub(r"(?<=\d)[OolI|]|[OolI|](?=\d)", lambda m: m.group().translate(_OCR_FIX), text)


def classify_pii(text: str) -> tuple[str, tuple[int, int]] | None:
    """글자 상자 하나에 개인정보 번호가 있으면 (종류, 글자 범위), 없으면 None."""
    t = _normalize_ocr(text)
    if m := _RRN.search(t):
        return "주민등록번호", m.span()
    if m := _MOBILE.search(t):
        return "전화번호", m.span()
    for m in _DIGIT_GROUPS.finditer(t):
        digits = re.sub(r"\D", "", m.group())
        compact = re.sub(r"\s", "", m.group())
        if 11 <= len(digits) <= 16 and not _LANDLINE.match(compact):
            return "계좌번호", m.span()
    return None


def _char_weight(ch: str) -> float:
    if ch.isspace():
        return 0.3
    if ord(ch) < 0x1100:  # 영문·숫자·기호는 한글보다 좁다
        return 0.55
    return 1.0


def _span_box(bounds, text: str, start: int, end: int) -> tuple[float, float, float, float]:
    """상자 안에서 text[start:end]가 차지하는 가로 범위 (글자 폭 가중치로 근사, 앞 1/4·뒤 1/2 글자 여유)."""
    x0, y0, x1, y1 = bounds
    weights = [_char_weight(c) for c in text] or [1.0]
    total = sum(weights)
    unit = (x1 - x0) / total
    left = x0 + unit * (sum(weights[:start]) - 0.25)
    right = x0 + unit * (sum(weights[:end]) + 0.5)
    return max(x0, left), y0, min(x1, right), y1


def _label_in(text: str) -> str | None:
    compact = text.replace(" ", "")
    for lab in _LABELS:
        if lab in compact:
            return lab
    return None


def _bounds(box) -> tuple[float, float, float, float]:
    xs = [p[0] for p in box]
    ys = [p[1] for p in box]
    return min(xs), min(ys), max(xs), max(ys)


def _same_row(a, b) -> bool:
    _, ay0, _, ay1 = a
    _, by0, _, by1 = b
    overlap = min(ay1, by1) - max(ay0, by0)
    return overlap > 0.5 * min(ay1 - ay0, by1 - by0)


def _value_after_label(text: str, label: str) -> tuple[int, int] | None:
    """'성명: 홍길동'에서 라벨 뒤 값의 글자 범위."""
    i = text.replace(" ", "").find(label)
    if i < 0:
        return None
    # 공백을 뺀 위치를 원래 문자열 위치로 되돌린다
    seen, start = 0, None
    for pos, ch in enumerate(text):
        if ch == " ":
            continue
        if seen == i + len(label):
            start = pos
            break
        seen += 1
    if start is None:
        return None
    while start < len(text) and text[start] in " :：-":
        start += 1
    return (start, len(text)) if len(text) - start >= 2 else None


def find_pii_boxes(ocr_results: list, width: int) -> list[dict]:
    """OCR 결과 [(box(4점), text, conf), ...] → 가릴 상자 [{'box': (x0,y0,x1,y1), 'kind': str}].

    - 번호 패턴(주민번호·휴대폰·계좌)은 그 번호 부분만 가린다. 기관 유선번호·금액·날짜는 남긴다.
    - '성명/주소/연락처' 같은 라벨은 라벨 뒤 값을, 값이 다음 상자에 있으면 같은 줄 오른쪽 상자를 가린다.
    - '귀하': 같은 줄 앞(왼쪽)의 이름을 가린다.
    """
    items = [(_bounds(b), str(t)) for b, t, *_ in ocr_results]
    out: list[dict] = []
    whole: set[int] = set()  # 통째로 가린 상자

    def right_neighbor(i):
        bb = items[i][0]
        cands = [(j, b2) for j, (b2, _) in enumerate(items)
                 if j != i and _same_row(bb, b2) and b2[0] >= bb[2] - 5 and b2[0] - bb[2] < 0.6 * width]
        return min(cands, key=lambda x: x[1][0])[0] if cands else None

    def left_neighbor(i):
        bb = items[i][0]
        cands = [(j, b2) for j, (b2, _) in enumerate(items)
                 if j != i and _same_row(bb, b2) and b2[2] <= bb[0] + 5 and bb[0] - b2[2] < 0.3 * width]
        return max(cands, key=lambda x: x[1][2])[0] if cands else None

    for i, (bb, text) in enumerate(items):
        hit = classify_pii(text)
        if hit:
            kind, (a, b) = hit
            out.append({"box": _span_box(bb, text, a, b), "kind": kind})
            continue
        if lab := _label_in(text):
            span = _value_after_label(text, lab)
            if span:
                out.append({"box": _span_box(bb, text, *span), "kind": "이름·주소·연락처"})
            elif (j := right_neighbor(i)) is not None and j not in whole:
                whole.add(j)
                out.append({"box": items[j][0], "kind": "이름·주소·연락처"})
        if (h := next((h for h in _HONORIFICS if h in text), None)) is not None:
            k = text.find(h)
            if len(text[:k].strip()) >= 2:
                out.append({"box": _span_box(bb, text, 0, k), "kind": "이름·주소·연락처"})
            elif (j := left_neighbor(i)) is not None and j not in whole:
                whole.add(j)
                out.append({"box": items[j][0], "kind": "이름·주소·연락처"})
    return out


# ---------- 가리기 ----------

def redact(img: Image.Image, boxes: list[dict]) -> Image.Image:
    out = img.copy()
    draw = ImageDraw.Draw(out)
    w, h = out.size
    for r in boxes:
        x0, y0, x1, y1 = r["box"]
        draw.rectangle([max(0, x0 - PAD), max(0, y0 - PAD), min(w, x1 + PAD), min(h, y1 + PAD)], fill="black")
    return out


def boxes_from_claude(regions: list[dict], page_index: int, size: tuple[int, int]) -> list[dict]:
    """Claude가 준 정규화 좌표(0~1000) → 픽셀 상자. 잘못된 좌표는 버린다."""
    w, h = size
    out = []
    for r in regions:
        if r.get("page") != page_index + 1:
            continue
        box = r.get("box") or []
        if len(box) != 4:
            continue
        x0, y0, x1, y1 = (max(0, min(1000, int(v))) for v in box)
        if x1 <= x0 or y1 <= y0:
            continue
        out.append({"box": (x0 * w / 1000, y0 * h / 1000, x1 * w / 1000, y1 * h / 1000), "kind": r.get("kind") or "기타"})
    return out
