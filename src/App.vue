<script setup lang="ts">
/**
 * 고지서·공문서 쉬운 말 풀이.
 * Claude는 문서를 읽고 정리만 하고, 마스킹·D-day·검증·결과 조립은 코드(lib/logic.ts)가 한다.
 */
import { computed, ref } from 'vue'
import ApiKeyPanel from '@/components/ApiKeyPanel.vue'
import CopyButton from '@/components/CopyButton.vue'
import FilePicker from '@/components/FilePicker.vue'
import McpGuide from '@/components/McpGuide.vue'
import { DEFAULT_MODEL, callStructured, type ContentBlock } from '@/lib/claude'
import { ToolError } from '@/lib/errors'
import { fileToBlock } from '@/lib/files'
import { MAX_FILES, checkItems, finalize, render, todayKst, type Notice } from '@/lib/logic'
import { LEVELS, LEVEL_GUIDE, NOTICE_SCHEMA, SYSTEM_PROMPT_BASE, TOOL_DESCRIPTION, TOOL_NAME } from '@/lib/prompts'
import { loadModel } from '@/lib/storage'
import { normalize } from '@/lib/validate'

const apiKey = ref('')
const model = ref(loadModel(DEFAULT_MODEL))
const files = ref<File[]>([])
const level = ref(LEVELS[0]!)

const loading = ref(false)
const error = ref('')
const result = ref<Notice | null>(null)
let controller: AbortController | null = null

const canSubmit = computed(() => !loading.value && files.value.length > 0 && apiKey.value.trim() !== '')

async function submit() {
  error.value = ''
  if (!apiKey.value.trim()) return void (error.value = '먼저 Anthropic API 키를 입력해주세요.')
  if (!files.value.length) return void (error.value = '문서 사진이나 PDF를 1개 이상 넣어주세요.')

  loading.value = true
  controller = new AbortController()
  try {
    const today = todayKst()
    const content: ContentBlock[] = []
    for (const f of files.value.slice(0, MAX_FILES)) content.push(await fileToBlock(f))
    content.push({ type: 'text', text: `오늘 날짜는 ${today}입니다. 이 문서를 정리해주세요.` })
    const raw = await callStructured({
      apiKey: apiKey.value,
      model: model.value,
      system: `${SYSTEM_PROMPT_BASE}\n${LEVEL_GUIDE[level.value]}`,
      content,
      toolName: TOOL_NAME,
      toolDescription: TOOL_DESCRIPTION,
      schema: NOTICE_SCHEMA,
      signal: controller.signal,
    })
    result.value = finalize(normalize<Notice>(raw, NOTICE_SCHEMA), today)
    requestAnimationFrame(() => document.getElementById('result')?.scrollIntoView({ behavior: 'smooth' }))
  } catch (e) {
    error.value = e instanceof ToolError ? e.message : `알 수 없는 오류: ${(e as Error).message}`
  } finally {
    loading.value = false
    controller = null
  }
}

function cancel() {
  controller?.abort()
}

const markdown = computed(() => (result.value ? render(result.value) : ''))
const checks = computed(() => (result.value ? checkItems(result.value) : []))
const jsonText = computed(() => (result.value ? JSON.stringify(result.value, null, 2) : ''))
const ddayClass = computed(() => result.value?.d_day?.status ?? '')
</script>

<template>
  <main class="wrap">
    <header class="top">
      <h1>📮 고지서·공문서 쉬운 말 풀이</h1>
      <p>세금 고지서, 건강보험 안내문, 과태료 통지서, 관공서 공문을 올리면 <b>무엇을, 언제까지, 얼마를</b> 해야 하는지 쉽게 정리해 드립니다.</p>
    </header>

    <ApiKeyPanel v-model:api-key="apiKey" v-model:model="model" />

    <form class="card" @submit.prevent="submit">
      <FilePicker
        v-model="files"
        :max="MAX_FILES"
        accept="image/*,.pdf,application/pdf"
        label="고지서·공문 사진 또는 PDF"
        hint="여러 장짜리 문서는 모든 페이지를 함께 넣으세요"
      />

      <fieldset class="seg">
        <legend class="legend">설명 난이도</legend>
        <label v-for="l in LEVELS" :key="l">
          <input type="radio" name="level" :value="l" v-model="level" />
          <span>{{ l }}</span>
        </label>
      </fieldset>

      <div v-if="error" class="error" role="alert">{{ error }}</div>

      <div class="actions">
        <button class="primary" type="submit" :disabled="!canSubmit">
          <template v-if="loading"><span class="spinner"></span>문서 읽고 정리하는 중…</template>
          <template v-else>쉽게 풀어주세요</template>
        </button>
        <button v-if="loading" type="button" class="ghost" @click="cancel">취소</button>
      </div>
      <p class="hint">문서는 이 브라우저에서 Claude API로만 전송되며 저장되지 않습니다. 주민등록번호·휴대전화 번호는 결과에서 자동으로 가려집니다.</p>
    </form>

    <section v-if="result" id="result">
      <div class="card">
        <div class="result-head">
          <h2>{{ result.doc_type }}</h2>
          <CopyButton :text="markdown" label="정리 결과 복사" />
        </div>
        <p class="summary">{{ result.one_line_summary }}</p>
        <p v-if="result.issuer" class="muted">보낸 곳: {{ result.issuer }}</p>

        <div v-if="result.scam_signals.length" class="alert">
          <h3>🚨 사기 의심 신호가 있습니다</h3>
          <ul>
            <li v-for="s in result.scam_signals" :key="s">{{ s }}</li>
          </ul>
          <p style="margin: 8px 0 0"><b>돈을 보내기 전에 기관 대표번호로 직접 확인하세요.</b></p>
        </div>

        <div class="facts">
          <div class="fact" :class="ddayClass">
            <span class="fact-label">기한</span>
            <template v-if="result.d_day">
              <strong>{{ result.d_day.label }}</strong>
              <span>{{ result.d_day.date }}</span>
            </template>
            <template v-else>
              <strong>{{ result.deadline_original_text ?? '없음' }}</strong>
            </template>
          </div>
          <div class="fact">
            <span class="fact-label">금액</span>
            <strong>{{ result.amount_krw !== null ? `${result.amount_krw.toLocaleString('en-US')}원` : '없음' }}</strong>
            <span v-if="result.amount_original_text">{{ result.amount_original_text }}</span>
          </div>
        </div>

        <h3>✅ 해야 할 일</h3>
        <ol class="plain">
          <li v-for="(s, i) in result.what_to_do" :key="i">{{ s }}</li>
        </ol>

        <template v-if="result.payment_methods.length">
          <h3>내는 방법</h3>
          <ul class="plain">
            <li v-for="m in result.payment_methods" :key="m">{{ m }}</li>
          </ul>
        </template>

        <template v-if="result.if_missed">
          <h3>놓치면</h3>
          <p>{{ result.if_missed }}</p>
        </template>

        <template v-if="result.glossary.length">
          <h3>어려운 말 풀이</h3>
          <dl class="glossary">
            <template v-for="g in result.glossary" :key="g.term">
              <dt>{{ g.term }}</dt>
              <dd>{{ g.easy }}</dd>
            </template>
          </dl>
        </template>

        <template v-if="checks.length">
          <h3>⚠️ 원본 확인 필요</h3>
          <ul class="plain">
            <li v-for="c in checks" :key="c">{{ c }}</li>
          </ul>
        </template>

        <p v-if="result.contact" class="muted">문의: {{ result.contact }}</p>
        <p class="disclaimer">정리 결과는 참고용입니다. 납부 전에는 고지서 원본이나 기관 공식 홈페이지에서 금액과 기한을 확인하세요.</p>
      </div>

      <details class="card">
        <summary><span>정리 결과 JSON</span></summary>
        <pre><code>{{ jsonText }}</code></pre>
      </details>
    </section>

    <McpGuide server-name="easy-notice" repo="easy-notice-mcp" tool="explain_notice" />

    <footer class="foot">올린 문서는 저장되지 않습니다. 결과는 참고용이며 원본 확인이 필요합니다.</footer>
  </main>
</template>

<style>
:root {
  --accent: #1f6f8b;
  --accent-soft: #e2f0f4;
}
@media (prefers-color-scheme: dark) {
  :root {
    --accent: #5fb7d4;
    --accent-soft: #17303a;
    --on-accent: #08161b;
  }
}
.summary { font-size: 1.08rem; margin: 0 0 6px; }
.facts { display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 10px; margin: 16px 0 4px; }
.fact { display: flex; flex-direction: column; gap: 2px; padding: 14px 16px; border-radius: 12px; background: var(--surface-2); border: 1px solid var(--border); }
.fact strong { font-size: 1.35rem; letter-spacing: -0.01em; }
.fact span { color: var(--muted); font-size: 0.9rem; }
.fact .fact-label { font-size: 0.8rem; font-weight: 600; color: var(--muted); }
.fact.upcoming { border-color: var(--accent); background: var(--accent-soft); }
.fact.today, .fact.overdue { border-color: var(--danger); background: var(--danger-soft); }
.fact.today strong, .fact.overdue strong { color: var(--danger); }
.glossary { margin: 0; display: grid; grid-template-columns: max-content 1fr; gap: 6px 14px; }
.glossary dt { font-weight: 700; }
.glossary dd { margin: 0; }
@media (max-width: 480px) {
  .glossary { grid-template-columns: 1fr; gap: 0; }
  .glossary dd { margin-bottom: 8px; }
}
</style>
