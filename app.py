"""고지서·공문서 쉬운 말 풀이 — Gradio 앱 겸 원격 MCP 서버 (ZeroGPU).

Claude는 문서를 읽고 정리만 하고, D-day 계산·개인정보 마스킹·값 검증·결과 조립은 코드가 결정한다.
ZeroGPU의 무료 모델로 (1) 개인정보를 이미지에서 먼저 가리고 (2) 짧은 음성 안내를 만들고 (3) 흐린 사진을 보정한다.
사용자가 '⚡ 빠르게'를 고르면 처음부터 GPU 없이 Claude API로만 처리한다 (pipeline.py).
화면은 시니어가 쓰기 쉽게: 한눈에 카드, 듣기 버튼, 달력 등록, 가족에게 보내기, 큰 글씨·인쇄 (senior.py).
입력 문서와 결과는 로그로 남기지 않는다 (민감 문서).

- 웹 UI: explain_upload(결과) → 버튼마다 따로(make_voice 등). API·MCP에는 노출하지 않음
- MCP 툴: explain_notice (gr.api) — 파일을 http(s) URL 또는 data: URI 문자열로 받는다. 기본은 빠르게(Claude API).
  gr.File(file_count="multiple")을 그대로 MCP에 노출하면 Gradio 6.31이 만드는 입력 스키마의
  $ref(#/$defs/FileData)가 깨져 있어 MCP 호출이 전부 검증 오류로 실패하기 때문에 분리했다.
"""
from __future__ import annotations

import models  # noqa: I001 - spaces를 torch·gradio보다 먼저 불러오고 ZeroGPU 모델을 올린다

import json
import os
from typing import Literal

import gradio as gr

import examples
import pipeline
import senior
import web_routes
from claude_util import MODELS, fetch_source, read_upload, server_key, today_kst
from errors import ToolError
from logic import LEVELS, MAX_FILES, render
from quota import client_ip, quota


def _report(outcome: pipeline.Outcome) -> str:
    return "\n".join(f"- {n}" for n in outcome.notes)


# ---------- MCP 툴 ----------

def explain_notice(
    files: list[str],
    reading_level: Literal["아주 쉽게", "보통"] = "아주 쉽게",
    mode: Literal["Claude API", "자동", "무료 모델(GPU)"] = "Claude API",
    redact: bool = True,
    enhance: bool = True,
    model: Literal["claude-sonnet-5-5", "claude-haiku-5-5"] = "claude-sonnet-5-5",
    x_anthropic_key: gr.Header = None,
) -> str:
    """세금 고지서, 건강보험·국민연금 안내문, 과태료 통지서, 관공서 공문 등을 쉬운 말로 풀어 해야 할 일, 기한(D-day), 금액, 사기 의심 신호를 정리하고, 짧은 음성 안내 문장·가족에게 보낼 요약·구글 캘린더 등록 링크를 만듭니다. MCP 연결 설정의 X-Anthropic-Key 헤더에 본인 Anthropic API 키가 필요합니다.

    Args:
        files: 문서 사진 또는 PDF 1~5개. 각 항목은 공개 http(s) URL 또는 data: URI(예: "data:image/jpeg;base64,..." / "data:application/pdf;base64,..."). 여러 장짜리 문서는 모든 페이지를 함께 넣으세요.
        reading_level: 설명 난이도. "아주 쉽게"(어르신·아이도 이해 가능) 또는 "보통".
        mode: 처리 방식. "Claude API"(기본, 가장 빠름: GPU 미사용, 원본이 Claude로 전송), "자동"(무료 GPU 모델로 개인정보를 먼저 가린 뒤 전송, GPU를 못 쓰면 Claude API로), "무료 모델(GPU)".
        redact: GPU 방식에서 주민번호·전화번호·계좌번호·이름·주소를 이미지에서 먼저 가릴지 여부.
        enhance: 사진 원근·대비 보정과 (GPU 방식) 저해상도 사진 2배 확대를 할지 여부.
        model: Claude 모델. "claude-sonnet-5-5"(정확, 기본) 또는 "claude-haiku-5-5"(빠르고 저렴).

    Returns:
        처리 방식 안내, 짧은 음성 안내 문장, 가족에게 보낼 요약, 구글 캘린더 등록 링크(기한이 있을 때), 읽기 쉽게 정리된 설명(마크다운), 구조화된 결과 JSON. 주민등록번호·휴대전화 번호는 결과에서 가려집니다.
    """
    try:
        items = [fetch_source(s) for s in list(files or [])[:MAX_FILES]]
        # MCP는 이미지를 돌려주지 않으므로 공유용 가린 사본은 만들지 않는다 (더 빠름)
        out = pipeline.explain(items, reading_level, x_anthropic_key, mode, redact, enhance,
                               share_copy=False, model=model)
    except ToolError as e:
        raise gr.Error(str(e), print_exception=False) from None
    report = _report(out)
    gcal = senior.google_calendar_url(out.data)
    return (
        (f"### 처리 방식\n{report}\n\n" if report else "")
        + f"### 🔊 음성 안내\n{out.voice['text']}\n\n"
        + f"### 👨‍👩‍👧 가족에게 보낼 요약\n```\n{senior.family_text(out.data)}\n```\n\n"
        + (f"### 📅 [구글 캘린더에 기한 추가]({gcal})\n\n" if gcal else "")
        + render(out.data)
        + "\n\n## 정리 결과 JSON\n\n```json\n" + json.dumps(out.data, ensure_ascii=False, indent=2) + "\n```"
    )


# ---------- 웹 UI: 설정 ----------

OPT_REDACT, OPT_ENHANCE = "개인정보 가리기", "사진 보정"
ALL_OPTIONS = [OPT_REDACT, OPT_ENHANCE]
MODE_CHOICES = [
    ("⚡ 빠르게 (Claude API, GPU 안 씀)", pipeline.CLAUDE),
    ("자동 (무료 GPU로 개인정보 먼저 가림)", pipeline.AUTO),
    ("무료 모델(GPU)만", pipeline.GPU),
]
MODE_INFO = {
    pipeline.CLAUDE: "가장 빠릅니다. GPU를 쓰지 않고 원본이 Claude로 전송돼요. "
                     "'개인정보 가리기'를 켜면 가린 공유용 사본도 만들어요(조금 느려짐).",
    pipeline.AUTO: "무료 GPU 모델로 개인정보를 먼저 가린 뒤 Claude에 보내요. GPU 대기 때문에 느릴 수 있고, "
                   "페이지가 많거나 GPU 사용량이 다 되면 빠르게 방식으로 바뀌어요.",
    pipeline.GPU: "항상 무료 GPU 모델을 써요. GPU를 쓸 수 없으면 오류로 알려 줘요.",
}
DEFAULT_PREFS = {"mode": pipeline.AUTO, "level": LEVELS[0], "model": "claude-sonnet-5-5", "options": ALL_OPTIONS,
                 "saved": False}
# 안드로이드 앱(시작 주소 /?app=1)은 GPU 하루 사용량이 적은 비로그인 상태라 처음엔 빠르게 방식으로 연다
APP_DEFAULT = {"mode": pipeline.CLAUDE, "options": [OPT_ENHANCE]}
KEY_STORE_SECRET = os.getenv("KEY_STORE_SECRET", "easy-notice-key-v1")


def load_prefs(prefs, request: gr.Request = None):
    p = {**DEFAULT_PREFS, **(prefs or {})}
    if not p.get("saved") and _is_app(request):
        p.update(APP_DEFAULT)
    mode = p["mode"] if p["mode"] in pipeline.MODES else DEFAULT_PREFS["mode"]
    level = p["level"] if p["level"] in LEVELS else DEFAULT_PREFS["level"]
    model = p["model"] if p["model"] in MODELS else DEFAULT_PREFS["model"]
    options = [o for o in (p["options"] or []) if o in ALL_OPTIONS]
    return gr.update(value=mode, info=MODE_INFO[mode]), level, model, options


def save_prefs(mode, level, model, options):
    return {"mode": mode, "level": level, "model": model, "options": list(options or []), "saved": True}


def on_mode_change(mode, options):
    """빠르게로 바꾸면 공유용 사본(느려짐)은 기본으로 끄고, 다른 방식이면 개인정보 가리기를 다시 켠다."""
    options = list(options or [])
    if mode == pipeline.CLAUDE:
        options = [o for o in options if o != OPT_REDACT]
    elif OPT_REDACT not in options:
        options = [OPT_REDACT, *options]
    return gr.update(value=options), gr.update(info=MODE_INFO.get(mode, ""))


def _is_app(request: gr.Request | None) -> bool:
    try:
        return request is not None and request.query_params.get("app") == "1"
    except AttributeError:
        return False


def load_key(stored):
    """가족이 '이 기기에 키 기억하기'로 저장해 둔 키를 채운다."""
    key = ((stored or {}).get("key") or "").strip() if isinstance(stored, dict) else ""
    return key, bool(key)


def save_key(key, remember):
    # 빈 문자열은 BrowserState가 저장하지 않아 '기억 끄기'가 반영되지 않으므로 항상 객체로 저장한다
    return {"key": (key or "").strip() if remember else ""}


# ---------- 웹 UI: 동작 ----------

def _user_id(request: gr.Request | None) -> str:
    if request is None:
        return "local"
    return client_ip(dict(request.headers), request.client.host if request.client else None)


def quota_text(api_key: str | None, request: gr.Request | None) -> str:
    """제출 버튼 아래 안내: 오늘 남은 무료 횟수 / 내 키 사용 중."""
    if (api_key or "").strip():
        return "🔑 내 키로 쓰는 중이에요 (횟수 제한 없음)"
    if server_key() is None:
        return "⚠️ 지금은 무료 사용을 할 수 없어요. '더보기 설정'에 Anthropic 키를 넣어 주세요."
    return f"오늘 무료로 **{quota.remaining(_user_id(request))}번** 더 쓸 수 있어요."


def explain_upload(files, reading_level, mode, options, model, api_key, request: gr.Request = None,
                   progress=gr.Progress()):
    """결과를 보여 준다. 음성은 '듣기'를 눌렀을 때만 만든다 (make_voice).

    본인 키가 없으면 운영자 키로 무료 처리한다 (IP당 하루 한도).
    """
    options = options or []
    try:
        if not files:
            raise ToolError("고지서 사진을 찍거나 파일을 올려 주세요.")
        items = [read_upload(p) for p in list(files)[:MAX_FILES]]
        out = pipeline.explain(
            items, reading_level, api_key, mode,
            redact=OPT_REDACT in options,
            enhance=OPT_ENHANCE in options,
            share_copy=OPT_REDACT in options,
            model=model,
            progress=lambda frac, msg: progress(frac, desc=msg),
            free_user=_user_id(request),
        )
    except ToolError as e:
        raise gr.Error(str(e), print_exception=False) from None
    gcal = senior.google_calendar_url(out.data)
    ics = senior.write_ics(out.data)
    return (
        gr.update(visible=True),                               # 결과 영역
        _report(out),                                          # 처리 정보
        senior.card_html(out.data),                            # 한눈에 카드
        out.voice["text"],                                     # 읽어 줄 내용
        out.voice["speech"],                                   # (숨김) TTS용 문장
        senior.family_text(out.data),                          # 가족에게 보낼 요약
        render(out.data),                                      # 자세한 설명
        out.images,                                            # 처리한 이미지
        out.data,                                              # JSON
        gr.update(value=senior.calendar_button_html(gcal), visible=bool(gcal)),  # 구글 캘린더 (새 탭)
        gr.update(value=ics, visible=bool(ics)),               # .ics
        senior.print_html(out.data),                           # (숨김) 인쇄용 HTML
        quota_text(api_key, request),                          # 남은 무료 횟수
    )


def show_example(key: str):
    """체험 모드: 키 없이, Claude를 부르지 않고 예시 결과를 보여 준다 (무료 횟수도 쓰지 않음)."""
    data, images, voice = examples.load(key, today_kst())
    gcal = senior.google_calendar_url(data)
    banner = ('<div style="background:#fff6e0;color:#5a3d00;border:2px solid #e8b84a;border-radius:12px;'
              'padding:.6em 1em;margin-bottom:.6em;font-weight:700">' + examples.DEMO_NOTE + "</div>")
    return (
        gr.update(visible=True),
        "- " + examples.DEMO_NOTE,
        banner + senior.card_html(data),
        voice["text"],
        voice["speech"],
        senior.family_text(data),
        render(data),
        images,
        data,
        gr.update(value=senior.calendar_button_html(gcal), visible=bool(gcal)),
        gr.update(value=senior.write_ics(data), visible=bool(gcal)),
        senior.print_html(data),
        gr.update(),  # 무료 횟수 안내는 그대로
    )


# ---------- 웹 UI: 브라우저 쪽 동작 (JS) ----------

LOAD_JS = """
() => {
  try { if (localStorage.getItem('notice-big-text') === '1') document.documentElement.classList.add('big-text'); } catch (e) {}
  return [];
}
"""

BIG_TEXT_JS = """
() => {
  const on = document.documentElement.classList.toggle('big-text');
  try { localStorage.setItem('notice-big-text', on ? '1' : '0'); } catch (e) {}
  return [];
}
"""

CAMERA_JS = """
() => {
  const root = document.getElementById('files-in');
  const input = root && root.querySelector('input[type=file]');
  if (!input) return [];
  const accept = input.getAttribute('accept');
  input.setAttribute('capture', 'environment');   // 휴대폰에서는 카메라가 바로 열림
  input.setAttribute('accept', 'image/*');
  input.click();
  setTimeout(() => { input.removeAttribute('capture'); if (accept) input.setAttribute('accept', accept); }, 1500);
  return [];
}
"""

SPEAK_JS = """
(text, slow) => {
  if (!text) return [];
  if (!window.speechSynthesis) { alert('이 기기에서는 소리 내어 읽기를 지원하지 않아요.'); return []; }
  window.speechSynthesis.cancel();
  const u = new SpeechSynthesisUtterance(text);
  u.lang = 'ko-KR';
  u.rate = slow ? 0.75 : 0.95;
  const ko = window.speechSynthesis.getVoices().find(v => v.lang && v.lang.startsWith('ko'));
  if (ko) u.voice = ko;
  window.speechSynthesis.speak(u);
  return [];
}
"""

STOP_JS = """
() => {
  if (window.speechSynthesis) window.speechSynthesis.cancel();
  document.querySelectorAll('audio').forEach(a => a.pause());
  return [];
}
"""

SHARE_JS = """
async (text) => {
  if (!text) return [];
  try {
    if (navigator.share) { await navigator.share({ title: '고지서 요약', text }); return []; }
  } catch (e) { if (e && e.name === 'AbortError') return []; }
  try {
    await navigator.clipboard.writeText(text);
    alert('요약을 복사했어요. 카카오톡이나 문자에 붙여넣어 보내세요.');
  } catch (e) {
    alert('복사하지 못했어요. 요약 글을 길게 눌러 직접 복사해 주세요.');
  }
  return [];
}
"""

PRINT_JS = """
(html) => {
  if (!html) return [];
  const w = window.open('', '_blank');
  if (!w) { alert('새 창이 막혀 있어요. 팝업을 허용한 뒤 다시 눌러 주세요.'); return []; }
  w.document.open(); w.document.write(html); w.document.close();
  setTimeout(() => { w.focus(); w.print(); }, 400);
  return [];
}
"""

# 글자 크기는 Gradio 테마 변수(--text-*)를 따라가게 하고, '글씨 크게'는 그 변수만 키운다.
# (테마가 변수를 .gradio-container에 정의하므로 거기서 !important로 덮어쓴다)
CSS = """
.big-btn { font-size: calc(var(--text-lg) * 1.2) !important; min-height: 3.2em !important; font-weight: 700 !important; }
#steps { font-size: calc(var(--text-md) * 1.15); }
.nc { font-size: calc(var(--text-md) * 1.3); }
html.big-text .gradio-container {
  --text-xxs: 14px !important; --text-xs: 16px !important; --text-sm: 18px !important; --text-md: 21px !important;
  --text-lg: 24px !important; --text-xl: 28px !important; --text-xxl: 34px !important;
  --block-label-text-size: 18px !important; --block-info-text-size: 17px !important;
  --checkbox-label-text-size: 20px !important; --button-large-text-size: 24px !important;
  --input-text-size: 21px !important; --prose-text-size: 21px !important;
}
"""

# ---------- 웹 UI: 화면 ----------

with gr.Blocks(title="고지서 쉬운 말 풀이", delete_cache=(1800, 3600)) as demo:
    prefs = gr.BrowserState(DEFAULT_PREFS, storage_key="easy-notice-prefs", secret="easy-notice-prefs-v1")
    key_store = gr.BrowserState({"key": ""}, storage_key="easy-notice-key-v2", secret=KEY_STORE_SECRET)

    with gr.Row(equal_height=True):
        gr.Markdown("# 📮 고지서 쉬운 말 풀이")
        big_text_btn = gr.Button("🔍 글씨 크게 / 작게", size="sm", scale=0, min_width=160)
    gr.Markdown(
        "**① 고지서 사진을 찍거나 올리고 → ② '쉽게 풀어주세요'를 누르세요.**  \n"
        "무엇을, 언제까지, 얼마를 해야 하는지 쉽게 정리해 드려요.",
        elem_id="steps",
    )

    with gr.Row():
        with gr.Column(scale=1):
            camera_btn = gr.Button("📷 사진 찍기", elem_classes="big-btn")
            files_in = gr.File(
                label=f"또는 사진·PDF 파일 올리기 (여러 장이면 모두, 최대 {MAX_FILES}개)",
                file_count="multiple",
                file_types=["image", ".pdf"],
                type="filepath",
                elem_id="files-in",
            )
            gr.Markdown("📸 **잘 찍는 요령**: 밝은 곳에서, 종이 네 모서리가 다 보이게, 흔들리지 않게 찍어 주세요.")
            submit = gr.Button("쉽게 풀어주세요", variant="primary", elem_classes="big-btn")
            quota_md = gr.Markdown()
            gr.Markdown("처음이라면 예시로 먼저 살펴보세요 (키·횟수 없이 바로 볼 수 있어요).")
            with gr.Row():
                ex_car_btn = gr.Button("📄 예시: 자동차세 고지서")
                ex_scam_btn = gr.Button("📄 예시: 사기 의심 문자")
            with gr.Accordion("⚙️ 더보기 설정", open=False):
                key_in = gr.Textbox(
                    label="내 Anthropic 키로 제한 없이 쓰기 (선택)",
                    type="password",
                    placeholder="sk-ant-...",
                    info="키가 없어도 하루 몇 번은 무료로 쓸 수 있어요. 키를 넣으면 횟수 제한 없이 쓰고, "
                         "비용은 키 주인 계정에 청구돼요. 요청 처리에만 쓰고 서버에 저장하지 않아요.",
                )
                remember_in = gr.Checkbox(
                    False, label="이 기기에 키 기억하기",
                    info="가족이 어르신 휴대폰에 한 번 넣어 두면 다음부터 다시 넣지 않아도 돼요. "
                         "여러 사람이 쓰는 PC에서는 켜지 마세요.",
                )
                mode_in = gr.Radio(MODE_CHOICES, value=DEFAULT_PREFS["mode"], label="처리 방식",
                                   info=MODE_INFO[DEFAULT_PREFS["mode"]])
                options_in = gr.CheckboxGroup(ALL_OPTIONS, value=DEFAULT_PREFS["options"], label="추가 기능")
                level_in = gr.Radio(LEVELS, value=DEFAULT_PREFS["level"], label="설명 난이도")
                model_in = gr.Radio([(label, mid) for mid, label in MODELS.items()],
                                    value=DEFAULT_PREFS["model"], label="Claude 모델")
                gr.Markdown("<small>여기서 고른 설정은 이 브라우저에 기억돼요.</small>")

        with gr.Column(scale=1, visible=False) as result_col:
            card_out = gr.HTML()
            with gr.Row():
                listen_btn = gr.Button("🔊 듣기", variant="primary", elem_classes="big-btn")
                stop_btn = gr.Button("⏹ 멈추기", elem_classes="big-btn")
            slow_in = gr.Checkbox(False, label="천천히 읽기")
            voice_text = gr.Textbox(label="읽어 줄 내용", interactive=False, lines=2)
            with gr.Row():
                gcal_btn = gr.HTML(visible=False)  # 새 탭으로 여는 링크 버튼
                ics_btn = gr.DownloadButton("📥 달력 파일 받기 (아이폰 등)", visible=False, elem_classes="big-btn")
            family_out = gr.Textbox(label="👨‍👩‍👧 가족에게 보낼 요약", lines=6, interactive=False, buttons=["copy"])
            with gr.Row():
                share_btn = gr.Button("📤 카카오톡·문자로 보내기", elem_classes="big-btn")
                print_btn = gr.Button("🖨 큰 글씨로 인쇄", elem_classes="big-btn")
            gr.Markdown("### 📖 자세한 설명")
            md_out = gr.Markdown()
            with gr.Accordion("처리 정보·문서 이미지", open=False):
                status_out = gr.Markdown()
                gallery_out = gr.Gallery(label="처리한 문서 이미지 (개인정보 가림)", columns=3, height="auto")
                with gr.Accordion("정리 결과 JSON", open=False):
                    json_out = gr.JSON()

    # 화면에 보이지 않는 값
    voice_speech = gr.Textbox(visible=False)
    print_store = gr.Textbox(visible=False)

    gr.Markdown(
        "<small>올린 문서는 저장하지 않으며(임시 파일은 1시간 안에 삭제), 주민등록번호·휴대전화 번호는 결과에서 자동으로 가려집니다. "
        "정부·공공기관 앱이 아닙니다. <a href='/privacy' target='_blank'>개인정보처리방침</a> · "
        "무료 모델: EasyOCR(Apache-2.0), Swin2SR(Apache-2.0), 글꼴 Noto Sans KR(OFL). 음성은 기기 내장 음성을 씁니다. "
        "정리 결과는 참고용입니다. 납부 전에는 원본이나 기관 공식 홈페이지에서 금액과 기한을 확인하세요. "
        "원격 MCP 연결은 아래 'Use via API or MCP'에서 안내합니다.</small>"
    )

    private = {"api_visibility": "private"}
    instant = {**private, "queue": False}  # 설정 불러오기·저장처럼 가벼운 일은 대기열을 건너뜀
    demo.load(None, None, None, js=LOAD_JS, **private)
    demo.load(load_prefs, [prefs], [mode_in, level_in, model_in, options_in], **instant)
    demo.load(load_key, [key_store], [key_in, remember_in], **instant).then(
        quota_text, [key_in], [quota_md], **instant)
    key_in.change(quota_text, [key_in], [quota_md], **instant)
    big_text_btn.click(None, None, None, js=BIG_TEXT_JS, **private)
    camera_btn.click(None, None, None, js=CAMERA_JS, **private)

    mode_in.input(on_mode_change, [mode_in, options_in], [options_in, mode_in], **instant)
    for comp in (mode_in, level_in, model_in, options_in):
        comp.change(save_prefs, [mode_in, level_in, model_in, options_in], [prefs], **instant)
    for comp in (key_in, remember_in):
        comp.change(save_key, [key_in, remember_in], [key_store], **instant)

    submit.click(
        explain_upload,
        [files_in, level_in, mode_in, options_in, model_in, key_in],
        [result_col, status_out, card_out, voice_text, voice_speech, family_out, md_out, gallery_out, json_out,
         gcal_btn, ics_btn, print_store, quota_md],
        **private,
    )
    result_outputs = [result_col, status_out, card_out, voice_text, voice_speech, family_out, md_out, gallery_out,
                      json_out, gcal_btn, ics_btn, print_store, quota_md]
    ex_car_btn.click(lambda: show_example("car_tax"), None, result_outputs, **instant)
    ex_scam_btn.click(lambda: show_example("scam_sms"), None, result_outputs, **instant)
    listen_btn.click(None, [voice_speech, slow_in], None, js=SPEAK_JS, **private)  # 기기 내장 음성 (서버·GPU 안 씀)
    stop_btn.click(None, None, None, js=STOP_JS, **private)
    share_btn.click(None, [family_out], None, js=SHARE_JS, **private)
    print_btn.click(None, [print_store], None, js=PRINT_JS, **private)

    gr.api(explain_notice, api_name="explain_notice")

if __name__ == "__main__":
    app, _, _ = demo.launch(
        mcp_server=True, css=CSS, pwa=True, favicon_path="static/icon-192.png", prevent_thread_lock=True,
    )
    web_routes.install(app)  # /manifest.json, /privacy, /.well-known/assetlinks.json, 아이콘
    demo.block_thread()
