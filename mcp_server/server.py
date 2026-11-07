"""고지서·공문서 쉬운 말 풀이 — 로컬 stdio MCP 서버.

실행: python mcp_server/server.py   (Claude Desktop 등 MCP 클라이언트가 실행)
Claude는 문서를 읽고 정리만 하고, D-day 계산·개인정보 마스킹·결과 조립은 코드가 결정한다.
입력·결과는 로그로 남기지 않는다 (민감 문서).
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Annotated, Literal

from pydantic import Field

sys.path.insert(0, str(Path(__file__).resolve().parent))

from mcp.server import MCPServer  # noqa: E402
from mcp.server.mcpserver.exceptions import ToolError as MCPToolError  # noqa: E402

from claude_util import ToolError, call_structured, file_block, resolve_client, today_kst  # noqa: E402
from logic import LEVELS, MAX_FILES, finalize, render  # noqa: E402
from prompts import LEVEL_GUIDE, NOTICE_SCHEMA, SYSTEM_PROMPT_BASE, TOOL_DESCRIPTION, TOOL_NAME  # noqa: E402
from validate import normalize  # noqa: E402

server = MCPServer(
    name="easy-notice",
    title="고지서·공문서 쉬운 말 풀이",
    instructions="고지서·공문 사진이나 PDF(로컬 파일 경로 또는 URL)를 쉬운 말로 풀어 할 일·기한·금액·사기 신호를 정리한다.",
    version="1.0.0",
)


def run_explain(files: list[str], reading_level: str) -> dict:
    if not files:
        raise ToolError("문서 사진이나 PDF를 1개 이상 넣어주세요.")
    if reading_level not in LEVEL_GUIDE:
        reading_level = LEVELS[0]

    client = resolve_client()
    today = today_kst()
    content = [file_block(p) for p in files[:MAX_FILES]]
    content.append({"type": "text", "text": f"오늘 날짜는 {today.isoformat()}입니다. 이 문서를 정리해주세요."})
    raw = call_structured(
        client,
        system=SYSTEM_PROMPT_BASE + "\n" + LEVEL_GUIDE[reading_level],
        content=content,
        tool_name=TOOL_NAME,
        tool_description=TOOL_DESCRIPTION,
        schema=NOTICE_SCHEMA,
    )
    return finalize(normalize(raw, NOTICE_SCHEMA), today)


@server.tool()
def explain_notice(
    files: Annotated[list[str], Field(
        description="문서 사진 또는 PDF 1~5개. 로컬 파일 절대 경로 또는 http(s) URL. 여러 장짜리 문서는 모든 페이지를 함께 넣으세요.",
        min_length=1, max_length=MAX_FILES,
    )],
    reading_level: Annotated[Literal["아주 쉽게", "보통"], Field(
        description='설명 난이도. "아주 쉽게"(어르신·아이도 이해 가능) 또는 "보통".',
    )] = "아주 쉽게",
) -> str:
    """세금 고지서, 건강보험·국민연금 안내문, 과태료 통지서, 관공서 공문 등을 쉬운 말로 풀어 해야 할 일, 기한(D-day), 금액, 사기 의심 신호를 정리합니다.

    결과: 읽기 쉽게 정리된 설명(마크다운)과 구조화된 결과 JSON. 주민등록번호·휴대전화 번호는 가려지고,
    D-day는 한국 시간 오늘 기준으로 코드가 계산합니다. 결과는 참고용이며 원본 확인이 필요합니다.
    """
    try:
        data = run_explain(files, reading_level)
    except ToolError as e:
        raise MCPToolError(str(e)) from e
    return render(data) + "\n\n## 정리 결과 JSON\n\n```json\n" + json.dumps(data, ensure_ascii=False, indent=2) + "\n```"


if __name__ == "__main__":
    server.run("stdio")
