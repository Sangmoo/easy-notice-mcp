"""고지서 풀이 전체 흐름.

처리 방식(mode)
- "자동"(추천): GPU(무료 모델)로 개인정보를 먼저 가리고 저해상도 사진을 키운 뒤 Claude에 보낸다.
  페이지가 많거나(GPU 사용량이 큰 작업) GPU를 쓸 수 없으면(ZeroGPU 하루 사용량 초과 등) Claude API 방식으로 넘어간다.
- "무료 모델(GPU)": 항상 GPU. 실패하면 오류로 알려 준다.
- "Claude API"(화면 표시: ⚡ 빠르게): GPU를 쓰지 않는다. 원본이 Claude로 간다.
  share_copy면 Claude가 알려 준 위치로 '공유용 사본'만 가린다(응답이 길어져 조금 느려짐).
  음성은 브라우저 읽기(화면)·안내 문장(MCP)으로 대신한다.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable

from PIL import Image

import models
import vision
from claude_util import call_structured, image_block, pdf_block, resolve_client, server_client, server_key, today_kst
from errors import ToolError
from logic import LEVELS, finalize
from quota import quota
from prompts import (
    LEVEL_GUIDE, PROMPT_ALREADY_REDACTED, PROMPT_FIND_PII, SYSTEM_PROMPT_BASE, schema_for,
)
from validate import normalize
from voice import build_script

MODES = ["자동", "무료 모델(GPU)", "Claude API"]
AUTO, GPU, CLAUDE = MODES
AUTO_GPU_MAX_PAGES = 4  # 자동 모드에서 이보다 많은 페이지는 GPU 대신 Claude API로

Progress = Callable[[float, str], None]


def _noop(_frac: float, _msg: str) -> None:
    pass


@dataclass
class Outcome:
    data: dict
    images: list[Image.Image]          # Claude에 보낸(또는 공유용으로 가린) 페이지 이미지
    voice: dict                        # {'text': 화면용, 'speech': TTS용}
    route: str                         # 'gpu' | 'claude'
    notes: list[str] = field(default_factory=list)
    free_remaining: int | None = None  # 운영자 키로 무료 사용했으면 오늘 남은 횟수


def choose_route(mode: str, image_pages: list[vision.Page], redact: bool, upscale_flags: list[bool]) -> tuple[str, list[str]]:
    if mode == CLAUDE:
        return "claude", ["Claude API 방식으로 처리했어요 (GPU 사용 안 함)."]
    if not (redact or any(upscale_flags)):
        return "claude", []  # GPU로 할 일이 없음
    if mode == AUTO and len(image_pages) > AUTO_GPU_MAX_PAGES:
        return "claude", [f"페이지가 많아({len(image_pages)}쪽) GPU 대신 Claude API 방식으로 처리했어요."]
    return "gpu", []


def explain(
    items: list[tuple[bytes, str]],
    reading_level: str,
    api_key: str | None,
    mode: str = AUTO,
    redact: bool = True,
    enhance: bool = True,
    share_copy: bool = True,
    model: str | None = None,
    progress: Progress | None = None,
    free_user: str | None = None,
) -> Outcome:
    """share_copy: Claude 방식일 때 Claude에게 개인정보 위치를 받아 공유용 가린 사본을 만들지.

    free_user: 웹·앱 화면에서 온 요청의 사용자 구분값(IP). 본인 키가 없으면 운영자 키로 무료 처리하고
    하루 한도를 센다. MCP는 None으로 불러 항상 본인 키를 요구한다.
    """
    step = progress or _noop
    use_operator = not (api_key or "").strip() and free_user is not None and server_key() is not None
    if use_operator:
        quota.check(free_user)  # 남은 횟수가 없으면 파일을 읽기 전에 바로 안내
        client = server_client()
    else:
        client = resolve_client(api_key)  # 키가 없으면 파일을 읽기 전에 바로 안내
    if not items:
        raise ToolError("문서 사진이나 PDF를 1개 이상 넣어주세요.")
    if reading_level not in LEVEL_GUIDE:
        reading_level = LEVELS[0]
    if mode not in MODES:
        mode = AUTO

    # 1) 페이지 준비 + CPU 보정 (가림이 필요하면 PDF도 이미지로)
    step(0.05, "문서를 준비하는 중")
    needs_images = redact and (mode != CLAUDE or share_copy)
    pages = vision.build_pages(items, as_images=needs_images)
    if enhance:
        pages = [vision.cpu_enhance(p) for p in pages]
    image_pages = [p for p in pages if p.image is not None]
    upscale_flags = [enhance and not p.from_pdf and vision.needs_upscale(p.image) for p in image_pages]

    # 2) GPU: 저해상도 확대 + OCR로 개인정보 찾아 가리기
    route, notes = choose_route(mode, image_pages, redact, upscale_flags)
    pre_redacted = False
    if route == "gpu":
        step(0.2, "무료 모델(GPU)로 개인정보를 가리고 사진을 다듬는 중")
        try:
            images, ocr_results = models.gpu_prepare([p.image for p in image_pages], upscale_flags, redact)
        except ToolError:
            raise
        except Exception as e:  # noqa: BLE001 - ZeroGPU 사용량 초과·대기열 오류 등
            if mode == GPU:
                raise ToolError(
                    "GPU 처리에 실패했습니다(ZeroGPU 하루 사용량 초과 등). "
                    "처리 방식을 'Claude API'나 '자동'으로 바꿔 다시 시도해주세요."
                ) from e
            route = "claude"
            notes.append("GPU를 지금 쓸 수 없어(사용량 초과 등) Claude API 방식으로 처리했어요.")
        else:
            hidden = 0
            for page, img, ocr_res, up in zip(image_pages, images, ocr_results, upscale_flags):
                if up:
                    page.notes.append("2배 확대")
                if redact:
                    boxes = vision.find_pii_boxes(ocr_res, img.width)
                    hidden += len(boxes)
                    img = vision.redact(img, boxes)
                page.image = img
            if redact:
                pre_redacted = True
                notes.append(f"무료 모델로 개인정보 {hidden}곳을 가린 뒤 Claude에 보냈어요.")

    # 3) Claude: 문서 읽고 정리 (Claude 방식 + 공유용 사본이면 개인정보 위치도 받음)
    step(0.5, "Claude가 문서를 읽고 정리하는 중")
    find_pii = redact and share_copy and not pre_redacted
    system = SYSTEM_PROMPT_BASE + "\n" + LEVEL_GUIDE[reading_level]
    if pre_redacted:
        system += PROMPT_ALREADY_REDACTED
    if find_pii:
        system += PROMPT_FIND_PII
    today = today_kst()
    content = [image_block(p.image) if p.image is not None else pdf_block(p.pdf) for p in pages]
    content.append({"type": "text", "text": f"오늘 날짜는 {today.isoformat()}입니다. 이 문서를 정리해주세요."})
    schema = schema_for(find_pii)
    if use_operator:
        quota.reserve(free_user)
    try:
        raw = call_structured(client, system, content, schema, model=model, operator_key=use_operator)
    except Exception:
        if use_operator:
            quota.release(free_user)  # 실패한 요청은 횟수에서 빼 준다
        raise
    data = finalize(normalize(raw, schema), today)
    regions = data.pop("pii_regions", None) or []

    # 4) Claude 방식 가림: 사용자에게 돌려줄 공유용 사본만 가린다 (원본은 이미 Claude로 감)
    if find_pii:
        hidden = 0
        for i, page in enumerate(pages):  # find_pii면 모든 페이지가 이미지
            boxes = vision.boxes_from_claude(regions, i, page.image.size)
            hidden += len(boxes)
            page.image = vision.redact(page.image, boxes)
        notes.append(f"원본이 Claude로 전송됐고, 아래 이미지는 Claude가 찾은 개인정보 {hidden}곳을 가린 공유용 사본이에요.")

    if redact and not pre_redacted and not find_pii:
        notes.append("개인정보를 미리 가리지 않고 원본을 Claude로 보냈어요 (결과 글의 주민번호·휴대폰 번호는 가려져요).")
    step(0.95, "결과를 정리하는 중")
    fixes = sorted({n for p in pages for n in p.notes})
    if fixes:
        notes.append("사진 보정: " + ", ".join(fixes))
    return Outcome(
        free_remaining=quota.remaining(free_user) if use_operator else None,
        data=data,
        images=[p.image for p in pages if p.image is not None],
        voice=build_script(data),
        route=route,
        notes=notes,
    )


def speak(speech: str, mode: str, slow: bool = False) -> tuple[tuple[int, object] | None, bool]:
    """'듣기'를 눌렀을 때만 부른다. 반환: (GPU 음성 또는 None, 브라우저로 읽어야 하는지).

    빠르게 방식이거나 GPU를 못 쓰면(사용량 초과 등) 브라우저 내장 음성으로 바로 대신 읽는다.
    """
    if not speech:
        return None, False
    if mode == CLAUDE:
        return None, True
    try:
        return models.gpu_tts(speech, slow), False
    except Exception:  # noqa: BLE001 - 사용량 초과 등
        return None, True
