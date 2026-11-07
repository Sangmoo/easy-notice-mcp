"""고지서·공문서 쉬운 말 풀이 — Gradio 앱 겸 원격 MCP 서버.

Claude는 문서를 읽고 정리만 하고,
D-day 계산·개인정보 마스킹·값 검증·결과 조립은 코드가 결정한다.
입력 문서와 결과는 로그로 남기지 않는다 (민감 문서).

- 웹 UI: 파일 업로드 → explain_upload (API·MCP에는 노출하지 않음)
- MCP 툴: explain_notice (gr.api) — 파일을 http(s) URL 또는 data: URI 문자열로 받는다.
  gr.File(file_count="multiple")을 그대로 MCP에 노출하면 Gradio 6.31이 만드는 입력 스키마의
  $ref(#/$defs/FileData)가 깨져 있어 MCP 호출이 전부 검증 오류로 실패하기 때문에 분리했다.
"""
from __future__ import annotations

# ZeroGPU Space는 gradio·torch보다 먼저 spaces를 import해야 한다. 로컬에서는 없어도 된다.
try:
    import spaces
except ImportError:  # pragma: no cover - 로컬 실행
    spaces = None

import json
from typing import Callable, Literal

import gradio as gr

from claude_util import call_structured, file_block, resolve_client, source_block, today_kst
from errors import ToolError
from logic import LEVELS, MAX_FILES, finalize, render
from prompts import LEVEL_GUIDE, NOTICE_SCHEMA, SYSTEM_PROMPT_BASE
from validate import normalize


def run_explain(sources: list[str], to_block: Callable[[str], dict], reading_level: str, api_key: str | None) -> dict:
    if not sources:
        raise ToolError("문서 사진이나 PDF를 1개 이상 넣어주세요.")
    if reading_level not in LEVEL_GUIDE:
        reading_level = LEVELS[0]

    client = resolve_client(api_key)  # 키가 없으면 파일을 읽기 전에 바로 안내
    content = [to_block(s) for s in sources[:MAX_FILES]]
    today = today_kst()
    content.append({"type": "text", "text": f"오늘 날짜는 {today.isoformat()}입니다. 이 문서를 정리해주세요."})
    raw = call_structured(
        client,
        system=SYSTEM_PROMPT_BASE + "\n" + LEVEL_GUIDE[reading_level],
        content=content,
        schema=NOTICE_SCHEMA,
    )
    return finalize(normalize(raw, NOTICE_SCHEMA), today)


def explain_notice(
    files: list[str],
    reading_level: Literal["아주 쉽게", "보통"] = "아주 쉽게",
    x_anthropic_key: gr.Header = None,
) -> str:
    """세금 고지서, 건강보험·국민연금 안내문, 과태료 통지서, 관공서 공문 등을 쉬운 말로 풀어 해야 할 일, 기한(D-day), 금액, 사기 의심 신호를 정리합니다. 주민등록번호·휴대전화 번호는 결과에서 가려집니다. MCP 연결 설정의 X-Anthropic-Key 헤더에 본인 Anthropic API 키가 필요합니다.

    Args:
        files: 문서 사진 또는 PDF 1~5개. 각 항목은 공개 http(s) URL 또는 data: URI(예: "data:image/jpeg;base64,..." / "data:application/pdf;base64,..."). 여러 장짜리 문서는 모든 페이지를 함께 넣으세요.
        reading_level: 설명 난이도. "아주 쉽게"(어르신·아이도 이해 가능) 또는 "보통".

    Returns:
        읽기 쉽게 정리된 설명(마크다운)과 구조화된 결과 JSON(기한, D-day, 금액, 할 일, 용어 풀이, 사기 의심 신호, 원본 확인 필요 항목).
    """
    try:
        data = run_explain(list(files or []), source_block, reading_level, x_anthropic_key)
    except ToolError as e:
        raise gr.Error(str(e), print_exception=False) from None
    return render(data) + "\n\n## 정리 결과 JSON\n\n```json\n" + json.dumps(data, ensure_ascii=False, indent=2) + "\n```"


def explain_upload(files: list[str] | None, reading_level: str, api_key: str):
    """웹 UI용. 화면에 입력한 본인 키로만 동작한다."""
    try:
        data = run_explain(list(files or []), file_block, reading_level, api_key)
    except ToolError as e:
        raise gr.Error(str(e), print_exception=False) from None
    return render(data), data


with gr.Blocks(title="고지서 쉬운 말 풀이", delete_cache=(1800, 3600)) as demo:
    gr.Markdown(
        "# 📮 고지서·공문서 쉬운 말 풀이\n"
        "세금 고지서, 건강보험 안내문, 과태료 통지서, 관공서 공문을 올리면 "
        "**무엇을, 언제까지, 얼마를** 해야 하는지 쉽게 정리해 드립니다. "
        "본인 Anthropic API 키가 필요합니다. 아래 **Use via API or MCP**에서 원격 MCP 서버로 연결할 수 있습니다."
    )
    with gr.Row():
        with gr.Column():
            key_in = gr.Textbox(
                label="Anthropic API 키 (필수)",
                type="password",
                placeholder="sk-ant-...",
                info="요청 처리에만 쓰고 저장하지 않습니다. 비용은 키 소유자 계정에 청구됩니다. 발급: console.anthropic.com",
            )
            files_in = gr.File(
                label=f"고지서·공문 사진 또는 PDF (최대 {MAX_FILES}개)",
                file_count="multiple",
                file_types=["image", ".pdf"],
                type="filepath",
            )
            level_in = gr.Radio(LEVELS, value=LEVELS[0], label="설명 난이도")
            submit = gr.Button("쉽게 풀어주세요", variant="primary")
        with gr.Column():
            md_out = gr.Markdown(label="쉬운 말 풀이")
            json_out = gr.JSON(label="정리 결과")
    submit.click(explain_upload, [files_in, level_in, key_in], [md_out, json_out], api_visibility="private")
    gr.Markdown(
        "<small>올린 문서는 저장하지 않으며(임시 파일은 1시간 안에 삭제), 주민등록번호·휴대전화 번호는 결과에서 자동으로 가려집니다. "
        "정리 결과는 참고용입니다. 납부 전에는 원본이나 기관 공식 홈페이지에서 금액과 기한을 확인하세요.</small>"
    )
    gr.api(explain_notice, api_name="explain_notice")


if spaces is not None:

    @spaces.GPU(duration=1)
    def _zerogpu_placeholder() -> None:
        """ZeroGPU Space는 시작할 때 @spaces.GPU 함수가 하나 이상 있어야 한다.

        이 앱은 연산을 Claude API가 하므로 GPU가 필요 없다. 이 함수는 호출하지 않으며 GPU 할당량도 쓰지 않는다.
        """

if __name__ == "__main__":
    demo.launch(mcp_server=True)
