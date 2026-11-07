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

    monkeypatch.setattr(pipeline, "resolve_client", fake_resolve)
    return messages


@pytest.fixture
def gpu(monkeypatch):
    """가짜 GPU 모델: 모든 페이지에서 (100,100)-(500,140)에 주민번호가 있다고 OCR."""
    calls = SimpleNamespace(prepare=[], tts=[], fail=False)

    def prepare(images, flags, do_ocr):
        if calls.fail:
            raise RuntimeError("ZeroGPU quota exceeded")
        calls.prepare.append((len(images), list(flags), do_ocr))
        out = [im.resize((im.width * 2, im.height * 2)) if f else im for im, f in zip(images, flags)]
        ocr = [[([[100, 100], [500, 100], [500, 140], [100, 140]], "900101-1234567", 0.9)] if do_ocr else [] for _ in out]
        return out, ocr

    def tts(speech):
        if calls.fail:
            raise RuntimeError("ZeroGPU quota exceeded")
        calls.tts.append(speech)
        return 16000, np.zeros(1600, dtype=np.float32)

    monkeypatch.setattr(models, "gpu_prepare", prepare)
    monkeypatch.setattr(models, "gpu_tts", tts)
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
    assert pipeline.speak(out, "Claude API") == (None, "Claude API 방식에서는 '🔊 브라우저로 읽기'로 들어 주세요.")
    assert gpu.tts == []


def test_auto_many_pages_use_claude(claude, gpu):
    _claude_with_regions(claude)
    out = pipeline.explain([(_pdf(5), "doc.pdf")], "보통", KEY)
    assert out.route == "claude" and gpu.prepare == []
    assert any("페이지가 많아(5쪽)" in n for n in out.notes)


def test_speak(claude, gpu):
    out = pipeline.explain([(_png(), "a.png")], "보통", KEY)
    audio, note = pipeline.speak(out, "자동")
    assert audio[0] == 16000 and note is None
    assert gpu.tts == [out.voice["speech"]] and not any(c.isdigit() for c in gpu.tts[0])
    gpu.fail = True
    assert pipeline.speak(out, "자동")[0] is None


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
    status, vtext, vspeech, audio, md, gallery, data = app.explain_upload(
        [str(f)], "아주 쉽게", "자동", ["개인정보 가리기", "사진 보정", "음성 안내"], KEY)
    assert "가린 뒤" in status
    assert vtext.startswith("건강보험료를 내라는 안내예요.") and "팔만 칠천육백오십 원" in vspeech
    assert audio[0] == 16000 and len(gallery) == 1
    assert md.startswith("## 건강보험료 고지서") and "010-2222-3333" not in md
    assert claude.seen["key"] == KEY


def test_ui_errors(tmp_path, claude, gpu):
    with pytest.raises(gr.Error, match="1개 이상"):
        app.explain_upload(None, "보통", "자동", [], KEY)
    f = tmp_path / "a.png"
    f.write_bytes(_png())
    with pytest.raises(gr.Error, match="API 키가 필요합니다"):
        app.explain_upload([str(f)], "보통", "자동", [], "")
    bad = tmp_path / "bad.jpg"
    bad.write_bytes(b"not an image")
    with pytest.raises(gr.Error, match="읽을 수 없습니다"):
        app.explain_upload([str(bad)], "보통", "자동", [], KEY)


def test_mcp_function(claude, gpu):
    out = app.explain_notice([_data_uri(_png()), _data_uri(_pdf(1), "application/pdf")], "보통", "자동", True, True, KEY)
    assert "### 🔊 음성 안내" in out and "## 건강보험료 고지서" in out and "```json" in out
    assert "가린 뒤" in out
    with pytest.raises(gr.Error, match="URL 또는 data: URI"):
        app.explain_notice(["/proc/self/environ"], "보통", "자동", True, True, KEY)


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
    assert set(props) == {"files", "reading_level", "mode", "redact", "enhance"}  # 키는 헤더로만
    assert props["mode"]["enum"] == ["자동", "무료 모델(GPU)", "Claude API"]
    assert not res.isError, res.content
    text = res.content[0].text
    assert "건강보험료 고지서" in text and "010-****-3333" in text and "010-2222-3333" not in text
    assert claude.seen["key"] == KEY and gpu.prepare


def test_remote_mcp_without_key(server, claude, gpu, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-server-should-be-ignored")
    _, res = _mcp(server, {}, {"files": [_data_uri(_png())]})
    assert res.isError and "API 키가 필요합니다" in res.content[0].text
    assert claude.calls == [] and gpu.prepare == []
