"""사용자에게 그대로 보여줄 수 있는 오류."""


class ToolError(Exception):
    """사용자에게 그대로 보여줄 수 있는 오류 (UI에서는 gr.Error, MCP에서는 툴 오류로 전달)."""
