/**
 * 틀리면 안 되는 부분은 코드가 결정한다: 개인정보 마스킹, 기한 검증·D-day 계산, 결과 조립.
 * mcp_server/logic.py와 동작이 같아야 한다 (tests/fixtures/cases.json으로 양쪽을 함께 검증).
 */
export const MAX_FILES = 5
const MAX_AMOUNT = 10_000_000_000 // 100억 초과는 잘못 읽었을 가능성이 높다

const MASK_PATTERNS: [RegExp, string][] = [
  [/(?<!\d)(\d{6})[-\s]?[1-8]\d{6}(?!\d)/g, '$1-*******'], // 주민·외국인등록번호
  [/(?<!\d)(01[016789])[-\s.]?\d{3,4}[-\s.]?(\d{4})(?!\d)/g, '$1-****-$2'], // 휴대전화
]
const ISO_DATE = /^\d{4}-\d{2}-\d{2}$/

export interface DDay {
  date: string
  days_left: number
  label: string
  status: 'upcoming' | 'today' | 'overdue'
}

export interface Notice {
  doc_type: string
  issuer: string | null
  one_line_summary: string
  what_to_do: string[]
  deadline: string | null
  deadline_original_text: string | null
  amount_krw: number | null
  amount_original_text: string | null
  payment_methods: string[]
  if_missed: string | null
  contact: string | null
  glossary: { term: string; easy: string }[]
  scam_signals: string[]
  unclear_parts: string[]
  validation_warnings?: string[]
  d_day?: DDay | null
}

export function mask<T>(value: T): T {
  if (typeof value === 'string') {
    let s: string = value
    for (const [re, repl] of MASK_PATTERNS) s = s.replace(re, repl)
    return s as T
  }
  if (Array.isArray(value)) return value.map((v) => mask(v)) as T
  if (value && typeof value === 'object') {
    return Object.fromEntries(Object.entries(value).map(([k, v]) => [k, mask(v)])) as T
  }
  return value
}

/** 'YYYY-MM-DD' → UTC 자정 기준 일 수. 존재하지 않는 날짜(2월 30일 등)는 null. */
function dayNumber(value: unknown): number | null {
  if (typeof value !== 'string' || !ISO_DATE.test(value)) return null
  const [y, m, d] = value.split('-').map(Number) as [number, number, number]
  const t = Date.UTC(y, m - 1, d)
  const back = new Date(t)
  if (back.getUTCFullYear() !== y || back.getUTCMonth() !== m - 1 || back.getUTCDate() !== d) return null
  return t / 86_400_000
}

export function parseDate(value: unknown): string | null {
  return dayNumber(value) === null ? null : (value as string)
}

/** 한국 시간 기준 오늘 (YYYY-MM-DD). */
export function todayKst(now = Date.now()): string {
  return new Date(now + 9 * 3_600_000).toISOString().slice(0, 10)
}

export function dDayInfo(deadline: unknown, today: string): DDay | null {
  const due = dayNumber(deadline)
  const base = dayNumber(today)
  if (due === null || base === null) return null
  const days = due - base
  let label: string
  let status: DDay['status']
  if (days > 0) [label, status] = [`D-${days}`, 'upcoming']
  else if (days === 0) [label, status] = ['오늘 마감', 'today']
  else [label, status] = [`기한 ${-days}일 지남`, 'overdue']
  return { date: deadline as string, days_left: days, label, status }
}

const won = (n: number) => n.toLocaleString('en-US')

export function checkData(data: Notice, today: string): string[] {
  const warnings: string[] = []
  const raw = data.deadline
  const year = Number(today.slice(0, 4))
  if (raw !== null && raw !== undefined && parseDate(raw) === null) {
    warnings.push(`기한 날짜를 해석하지 못했습니다("${raw}"). 원본에서 기한을 확인하세요.`)
  } else if (raw) {
    const y = Number(raw.slice(0, 4))
    if (y < year - 1 || y > year + 2) warnings.push(`기한 연도(${y}년)가 예상 범위를 벗어납니다. 원본에서 연도를 확인하세요.`)
  }
  const amount = data.amount_krw
  if (amount !== null && amount !== undefined && amount > MAX_AMOUNT)
    warnings.push(`금액(${won(amount)}원)이 비정상적으로 큽니다. 원본에서 금액을 확인하세요.`)
  if (amount === 0) warnings.push('금액이 0원으로 읽혔습니다. 낼 돈이 없는 문서인지 원본에서 확인하세요.')
  return warnings
}

/** 검증된 Claude 결과 → 마스킹 → 기한 검증·D-day → 확인 필요 항목. */
export function finalize(input: Notice, today: string): Notice {
  const data: Notice = mask({ ...input })
  if (data.deadline !== null && parseDate(data.deadline) === null && !data.deadline_original_text) {
    data.deadline_original_text = data.deadline
  }
  data.validation_warnings = checkData(data, today)
  if (parseDate(data.deadline) === null) data.deadline = null
  data.d_day = dDayInfo(data.deadline, today)
  return data
}

export function checkItems(data: Notice): string[] {
  return [...(data.validation_warnings ?? []), ...(data.unclear_parts ?? [])]
}

/** 마크다운 텍스트 (복사용, MCP 서버 출력과 동일). */
export function render(data: Notice): string {
  const out = [`## ${data.doc_type}`, data.one_line_summary]
  if (data.scam_signals.length) {
    out.push(
      '### 🚨 사기 의심 신호가 있습니다\n' +
        data.scam_signals.map((s) => `- ${s}`).join('\n') +
        '\n\n**돈을 보내기 전에 기관 대표번호로 직접 확인하세요.**',
    )
  }
  const d = data.d_day
  if (d) {
    const icon = { upcoming: '📅', today: '⏰', overdue: '❗' }[d.status]
    out.push(`### ${icon} 기한: ${d.date} (${d.label})`)
  } else if (data.deadline_original_text) {
    out.push(`### 📅 기한: ${data.deadline_original_text}`)
  }
  if (data.amount_krw !== null) out.push(`### 💰 금액: ${won(data.amount_krw)}원`)
  if (data.amount_original_text) out.push(data.amount_original_text)
  out.push('### ✅ 해야 할 일\n' + data.what_to_do.map((s, i) => `${i + 1}. ${s}`).join('\n'))
  if (data.payment_methods.length) out.push('### 내는 방법\n' + data.payment_methods.map((m) => `- ${m}`).join('\n'))
  if (data.if_missed) out.push(`### 놓치면\n${data.if_missed}`)
  if (data.glossary.length) out.push('### 어려운 말 풀이\n' + data.glossary.map((g) => `- **${g.term}**: ${g.easy}`).join('\n'))
  const check = checkItems(data)
  if (check.length) out.push('### 원본 확인 필요\n' + check.map((u) => `- ${u}`).join('\n'))
  if (data.contact) out.push(`문의: ${data.contact}`)
  out.push('---\n*정리 결과는 참고용입니다. 납부 전에는 고지서 원본이나 기관 공식 홈페이지에서 금액과 기한을 확인하세요.*')
  return out.join('\n\n')
}
