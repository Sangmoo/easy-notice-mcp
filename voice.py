"""음성 안내 문장 만들기 (짧게).

기한·금액처럼 틀리면 안 되는 값은 Claude 문장이 아니라 코드가 검증한 값으로 읽어 준다.
TTS 모델은 숫자를 읽지 못하므로(로마자 변환 시 숫자가 그대로 남음) 한글 수사로 바꾼 문장을 따로 만든다.
"""
from __future__ import annotations

import re

MAX_SUMMARY_CHARS = 40

_DIGITS = ["", "일", "이", "삼", "사", "오", "육", "칠", "팔", "구"]
_SMALL_UNITS = ["", "십", "백", "천"]
_BIG_UNITS = ["", "만", "억", "조"]
_MONTHS = {6: "유월", 10: "시월"}


def number_to_korean(n: int) -> str:
    """정수 → 한자어 수사. 130000 → '십삼만', 87650 → '팔만 칠천육백오십'."""
    if n == 0:
        return "영"
    if n < 0:
        return "마이너스 " + number_to_korean(-n)
    groups = []
    big = 0
    while n > 0 and big < len(_BIG_UNITS):
        n, chunk = divmod(n, 10000)
        if chunk:
            words = ""
            for pos in range(3, -1, -1):
                d = (chunk // 10**pos) % 10
                if d == 0:
                    continue
                # '일십', '일백', '일천'은 '십', '백', '천'으로 읽는다
                words += ("" if d == 1 and pos > 0 else _DIGITS[d]) + _SMALL_UNITS[pos]
            # '일만'은 '만'으로 읽는다
            if big == 1 and chunk == 1:
                words = ""
            groups.append(words + _BIG_UNITS[big])
        big += 1
    return " ".join(reversed(groups)).strip()


def _month_korean(m: int) -> str:
    return _MONTHS.get(m, number_to_korean(m) + "월")


def _clean_summary(text: str | None, fallback: str) -> str:
    s = re.sub(r"\s+", " ", (text or "").strip())
    # 숫자·개인정보가 섞이면 읽기 어렵고 틀릴 수 있으므로 쓰지 않는다
    if not s or re.search(r"\d", s):
        s = fallback
    if len(s) > MAX_SUMMARY_CHARS:
        cut = s[:MAX_SUMMARY_CHARS]
        s = cut[: cut.rfind(" ")] if " " in cut else cut
    s = s.rstrip(" .")
    return s + "."


def build_script(data: dict) -> dict:
    """정리 결과 → {'text': 화면용 짧은 안내, 'speech': TTS용(숫자를 한글로)}.

    최대 4문장: 한 줄 요약 / 사기 경고 / 기한 / 금액.
    """
    summary = _clean_summary(data.get("voice_summary"), f"{data.get('doc_type') or '안내문'}입니다")
    text, speech = [summary], [summary]

    if data.get("scam_signals"):
        s = "사기가 의심돼요. 돈을 보내기 전에 기관 대표번호로 꼭 확인하세요."
        text.append(s)
        speech.append(s)

    dday = data.get("d_day")
    if dday:
        y, m, d = (int(x) for x in dday["date"].split("-"))
        days = dday["days_left"]
        date_t, date_s = f"{m}월 {d}일", f"{_month_korean(m)} {number_to_korean(d)}일"
        if days > 0:
            text.append(f"{date_t}까지, {days}일 남았어요.")
            speech.append(f"{date_s}까지, {number_to_korean(days)}일 남았어요.")
        elif days == 0:
            text.append(f"오늘({date_t})까지예요.")
            speech.append(f"오늘, {date_s}까지예요.")
        else:
            text.append(f"기한({date_t})이 {-days}일 지났어요.")
            speech.append(f"기한이 {number_to_korean(-days)}일 지났어요.")

    amount = data.get("amount_krw")
    if amount:
        text.append(f"금액은 {amount:,}원이에요.")
        speech.append(f"금액은 {number_to_korean(amount)} 원이에요.")

    return {"text": " ".join(text), "speech": " ".join(speech)}
