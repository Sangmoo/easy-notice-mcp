"""시니어용 보기 검증: 한눈에 카드, 전화 버튼, 달력(구글 링크·.ics), 가족 요약, 인쇄."""
import datetime
import sys
import urllib.parse
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import senior  # noqa: E402

BASE = {
    "doc_type": "자동차세 고지서",
    "one_line_summary": "2기분 자동차세를 내라는 고지서예요.",
    "what_to_do": ["11월 30일까지 자동차세를 내요.", "위택스 앱이나 은행에서 낼 수 있어요."],
    "amount_krw": 130000,
    "deadline_original_text": "2026.11.30.까지",
    "d_day": {"date": "2026-11-30", "days_left": 23, "label": "D-23", "status": "upcoming"},
    "payment_methods": ["위택스", "가상계좌"],
    "if_missed": "가산금 3%가 붙어요.",
    "glossary": [{"term": "납기", "easy": "내야 하는 마지막 날"}],
    "contact": "마포구청 세무과 02-3153-8000, 담당 010-****-5432",
    "scam_signals": [],
}


@pytest.mark.parametrize("contact, phone", [
    ("마포구청 세무과 02-3153-8000, 담당 010-****-5432", "02-3153-8000"),
    ("국민건강보험공단 1577-1000", "1577-1000"),
    ("031-123-4567", "031-123-4567"),
    ("담당 010-****-5432", None),       # 가려진 휴대폰은 쓰지 않음
    ("010-1234-5678", None),            # 개인 휴대폰은 기관 번호가 아님
    (None, None),
])
def test_institution_phone(contact, phone):
    assert senior.institution_phone(contact) == phone


@pytest.mark.parametrize("days, tone", [(23, "ok"), (7, "warn"), (3, "danger"), (0, "danger"), (-2, "danger")])
def test_deadline_tone(days, tone):
    assert senior.deadline_tone({"days_left": days}) == tone


def test_card_normal():
    html = senior.card_html(BASE)
    assert "자동차세 고지서" in html and "D-23" in html and "2026년 11월 30일" in html
    assert "130,000원" in html and "11월 30일까지 자동차세를 내요." in html and "외 1가지" in html
    assert 'href="tel:0231538000"' in html and "사기일 수 있어요" not in html
    assert "nc-box ok" in html


def test_card_scam_and_escaping():
    data = {**BASE, "scam_signals": ["개인 계좌로 입금 요구 <script>alert(1)</script>"],
            "d_day": {"date": "2026-11-08", "days_left": 1, "label": "D-1", "status": "upcoming"}}
    html = senior.card_html(data)
    assert "사기일 수 있어요" in html
    assert 'href="tel:112"' in html and 'href="tel:1332"' in html and 'href="tel:0231538000"' in html
    assert "<script>" not in html and "&lt;script&gt;" in html
    assert "nc-box danger" in html


def test_card_without_deadline_or_amount():
    data = {**BASE, "d_day": None, "deadline_original_text": None, "amount_krw": None, "what_to_do": [], "contact": None}
    html = senior.card_html(data)
    assert "적힌 기한 없음" in html and "적힌 금액 없음" in html and "따로 할 일 없음" in html
    assert "tel:" not in html


def test_family_text_has_no_private_numbers():
    text = senior.family_text(BASE)
    assert text.splitlines()[0] == "[고지서 요약] 자동차세 고지서"
    assert "- 기한: 2026년 11월 30일 (D-23)" in text and "- 금액: 130,000원" in text
    assert "- 문의: 02-3153-8000" in text and "010" not in text
    assert "사기 의심" not in text
    assert "사기 의심" in senior.family_text({**BASE, "scam_signals": ["x"]})


def test_google_calendar_url():
    url = senior.google_calendar_url(BASE)
    q = urllib.parse.parse_qs(urllib.parse.urlsplit(url).query)
    assert url.startswith("https://calendar.google.com/calendar/render?")
    assert q["action"] == ["TEMPLATE"] and q["dates"] == ["20261130/20261201"]  # 종일 일정
    assert q["text"] == ["자동차세 고지서 납부 기한"] and q["ctz"] == ["Asia/Seoul"]
    assert "금액: 130,000원" in q["details"][0] and "010" not in q["details"][0]
    assert senior.google_calendar_url({**BASE, "d_day": None}) is None
    q2 = urllib.parse.parse_qs(urllib.parse.urlsplit(senior.google_calendar_url({**BASE, "amount_krw": None})).query)
    assert q2["text"] == ["자동차세 고지서 처리 기한"]


def test_ics_content():
    ics = senior.ics_content(BASE, now=datetime.datetime(2026, 11, 7, 1, 2, 3, tzinfo=datetime.timezone.utc))
    assert ics.startswith("BEGIN:VCALENDAR\r\n") and ics.endswith("END:VCALENDAR\r\n")
    assert "DTSTART;VALUE=DATE:20261130" in ics and "DTEND;VALUE=DATE:20261201" in ics
    assert "DTSTAMP:20261107T010203Z" in ics
    assert ics.count("BEGIN:VALARM") == 2 and "TRIGGER:-P2DT15H" in ics and "TRIGGER:PT9H" in ics
    unfolded = ics.replace("\r\n ", "")
    assert "SUMMARY:자동차세 고지서 납부 기한" in unfolded
    assert "금액: 130\\,000원" in unfolded  # 쉼표는 이스케이프
    for line in ics.split("\r\n"):
        assert len(line.encode("utf-8")) <= 75  # 줄 접기
    assert senior.ics_content({**BASE, "d_day": None}) is None


def test_write_ics(tmp_path):
    path = senior.write_ics(BASE)
    assert path.endswith(".ics") and Path(path).read_bytes().startswith(b"BEGIN:VCALENDAR")
    assert senior.write_ics({**BASE, "d_day": None}) is None


def test_print_html():
    page = senior.print_html({**BASE, "scam_signals": ["개인 계좌 입금 요구"]})
    assert page.startswith("<!doctype html>") and "font-size:22pt" in page
    for text in ["자동차세 고지서", "2026년 11월 30일", "130,000원", "사기 의심", "해야 할 일", "위택스",
                 "가산금 3%", "납기: 내야 하는 마지막 날", "02-3153-8000"]:
        assert text in page
    assert "010" not in page


def test_calendar_button_opens_new_tab():
    html = senior.calendar_button_html(senior.google_calendar_url(BASE))
    assert 'target="_blank"' in html and 'rel="noopener"' in html and "&amp;" in html  # URL의 &는 이스케이프
    assert senior.calendar_button_html(None) == ""
