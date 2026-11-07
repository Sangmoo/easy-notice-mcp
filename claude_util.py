"""Claude 호출 공통 유틸.

- API 키: 사용자 본인 키 필수 (웹 화면 입력란 또는 MCP 헤더 X-Anthropic-Key)
- 이미지/PDF(업로드 파일, 또는 원격 MCP의 http(s) URL·data: URI)를 Claude 입력 블록으로 변환
- structured outputs(output_config.format)로 항상 스키마에 맞는 JSON을 받음
  (Sonnet 5.5 / Opus 5.5는 tool_choice로 툴 호출을 강제하는 방식을 400으로 거부한다)
"""
from __future__ import annotations

import base64
import binascii
import datetime
import io
import ipaddress
import json
import os
import socket
import urllib.parse
import urllib.request
from pathlib import Path

import anthropic
from PIL import Image, ImageOps, UnidentifiedImageError

from errors import ToolError
from validate import to_api_schema

MODEL = os.getenv("CLAUDE_MODEL", "claude-sonnet-5-5")
MAX_SIDE = 1568  # 이 이상은 Claude가 내부적으로 축소하므로 미리 줄여 전송량/비용 절감
MAX_IMAGE_BYTES = 20 * 1024 * 1024
MAX_PDF_BYTES = 32 * 1024 * 1024  # Claude PDF 입력 한도

KST = datetime.timezone(datetime.timedelta(hours=9))


def today_kst() -> datetime.date:
    return datetime.datetime.now(KST).date()


def resolve_client(user_key: str | None) -> anthropic.Anthropic:
    """사용자 본인의 Anthropic API 키로만 클라이언트를 만든다 (서버 키·데모 키 없음).

    키는 요청 처리에만 쓰고 저장하거나 로그로 남기지 않는다.
    """
    key = (user_key or "").strip()
    if not key:
        raise ToolError(
            "Anthropic API 키가 필요합니다. "
            "웹 화면에서는 키 입력란에, MCP에서는 X-Anthropic-Key 헤더에 본인 키를 넣어주세요."
        )
    if not key.startswith("sk-ant-"):
        raise ToolError("Anthropic API 키 형식이 아닙니다(sk-ant-로 시작). 키를 다시 확인해주세요.")
    return anthropic.Anthropic(api_key=key)


# ---------- 입력 파일 ----------
#
# 웹 UI 업로드는 Gradio가 만든 임시 파일 경로(read_upload)로,
# 원격 MCP 호출은 http(s) URL 또는 data: URI(fetch_source)로 들어온다.
# 원격 호출자가 서버의 로컬 경로를 넘기면 Space의 파일(환경변수 등)을 읽게 되므로 절대 허용하지 않는다.

_PRIVATE_NET_MSG = "내부 네트워크 주소의 파일은 받을 수 없습니다."


def _check_public_host(url: str) -> None:
    """SSRF 방지: 사설·루프백·링크로컬 등 내부 주소로 향하는 URL은 거부."""
    host = urllib.parse.urlsplit(url).hostname
    if not host:
        raise ToolError(f"URL 형식이 올바르지 않습니다: {url[:80]}")
    try:
        infos = socket.getaddrinfo(host, None)
    except socket.gaierror as e:
        raise ToolError(f"주소를 찾을 수 없습니다: {host}") from e
    for info in infos:
        ip = ipaddress.ip_address(info[4][0].split("%")[0])
        if not ip.is_global:
            raise ToolError(_PRIVATE_NET_MSG)


class _SafeRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):  # noqa: D401
        if not newurl.startswith(("http://", "https://")):
            raise ToolError("허용되지 않는 리다이렉트입니다.")
        _check_public_host(newurl)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


_opener = urllib.request.build_opener(_SafeRedirect)


def fetch_source(src: str) -> tuple[bytes, str]:
    """http(s) URL 또는 data: URI → (바이트, 이름). 그 밖의 형식(로컬 경로 등)은 거부."""
    src = (src or "").strip()
    if src.startswith("data:"):
        header, _, payload = src.partition(",")
        if ";base64" not in header:
            raise ToolError("data: URI는 base64 형식이어야 합니다.")
        try:
            data = base64.b64decode(payload, validate=False)
        except (ValueError, binascii.Error) as e:
            raise ToolError("data: URI를 해석하지 못했습니다.") from e
        name = "document.pdf" if "application/pdf" in header else "image"
    elif src.startswith(("http://", "https://")):
        _check_public_host(src)
        req = urllib.request.Request(src, headers={"User-Agent": "easy-notice-mcp/1.0"})
        try:
            with _opener.open(req, timeout=20) as r:
                data = r.read(MAX_PDF_BYTES + 1)
                ctype = r.headers.get("Content-Type", "")
        except ToolError:
            raise
        except Exception as e:  # noqa: BLE001 - 네트워크 오류를 사용자 메시지로 변환
            raise ToolError(f"URL에서 파일을 받지 못했습니다: {src[:120]}") from e
        name = urllib.parse.urlsplit(src).path.rsplit("/", 1)[-1] or "file"
        if "pdf" in ctype and not name.lower().endswith(".pdf"):
            name += ".pdf"
    else:
        raise ToolError("파일은 http(s) URL 또는 data: URI로 넣어주세요.")
    if not data:
        raise ToolError("빈 파일입니다.")
    if len(data) > MAX_PDF_BYTES:
        raise ToolError("파일이 너무 큽니다(32MB 초과).")
    return data, name


def pdf_block(data: bytes) -> dict:
    return {
        "type": "document",
        "source": {
            "type": "base64",
            "media_type": "application/pdf",
            "data": base64.standard_b64encode(data).decode(),
        },
    }


def image_block(img: Image.Image) -> dict:
    """PIL 이미지 → JPEG base64 블록 (긴 변 MAX_SIDE로 축소)."""
    img = img.convert("RGB")
    img.thumbnail((MAX_SIDE, MAX_SIDE))
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=85)
    return {
        "type": "image",
        "source": {
            "type": "base64",
            "media_type": "image/jpeg",
            "data": base64.standard_b64encode(buf.getvalue()).decode(),
        },
    }


def read_upload(path: str) -> tuple[bytes, str]:
    """웹 UI 업로드(Gradio 임시 파일 경로) → (바이트, 이름)."""
    p = Path(path)
    if not p.is_file():
        raise ToolError(f"파일을 찾을 수 없습니다: {p.name}")
    if p.stat().st_size > MAX_PDF_BYTES:
        raise ToolError(f"파일이 너무 큽니다(32MB 초과): {p.name}")
    return p.read_bytes(), p.name


# ---------- Claude 호출 ----------

def call_structured(
    client: anthropic.Anthropic,
    system: str,
    content: list[dict],
    schema: dict,
    max_tokens: int = 16000,
) -> dict:
    """structured outputs로 스키마에 맞는 JSON을 받아 dict로 돌려준다."""
    try:
        resp = client.messages.create(
            model=MODEL,
            max_tokens=max_tokens,
            system=system,
            messages=[{"role": "user", "content": content}],
            output_config={"format": {"type": "json_schema", "schema": to_api_schema(schema)}},
        )
    except anthropic.AuthenticationError as e:
        raise ToolError("Anthropic API 키가 올바르지 않습니다.") from e
    except anthropic.PermissionDeniedError as e:
        raise ToolError(f"이 API 키로는 요청할 수 없습니다: {e.message}") from e
    except anthropic.NotFoundError as e:
        raise ToolError(f"모델을 찾을 수 없습니다: {MODEL}") from e
    except anthropic.RateLimitError as e:
        raise ToolError("Anthropic API 요청 한도에 걸렸습니다. 잠시 후 다시 시도해주세요.") from e
    except anthropic.BadRequestError as e:
        raise ToolError(f"요청이 거부되었습니다: {e.message}") from e
    except anthropic.APIStatusError as e:
        raise ToolError(f"Claude 서버 오류({e.status_code})입니다. 잠시 후 다시 시도해주세요.") from e
    except anthropic.APIConnectionError as e:
        raise ToolError("Claude API에 연결하지 못했습니다. 잠시 후 다시 시도해주세요.") from e

    if resp.stop_reason == "refusal":
        raise ToolError("Claude가 이 문서의 처리를 거절했습니다. 다른 문서로 시도해주세요.")
    if resp.stop_reason == "max_tokens":
        raise ToolError("응답이 길어 중간에 잘렸습니다. 파일 수를 줄여 다시 시도해주세요.")
    text = next((b.text for b in resp.content if b.type == "text"), None)
    if not text:
        raise ToolError("Claude 응답에서 결과를 찾지 못했습니다. 다시 시도해주세요.")
    try:
        return json.loads(text)
    except json.JSONDecodeError as e:
        raise ToolError("Claude 응답을 해석하지 못했습니다. 다시 시도해주세요.") from e
