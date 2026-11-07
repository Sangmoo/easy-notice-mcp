<script setup lang="ts">
/** MCP 연결 안내 (두 프로젝트 공통). */
import { computed } from 'vue'
import CopyButton from './CopyButton.vue'

const props = defineProps<{ serverName: string; repo: string; tool: string }>()

const config = computed(() =>
  JSON.stringify(
    {
      mcpServers: {
        [props.serverName]: {
          command: 'python',
          args: [`C:/path/to/${props.repo}/mcp_server/server.py`],
          env: { ANTHROPIC_API_KEY: 'sk-ant-...' },
        },
      },
    },
    null,
    2,
  ),
)
const install = computed(
  () => `git clone https://github.com/Sangmoo/${props.repo}.git\ncd ${props.repo}\npip install -r requirements.txt`,
)
</script>

<template>
  <details class="card">
    <summary><span>🧩 Claude Desktop 등에서 MCP 서버로 쓰기</span></summary>
    <p>
      같은 기능을 로컬 MCP 서버(<code>{{ tool }}</code> 툴)로도 제공합니다. 사진은 로컬 파일 경로나 이미지 URL로 넘기면 됩니다.
    </p>
    <h3>1. 설치</h3>
    <pre><code>{{ install }}</code></pre>
    <div class="actions" style="margin-top: 6px"><CopyButton :text="install" /></div>
    <h3>2. <code>claude_desktop_config.json</code>에 추가</h3>
    <pre><code>{{ config }}</code></pre>
    <div class="actions" style="margin-top: 6px"><CopyButton :text="config" /></div>
    <p class="hint">
      경로는 내려받은 폴더의 실제 위치로 바꾸세요. 가상환경을 쓰면 <code>command</code>에 그 python 경로를 넣습니다.
      소스: <a :href="`https://github.com/Sangmoo/${repo}`" target="_blank" rel="noopener">github.com/Sangmoo/{{ repo }}</a>
    </p>
  </details>
</template>
