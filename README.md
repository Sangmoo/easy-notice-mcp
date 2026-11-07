---
title: 고지서 공문서 쉬운 말 풀이
emoji: 📮
colorFrom: blue
colorTo: green
sdk: static
pinned: false
app_build_command: npm run build
app_file: dist/index.html
license: mit
short_description: 고지서·공문을 쉬운 말로 풀어주는 웹 + MCP 서버
tags:
  - korean
  - claude
  - mcp
  - vue
---

# 📮 고지서·공문서 쉬운 말 풀이 (웹 + MCP)

세금 고지서, 건강보험 안내문, 과태료 통지서, 관공서 공문을 사진이나 PDF로 넣으면
"무엇을, 언제까지, 얼마를" 해야 하는지 쉬운 말로 정리합니다.

- 기한을 오늘(한국 시간) 기준 D-day로 계산 (코드 계산)
- 어려운 행정 용어 풀이, 설명 난이도 선택(아주 쉽게 / 보통)
- 개인 계좌 입금 요구, 출처 불명 링크 등 사기 의심 신호 경고
- 주민등록번호·휴대전화 번호 자동 마스킹 (Claude가 옮겨 적어도 코드가 한 번 더 가림)
- 읽어 온 값 검증: 존재하지 않는 날짜, 비정상 연도·금액은 "원본 확인 필요"로 표시

| 사용 방법 | 위치 | 키 |
|---|---|---|
| 웹 | https://huggingface.co/spaces/Sangmoo/easy-notice-mcp | 화면에 본인 Anthropic API 키 입력 (브라우저 → api.anthropic.com 직접 호출, 저장 서버 없음) |
| MCP 서버 | 이 저장소의 `mcp_server/` (로컬 stdio) | MCP 클라이언트 설정의 `env.ANTHROPIC_API_KEY` |

## 역할 분담

| Claude | 코드 |
|---|---|
| 문서 읽기, 할 일·기한·금액 추출, 용어 풀이, 사기 신호 | 응답 스키마 검증·정규화, 주민번호·전화번호 마스킹, 날짜 검증·D-day, 이상값 경고, 결과 조립 |

## 구조

```
├── shared/prompts.json      # 시스템 프롬프트 + 난이도 가이드 + 출력 스키마 (웹·MCP 공용)
├── src/                     # Vue 3 웹앱 (HF static Space에서 npm run build → dist/)
│   ├── App.vue
│   ├── components/          # API 키 패널, 파일 선택, 복사 버튼, MCP 안내
│   └── lib/
│       ├── claude.ts        # 브라우저에서 Messages API 호출 (tool_choice 강제)
│       ├── files.ts         # 이미지 축소·JPEG 변환, PDF base64
│       ├── validate.ts      # 스키마 기반 출력 검증·정규화
│       └── logic.ts         # 마스킹, D-day, 이상값 검사, 결과 조립
├── mcp_server/              # 로컬 stdio MCP 서버 (Python)
│   ├── server.py            # explain_notice 툴
│   ├── claude_util.py / validate.py / logic.py / prompts.py
└── tests/
    ├── fixtures/cases.json  # Python·TypeScript 공용 검증 데이터
    ├── test_logic.py / logic.test.ts
    └── test_server.py       # 가짜 Claude로 전체 흐름 + 실제 stdio MCP 프로토콜
```

## MCP 서버로 쓰기

```bash
git clone https://github.com/Sangmoo/easy-notice-mcp.git
cd easy-notice-mcp
python -m venv .venv
.venv\Scripts\activate            # macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt
```

`claude_desktop_config.json` (경로는 실제 위치로):

```json
{
  "mcpServers": {
    "easy-notice": {
      "command": "C:/path/to/easy-notice-mcp/.venv/Scripts/python.exe",
      "args": ["C:/path/to/easy-notice-mcp/mcp_server/server.py"],
      "env": { "ANTHROPIC_API_KEY": "sk-ant-...", "CLAUDE_MODEL": "claude-sonnet-5-5" }
    }
  }
}
```

툴: `explain_notice(files, reading_level="아주 쉽게")`

- `files`: 문서 사진 또는 PDF 1~5개 — 로컬 파일 절대 경로 또는 http(s) URL
- `reading_level`: `아주 쉽게` | `보통`

빠른 확인: `npx @modelcontextprotocol/inspector` → STDIO, command에 위 python 경로, args에 `mcp_server/server.py`.

서버는 입력 문서와 결과를 로그로 남기지 않습니다.

## 개발

```bash
npm install
npm run dev          # http://localhost:5173
npm test             # TypeScript 검증 (vitest)
npm run build        # 타입 체크 + dist/ 빌드 (HF Space가 실행하는 것과 동일)

pip install -r requirements-dev.txt
python -m pytest -q  # Python 검증 + MCP stdio 프로토콜 테스트
```

## 배포

- GitHub: https://github.com/Sangmoo/easy-notice-mcp
- Hugging Face Space(static): https://huggingface.co/spaces/Sangmoo/easy-notice-mcp — `main`에 push하면 Space가 `npm run build` 후 `dist/index.html`을 서빙

정리 결과는 참고용입니다. 납부 전에는 고지서 원본이나 기관 공식 홈페이지에서 금액과 기한을 확인하세요.
