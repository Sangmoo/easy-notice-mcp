<script setup lang="ts">
/** 파일 선택 + 미리보기 + 드래그 앤 드롭 (두 프로젝트 공통). */
import { onBeforeUnmount, ref, watch } from 'vue'
import { isPdf } from '@/lib/files'

const props = defineProps<{ max: number; accept: string; label: string; hint?: string }>()
const files = defineModel<File[]>({ required: true })

const previews = ref<{ file: File; url: string | null }[]>([])
const dragging = ref(false)
const notice = ref('')
const input = ref<HTMLInputElement>()

function revokeAll() {
  previews.value.forEach((p) => p.url && URL.revokeObjectURL(p.url))
}

watch(
  files,
  (list) => {
    revokeAll()
    previews.value = list.map((file) => ({ file, url: isPdf(file) ? null : URL.createObjectURL(file) }))
  },
  { immediate: true },
)
onBeforeUnmount(revokeAll)

function accepts(file: File): boolean {
  return props.accept.split(',').some((a) => {
    a = a.trim()
    if (a.endsWith('/*')) return file.type.startsWith(a.slice(0, -1))
    if (a.startsWith('.')) return file.name.toLowerCase().endsWith(a)
    return file.type === a
  })
}

function add(list: FileList | null) {
  if (!list) return
  const incoming = Array.from(list)
  const ok = incoming.filter(accepts)
  const merged = [...files.value, ...ok]
  notice.value = ''
  if (ok.length < incoming.length) notice.value = '지원하지 않는 형식의 파일은 뺐습니다.'
  if (merged.length > props.max) notice.value = `최대 ${props.max}개까지 넣을 수 있어 앞의 ${props.max}개만 사용합니다.`
  files.value = merged.slice(0, props.max)
  if (input.value) input.value.value = ''
}

function remove(i: number) {
  files.value = files.value.filter((_, idx) => idx !== i)
  notice.value = ''
}

function onDrop(e: DragEvent) {
  dragging.value = false
  add(e.dataTransfer?.files ?? null)
}
</script>

<template>
  <div class="field">
    <span>{{ label }}</span>
    <div
      class="drop"
      :class="{ dragging }"
      @dragover.prevent="dragging = true"
      @dragleave="dragging = false"
      @drop.prevent="onDrop"
      @click="input?.click()"
      @keydown.enter.prevent="input?.click()"
      tabindex="0"
      role="button"
    >
      <input ref="input" type="file" multiple :accept="accept" hidden @change="add(($event.target as HTMLInputElement).files)" />
      <p class="drop-title">여기를 눌러 선택하거나 끌어다 놓으세요</p>
      <p class="hint">{{ hint }} ({{ files.length }}/{{ max }})</p>
    </div>
    <p v-if="notice" class="hint warn">{{ notice }}</p>
    <ul v-if="previews.length" class="thumbs">
      <li v-for="(p, i) in previews" :key="p.url ?? p.file.name + i">
        <img v-if="p.url" :src="p.url" :alt="p.file.name" />
        <div v-else class="pdf">PDF<br /><small>{{ p.file.name }}</small></div>
        <button type="button" class="remove" :aria-label="`${p.file.name} 빼기`" @click.stop="remove(i)">×</button>
      </li>
    </ul>
  </div>
</template>
