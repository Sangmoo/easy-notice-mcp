/**
 * 브라우저에서 Claude Messages API를 직접 호출한다 (두 프로젝트 공통).
 * 키는 사용자의 브라우저에만 있고 이 사이트의 서버로는 가지 않는다 (static Space라 서버가 없음).
 * tool_choice로 툴 호출을 강제해서 항상 스키마 형태의 객체를 받는다.
 */
import { ToolError } from './errors'
import type { JsonSchema } from './validate'

export const MODELS = [
  { id: 'claude-sonnet-5-5', label: 'Sonnet 5.5 (기본, 균형)' },
  { id: 'claude-opus-5-5', label: 'Opus 5.5 (최고 품질, 비쌈)' },
  { id: 'claude-haiku-5-5', label: 'Haiku 5.5 (빠르고 저렴)' },
] as const
export const DEFAULT_MODEL = MODELS[0].id

export type ContentBlock =
  | { type: 'text'; text: string }
  | { type: 'image'; source: { type: 'base64'; media_type: string; data: string } }
  | { type: 'document'; source: { type: 'base64'; media_type: 'application/pdf'; data: string } }

export interface StructuredCall {
  apiKey: string
  model: string
  system: string
  content: ContentBlock[]
  toolName: string
  toolDescription: string
  schema: JsonSchema
  maxTokens?: number
  signal?: AbortSignal
}

const API_URL = 'https://api.anthropic.com/v1/messages'

export function looksLikeApiKey(key: string): boolean {
  return /^sk-ant-[A-Za-z0-9_-]{20,}$/.test(key.trim())
}

export async function callStructured(opts: StructuredCall): Promise<unknown> {
  const apiKey = opts.apiKey.trim()
  if (!apiKey) throw new ToolError('Anthropic API 키를 먼저 입력해주세요.')

  let resp: Response
  try {
    resp = await fetch(API_URL, {
      method: 'POST',
      signal: opts.signal,
      headers: {
        'content-type': 'application/json',
        'x-api-key': apiKey,
        'anthropic-version': '2023-06-01',
        'anthropic-dangerous-direct-browser-access': 'true',
      },
      body: JSON.stringify({
        model: opts.model,
        max_tokens: opts.maxTokens ?? 4000,
        system: opts.system,
        messages: [{ role: 'user', content: opts.content }],
        tools: [{ name: opts.toolName, description: opts.toolDescription, input_schema: opts.schema }],
        tool_choice: { type: 'tool', name: opts.toolName },
      }),
    })
  } catch (e) {
    if ((e as Error).name === 'AbortError') throw new ToolError('요청을 취소했습니다.')
    throw new ToolError('Claude API에 연결하지 못했습니다. 인터넷 연결을 확인해주세요.')
  }

  let body: any = null
  try {
    body = await resp.json()
  } catch {
    /* 본문 없음 */
  }

  if (!resp.ok) {
    const msg: string = body?.error?.message ?? ''
    if (resp.status === 401) throw new ToolError('Anthropic API 키가 올바르지 않습니다.')
    if (resp.status === 403) throw new ToolError(`이 키로는 요청할 수 없습니다: ${msg}`)
    if (resp.status === 404) throw new ToolError(`모델을 찾을 수 없습니다: ${opts.model}`)
    if (resp.status === 413) throw new ToolError('파일이 너무 큽니다. 장수나 크기를 줄여주세요.')
    if (resp.status === 429) throw new ToolError('Anthropic API 요청 한도에 걸렸습니다. 잠시 후 다시 시도해주세요.')
    if (resp.status === 529 || resp.status >= 500)
      throw new ToolError('Claude 서버가 혼잡합니다. 잠시 후 다시 시도해주세요.')
    throw new ToolError(`요청이 거부되었습니다: ${msg || resp.status}`)
  }

  if (body?.stop_reason === 'max_tokens') {
    throw new ToolError('응답이 길어 중간에 잘렸습니다. 파일 수를 줄여 다시 시도해주세요.')
  }
  const block = (body?.content ?? []).find((b: any) => b?.type === 'tool_use')
  if (!block) throw new ToolError('Claude 응답에서 결과를 찾지 못했습니다. 다시 시도해주세요.')
  return block.input
}
