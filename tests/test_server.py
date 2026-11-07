"""MCP 서버 검증.

1) 가짜 Anthropic 클라이언트로 입력 변환 → Claude 호출 → 검증·마스킹 → 결과 조립 전체 흐름
2) 실제 stdio 프로세스를 띄워 MCP 프로토콜(initialize / list_tools / call_tool 오류 경로) 확인
"""
import asyncio
import os
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
from PIL import Image

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "mcp_server"))

import claude_util  # noqa: E402
import server  # noqa: E402
from claude_util import ToolError  # noqa: E402

FAKE_OUTPUT = {
    "doc_type": "건강보험료 고지서", "issuer": "국민건강보험공단",
    "one_line_summary": "11월분 건강보험료 안내입니다.", "what_to_do": ["기한까지 보험료를 냅니다."],
    "deadline": "2099-12-10", "deadline_original_text": "12월 10일", "amount_krw": 87650,
    "amount_original_text": None, "payment_methods": ["자동이체"], "if_missed": None,
    "contact": "1577-1000 / 담당자 010-2222-3333", "glossary": [],
    "scam_signals": [], "unclear_parts": [], "extra": "버려져야 함",
}


class FakeMessages:
    def __init__(self, output):
        self.output, self.calls = output, []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        return SimpleNamespace(stop_reason="tool_use", content=[SimpleNamespace(type="tool_use", input=self.output)])


@pytest.fixture
def files(tmp_path):
    img = tmp_path / "page1.jpg"
    Image.new("RGB", (1200, 1700), "white").save(img)
    pdf = tmp_path / "page2.pdf"
    pdf.write_bytes(b"%PDF-1.4\n%test\n")
    return [str(img), str(pdf)]


@pytest.fixture
def fake(monkeypatch):
    messages = FakeMessages(FAKE_OUTPUT)
    monkeypatch.setattr(server, "resolve_client", lambda: SimpleNamespace(messages=messages))
    return messages


def test_full_flow(files, fake):
    data = server.run_explain(files, "보통")
    call = fake.calls[0]
    assert call["tool_choice"] == {"type": "tool", "name": "submit_explanation"}
    assert call["system"].endswith(server.LEVEL_GUIDE["보통"])
    blocks = call["messages"][0]["content"]
    assert [b["type"] for b in blocks] == ["image", "document", "text"]
    assert "오늘 날짜는" in blocks[-1]["text"]

    assert "extra" not in data
    assert data["contact"] == "1577-1000 / 담당자 010-****-3333"
    assert data["d_day"]["status"] == "upcoming"
    assert data["validation_warnings"] == ["기한 연도(2099년)가 예상 범위를 벗어납니다. 원본에서 연도를 확인하세요."]


def test_bad_level_and_cap(files, fake):
    server.run_explain(files * 4, "어렵게")
    call = fake.calls[0]
    assert call["system"].endswith(server.LEVEL_GUIDE["아주 쉽게"])
    assert len(call["messages"][0]["content"]) == 5 + 1


def test_tool_output(files, fake):
    out = server.explain_notice(files)
    assert out.startswith("## 건강보험료 고지서") and "87,650원" in out and "010-2222-3333" not in out


def test_errors(tmp_path, monkeypatch):
    with pytest.raises(ToolError, match="1개 이상"):
        server.run_explain([], "보통")
    with pytest.raises(ToolError, match="찾을 수 없습니다"):
        claude_util.file_block(str(tmp_path / "nope.pdf"))
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    with pytest.raises(ToolError, match="API 키가 없습니다"):
        claude_util.resolve_client()


def test_stdio_protocol(files):
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client

    env = {k: v for k, v in os.environ.items() if k != "ANTHROPIC_API_KEY"}
    params = StdioServerParameters(command=sys.executable, args=[str(ROOT / "mcp_server" / "server.py")], env=env)

    async def run():
        async with stdio_client(params) as (r, w):
            async with ClientSession(r, w) as s:
                await s.initialize()
                tools = (await s.list_tools()).tools
                res = await s.call_tool("explain_notice", {"files": files})
                return tools, res

    tools, res = asyncio.run(run())
    assert [t.name for t in tools] == ["explain_notice"]
    assert tools[0].input_schema["properties"]["reading_level"]["enum"] == ["아주 쉽게", "보통"]
    assert res.is_error and "API 키가 없습니다" in res.content[0].text
