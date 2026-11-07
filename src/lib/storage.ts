/** API 키·설정 보관 (두 프로젝트 공통). 기본은 탭을 닫으면 지워지는 sessionStorage. */
const KEY = 'anthropic-api-key'
const MODEL_KEY = 'claude-model'

function safe<T>(fn: () => T, fallback: T): T {
  try {
    return fn()
  } catch {
    return fallback
  }
}

export function loadKey(): { key: string; remember: boolean } {
  const local = safe(() => localStorage.getItem(KEY), null)
  if (local) return { key: local, remember: true }
  return { key: safe(() => sessionStorage.getItem(KEY), null) ?? '', remember: false }
}

export function saveKey(key: string, remember: boolean): void {
  safe(() => {
    sessionStorage.removeItem(KEY)
    localStorage.removeItem(KEY)
    if (!key) return
    ;(remember ? localStorage : sessionStorage).setItem(KEY, key)
  }, undefined)
}

export function loadModel(fallback: string): string {
  return safe(() => localStorage.getItem(MODEL_KEY), null) ?? fallback
}

export function saveModel(model: string): void {
  safe(() => localStorage.setItem(MODEL_KEY, model), undefined)
}
