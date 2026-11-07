"""앱·MCP 검증.

1) 가짜 Anthropic 클라이언트로 입력 변환 → structured outputs 호출 → 검증·마스킹 → 결과 조립
2) API 키 결정 (헤더 우선, 서버 키 + 하루 한도)
3) 실제로 Gradio 서버를 띄워 원격 MCP(streamable HTTP)로 툴 목록·호출·헤더 전달 확인
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
import pytest
from PIL import Image

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import app  # noqa: E402
import claude_util  # noqa: E402
from errors import ToolError  # noqa: E402

FAKE_OUTPUT = {
    "doc_type": "건강보험료 고지서", "issuer": "국민건강보험공단",
    "one_line_summary": "11월분 건강보험료 안내입니다.", "what_to_do": ["기한까지 보험료를 냅니다."],
    "deadline": "2099-12-10", "deadline_original_text": "12월 10일", "amount_krw": 87650,
    "amount_original_text": None, "payment_methods": ["자동이체"], "if_missed": None,
    "contact": "1577-1000 / 담당자 010-2222-3333", "glossary": [],
    "scam_signals": [], "unclear_parts": [],
}


class FakeMessages:
    def __init__(self, output, stop_reason="end_turn"):
        self.output, self.stop_reason, self.calls = output, stop_reason, []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        text = self.output if isinstance(self.output, str) else json.dumps(self.output, ensure_ascii=False)
        return SimpleNamespace(stop_reason=self.stop_reason, content=[SimpleNamespace(type="text", text=text)])


def _data_uri(kind: str = "image/png") -> str:
    if kind == "application/pdf":
        return "data:application/pdf;base64," + base64.b64encode(b"%PDF-1.4\n%test\n").decode()
    buf = io.BytesIO()
    Image.new("RGB", (800, 1100), "white").save(buf, format="PNG")
    return "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode()


@pytest.fixture
def files(tmp_path):
    img = tmp_path / "page1.png"
    Image.new("RGBA", (2400, 3400), (255, 255, 255, 255)).save(img)
    pdf = tmp_path / "page2.pdf"
    pdf.write_bytes(b"%PDF-1.4\n%test\n")
    return [str(img), str(pdf)]


@pytest.fixture
def fake(monkeypatch):
    messages = FakeMessages(FAKE_OUTPUT)
    seen = {}

    def fake_resolve(key):
        seen["key"] = key
        return SimpleNamespace(messages=messages)

    monkeypatch.setattr(app, "resolve_client", fake_resolve)
    messages.seen = seen
    return messages


# ---------- 1) 전체 흐름 ----------

def test_full_flow_uses_structured_outputs(files, fake):
    data = app.run_explain(files, app.file_block, "보통", "sk-ant-test")
    call = fake.calls[0]
    # Sonnet/Opus 5.5가 거부하는 강제 tool_choice를 쓰지 않는다
    assert "tool_choice" not in call and "tools" not in call
    fmt = call["output_config"]["format"]
    assert fmt["type"] == "json_schema"
    assert fmt["schema"]["additionalProperties"] is False
    assert fmt["schema"]["properties"]["glossary"]["items"]["additionalProperties"] is False
    assert call["system"].endswith(app.LEVEL_GUIDE["보통"])
    blocks = call["messages"][0]["content"]
    assert [b["type"] for b in blocks] == ["image", "document", "text"]
    img = Image.open(io.BytesIO(base64.b64decode(blocks[0]["source"]["data"])))
    assert max(img.size) == claude_util.MAX_SIDE

    assert data["contact"] == "1577-1000 / 담당자 010-****-3333"
    assert data["d_day"]["status"] == "upcoming"
    assert data["validation_warnings"] == ["기한 연도(2099년)가 예상 범위를 벗어납니다. 원본에서 연도를 확인하세요."]


def test_ui_function_outputs(files, fake):
    md, data = app.explain_upload(files, "아주 쉽게")
    assert md.startswith("## 건강보험료 고지서") and "87,650원" in md and "010-2222-3333" not in md
    assert fake.seen["key"] is None  # 웹 UI는 서버 데모 키
    assert data["amount_krw"] == 87650


def test_mcp_function_with_data_uri(fake):
    out = app.explain_notice([_data_uri(), _data_uri("application/pdf")], "보통", "sk-ant-test")
    assert out.startswith("## 건강보험료 고지서") and "```json" in out
    assert fake.seen["key"] == "sk-ant-test"
    assert [b["type"] for b in fake.calls[0]["messages"][0]["content"]] == ["image", "document", "text"]


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


def test_errors_become_gr_error(tmp_path, fake):
    with pytest.raises(gr.Error, match="1개 이상"):
        app.explain_notice([], "보통", None)
    with pytest.raises(gr.Error, match="1개 이상"):
        app.explain_upload(None, "보통")
    bad = tmp_path / "bad.jpg"
    bad.write_bytes(b"not an image")
    with pytest.raises(gr.Error, match="읽을 수 없습니다"):
        app.explain_upload([str(bad)], "보통")
    with pytest.raises(gr.Error, match="URL 또는 data: URI"):
        app.explain_notice([str(bad)], "보통", None)  # 원격 호출자는 서버 로컬 경로를 못 읽음
    assert fake.calls == []  # 파일 오류는 Claude를 부르기 전에 걸러짐


@pytest.mark.parametrize("stop, text, msg", [
    ("refusal", "{}", "거절"),
    ("max_tokens", '{"doc_type": "자', "잘렸습니다"),
    ("end_turn", "not json", "해석하지 못했습니다"),
])
def test_bad_responses(stop, text, msg):
    client = SimpleNamespace(messages=FakeMessages(text, stop_reason=stop))
    with pytest.raises(ToolError, match=msg):
        claude_util.call_structured(client, "s", [], app.NOTICE_SCHEMA)


# ---------- 2) API 키 결정 ----------

def test_resolve_client(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    with pytest.raises(ToolError, match="API 키가 없습니다"):
        claude_util.resolve_client(None)
    with pytest.raises(ToolError, match="API 키가 없습니다"):
        claude_util.resolve_client("   ")
    assert claude_util.resolve_client(" sk-ant-user ").api_key == "sk-ant-user"

    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-server")
    monkeypatch.setenv("DEMO_DAILY_LIMIT", "2")
    monkeypatch.setattr(claude_util, "_usage", {"date": None, "count": 0})
    assert claude_util.resolve_client(None).api_key == "sk-ant-server"
    assert claude_util.resolve_client("").api_key == "sk-ant-server"
    with pytest.raises(ToolError, match="한도"):
        claude_util.resolve_client(None)
    assert claude_util.resolve_client("sk-ant-user").api_key == "sk-ant-user"  # 본인 키는 한도 없음


# ---------- 3) 원격 MCP (실제 Gradio 서버) ----------

def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture
def server(fake, monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    port = _free_port()
    app.demo.launch(server_name="127.0.0.1", server_port=port, mcp_server=True, prevent_thread_lock=True, quiet=True)
    yield f"http://127.0.0.1:{port}"
    app.demo.close()


def test_remote_mcp(server, fake):
    from mcp import ClientSession
    from mcp.client.streamable_http import streamablehttp_client

    async def run(headers):
        async with streamablehttp_client(f"{server}/gradio_api/mcp/", headers=headers) as (r, w, _):
            async with ClientSession(r, w) as s:
                await s.initialize()
                tools = (await s.list_tools()).tools
                res = await s.call_tool("explain_notice", {"files": [_data_uri()], "reading_level": "보통"})
                return tools, res

    tools, res = asyncio.run(run({"X-Anthropic-Key": "sk-ant-from-header"}))
    names = [t.name for t in tools]
    assert names == ["explain_notice"]  # 웹 UI용 핸들러는 노출되지 않음
    tool = tools[names.index("explain_notice")]
    assert "x_anthropic_key" not in tool.inputSchema["properties"]  # 헤더는 툴 인자가 아님
    assert not res.isError, res.content
    text = "\n".join(c.text for c in res.content if c.type == "text")
    assert "건강보험료 고지서" in text and "010-****-3333" in text and "010-2222-3333" not in text
    assert fake.seen["key"] == "sk-ant-from-header"  # MCP 헤더가 그대로 전달됨
    blocks = fake.calls[-1]["messages"][0]["content"]
    assert blocks[0]["type"] == "image"  # data: URI가 이미지로 변환됨


def test_remote_mcp_without_key(server):
    """헤더도 서버 키도 없으면 친절한 오류가 MCP 툴 오류로 돌아온다 (가짜 클라이언트 미사용 경로)."""
    from mcp import ClientSession
    from mcp.client.streamable_http import streamablehttp_client

    app_resolve = app.resolve_client
    try:
        app.resolve_client = claude_util.resolve_client

        async def run():
            async with streamablehttp_client(f"{server}/gradio_api/mcp/") as (r, w, _):
                async with ClientSession(r, w) as s:
                    await s.initialize()
                    return await s.call_tool("explain_notice", {"files": [_data_uri()]})

        res = asyncio.run(run())
    finally:
        app.resolve_client = app_resolve
    assert res.isError
    assert "API 키가 없습니다" in res.content[0].text
