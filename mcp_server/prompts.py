"""시스템 프롬프트와 출력 스키마.

웹(Vue)과 MCP 서버가 같은 프롬프트·스키마를 쓰도록 shared/prompts.json 하나만 수정한다.
"""
import json
from pathlib import Path

_SHARED = json.loads((Path(__file__).resolve().parent.parent / "shared" / "prompts.json").read_text(encoding="utf-8"))

SYSTEM_PROMPT_BASE: str = _SHARED["system_prompt_base"]
LEVEL_GUIDE: dict[str, str] = _SHARED["level_guide"]
TOOL_NAME: str = _SHARED["tool_name"]
TOOL_DESCRIPTION: str = _SHARED["tool_description"]
NOTICE_SCHEMA: dict = _SHARED["schema"]
