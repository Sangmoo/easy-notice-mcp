"""앱·처리 흐름·MCP 검증 (가짜 Claude + 가짜 GPU 모델).

1) 처리 방식(자동/GPU/Claude API) 선택과 GPU 실패 시 Claude 대체
2) 개인정보: GPU 방식은 Claude에 보내기 '전에' 가림, Claude 방식은 Claude 좌표로 공유용 사본만 가림
3) structured outputs 사용, API 키 필수, 입력 보안(로컬 경로·내부망 차단)
4) 웹 UI 출력, 음성(GPU/브라우저 대체)
5) 실제 Gradio 서버를 띄워 원격 MCP(streamable HTTP) 호출
"""
import asyncio
import base64
import io
import json
import socket
import sys
from pathlib import Path
from types import SimpleNamespace

import gradio as gr
import numpy as np
import pytest
from PIL import Image

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import app  # noqa: E402
import claude_util  # noqa: E402
import models  # noqa: E402
import pipeline  # noqa: E402
import quota as quota_mod  # noqa: E402
from errors import ToolError  # noqa: E402

FAKE_OUTPUT = {
    "doc_type": "건강보험료 고지서", "issuer": "국민건강보험공단",
    "one_line_summary": "11월분 건강보험료 안내입니다.", "what_to_do": ["기한까지 보험료를 냅니다."],
    "deadline": "2099-12-10", "deadline_original_text": "12월 10일", "amount_krw": 87650,
    "amount_original_text": None, "payment_methods": ["자동이체"], "if_missed": None,
    "contact": "1577-1000 / 담당자 010-2222-3333", "glossary": [],
    "scam_signals": [], "unclear_parts": [], "voice_summary": "건강보험료를 내라는 안내예요",
}
KEY = "sk-ant-test-key"
NOOP = lambda *a, **k: None  # noqa: E731 - gr.Progress 대신


def _png(w=1200, h=1600) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (w, h), "white").save(buf, format="PNG")
    return buf.getvalue()


def _pdf(pages=2) -> bytes:
    buf = io.BytesIO()
    imgs = [Image.new("RGB", (600, 800), "white") for _ in range(pages)]
    imgs[0].save(buf, "PDF", save_all=True, append_images=imgs[1:])
    return buf.getvalue()


def _data_uri(data: bytes, mime="image/png") -> str:
    return f"data:{mime};base64," + base64.b64encode(data).decode()


class FakeMessages:
    def __init__(self, output, stop_reason="end_turn"):
        self.output, self.stop_reason, self.calls = output, stop_reason, []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        text = self.output if isinstance(self.output, str) else json.dumps(self.output, ensure_ascii=False)
        return SimpleNamespace(stop_reason=self.stop_reason, content=[SimpleNamespace(type="text", text=text)])


@pytest.fixture
def claude(monkeypatch):
    """가짜 Claude. 받은 키는 claude.seen['key']에."""
    messages = FakeMessages(dict(FAKE_OUTPUT))
    messages.seen = {}
    real = claude_util.resolve_client

    def fake_resolve(key):
        real(key)  # 키 필수·형식 검사는 진짜 함수로
        messages.seen["key"] = key
        return SimpleNamespace(messages=messages)

    def fake_server_client():
        messages.seen["key"] = "OPERATOR"
        return SimpleNamespace(messages=messages)

    monkeypatch.setattr(pipeline, "resolve_client", fake_resolve)
    monkeypatch.setattr(pipeline, "server_client", fake_server_client)
    fresh = quota_mod.FreeQuota()
    monkeypatch.setattr(pipeline, "quota", fresh)
    monkeypatch.setattr(app, "quota", fresh)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("FREE_DAILY_PER_USER", raising=False)
    monkeypatch.delenv("FREE_DAILY_TOTAL", raising=False)
    messages.quota = fresh
    return messages


@pytest.fixture
def gpu(monkeypatch):
    """가짜 GPU 모델: 모든 페이지에서 (100,100)-(500,140)에 주민번호가 있다고 OCR."""
    calls = SimpleNamespace(prepare=[], fail=False)

    def prepare(images, flags, do_ocr):
        if calls.fail:
            raise RuntimeError("ZeroGPU quota exceeded")
        calls.prepare.append((len(images), list(flags), do_ocr))
        out = [im.resize((im.width * 2, im.height * 2)) if f else im for im, f in zip(images, flags)]
        ocr = [[([[100, 100], [500, 100], [500, 140], [100, 140]], "900101-1234567", 0.9)] if do_ocr else [] for _ in out]
        return out, ocr

    monkeypatch.setattr(models, "gpu_prepare", prepare)
    return calls


def _sent_images(call):
    return [Image.open(io.BytesIO(base64.b64decode(b["source"]["data"])))
            for b in call["messages"][0]["content"] if b["type"] == "image"]


# ---------- 1·2) 처리 방식과 개인정보 가림 ----------

def test_auto_gpu_redacts_before_sending(claude, gpu):
    out = pipeline.explain([(_png(), "a.png")], "보통", KEY)
    call = claude.calls[0]
    assert out.route == "gpu"
    assert gpu.prepare == [(1, [False], True)]
    # Claude가 받은 이미지에서 주민번호 자리가 이미 검게 칠해져 있다
    img = _sent_images(call)[0]
    sx = img.width / 1200
    assert np.asarray(img)[int(120 * sx), int(400 * sx)].max() < 40
    assert "미리 가린 부분" in call["system"] and "pii_regions" not in call["output_config"]["format"]["schema"]["properties"]
    assert "tool_choice" not in call and "tools" not in call
    assert call["output_config"]["effort"] == "low" and call["model"] == "claude-sonnet-5-5"
    assert any("1곳을 가린 뒤" in n for n in out.notes)
    assert out.voice["text"].startswith("건강보험료를 내라는 안내예요.")
    assert out.data["contact"] == "1577-1000 / 담당자 010-****-3333"


def test_low_res_photo_is_upscaled(claude, gpu):
    out = pipeline.explain([(_png(600, 800), "small.png")], "보통", KEY, redact=False)
    assert gpu.prepare == [(1, [True], False)]
    assert out.images[0].size == (1200, 1600)
    assert any("2배 확대" in n for n in out.notes)


def test_no_gpu_work_goes_straight_to_claude(claude, gpu):
    out = pipeline.explain([(_pdf(), "doc.pdf")], "보통", KEY, redact=False, enhance=True)
    assert out.route == "claude" and gpu.prepare == []
    assert [b["type"] for b in claude.calls[0]["messages"][0]["content"]] == ["document", "text"]  # PDF 원본 그대로


def test_pdf_pages_rendered_for_redaction(claude, gpu):
    out = pipeline.explain([(_pdf(3), "doc.pdf")], "보통", KEY)
    assert gpu.prepare == [(3, [False, False, False], True)]  # PDF 페이지는 확대하지 않음
    assert [b["type"] for b in claude.calls[0]["messages"][0]["content"]] == ["image"] * 3 + ["text"]
    assert len(out.images) == 3


def _claude_with_regions(claude):
    claude.output = {**FAKE_OUTPUT, "pii_regions": [
        {"page": 1, "box": [100, 100, 400, 150], "kind": "주민등록번호"},
        {"page": 9, "box": [0, 0, 10, 10], "kind": "이름"},
    ]}


def test_auto_falls_back_to_claude_when_gpu_fails(claude, gpu):
    gpu.fail = True
    _claude_with_regions(claude)
    out = pipeline.explain([(_png(), "a.png")], "보통", KEY)
    call = claude.calls[0]
    assert out.route == "claude"
    assert any("GPU를 지금 쓸 수 없어" in n for n in out.notes)
    assert "pii_regions" in call["output_config"]["format"]["schema"]["required"]
    assert "pii_regions" in call["system"]
    # Claude에는 원본이 갔고, 사용자 사본은 Claude 좌표로 가림
    assert np.asarray(_sent_images(call)[0]).min() > 200
    shared = np.asarray(out.images[0])
    assert shared[int(1600 * 0.125), int(1200 * 0.25)].max() < 40
    assert "pii_regions" not in out.data
    assert any("공유용 사본" in n and "1곳" in n for n in out.notes)


def test_gpu_mode_failure_is_an_error(claude, gpu):
    gpu.fail = True
    with pytest.raises(ToolError, match="GPU 처리에 실패"):
        pipeline.explain([(_png(), "a.png")], "보통", KEY, mode="무료 모델(GPU)")
    assert claude.calls == []


def test_claude_mode_never_uses_gpu(claude, gpu):
    _claude_with_regions(claude)
    out = pipeline.explain([(_png(), "a.png")], "보통", KEY, mode="Claude API")
    assert out.route == "claude" and gpu.prepare == []


def test_fast_mode_without_share_copy_is_lean(claude, gpu):
    """빠르게 + 공유용 사본 끔: GPU 없음, 좌표 요청 없음, PDF는 원본 그대로, 선택한 모델 사용."""
    out = pipeline.explain([(_pdf(2), "doc.pdf")], "보통", KEY, mode="Claude API", share_copy=False,
                           model="claude-haiku-5-5")
    call = claude.calls[0]
    assert gpu.prepare == [] and out.route == "claude"
    assert "pii_regions" not in call["output_config"]["format"]["schema"]["properties"]
    assert "pii_regions" not in call["system"]
    assert [b["type"] for b in call["messages"][0]["content"]] == ["document", "text"]
    assert call["model"] == "claude-haiku-5-5"
    assert any("원본을 Claude로 보냈어요" in n for n in out.notes)


def test_unknown_model_falls_back_to_default(claude, gpu):
    pipeline.explain([(_png(), "a.png")], "보통", KEY, mode="Claude API", share_copy=False, model="gpt-x")
    assert claude.calls[0]["model"] == "claude-sonnet-5-5"


def test_progress_steps(claude, gpu):
    steps = []
    pipeline.explain([(_png(), "a.png")], "보통", KEY, progress=lambda f, m: steps.append((f, m)))
    assert [m for _, m in steps][:3] == ["문서를 준비하는 중", "무료 모델(GPU)로 개인정보를 가리고 사진을 다듬는 중",
                                        "Claude가 문서를 읽고 정리하는 중"]
    assert [f for f, _ in steps] == sorted(f for f, _ in steps)


def test_auto_many_pages_use_claude(claude, gpu):
    _claude_with_regions(claude)
    out = pipeline.explain([(_pdf(5), "doc.pdf")], "보통", KEY)
    assert out.route == "claude" and gpu.prepare == []
    assert any("페이지가 많아(5쪽)" in n for n in out.notes)


@pytest.mark.parametrize("stop, text, msg", [
    ("refusal", "{}", "거절"),
    ("max_tokens", '{"doc_type": "자', "잘렸습니다"),
    ("end_turn", "not json", "해석하지 못했습니다"),
])
def test_bad_responses(stop, text, msg):
    client = SimpleNamespace(messages=FakeMessages(text, stop_reason=stop))
    with pytest.raises(ToolError, match=msg):
        claude_util.call_structured(client, "s", [], pipeline.schema_for(False))


# ---------- 3) 키·입력 ----------

def test_api_key_required(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-server-should-be-ignored")
    for missing in (None, "", "   "):
        with pytest.raises(ToolError, match="API 키가 필요합니다"):
            claude_util.resolve_client(missing)
    with pytest.raises(ToolError, match="형식"):
        claude_util.resolve_client("abc123")
    assert claude_util.resolve_client(" sk-ant-user ").api_key == "sk-ant-user"


@pytest.mark.parametrize("src, msg", [
    ("C:/Windows/win.ini", "URL 또는 data: URI"),
    ("/proc/self/environ", "URL 또는 data: URI"),
    ("file:///etc/passwd", "URL 또는 data: URI"),
    ("http://127.0.0.1:7860/x.png", "내부 네트워크"),
    ("http://169.254.169.254/latest/meta-data", "내부 네트워크"),
    ("http://10.0.0.5/a.pdf", "내부 네트워크"),
    ("http://localhost/a.png", "내부 네트워크"),
    ("data:image/png,notbase64", "base64"),
    ("", "URL 또는 data: URI"),
])
def test_fetch_source_rejects_unsafe(src, msg):
    with pytest.raises(ToolError, match=msg):
        claude_util.fetch_source(src)


# ---------- 4) 웹 UI·MCP 함수 ----------

def test_ui_outputs(tmp_path, claude, gpu):
    f = tmp_path / "a.png"
    f.write_bytes(_png())
    (col, status, card, vtext, vspeech, family, md, gallery, data,
     gcal, ics, print_page, quota_line) = app.explain_upload(
        [str(f)], "아주 쉽게", "자동", ["개인정보 가리기", "사진 보정"], "claude-sonnet-5-5", KEY, progress=NOOP)
    assert col["visible"] is True
    assert "가린 뒤" in status
    assert "건강보험료 고지서" in card and "87,650원" in card and 'href="tel:15771000"' in card
    assert vtext.startswith("건강보험료를 내라는 안내예요.") and "팔만 칠천육백오십 원" in vspeech
    assert family.startswith("[고지서 요약] 건강보험료 고지서") and "010" not in family
    assert gcal["visible"] and "https://calendar.google.com/" in gcal["value"] and 'target="_blank"' in gcal["value"]
    assert ics["visible"] and ics["value"].endswith(".ics")
    assert "<!doctype html>" in print_page
    assert len(gallery) == 1 and md.startswith("## 건강보험료 고지서") and "010-2222-3333" not in md
    assert "제한 없음" in quota_line  # 본인 키로 사용
    assert claude.seen["key"] == KEY


@pytest.mark.parametrize("key, doc, scam", [("car_tax", "자동차세 고지서 (예시)", False),
                                            ("scam_sms", "과태료 미납 안내 문자 (사기 의심 예시)", True)])
def test_examples_need_no_key(key, doc, scam, claude, gpu):
    """체험 모드: Claude·GPU·무료 횟수를 쓰지 않고 모든 결과 칸을 채운다."""
    out = app.show_example(key)
    (col, status, card, vtext, vspeech, family, md, gallery, data, gcal, ics, print_page, quota_line) = out
    assert col["visible"] and "예시 화면입니다" in status and "예시 화면입니다" in card
    assert doc in card and data["doc_type"] == doc and len(gallery) == 1
    assert ("사기일 수 있어요" in card) is scam and ('href="tel:112"' in card) is scam
    assert vtext and not any(c.isdigit() for c in vspeech)
    assert gcal["visible"] and ics["visible"] and "<!doctype html>" in print_page
    assert data["d_day"]["status"] == ("today" if scam else "upcoming")  # 기한은 오늘 기준으로 계산
    assert claude.calls == [] and gpu.prepare == [] and claude.quota.remaining("local") == 5


def test_app_mode_starts_fast():
    class Req:
        query_params = {"app": "1"}

    mode, level, model, options = app.load_prefs(dict(app.DEFAULT_PREFS), Req())
    assert mode["value"] == "Claude API" and options == ["사진 보정"]
    saved = app.save_prefs("자동", "보통", "claude-haiku-5-5", ["개인정보 가리기"])
    mode, *_ = app.load_prefs(saved, Req())  # 사용자가 고른 설정이 있으면 그대로
    assert mode["value"] == "자동"
    mode, *_ = app.load_prefs(dict(app.DEFAULT_PREFS), None)  # 웹은 자동
    assert mode["value"] == "자동"


def test_ui_without_deadline_hides_calendar(tmp_path, claude, gpu):
    claude.output = {**FAKE_OUTPUT, "deadline": None, "deadline_original_text": None}
    f = tmp_path / "a.png"
    f.write_bytes(_png())
    out = app.explain_upload([str(f)], "보통", "Claude API", [], "claude-sonnet-5-5", KEY, progress=NOOP)
    gcal, ics = out[9], out[10]
    assert gcal["visible"] is False and ics["visible"] is False


def test_key_memory():
    assert app.load_key({"key": "  sk-ant-saved "}) == ("sk-ant-saved", True)
    assert app.load_key(None) == ("", False)
    assert app.load_key("sk-ant-old-format") == ("", False)
    assert app.save_key(" sk-ant-x ", True) == {"key": "sk-ant-x"}
    assert app.save_key("sk-ant-x", False) == {"key": ""}  # 끄면 저장된 키를 지움 (빈 값도 객체로 저장)


def test_ui_errors(tmp_path, claude, gpu):
    with pytest.raises(gr.Error, match="사진을 찍거나 파일을 올려"):
        app.explain_upload(None, "보통", "자동", [], "claude-sonnet-5-5", KEY, progress=NOOP)
    f = tmp_path / "a.png"
    f.write_bytes(_png())
    with pytest.raises(gr.Error, match="API 키가 필요합니다"):
        app.explain_upload([str(f)], "보통", "자동", [], "claude-sonnet-5-5", "", progress=NOOP)
    bad = tmp_path / "bad.jpg"
    bad.write_bytes(b"not an image")
    with pytest.raises(gr.Error, match="읽을 수 없습니다"):
        app.explain_upload([str(bad)], "보통", "자동", [], "claude-sonnet-5-5", KEY, progress=NOOP)


def test_mode_switch_and_prefs():
    opts, info = app.on_mode_change("Claude API", ["개인정보 가리기", "음성 안내"])
    assert opts["value"] == ["음성 안내"] and "가장 빠릅니다" in info["info"]
    opts, _ = app.on_mode_change("자동", ["음성 안내"])
    assert opts["value"] == ["개인정보 가리기", "음성 안내"]
    mode, level, model, options = app.load_prefs(
        {"mode": "bogus", "level": "x", "model": "y", "options": ["z", "사진 보정"]})
    assert mode["value"] == "자동" and level == "아주 쉽게" and model == "claude-sonnet-5-5"
    assert options == ["사진 보정"]
    mode, *_ = app.load_prefs({"mode": "Claude API"})
    assert mode["value"] == "Claude API"
    assert app.save_prefs("Claude API", "보통", "claude-haiku-5-5", None)["options"] == []


def test_mcp_function(claude, gpu):
    out = app.explain_notice([_data_uri(_png()), _data_uri(_pdf(1), "application/pdf")], "보통", "자동", True, True,
                             "claude-sonnet-5-5", KEY)
    assert "### 🔊 음성 안내" in out and "## 건강보험료 고지서" in out and "```json" in out
    assert "[고지서 요약] 건강보험료 고지서" in out and "calendar.google.com" in out
    assert "가린 뒤" in out
    # 기본값은 빠르게(Claude API): GPU 없이, 좌표도 요청하지 않음
    claude.calls.clear()
    gpu.prepare.clear()
    app.explain_notice([_data_uri(_png())], x_anthropic_key=KEY)
    assert gpu.prepare == [] and "pii_regions" not in claude.calls[0]["system"]
    with pytest.raises(gr.Error, match="URL 또는 data: URI"):
        app.explain_notice(["/proc/self/environ"], x_anthropic_key=KEY)


# ---------- 5) 원격 MCP (실제 Gradio 서버) ----------

def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture
def server():
    port = _free_port()
    app.demo.launch(server_name="127.0.0.1", server_port=port, mcp_server=True, prevent_thread_lock=True, quiet=True)
    yield f"http://127.0.0.1:{port}"
    app.demo.close()


def _mcp(server, headers, args):
    from mcp import ClientSession
    from mcp.client.streamable_http import streamablehttp_client

    async def run():
        async with streamablehttp_client(f"{server}/gradio_api/mcp/", headers=headers) as (r, w, _):
            async with ClientSession(r, w) as s:
                await s.initialize()
                tools = (await s.list_tools()).tools
                return tools, await s.call_tool(tools[0].name, args)

    return asyncio.run(run())


def test_remote_mcp(server, claude, gpu):
    tools, res = _mcp(server, {"X-Anthropic-Key": KEY}, {"files": [_data_uri(_png())], "mode": "자동"})
    assert [t.name for t in tools] == ["explain_notice"]  # 웹 UI용 핸들러는 노출되지 않음
    props = tools[0].inputSchema["properties"]
    assert set(props) == {"files", "reading_level", "mode", "redact", "enhance", "model"}  # 키는 헤더로만
    assert props["mode"]["enum"] == ["Claude API", "자동", "무료 모델(GPU)"]
    assert props["mode"]["default"] == "Claude API"
    assert not res.isError, res.content
    text = res.content[0].text
    assert "건강보험료 고지서" in text and "010-****-3333" in text and "010-2222-3333" not in text
    assert claude.seen["key"] == KEY and gpu.prepare


def test_remote_mcp_without_key(server, claude, gpu, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-server-should-be-ignored")
    _, res = _mcp(server, {}, {"files": [_data_uri(_png())]})
    assert res.isError and "API 키가 필요합니다" in res.content[0].text
    assert claude.calls == [] and gpu.prepare == []



# ---------- 6) 운영자 키 무료 사용 ----------

def test_free_use_with_operator_key(claude, gpu, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-operator")
    out = pipeline.explain([(_png(), "a.png")], "보통", "", mode="Claude API", share_copy=False, free_user="1.1.1.1")
    assert claude.seen["key"] == "OPERATOR" and out.free_remaining == 4
    # 본인 키가 있으면 운영자 키·한도를 쓰지 않음
    out = pipeline.explain([(_png(), "a.png")], "보통", KEY, mode="Claude API", share_copy=False, free_user="1.1.1.1")
    assert claude.seen["key"] == KEY and out.free_remaining is None
    assert claude.quota.remaining("1.1.1.1") == 4


def test_free_use_limit_and_refund(claude, gpu, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-operator")
    claude.stop_reason = "refusal"  # Claude 단계 실패 → 횟수 돌려줌
    with pytest.raises(ToolError, match="거절"):
        pipeline.explain([(_png(), "a.png")], "보통", None, mode="Claude API", share_copy=False, free_user="1.1.1.1")
    assert claude.quota.remaining("1.1.1.1") == 5
    claude.stop_reason = "end_turn"
    for _ in range(5):
        pipeline.explain([(_png(), "a.png")], "보통", None, mode="Claude API", share_copy=False, free_user="1.1.1.1")
    n = len(claude.calls)
    with pytest.raises(ToolError, match="5번을 모두 쓰셨어요"):
        pipeline.explain([(b"not read", "x.png")], "보통", None, mode="Claude API", free_user="1.1.1.1")
    assert len(claude.calls) == n  # 한도 초과는 파일 읽기·Claude 호출 전에 막힘


def test_mcp_never_uses_operator_key(claude, gpu, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-operator")
    with pytest.raises(gr.Error, match="API 키가 필요합니다"):
        app.explain_notice([_data_uri(_png())], x_anthropic_key=None)
    assert claude.calls == []


def test_no_operator_key_requires_own_key(claude, gpu):
    with pytest.raises(ToolError, match="API 키가 필요합니다"):
        pipeline.explain([(_png(), "a.png")], "보통", "", free_user="1.1.1.1")


def test_ui_free_use_and_quota_text(tmp_path, claude, gpu, monkeypatch):
    f = tmp_path / "a.png"
    f.write_bytes(_png())
    assert "무료 사용을 할 수 없어요" in app.quota_text("", None)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-operator")
    assert app.quota_text("", None) == "오늘 무료로 **5번** 더 쓸 수 있어요."
    assert "제한 없음" in app.quota_text(KEY, None)
    out = app.explain_upload([str(f)], "보통", "Claude API", [], "claude-sonnet-5-5", "", progress=NOOP)
    assert claude.seen["key"] == "OPERATOR" and out[-1] == "오늘 무료로 **4번** 더 쓸 수 있어요."


def test_big_text_is_default():
    # 큰 글씨가 기본: '작게'를 고른 경우(html.small-text)에만 테마 크기로 돌아간다
    assert "html:not(.small-text) .gradio-container" in app.CSS and "--text-md: 21px" in app.CSS
    assert "html.big-text" not in app.CSS
    assert "notice-small-text" in app.LOAD_JS and "notice-small-text" in app.BIG_TEXT_JS
