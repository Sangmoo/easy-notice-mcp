---
title: 고지서 공문서 쉬운 말 풀이 MCP
emoji: 📮
colorFrom: gray
colorTo: yellow
sdk: gradio
sdk_version: 6.31.0
python_version: '3.12'
app_file: app.py
pinned: false
license: mit
short_description: 고지서·공문을 쉬운 말로 풀어주는 원격 MCP 서버
tags:
  - mcp-server
  - korean
  - claude
---

# 📮 고지서·공문서 쉬운 말 풀이 (원격 MCP)

세금 고지서, 건강보험 안내문, 과태료 통지서, 관공서 공문을 사진이나 PDF로 넣으면
"무엇을, 언제까지, 얼마를" 해야 하는지 쉬운 말로 정리합니다.

- 기한을 오늘(한국 시간) 기준 D-day로 계산 (코드 계산)
- 어려운 행정 용어 풀이, 설명 난이도 선택(아주 쉽게 / 보통)
- 개인 계좌 입금 요구, 출처 불명 링크 등 사기 의심 신호 경고
- 주민등록번호·휴대전화 번호 자동 마스킹 (Claude가 옮겨 적어도 코드가 한 번 더 가림)
- 읽어 온 값 검증: 존재하지 않는 날짜, 비정상 연도·금액은 "원본 확인 필요"로 표시

## MCP 연결 (원격)

Cursor 등 URL + 헤더를 지원하는 클라이언트:

```json
{
  "mcpServers": {
    "easy-notice": {
      "url": "https://sangmoo-easy-notice-mcp.hf.space/gradio_api/mcp/",
      "headers": { "X-Anthropic-Key": "<본인 Anthropic API 키>" }
    }
  }
}
```

Claude Desktop (`claude_desktop_config.json`, `mcp-remote`로 감싸기):

```json
{
  "mcpServers": {
    "easy-notice": {
      "command": "npx",
      "args": [
        "mcp-remote",
        "https://sangmoo-easy-notice-mcp.hf.space/gradio_api/mcp/",
        "--header",
        "X-Anthropic-Key:${ANTHROPIC_KEY}"
      ],
      "env": { "ANTHROPIC_KEY": "sk-ant-..." }
    }
  }
}
```

Claude Code: `claude mcp add --transport http easy-notice https://sangmoo-easy-notice-mcp.hf.space/gradio_api/mcp/ --header "X-Anthropic-Key: sk-ant-..."`

**본인 Anthropic API 키가 필수입니다.** MCP는 `X-Anthropic-Key` 헤더로, 웹 화면은 키 입력란으로 넣습니다.
서버에는 키가 등록되어 있지 않으며(서버 키로 대신 처리하지 않음), 넣은 키는 요청 처리에만 쓰고 저장하거나 로그로 남기지 않습니다. 비용은 키 소유자 계정에 청구됩니다.

### 툴

`explain_notice(files, reading_level="아주 쉽게")` — HF Space에서는 Space 이름이 붙어 `easy_notice_mcp_explain_notice`로 표시됩니다(클라이언트가 자동으로 인식).

- `files`: 문서 사진 또는 PDF 1~5개 — 공개 **http(s) URL** 또는 **data: URI** (`data:image/jpeg;base64,...`, `data:application/pdf;base64,...`)
- `reading_level`: `아주 쉽게` | `보통`
- 결과: 마크다운 설명 + 구조화된 JSON

보안상 서버의 로컬 파일 경로나 내부 네트워크 주소(127.0.0.1, 10.x, 169.254.x 등)는 받지 않습니다.

## 역할 분담

| Claude | 코드 |
|---|---|
| 문서 읽기, 할 일·기한·금액 추출, 용어 풀이, 사기 신호 | 출력 형식 강제(structured outputs) 및 값 정규화, 주민번호·전화번호 마스킹, 날짜 검증·D-day, 이상값 경고, 결과 조립 |

Claude 응답은 structured outputs(`output_config.format`, JSON Schema)로 받습니다. Sonnet 5.5 / Opus 5.5는 `tool_choice`로 툴 호출을 강제하는 방식을 400으로 거부하기 때문입니다.

## 구조

```
├── app.py          # Gradio UI + MCP 툴 (진입점)
├── prompts.py      # 시스템 프롬프트, 난이도 가이드, 출력 JSON 스키마
├── claude_util.py  # 본인 API 키 확인, 파일/URL 입력, structured outputs 호출
├── validate.py     # 스키마 기준 출력 정규화, API용 스키마 변환
├── logic.py        # 마스킹, D-day, 이상값 검사, 결과 조립
├── errors.py
└── tests/          # 데이터 검증 + 가짜 Claude로 전체 흐름 + 실제 원격 MCP(HTTP) 호출
```

## Space 설정

- 하드웨어: ZeroGPU. 이 앱은 GPU를 쓰지 않지만 ZeroGPU Space는 시작할 때 `@spaces.GPU` 함수가 하나 있어야 해서,
  `app.py`에 호출하지 않는 자리표시 함수(`_zerogpu_placeholder`)를 두었습니다. GPU 할당량은 쓰지 않습니다.
- Secret 불필요. (선택) Variable `CLAUDE_MODEL` — 기본 `claude-sonnet-5-5`

## 로컬 실행·테스트

```bash
python -m venv .venv
.venv\Scripts\activate            # macOS/Linux: source .venv/bin/activate
pip install -r requirements-dev.txt
python app.py                     # http://127.0.0.1:7860, MCP: /gradio_api/mcp/
python -m pytest -q
```

정리 결과는 참고용입니다. 납부 전에는 고지서 원본이나 기관 공식 홈페이지에서 금액과 기한을 확인하세요.
