/**
 * Claude 출력 검증·정규화 (두 프로젝트 공통, mcp_server/validate.py와 동작 동일).
 * 스키마에 정의된 키만 남기고 타입을 맞춘다. 필수 문자열이 비면 ToolError.
 */
import { ToolError } from './errors'

export interface JsonSchema {
  type?: string | string[]
  enum?: string[]
  default?: string
  items?: JsonSchema
  properties?: Record<string, JsonSchema>
  required?: string[]
  description?: string
}

const NUM_RE = /-?\d[\d,]*(?:\.\d+)?/

function types(spec: JsonSchema): string[] {
  const t = spec.type ?? 'string'
  return Array.isArray(t) ? t : [t]
}

/** Python round()가 아니라 사사오입. 음수는 여기까지 오지 않는다(호출 측에서 거름). */
function roundHalfUp(n: number): number {
  return Math.floor(n + 0.5)
}

function toInt(v: unknown): number | null {
  if (typeof v === 'boolean') return null
  if (typeof v === 'number') return Number.isFinite(v) ? roundHalfUp(v) : null
  if (typeof v === 'string') {
    const m = v.match(NUM_RE)
    if (!m) return null
    const n = Number(m[0].replace(/,/g, ''))
    return Number.isFinite(n) ? roundHalfUp(n) : null
  }
  return null
}

function coerce(v: unknown, spec: JsonSchema, path: string, required: boolean): unknown {
  const ts = types(spec)
  const nullable = ts.includes('null')
  const base = ts.find((t) => t !== 'null') ?? 'string'

  if (base === 'array') {
    if (v === null || v === undefined) return []
    const arr = Array.isArray(v) ? v : [v]
    const itemSpec = spec.items ?? { type: 'string' }
    const out: unknown[] = []
    arr.forEach((item, i) => {
      try {
        const c = coerce(item, itemSpec, `${path}[${i}]`, true)
        if (c !== null && c !== undefined) out.push(c)
      } catch {
        /* 잘못된 원소는 버린다 */
      }
    })
    return out
  }

  if (base === 'integer') {
    const n = toInt(v)
    if (n === null || n < 0) {
      if (nullable || !required) return null
      throw new ToolError(`결과의 '${path}' 값이 올바르지 않습니다. 다시 시도해주세요.`)
    }
    return n
  }

  if (base === 'string') {
    let s: string | null = null
    if (typeof v === 'string') s = v.trim()
    else if (typeof v === 'number' && Number.isFinite(v)) s = String(v)
    if (s === '' || s === 'null' || s === 'None') s = null
    if (s === null) {
      if (nullable || !required) return null
      throw new ToolError(`결과에 '${path}' 항목이 없습니다. 다시 시도해주세요.`)
    }
    if (spec.enum && !spec.enum.includes(s)) {
      const lower = s.toLowerCase()
      s = spec.enum.find((e) => e.toLowerCase() === lower) ?? spec.default ?? spec.enum[spec.enum.length - 1]
    }
    return s
  }

  if (base === 'object') {
    return v && typeof v === 'object' && !Array.isArray(v)
      ? coerceObject(v as Record<string, unknown>, spec, path)
      : null
  }
  return v
}

function coerceObject(data: Record<string, unknown>, schema: JsonSchema, path = ''): Record<string, unknown> {
  const props = schema.properties ?? {}
  const required = new Set(schema.required ?? [])
  const out: Record<string, unknown> = {}
  for (const [key, spec] of Object.entries(props)) {
    const sub = path ? `${path}.${key}` : key
    out[key] = coerce(data[key], spec, sub, required.has(key))
  }
  return out
}

export function normalize<T = Record<string, unknown>>(data: unknown, schema: JsonSchema): T {
  if (!data || typeof data !== 'object' || Array.isArray(data)) {
    throw new ToolError('Claude 응답 형식이 올바르지 않습니다. 다시 시도해주세요.')
  }
  return coerceObject(data as Record<string, unknown>, schema) as T
}
