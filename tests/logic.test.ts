/** TypeScript 쪽 데이터 검증. tests/test_logic.py와 같은 fixture를 쓴다. 실행: npm test */
import { describe, expect, it } from 'vitest'
import cases from './fixtures/cases.json'
import { ToolError } from '../src/lib/errors'
import { dDayInfo, finalize, mask, render, todayKst, type Notice } from '../src/lib/logic'
import { LEVELS, NOTICE_SCHEMA } from '../src/lib/prompts'
import { normalize } from '../src/lib/validate'

const TODAY = cases.today

describe('mask', () => {
  for (const c of cases.mask) {
    it(JSON.stringify(c.input).slice(0, 40), () => expect(mask(c.input)).toEqual(c.expected))
  }
})

describe('dDayInfo', () => {
  for (const c of cases.d_day) {
    it(String(c.deadline), () => expect(dDayInfo(c.deadline, TODAY)).toEqual(c.expected))
  }
})

describe('finalize', () => {
  for (const c of cases.finalize) {
    it(c.name, () => {
      if ('error' in c && c.error) {
        expect(() => normalize(c.input, NOTICE_SCHEMA)).toThrow(ToolError)
        return
      }
      const data = finalize(normalize<Notice>(c.input, NOTICE_SCHEMA), TODAY)
      expect(data).toEqual((c as { expected: unknown }).expected)
      if ('render' in c) expect(render(data)).toBe(c.render)
    })
  }
})

describe('misc', () => {
  it('KST 날짜 경계', () => {
    expect(todayKst(Date.UTC(2026, 10, 6, 14, 59))).toBe('2026-11-06') // KST 23:59
    expect(todayKst(Date.UTC(2026, 10, 6, 15, 0))).toBe('2026-11-07') // KST 00:00
  })
  it('난이도 목록', () => expect(LEVELS).toEqual(['아주 쉽게', '보통']))
})
