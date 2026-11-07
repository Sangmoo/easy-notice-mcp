"""틀리면 안 되는 부분은 코드가 결정한다: 개인정보 마스킹, 기한 검증·D-day 계산, 결과 조립.

src/lib/logic.ts와 동작이 같아야 한다 (tests/fixtures/cases.json으로 양쪽을 함께 검증).
"""
from __future__ import annotations

import datetime
import re

MAX_FILES = 5
LEVELS = ["아주 쉽게", "보통"]
MAX_AMOUNT = 10_000_000_000  # 100억 초과는 잘못 읽었을 가능성이 높다

# Claude가 실수로 옮겨 적더라도 최종 출력에서 한 번 더 가린다.
# \b는 Python에서 한글도 단어 문자로 보므로("주민번호900101-…"에서 경계가 없음) 숫자 lookaround를 쓴다.
MASK_PATTERNS = [
    (re.compile(r"(?<!\d)(\d{6})[-\s]?[1-8]\d{6}(?!\d)"), r"\1-*******"),  # 주민·외국인등록번호
    (re.compile(r"(?<!\d)(01[016789])[-\s.]?\d{3,4}[-\s.]?(\d{4})(?!\d)"), r"\1-****-\2"),  # 휴대전화
]
ISO_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def mask(value):
    if isinstance(value, str):
        for pattern, repl in MASK_PATTERNS:
            value = pattern.sub(repl, value)
        return value
    if isinstance(value, list):
        return [mask(v) for v in value]
    if isinstance(value, dict):
        return {k: mask(v) for k, v in value.items()}
    return value


def parse_date(value) -> datetime.date | None:
    """YYYY-MM-DD만 받는다 (Python 3.11+의 느슨한 fromisoformat과 무관하게 웹과 동일하게)."""
    if not isinstance(value, str) or not ISO_DATE.match(value):
        return None
    try:
        return datetime.date.fromisoformat(value)
    except ValueError:
        return None


def d_day_info(deadline, today: datetime.date) -> dict | None:
    due = parse_date(deadline)
    if due is None:
        return None
    days = (due - today).days
    if days > 0:
        label, status = f"D-{days}", "upcoming"
    elif days == 0:
        label, status = "오늘 마감", "today"
    else:
        label, status = f"기한 {-days}일 지남", "overdue"
    return {"date": due.isoformat(), "days_left": days, "label": label, "status": status}


def check_data(data: dict, today: datetime.date) -> list[str]:
    """Claude가 읽은 값 중 사람이 원본과 대조해야 할 것들."""
    warnings: list[str] = []
    raw = data.get("deadline")
    due = parse_date(raw)
    if raw is not None and due is None:
        warnings.append(f"기한 날짜를 해석하지 못했습니다(\"{raw}\"). 원본에서 기한을 확인하세요.")
    elif due is not None:
        if due.year < today.year - 1 or due.year > today.year + 2:
            warnings.append(f"기한 연도({due.year}년)가 예상 범위를 벗어납니다. 원본에서 연도를 확인하세요.")
    amount = data.get("amount_krw")
    if amount is not None and amount > MAX_AMOUNT:
        warnings.append(f"금액({amount:,}원)이 비정상적으로 큽니다. 원본에서 금액을 확인하세요.")
    if amount == 0:
        warnings.append("금액이 0원으로 읽혔습니다. 낼 돈이 없는 문서인지 원본에서 확인하세요.")
    return warnings


def finalize(data: dict, today: datetime.date) -> dict:
    """검증된 Claude 결과 → 마스킹 → 기한 검증·D-day → 확인 필요 항목."""
    data = mask(dict(data))
    if data.get("deadline") is not None and parse_date(data["deadline"]) is None:
        if not data.get("deadline_original_text"):
            data["deadline_original_text"] = data["deadline"]
    data["validation_warnings"] = check_data(data, today)
    if parse_date(data.get("deadline")) is None:
        data["deadline"] = None
    data["d_day"] = d_day_info(data.get("deadline"), today)
    return data


def render(data: dict) -> str:
    out = [f"## {data['doc_type']}", data["one_line_summary"]]

    if data.get("scam_signals"):
        out.append(
            "### 🚨 사기 의심 신호가 있습니다\n"
            + "\n".join(f"- {s}" for s in data["scam_signals"])
            + "\n\n**돈을 보내기 전에 기관 대표번호로 직접 확인하세요.**"
        )

    dday = data.get("d_day")
    if dday:
        icon = {"upcoming": "📅", "today": "⏰", "overdue": "❗"}[dday["status"]]
        out.append(f"### {icon} 기한: {dday['date']} ({dday['label']})")
    elif data.get("deadline_original_text"):
        out.append(f"### 📅 기한: {data['deadline_original_text']}")

    if data.get("amount_krw") is not None:
        out.append(f"### 💰 금액: {data['amount_krw']:,}원")
    if data.get("amount_original_text"):
        out.append(data["amount_original_text"])

    out.append("### ✅ 해야 할 일\n" + "\n".join(f"{i}. {s}" for i, s in enumerate(data["what_to_do"], 1)))

    if data.get("payment_methods"):
        out.append("### 내는 방법\n" + "\n".join(f"- {m}" for m in data["payment_methods"]))
    if data.get("if_missed"):
        out.append(f"### 놓치면\n{data['if_missed']}")
    if data.get("glossary"):
        out.append("### 어려운 말 풀이\n" + "\n".join(f"- **{g['term']}**: {g['easy']}" for g in data["glossary"]))
    check = list(data.get("validation_warnings") or []) + list(data.get("unclear_parts") or [])
    if check:
        out.append("### 원본 확인 필요\n" + "\n".join(f"- {u}" for u in check))
    if data.get("contact"):
        out.append(f"문의: {data['contact']}")

    out.append("---\n*정리 결과는 참고용입니다. 납부 전에는 고지서 원본이나 기관 공식 홈페이지에서 금액과 기한을 확인하세요.*")
    return "\n\n".join(out)
