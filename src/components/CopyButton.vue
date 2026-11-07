<script setup lang="ts">
import { ref } from 'vue'

const props = defineProps<{ text: string; label?: string }>()
const done = ref(false)

async function copy() {
  try {
    await navigator.clipboard.writeText(props.text)
  } catch {
    const ta = document.createElement('textarea')
    ta.value = props.text
    document.body.appendChild(ta)
    ta.select()
    document.execCommand('copy')
    ta.remove()
  }
  done.value = true
  setTimeout(() => (done.value = false), 1500)
}
</script>

<template>
  <button type="button" class="ghost small" @click="copy">{{ done ? '복사됨 ✓' : (label ?? '복사') }}</button>
</template>
