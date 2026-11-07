/** 프롬프트·스키마는 shared/prompts.json 하나를 MCP 서버와 함께 쓴다. */
import shared from '../../shared/prompts.json'
import type { JsonSchema } from './validate'

export const SYSTEM_PROMPT_BASE: string = shared.system_prompt_base
export const LEVEL_GUIDE: Record<string, string> = shared.level_guide
export const LEVELS = Object.keys(LEVEL_GUIDE)
export const TOOL_NAME: string = shared.tool_name
export const TOOL_DESCRIPTION: string = shared.tool_description
export const NOTICE_SCHEMA = shared.schema as JsonSchema
