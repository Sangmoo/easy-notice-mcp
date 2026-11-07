"""시스템 프롬프트와 출력 JSON 스키마.

출력 형식은 structured outputs(output_config.format)로 강제한다. API로 보낼 때는
validate.to_api_schema()가 모든 object에 additionalProperties: false를 붙인다.
"""

SYSTEM_PROMPT_BASE = """당신은 한국의 고지서·공문서·안내문을 누구나 이해할 수 있게 풀어주는 도우미입니다.
사용자가 올린 문서(사진 또는 PDF)를 읽고 "그래서 내가 뭘, 언제까지, 얼마를 해야 하는지"를 정리합니다.

반드시 지킬 규칙:
1. 문서에 적힌 내용만 정리한다. 문서에 없는 금액·기한·절차를 지어내지 않는다.
2. 날짜는 deadline에 YYYY-MM-DD 형식으로 넣고, 문서에 적힌 원문 표현은 deadline_original_text에 그대로 둔다. 기한이 없으면 null.
3. 금액은 납부해야 할 최종 금액을 amount_krw에 정수(원)로 넣는다. 여러 금액이 있으면 "납기 내 금액"을 넣고, 나머지는 amount_original_text에 설명한다.
4. 주민등록번호, 전체 계좌번호, 개인 전화번호, 상세 주소 등 개인정보는 결과에 절대 옮겨 적지 않는다. 필요하면 "주민번호 앞자리" 정도로만 언급한다.
5. 어려운 행정·법률 용어는 glossary에 쉬운 말로 풀어둔다.
6. 다음과 같은 사기·스미싱 의심 신호가 보이면 scam_signals에 적는다:
   개인 명의 계좌로 입금 요구, 단축 URL이나 출처 불명 링크, 공식 기관명과 다른 연락처, 지나친 긴급성 강조("오늘 안 내면 체포"), 앱 설치 요구, 기관이 보통 요구하지 않는 정보 요구.
   특히 한국에서 자주 쓰이는 고지서 사칭 수법을 확인한다:
   - '보안 고지서', '전자 고지서'를 보려면 별도 앱·뷰어나 설치 파일(APK)을 깔라고 함 → 국민건강보험공단 등 기관은 고지서를 보려고 앱 설치 파일을 요구하지 않는다.
   - 과태료·범칙금·벌금·신호위반 '고지서'를 문자 메시지의 링크로 보내 확인·납부하게 함 → 경찰청은 이런 고지서를 문자 링크로 보내지 않는다(교통민원24·이파인에서 직접 조회).
   - 택배·우편 반송, 소액결제, 건강검진 결과 등을 핑계로 링크를 누르게 함.
   이런 신호가 있으면 what_to_do에 '링크를 누르지 말고 돈도 보내지 말 것', '기관 공식 앱·누리집이나 대표번호로 직접 확인할 것',
   '이미 앱을 깔았거나 링크를 눌렀다면 118(한국인터넷진흥원)이나 112에 알릴 것'을 넣는다.
7. 글씨가 흐리거나 잘려서 확실하지 않은 부분은 추측하지 말고 unclear_parts에 적는다.
"""

LEVEL_GUIDE = {
    "아주 쉽게": "설명은 초등학생이나 어르신도 이해할 수 있게 아주 짧은 문장과 쉬운 단어로 쓴다. 한자어·외래어는 피한다.",
    "보통": "설명은 일반 성인이 빠르게 읽을 수 있게 간결하게 쓴다.",
}

NOTICE_SCHEMA = {
    "type": "object",
    "properties": {
        "doc_type": {"type": "string", "description": "예: 자동차세 고지서, 건강보험료 고지서, 과태료 사전통지서, 주민센터 안내문"},
        "issuer": {"type": ["string", "null"], "description": "보낸 기관"},
        "one_line_summary": {"type": "string", "description": "이 문서가 무엇인지 한 문장"},
        "what_to_do": {"type": "array", "items": {"type": "string"}, "description": "해야 할 일을 순서대로. 할 일이 없으면 '따로 할 일 없음'"},
        "deadline": {"type": ["string", "null"], "description": "YYYY-MM-DD 또는 null"},
        "deadline_original_text": {"type": ["string", "null"]},
        "amount_krw": {"type": ["integer", "null"]},
        "amount_original_text": {"type": ["string", "null"]},
        "payment_methods": {"type": "array", "items": {"type": "string"}, "description": "문서에 적힌 납부·처리 방법"},
        "if_missed": {"type": ["string", "null"], "description": "기한을 놓치면 생기는 일 (가산금 등). 문서에 없으면 null"},
        "contact": {"type": ["string", "null"], "description": "문서에 적힌 기관 문의처"},
        "glossary": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {"term": {"type": "string"}, "easy": {"type": "string"}},
                "required": ["term", "easy"],
            },
        },
        "scam_signals": {"type": "array", "items": {"type": "string"}},
        "unclear_parts": {"type": "array", "items": {"type": "string"}},
    },
    "required": [
        "doc_type", "one_line_summary", "what_to_do", "deadline", "amount_krw",
        "payment_methods", "glossary", "scam_signals", "unclear_parts",
    ],
}


# ---------- 추가 필드 ----------

# 음성 안내 첫 문장 (기한·금액은 코드가 검증한 값으로 따로 읽어 준다)
NOTICE_SCHEMA["properties"]["voice_summary"] = {
    "type": "string",
    "description": "음성 안내용 첫 문장. 이 문서가 무엇이고 무엇을 해야 하는지 30자 안팎의 한 문장, 해요체. "
                   "숫자·날짜·금액·개인정보는 넣지 않는다(따로 읽어 줌). 예: '자동차세를 내라는 고지서예요'",
}

# Claude 모드에서 개인정보 위치를 받아 사용자용 사본을 가릴 때만 쓰는 필드
PII_REGIONS_SCHEMA = {
    "type": "array",
    "description": "이미지에서 개인정보 값이 적힌 영역. 없으면 빈 배열",
    "items": {
        "type": "object",
        "properties": {
            "page": {"type": "integer", "description": "이미지 순서 (1부터)"},
            "box": {
                "type": "array",
                "items": {"type": "integer"},
                "description": "[왼쪽, 위, 오른쪽, 아래]. 이미지 왼쪽 위가 (0,0), 오른쪽 아래가 (1000,1000)인 정수 좌표",
            },
            "kind": {"type": "string", "enum": ["주민등록번호", "전화번호", "계좌번호", "이름", "주소", "기타"]},
        },
        "required": ["page", "box", "kind"],
    },
}


def schema_for(find_pii: bool) -> dict:
    """find_pii면 pii_regions를 필수로 추가한 스키마 사본."""
    if not find_pii:
        return NOTICE_SCHEMA
    schema = {**NOTICE_SCHEMA, "properties": {**NOTICE_SCHEMA["properties"], "pii_regions": PII_REGIONS_SCHEMA}}
    schema["required"] = [*NOTICE_SCHEMA["required"], "pii_regions"]
    return schema


PROMPT_ALREADY_REDACTED = (
    "\n문서 이미지의 검은 상자는 개인정보(이름·주소·주민번호·전화번호·계좌번호)를 미리 가린 부분이다. "
    "읽으려 하거나 추측하지 말고, unclear_parts에도 넣지 않는다."
)

PROMPT_FIND_PII = (
    "\npii_regions에는 각 이미지에서 개인정보 '값'(이름, 주소, 주민등록번호, 개인 전화번호, 계좌번호)이 적힌 영역을 "
    "이미지 왼쪽 위 (0,0)·오른쪽 아래 (1000,1000) 기준 정수 좌표로 적는다. 라벨 글자('성명', '주소' 등)는 빼고 값만 감싼다. "
    "기관 대표번호, 납부 금액, 날짜, 납부번호는 개인정보가 아니다."
)
