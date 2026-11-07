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
- **ZeroGPU 무료 모델**
  1. 개인정보 먼저 가리기: OCR로 이름·주소·주민번호·휴대폰·계좌번호 '값'만 찾아 검게 칠한 뒤 Claude에 보냄 (라벨·금액·기관 번호는 남김)
  2. 짧은 음성 안내: "무엇인지 + 기한 + 금액"을 최대 4문장으로. 기한·금액은 코드가 검증한 값을 한글 수사로 읽음
  3. 사진 보정: 문서 원근·대비 보정(CPU) + 저해상도 사진 2배 확대(GPU)

## 시니어가 쓰기 쉬운 화면

- **단순한 첫 화면**: "① 사진 찍기/올리기 → ② 쉽게 풀어주세요" 두 단계만. 처리 방식·모델 등은 "⚙️ 더보기 설정"에
- **📷 사진 찍기**: 휴대폰에서 카메라가 바로 열림 + 잘 찍는 요령 안내
- **한눈에 카드**: 맨 위에 큰 글씨로 "📅 언제까지 / 💰 얼마 / ✅ 무엇을". 기한 3일 이내·지남은 빨간색, 7일 이내는 노란색
- **🚨 사기 의심 경고**: 빨간 경고와 바로 걸 수 있는 전화 버튼(기관 대표번호, 경찰 112, 금융감독원 1332)
- **🔊 듣기 / ⏹ 멈추기**: 눌렀을 때만 읽음(자동 재생 없음), "천천히 읽기" 선택 가능. GPU를 못 쓰면 휴대폰·PC 내장 음성으로 읽음
- **📅 달력 등록**: "구글 캘린더에 추가"(새 탭, 안드로이드에서 한 번에) + 달력 파일(.ics, 아이폰 등 — 3일 전·당일 오전 9시 알림 포함)
- **👨‍👩‍👧 가족에게 보내기**: 개인정보 없는 짧은 요약 + 복사 / 카카오톡·문자 공유
- **🖨 큰 글씨로 인쇄**: 한 장짜리 인쇄용 페이지
- **🔍 글씨 크게/작게**: 화면 전체 글자 크기, 이 브라우저에 기억
- **키 없이 바로 사용**: 운영자 키(Space Secret)로 한 사람(IP)당 하루 5번까지 무료. 남은 횟수를 버튼 아래에 표시
- **내 키로 제한 없이 쓰기**(선택, "더보기 설정"): 가족이 Anthropic 키를 넣어 두면 횟수 제한 없음. "이 기기에 키 기억하기"로 다음부터 다시 넣지 않아도 됨(브라우저에 암호화 저장, 끄면 삭제). 여러 사람이 쓰는 PC에서는 켜지 마세요. Space Secret `KEY_STORE_SECRET`으로 저장 암호화 키를 바꿀 수 있습니다.

## 처리 방식

| 방식 | 개인정보 가림 | 음성 | 화질 |
|---|---|---|---|
| **⚡ 빠르게**(`Claude API`) | 원본 전송. '개인정보 가리기'를 켜면 Claude가 찾은 위치로 **공유용 사본**만 가림(조금 느려짐) | 브라우저 음성(웹)·안내 문장(MCP) | CPU 보정만 |
| **자동** (웹 기본) | GPU OCR로 가린 뒤 전송 | GPU TTS | CPU 보정 + GPU 확대 |
| 무료 모델(GPU) | 위와 같음 (GPU 실패 시 오류) | GPU TTS | 위와 같음 |

- 웹 화면은 고른 처리 방식·난이도·모델·추가 기능을 브라우저에 기억합니다(API 키는 저장하지 않음). ⚡ 빠르게를 한 번 고르면 다음부터 처음부터 GPU 없이 동작합니다.
- 결과 글을 먼저 보여 주고, 음성은 이어서 만듭니다. 진행 단계도 표시합니다.
- 자동 모드는 GPU 사용량이 큰 작업(이미지 5쪽 이상)이거나 GPU를 쓸 수 없을 때(ZeroGPU 하루 사용량: 비로그인 2분·무료 계정 5분) Claude API 방식으로 넘어갑니다.
- Claude 모델: Sonnet 5.5(정확, 기본) / Haiku 5.5(빠르고 저렴). 정리 작업이라 effort는 `low`로 둡니다(Space Variable `NOTICE_EFFORT`로 변경 가능).

| 기능 | 모델 | 라이선스 |
|---|---|---|
| OCR(개인정보 위치) | EasyOCR ko+en | Apache-2.0 |
| 2배 확대 | caidas/swin2SR-classical-sr-x2-64 | Apache-2.0 |
| 음성 | facebook/mms-tts-kor | CC-BY-NC-4.0 (비상업 무료) |

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

**MCP는 본인 Anthropic API 키가 필수입니다** (`X-Anthropic-Key` 헤더). 운영자 키는 웹·앱 화면의 무료 사용에만 쓰고 MCP에는 쓰지 않습니다.
넣은 키는 요청 처리에만 쓰고 저장하거나 로그로 남기지 않습니다. 비용은 키 소유자 계정에 청구됩니다.

### 툴

`explain_notice(files, reading_level="아주 쉽게", mode="Claude API", redact=True, enhance=True, model="claude-sonnet-5-5")` — HF Space에서는 Space 이름이 붙어 `easy_notice_mcp_explain_notice`로 표시됩니다(클라이언트가 자동으로 인식).

- `files`: 문서 사진 또는 PDF 1~5개 — 공개 **http(s) URL** 또는 **data: URI** (`data:image/jpeg;base64,...`, `data:application/pdf;base64,...`)
- `reading_level`: `아주 쉽게` | `보통`
- `mode`: `Claude API`(기본, 가장 빠름) | `자동` | `무료 모델(GPU)`
- `model`: `claude-sonnet-5-5`(기본) | `claude-haiku-5-5`
- `redact`: 개인정보 가리기, `enhance`: 사진 보정
- 결과: 처리 방식 안내 + 짧은 음성 안내 문장 + 가족에게 보낼 요약 + 구글 캘린더 등록 링크 + 마크다운 설명 + 구조화된 JSON (음성 파일·가린 이미지·.ics는 웹 화면에서 제공)

보안상 서버의 로컬 파일 경로나 내부 네트워크 주소(127.0.0.1, 10.x, 169.254.x 등)는 받지 않습니다.

## 역할 분담

| Claude | 코드 |
|---|---|
| 문서 읽기, 할 일·기한·금액 추출, 용어 풀이, 사기 신호 | 출력 형식 강제(structured outputs) 및 값 정규화, 주민번호·전화번호 마스킹, 날짜 검증·D-day, 이상값 경고, 결과 조립 |

Claude 응답은 structured outputs(`output_config.format`, JSON Schema)로 받습니다. Sonnet 5.5 / Opus 5.5는 `tool_choice`로 툴 호출을 강제하는 방식을 400으로 거부하기 때문입니다.

## 구조

```
├── app.py          # Gradio UI + MCP 툴 (진입점)
├── pipeline.py     # 처리 방식 선택, GPU 실패 시 Claude 대체, 가림·음성 조립
├── models.py       # ZeroGPU 무료 모델 (EasyOCR·Swin2SR·MMS-TTS)과 @spaces.GPU 함수
├── vision.py       # 페이지 준비, 원근·대비 보정, OCR 결과에서 개인정보 찾기·가리기
├── voice.py        # 짧은 음성 안내 문장, 숫자 → 한글 수사
├── senior.py       # 한눈에 카드, 전화 버튼, 구글 캘린더·.ics, 가족 요약, 큰 글씨 인쇄
├── quota.py        # 운영자 키 무료 사용 한도 (IP당·전체 하루), 실제 IP 판별
├── prompts.py      # 시스템 프롬프트, 난이도 가이드, 출력 JSON 스키마
├── claude_util.py  # 본인 API 키 확인, 파일/URL 입력, structured outputs 호출
├── validate.py     # 스키마 기준 출력 정규화, API용 스키마 변환
├── logic.py        # 마스킹, D-day, 이상값 검사, 결과 조립
├── errors.py
└── tests/          # 데이터 검증 + 가짜 Claude로 전체 흐름 + 실제 원격 MCP(HTTP) 호출
```

## Space 설정

- 하드웨어: ZeroGPU. 모델은 시작할 때 GPU용으로 올려 두고 `@spaces.GPU` 함수(`gpu_prepare`, `gpu_tts`) 안에서만 실행합니다.
- Secret `ANTHROPIC_API_KEY`: 운영자 키. 웹·앱 화면에서 키 없이 쓰는 무료 사용에 쓰입니다(없으면 사용자가 키를 넣어야 함). Anthropic 콘솔에서 **월 사용 한도**를 꼭 걸어 두세요.
- Variable `FREE_DAILY_PER_USER`(기본 5): 한 사람(IP)당 하루 무료 횟수 / `FREE_DAILY_TOTAL`(기본 300): 전체 하루 무료 횟수. 카운터는 Space가 다시 시작되면 초기화됩니다.
- (선택) Variable `CLAUDE_MODEL`(기본 모델), `NOTICE_EFFORT`(기본 `low`)

## 로컬 실행·테스트

```bash
python -m venv .venv
.venv\Scripts\activate            # macOS/Linux: source .venv/bin/activate
pip install -r requirements-dev.txt
python app.py                     # http://127.0.0.1:7860, MCP: /gradio_api/mcp/
python -m pytest -q
RUN_MODEL_TESTS=1 python -m pytest -q -k real_ocr   # 실제 OCR로 가림 확인 (모델 다운로드, 한글 글꼴 필요)
```

정리 결과는 참고용입니다. 납부 전에는 고지서 원본이나 기관 공식 홈페이지에서 금액과 기한을 확인하세요.
