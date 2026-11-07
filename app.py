"""고지서·공문서 쉬운 말 풀이 — Gradio 앱 겸 원격 MCP 서버 (ZeroGPU).

Claude는 문서를 읽고 정리만 하고, D-day 계산·개인정보 마스킹·값 검증·결과 조립은 코드가 결정한다.
ZeroGPU의 무료 모델로 (1) 개인정보를 이미지에서 먼저 가리고 (2) 짧은 음성 안내를 만들고 (3) 흐린 사진을 보정한다.
GPU 사용량이 큰 작업이거나 GPU를 쓸 수 없으면 Claude API 방식으로 처리한다 (pipeline.py).
입력 문서와 결과는 로그로 남기지 않는다 (민감 문서).

- 웹 UI: 파일 업로드 → explain_upload (API·MCP에는 노출하지 않음)
- MCP 툴: explain_notice (gr.api) — 파일을 http(s) URL 또는 data: URI 문자열로 받는다.
  gr.File(file_count="multiple")을 그대로 MCP에 노출하면 Gradio 6.31이 만드는 입력 스키마의
  $ref(#/$defs/FileData)가 깨져 있어 MCP 호출이 전부 검증 오류로 실패하기 때문에 분리했다.
"""
from __future__ import annotations

import models  # noqa: I001 - spaces를 torch·gradio보다 먼저 불러오고 ZeroGPU 모델을 올린다

import json
from typing import Literal

import gradio as gr

import pipeline
from claude_util import fetch_source, read_upload
from errors import ToolError
from logic import LEVELS, MAX_FILES, render
from pipeline import MODES


def _report(outcome: pipeline.Outcome) -> str:
    lines = [f"- {n}" for n in outcome.notes]
    return "\n".join(lines) if lines else ""


def explain_notice(
    files: list[str],
    reading_level: Literal["아주 쉽게", "보통"] = "아주 쉽게",
    mode: Literal["자동", "무료 모델(GPU)", "Claude API"] = "자동",
    redact: bool = True,
    enhance: bool = True,
    x_anthropic_key: gr.Header = None,
) -> str:
    """세금 고지서, 건강보험·국민연금 안내문, 과태료 통지서, 관공서 공문 등을 쉬운 말로 풀어 해야 할 일, 기한(D-day), 금액, 사기 의심 신호를 정리하고, 짧은 음성 안내 문장을 만듭니다. MCP 연결 설정의 X-Anthropic-Key 헤더에 본인 Anthropic API 키가 필요합니다.

    Args:
        files: 문서 사진 또는 PDF 1~5개. 각 항목은 공개 http(s) URL 또는 data: URI(예: "data:image/jpeg;base64,..." / "data:application/pdf;base64,..."). 여러 장짜리 문서는 모든 페이지를 함께 넣으세요.
        reading_level: 설명 난이도. "아주 쉽게"(어르신·아이도 이해 가능) 또는 "보통".
        mode: 처리 방식. "자동"(추천: 무료 GPU 모델로 개인정보를 먼저 가리고, 페이지가 많거나 GPU를 못 쓰면 Claude API로), "무료 모델(GPU)", "Claude API"(GPU 미사용, 원본이 Claude로 전송됨).
        redact: 주민번호·전화번호·계좌번호·이름·주소를 가릴지 여부.
        enhance: 사진 원근·대비 보정과 저해상도 사진 2배 확대를 할지 여부.

    Returns:
        처리 방식 안내, 짧은 음성 안내 문장, 읽기 쉽게 정리된 설명(마크다운), 구조화된 결과 JSON(기한, D-day, 금액, 할 일, 용어 풀이, 사기 의심 신호, 원본 확인 필요 항목). 주민등록번호·휴대전화 번호는 결과에서 가려집니다.
    """
    try:
        items = [fetch_source(s) for s in list(files or [])[:MAX_FILES]]
        out = pipeline.explain(items, reading_level, x_anthropic_key, mode, redact, enhance)
    except ToolError as e:
        raise gr.Error(str(e), print_exception=False) from None
    report = _report(out)
    return (
        (f"### 처리 방식\n{report}\n\n" if report else "")
        + f"### 🔊 음성 안내\n{out.voice['text']}\n\n"
        + render(out.data)
        + "\n\n## 정리 결과 JSON\n\n```json\n" + json.dumps(out.data, ensure_ascii=False, indent=2) + "\n```"
    )


def explain_upload(files, reading_level, mode, options, api_key):
    """웹 UI용. 화면에 입력한 본인 키로만 동작한다."""
    options = options or []
    try:
        if not files:
            raise ToolError("문서 사진이나 PDF를 1개 이상 넣어주세요.")
        items = [read_upload(p) for p in list(files)[:MAX_FILES]]
        out = pipeline.explain(items, reading_level, api_key, mode, "개인정보 가리기" in options, "사진 보정" in options)
    except ToolError as e:
        raise gr.Error(str(e), print_exception=False) from None

    audio, voice_note = None, None
    if "음성 안내" in options:
        audio, voice_note = pipeline.speak(out, mode)
    notes = out.notes + ([voice_note] if voice_note else [])
    status = "\n".join(f"- {n}" for n in notes)
    return (
        status,
        out.voice["text"],
        out.voice["speech"],
        audio,
        render(out.data),
        out.images,
        out.data,
    )


BROWSER_SPEAK_JS = """
(text) => {
  if (!text || !window.speechSynthesis) return [];
  window.speechSynthesis.cancel();
  const u = new SpeechSynthesisUtterance(text);
  u.lang = 'ko-KR';
  u.rate = 0.95;
  const ko = window.speechSynthesis.getVoices().find(v => v.lang && v.lang.startsWith('ko'));
  if (ko) u.voice = ko;
  window.speechSynthesis.speak(u);
  return [];
}
"""

with gr.Blocks(title="고지서 쉬운 말 풀이", delete_cache=(1800, 3600)) as demo:
    gr.Markdown(
        "# 📮 고지서·공문서 쉬운 말 풀이\n"
        "세금 고지서, 건강보험 안내문, 과태료 통지서, 관공서 공문을 올리면 "
        "**무엇을, 언제까지, 얼마를** 해야 하는지 쉽게 정리하고 짧게 읽어 드립니다. "
        "본인 Anthropic API 키가 필요합니다. 아래 **Use via API or MCP**에서 원격 MCP 서버로 연결할 수 있습니다."
    )
    with gr.Row():
        with gr.Column(scale=1):
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
            options_in = gr.CheckboxGroup(
                ["개인정보 가리기", "사진 보정", "음성 안내"],
                value=["개인정보 가리기", "사진 보정", "음성 안내"],
                label="추가 기능",
            )
            mode_in = gr.Radio(
                MODES,
                value=MODES[0],
                label="처리 방식",
                info="자동: 무료 GPU 모델로 개인정보를 먼저 가린 뒤 Claude에 보냄. 페이지가 많거나 GPU 사용량이 다 되면 Claude API로 처리. "
                     "Claude API: GPU 미사용(원본이 Claude로 전송되고, 가린 사본만 돌려줌).",
            )
            submit = gr.Button("쉽게 풀어주세요", variant="primary")
        with gr.Column(scale=1):
            status_out = gr.Markdown()
            with gr.Group():
                voice_text = gr.Textbox(label="🔊 음성 안내", interactive=False, lines=2)
                voice_speech = gr.Textbox(visible=False)
                audio_out = gr.Audio(label="음성 (무료 모델)", type="numpy", interactive=False, autoplay=False)
                speak_btn = gr.Button("🔊 브라우저로 읽기", size="sm")
            md_out = gr.Markdown(label="쉬운 말 풀이")
            gallery_out = gr.Gallery(label="처리한 문서 이미지 (개인정보 가림)", columns=3, height="auto")
            with gr.Accordion("정리 결과 JSON", open=False):
                json_out = gr.JSON()

    submit.click(
        explain_upload,
        [files_in, level_in, mode_in, options_in, key_in],
        [status_out, voice_text, voice_speech, audio_out, md_out, gallery_out, json_out],
        api_visibility="private",
    )
    speak_btn.click(None, [voice_speech], None, js=BROWSER_SPEAK_JS, api_visibility="private")
    gr.Markdown(
        "<small>올린 문서는 저장하지 않으며(임시 파일은 1시간 안에 삭제), 주민등록번호·휴대전화 번호는 결과에서 자동으로 가려집니다. "
        "무료 모델: EasyOCR(Apache-2.0), Swin2SR(Apache-2.0), MMS-TTS 한국어(CC-BY-NC-4.0, 비상업 무료). "
        "정리 결과는 참고용입니다. 납부 전에는 원본이나 기관 공식 홈페이지에서 금액과 기한을 확인하세요.</small>"
    )
    gr.api(explain_notice, api_name="explain_notice")

if __name__ == "__main__":
    demo.launch(mcp_server=True)
