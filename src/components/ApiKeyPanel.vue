<script setup lang="ts">
/** API 키·모델 입력 (두 프로젝트 공통). 키는 브라우저 저장소에만 둔다. */
import { computed, ref, watch } from 'vue'
import { MODELS, looksLikeApiKey } from '@/lib/claude'
import { loadKey, saveKey, saveModel } from '@/lib/storage'

const apiKey = defineModel<string>('apiKey', { required: true })
const model = defineModel<string>('model', { required: true })

const initial = loadKey()
const remember = ref(initial.remember)
const show = ref(false)
if (!apiKey.value) apiKey.value = initial.key

watch([apiKey, remember], ([k, r]) => saveKey(k.trim(), r))
watch(model, (m) => saveModel(m))

const warn = computed(() => apiKey.value.trim() !== '' && !looksLikeApiKey(apiKey.value))
const open = ref(!apiKey.value)
</script>

<template>
  <details class="card key-panel" :open="open">
    <summary>
      <span>🔑 Anthropic API 키 · 모델</span>
      <span class="badge" :class="apiKey ? 'ok' : 'need'">{{ apiKey ? '입력됨' : '필요' }}</span>
    </summary>
    <div class="row">
      <input
        :type="show ? 'text' : 'password'"
        v-model.trim="apiKey"
        placeholder="sk-ant-..."
        autocomplete="off"
        spellcheck="false"
        aria-label="Anthropic API 키"
      />
      <button type="button" class="ghost" @click="show = !show">{{ show ? '숨기기' : '보기' }}</button>
    </div>
    <p v-if="warn" class="hint warn">키 형식이 sk-ant-… 가 아닌 것 같습니다.</p>
    <label class="check">
      <input type="checkbox" v-model="remember" />
      이 브라우저에 기억하기 (끄면 탭을 닫을 때 지워짐)
    </label>
    <label class="field">
      <span>모델</span>
      <select v-model="model">
        <option v-for="m in MODELS" :key="m.id" :value="m.id">{{ m.label }}</option>
      </select>
    </label>
    <p class="hint">
      키는 이 페이지에서 <code>api.anthropic.com</code>으로만 직접 전송되며, 이 사이트에는 서버가 없어 어디에도 저장되지 않습니다.
      비용은 키 소유자 계정에 청구됩니다. 키 발급:
      <a href="https://console.anthropic.com/settings/keys" target="_blank" rel="noopener">console.anthropic.com</a>
    </p>
  </details>
</template>
