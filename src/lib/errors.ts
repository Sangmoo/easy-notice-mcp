/** 사용자에게 그대로 보여줄 수 있는 오류. */
export class ToolError extends Error {
  constructor(message: string) {
    super(message)
    this.name = 'ToolError'
  }
}
