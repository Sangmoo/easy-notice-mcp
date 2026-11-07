"""체험 모드("📄 예시로 보기") — API 키 없이, Claude를 부르지 않고 미리 만든 결과를 보여 준다.

Play 심사자와 처음 쓰는 어르신이 모든 기능(한눈에 카드, 듣기, 달력, 가족에게 보내기, 인쇄)을 바로 써 볼 수 있게 한다.
예시 고지서·문자는 지어낸 것이고, 개인정보 자리는 가린 모습이다. 기한은 오늘 기준으로 계산해 언제 봐도 실제처럼 보인다.
"""
from __future__ import annotations

import datetime
from pathlib import Path

from PIL import Image

from logic import finalize
from voice import build_script

EXAMPLE_DIR = Path(__file__).resolve().parent / "static" / "examples"
DEMO_NOTE = "📄 예시 화면입니다 (가짜 고지서로 만든 결과이며, 실제 분석이 아니에요)."

EXAMPLES = {
    "car_tax": "자동차세 고지서 예시",
    "scam_sms": "가짜 과태료 문자 예시 (사기 경고)",
}


def _car_tax(today: datetime.date) -> dict:
    due = today + datetime.timedelta(days=12)
    return {
        "doc_type": "자동차세 고지서 (예시)",
        "issuer": "○○시 ○○구청",
        "one_line_summary": "자동차를 가진 사람에게 나오는 2기분 자동차세를 내라는 고지서예요.",
        "what_to_do": [
            f"{due.month}월 {due.day}일까지 자동차세 130,000원을 내요.",
            "위택스 앱, 은행 앱, 가상계좌, 편의점 중 편한 곳에서 낼 수 있어요.",
            "이미 자동이체를 신청했다면 따로 낼 필요가 없어요.",
        ],
        "deadline": due.isoformat(),
        "deadline_original_text": "고지서를 받은 날부터 2주 안",
        "amount_krw": 130000,
        "amount_original_text": None,
        "payment_methods": ["위택스(wetax.go.kr) 또는 위택스 앱", "은행 앱의 지방세 납부", "고지서의 가상계좌", "편의점"],
        "if_missed": "기한이 지나면 가산금 3%가 더 붙어요.",
        "contact": "○○구청 세무과 (고지서에 적힌 대표번호)",
        "glossary": [
            {"term": "2기분", "easy": "1년 세금을 두 번에 나눠 낼 때 하반기(7~12월) 몫"},
            {"term": "가산금", "easy": "늦게 내면 벌금처럼 더 붙는 돈"},
            {"term": "가상계좌", "easy": "이 고지서 납부만을 위해 만든 임시 계좌번호"},
        ],
        "scam_signals": [],
        "unclear_parts": [],
        "voice_summary": "자동차세를 내라는 고지서예요",
    }


def _scam_sms(today: datetime.date) -> dict:
    return {
        "doc_type": "과태료 미납 안내 문자 (사기 의심 예시)",
        "issuer": None,
        "one_line_summary": "과태료를 오늘까지 개인 계좌로 내라는 문자예요. 진짜 기관 문자와 다른 점이 많아 사기일 가능성이 높아요.",
        "what_to_do": [
            "문자 속 링크를 누르지 말고, 돈도 보내지 마세요.",
            "경찰청 교통민원24(이파인)에 직접 들어가거나 112에 전화해 진짜 과태료가 있는지 확인하세요.",
            "이미 돈을 보냈다면 바로 은행과 112에 알리세요.",
        ],
        "deadline": today.isoformat(),
        "deadline_original_text": "오늘까지",
        "amount_krw": 64000,
        "amount_original_text": None,
        "payment_methods": [],
        "if_missed": None,
        "contact": None,
        "glossary": [{"term": "압류", "easy": "돈을 안 내면 나라가 재산을 마음대로 못 쓰게 묶는 것"}],
        "scam_signals": [
            "공공기관은 개인 명의 계좌로 돈을 받지 않아요.",
            "출처를 알 수 없는 인터넷 주소(링크)를 눌러 내라고 해요.",
            "'오늘까지 안 내면 압류'처럼 겁을 주며 서두르게 해요.",
            "담당자 개인 휴대폰 번호로 연락하라고 해요.",
        ],
        "unclear_parts": [],
        "voice_summary": "과태료를 내라는 문자인데 사기일 수 있어요",
    }


_BUILDERS = {"car_tax": (_car_tax, "car-tax.png"), "scam_sms": (_scam_sms, "scam-sms.png")}


def load(key: str, today: datetime.date) -> tuple[dict, list[Image.Image], dict]:
    """(정리 결과, 처리한 이미지, 음성 문장)."""
    builder, image_name = _BUILDERS[key]
    data = finalize(builder(today), today)
    image = Image.open(EXAMPLE_DIR / image_name).convert("RGB")
    return data, [image], build_script(data)
