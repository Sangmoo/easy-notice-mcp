"""ZeroGPU에서 도는 무료 모델들.

| 기능 | 모델 | 라이선스 |
|---|---|---|
| 글자 위치 찾기(개인정보 가림용 OCR) | EasyOCR (ko+en, CRAFT + CRNN) | Apache-2.0 |
| 저해상도 사진 2배 확대 | caidas/swin2SR-classical-sr-x2-64 | Apache-2.0 |
| 음성 안내(TTS) | facebook/mms-tts-kor (VITS) | CC-BY-NC-4.0 (비상업 무료) |

ZeroGPU 규칙: 모델은 시작할 때 모듈 수준에서 .to("cuda")로 올려 두고, @spaces.GPU 함수 안에서만 실행한다.
ZeroGPU가 아닌 곳(로컬·테스트)에서는 처음 쓸 때 CPU로 불러온다.
"""
from __future__ import annotations

# spaces는 torch보다 먼저 import해야 한다 (ZeroGPU의 CUDA 에뮬레이션)
try:
    import spaces
    from spaces.config import Config as _SpacesConfig

    ON_ZEROGPU = bool(_SpacesConfig.zero_gpu)
except ImportError:  # pragma: no cover - spaces 미설치 로컬
    spaces = None
    ON_ZEROGPU = False

import threading

import numpy as np
import torch
from PIL import Image

DEVICE = "cuda" if (ON_ZEROGPU or torch.cuda.is_available()) else "cpu"

OCR_LANGS = ["ko", "en"]
SR_ID = "caidas/swin2SR-classical-sr-x2-64"
TTS_ID = "facebook/mms-tts-kor"

GPU_SECONDS_PER_PAGE = 6
GPU_BASE_SECONDS = 10
TTS_GPU_SECONDS = 20


def gpu(**kwargs):
    """spaces.GPU (ZeroGPU에서만 동작, 그 밖에선 그대로 실행)."""
    if spaces is None:
        return lambda f: f
    return spaces.GPU(**kwargs)


# ---------- 모델 불러오기 ----------

_lock = threading.Lock()
_models: dict = {}


def _load_ocr():
    import easyocr

    # gpu=False·quantize=False로 CPU에 불러온 뒤 일반 모듈째 옮긴다
    # (gpu=True는 DataParallel로 감싸고, quantize=True는 CUDA로 옮길 수 없다)
    reader = easyocr.Reader(OCR_LANGS, gpu=False, quantize=False, verbose=False)
    if DEVICE == "cuda":
        reader.detector = reader.detector.to("cuda")
        reader.recognizer = reader.recognizer.to("cuda")
    reader.device = DEVICE
    return reader


def _load_sr():
    from transformers import AutoImageProcessor, Swin2SRForImageSuperResolution

    proc = AutoImageProcessor.from_pretrained(SR_ID)
    model = Swin2SRForImageSuperResolution.from_pretrained(SR_ID).to(DEVICE).eval()
    return proc, model


def _load_tts():
    import uroman
    from transformers import AutoTokenizer, VitsModel

    tok = AutoTokenizer.from_pretrained(TTS_ID)
    model = VitsModel.from_pretrained(TTS_ID).to(DEVICE).eval()
    return tok, model, uroman.Uroman()


_LOADERS = {"ocr": _load_ocr, "sr": _load_sr, "tts": _load_tts}


def get(name: str):
    with _lock:
        if name not in _models:
            _models[name] = _LOADERS[name]()
        return _models[name]


def preload() -> None:
    for name in _LOADERS:
        get(name)


if ON_ZEROGPU:
    preload()


# ---------- 모델 실행 (GPU 함수 안에서 부르는 일반 함수) ----------

def upscale(img: Image.Image) -> Image.Image:
    proc, model = get("sr")
    inputs = proc(img, return_tensors="pt").to(DEVICE)
    with torch.no_grad():
        out = model(**inputs).reconstruction
    arr = out.squeeze(0).float().clamp(0, 1).cpu().numpy()
    arr = (np.moveaxis(arr, 0, -1) * 255).round().astype(np.uint8)
    w, h = img.size
    return Image.fromarray(arr[: h * 2, : w * 2])  # 처리기가 붙인 여백을 잘라냄


def ocr(img: Image.Image) -> list:
    reader = get("ocr")
    results = reader.readtext(np.asarray(img), detail=1, paragraph=False)
    # 피클 가능한 기본 타입으로 (ZeroGPU는 결과를 프로세스 사이로 넘긴다)
    return [([[float(x), float(y)] for x, y in box], str(text), float(conf)) for box, text, conf in results]


def tts(speech: str) -> tuple[int, np.ndarray]:
    tok, model, rom = get("tts")
    inputs = tok(rom.romanize_string(speech), return_tensors="pt").to(DEVICE)
    torch.manual_seed(0)  # 같은 문장은 같은 소리로
    with torch.no_grad():
        wav = model(**inputs).waveform[0].float().cpu().numpy()
    return int(model.config.sampling_rate), wav


# ---------- @spaces.GPU 함수 ----------

def _prepare_seconds(images, upscale_flags, do_ocr):
    return min(120, GPU_BASE_SECONDS + GPU_SECONDS_PER_PAGE * max(1, len(images)))


@gpu(duration=_prepare_seconds)
def gpu_prepare(images: list[Image.Image], upscale_flags: list[bool], do_ocr: bool):
    """페이지별로 (필요하면) 2배 확대 → (필요하면) OCR. 반환: (이미지 목록, OCR 결과 목록)."""
    out_images, out_ocr = [], []
    for img, up in zip(images, upscale_flags):
        if up:
            img = upscale(img)
        out_images.append(img)
        out_ocr.append(ocr(img) if do_ocr else [])
    return out_images, out_ocr


@gpu(duration=TTS_GPU_SECONDS)
def gpu_tts(speech: str):
    return tts(speech)
