"""시니어용 보기: 한눈에 카드, 전화 버튼, 달력 등록, 가족에게 보낼 요약, 큰 글씨 인쇄.

모두 코드가 검증한 값(기한·D-day·금액)과 이미 마스킹된 결과만 쓴다. 이름·주민번호 같은 개인정보는 넣지 않는다.
"""
from __future__ import annotations

import datetime
import html
import re
import tempfile
import urllib.parse
import uuid
from pathlib import Path

SCAM_CALLS = [("경찰 112", "112"), ("금융감독원 1332", "1332")]

# 기관 대표번호·유선번호 (가려진 번호·휴대폰은 제외)
_PHONE = re.compile(r"(?<![\d*])(?:0(?:2|[3-6]\d|70|80)-?\d{3,4}-?\d{4}|1[5-9]\d{2}-?\d{4})(?![\d*])")


def _e(text) -> str:
    return html.escape(str(text or ""))


def institution_phone(contact: str | None) -> str | None:
    """문의처 문장에서 기관 전화번호 하나 (가려진 번호는 무시)."""
    if not contact:
        return None
    m = _PHONE.search(contact)
    return m.group() if m else None


def _tel(number: str) -> str:
    return "tel:" + re.sub(r"\D", "", number)


def _date_ko(iso: str) -> str:
    y, m, d = (int(x) for x in iso.split("-"))
    return f"{y}년 {m}월 {d}일"


def deadline_tone(d_day: dict | None) -> str:
    if not d_day:
        return "none"
    if d_day["days_left"] <= 3:
        return "danger"  # 3일 이내·오늘·지남
    if d_day["days_left"] <= 7:
        return "warn"
    return "ok"


def _deadline_text(data: dict) -> tuple[str, str]:
    d = data.get("d_day")
    if d:
        return _date_ko(d["date"]), d["label"]
    return (data.get("deadline_original_text") or "적힌 기한 없음"), ""


def _amount_text(data: dict) -> str:
    a = data.get("amount_krw")
    return f"{a:,}원" if a is not None else "적힌 금액 없음"


CARD_CSS = """
<style>
.nc{font-family:inherit;line-height:1.45}
.nc *{box-sizing:border-box}
/* 상자는 밝은 배경이므로 어두운 화면(다크 모드)에서도 글자를 진하게 고정 */
.nc .nc-box,.nc .nc-box *{color:#111 !important}
.nc .nc-box.danger .nc-big{color:#b3261e !important}
.nc .nc-scam,.nc .nc-scam *{color:#fff !important}
.nc .nc-scam .nc-call{color:#b3261e !important}
.nc .nc-call.plain{color:#fff !important}
.nc-title{font-size:1.5em;font-weight:800;margin:0 0 .3em}
.nc-sum{font-size:1.15em;margin:0 0 .8em}
.nc-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(min(100%,9em),1fr));gap:.6em}
.nc-box{border-radius:14px;padding:.8em 1em;background:#f3f5f7;border:2px solid #d6dbe0}
.nc-box b{display:block;font-size:.95em;color:#333}
.nc-big{font-size:1.6em;font-weight:800;margin-top:.15em;word-break:keep-all;overflow-wrap:anywhere}
.nc-sub{font-size:1.05em;color:#333}
.nc-box.ok{background:#eef7f0;border-color:#9cc9a8}
.nc-box.warn{background:#fff6e0;border-color:#e8b84a}
.nc-box.danger{background:#fdeceb;border-color:#d93025}
.nc-box.danger .nc-big{color:#b3261e}
.nc-scam{background:#b3261e;color:#fff;border-radius:14px;padding:1em;margin:0 0 .8em}
.nc-scam h3{color:#fff;font-size:1.5em;margin:0 0 .4em}
.nc-scam ul{margin:.3em 0 .6em 1.2em;font-size:1.1em}
.nc-calls{display:flex;flex-wrap:wrap;gap:.5em;margin-top:.6em}
.nc-call{display:inline-block;padding:.6em 1em;border-radius:12px;background:#fff;color:#b3261e !important;
  font-weight:800;font-size:1.15em;text-decoration:none !important;border:2px solid #fff}
.nc-call.plain{background:#1f6f8b;color:#fff !important;border-color:#1f6f8b}
</style>
"""


def card_html(data: dict) -> str:
    """결과 맨 위 '한눈에 보기' 카드. 사기 의심이면 빨간 경고와 전화 버튼을 먼저 보여 준다."""
    parts = [CARD_CSS, '<div class="nc">']
    phone = institution_phone(data.get("contact"))
    if data.get("scam_signals"):
        calls = "".join(f'<a class="nc-call" href="{_tel(n)}">📞 {_e(label)}</a>' for label, n in SCAM_CALLS)
        if phone:
            calls = f'<a class="nc-call" href="{_tel(phone)}">📞 기관에 확인 {_e(phone)}</a>' + calls
        reasons = "".join(f"<li>{_e(s)}</li>" for s in data["scam_signals"])
        parts.append(
            '<div class="nc-scam" role="alert"><h3>🚨 사기일 수 있어요! 돈을 보내지 마세요</h3>'
            f"<ul>{reasons}</ul>먼저 기관 대표번호로 직접 확인하세요.<div class=\"nc-calls\">{calls}</div></div>"
        )
    parts.append(f'<p class="nc-title">{_e(data.get("doc_type"))}</p>')
    if data.get("one_line_summary"):
        parts.append(f'<p class="nc-sum">{_e(data["one_line_summary"])}</p>')
    date_text, label = _deadline_text(data)
    todo = data.get("what_to_do") or []
    more = f'<div class="nc-sub">외 {len(todo) - 1}가지 (아래 설명 참고)</div>' if len(todo) > 1 else ""
    parts.append(
        '<div class="nc-grid">'
        f'<div class="nc-box {deadline_tone(data.get("d_day"))}"><b>📅 언제까지</b>'
        f'<div class="nc-big">{_e(label) or _e(date_text)}</div>'
        f'<div class="nc-sub">{_e(date_text) if label else ""}</div></div>'
        f'<div class="nc-box"><b>💰 얼마</b><div class="nc-big">{_e(_amount_text(data))}</div></div>'
        f'<div class="nc-box"><b>✅ 무엇을</b><div class="nc-sub" style="font-size:1.2em;font-weight:700">'
        f'{_e(todo[0]) if todo else "따로 할 일 없음"}</div>{more}</div>'
        "</div>"
    )
    if phone and not data.get("scam_signals"):
        parts.append(f'<div class="nc-calls"><a class="nc-call plain" href="{_tel(phone)}">📞 문의 전화 {_e(phone)}</a></div>')
    parts.append("</div>")
    return "".join(parts)


def family_text(data: dict) -> str:
    """가족에게 카카오톡·문자로 보낼 짧은 요약 (개인정보 없이)."""
    date_text, label = _deadline_text(data)
    lines = [f"[고지서 요약] {data.get('doc_type') or '안내문'}"]
    if data.get("scam_signals"):
        lines.append("⚠️ 사기 의심 신호가 있어요. 돈 보내기 전에 꼭 확인해 주세요.")
    lines.append(f"- 기한: {date_text}" + (f" ({label})" if label else ""))
    lines.append(f"- 금액: {_amount_text(data)}")
    for i, todo in enumerate((data.get("what_to_do") or [])[:3], 1):
        lines.append(f"- 할 일 {i}: {todo}")
    if phone := institution_phone(data.get("contact")):
        lines.append(f"- 문의: {phone}")
    lines.append("(자동 정리 결과라 원본 확인이 필요해요)")
    return "\n".join(lines)


# ---------- 달력 ----------

def _event_title(data: dict) -> str:
    kind = "납부" if data.get("amount_krw") else "처리"
    return f"{data.get('doc_type') or '고지서'} {kind} 기한"


def _event_details(data: dict) -> str:
    lines = []
    if data.get("amount_krw") is not None:
        lines.append(f"금액: {data['amount_krw']:,}원")
    for todo in (data.get("what_to_do") or [])[:3]:
        lines.append(f"할 일: {todo}")
    if phone := institution_phone(data.get("contact")):
        lines.append(f"문의: {phone}")
    lines.append("고지서 쉽게 보기로 정리 (원본 확인 필요)")
    return "\n".join(lines)


def google_calendar_url(data: dict) -> str | None:
    """'구글 캘린더에 추가' 링크 (종일 일정). 기한이 없으면 None."""
    d = data.get("d_day")
    if not d:
        return None
    day = datetime.date.fromisoformat(d["date"])
    dates = f"{day:%Y%m%d}/{day + datetime.timedelta(days=1):%Y%m%d}"
    query = urllib.parse.urlencode({
        "action": "TEMPLATE",
        "text": _event_title(data),
        "dates": dates,
        "details": _event_details(data),
        "ctz": "Asia/Seoul",
    })
    return "https://calendar.google.com/calendar/render?" + query


def calendar_button_html(url: str | None) -> str:
    """새 탭에서 여는 큰 '구글 캘린더에 추가' 버튼 (같은 탭으로 가면 결과 화면을 잃는다)."""
    if not url:
        return ""
    return (
        '<a href="' + html.escape(url, quote=True) + '" target="_blank" rel="noopener" '
        'style="display:flex;align-items:center;justify-content:center;min-height:3.2em;padding:.5em 1em;'
        'border-radius:10px;background:#1a73e8;color:#fff !important;font-weight:700;'
        'font-size:calc(var(--text-lg) * 1.2);text-decoration:none !important">📅 구글 캘린더에 추가</a>'
    )


def _ics_escape(text: str) -> str:
    return text.replace("\\", "\\\\").replace(";", "\\;").replace(",", "\\,").replace("\n", "\\n")


def _fold(line: str) -> str:
    """iCalendar 줄은 75바이트마다 접는다 (한글이 깨지지 않게 글자 단위로)."""
    out, cur = [], ""
    for ch in line:
        if len((cur + ch).encode("utf-8")) > (75 if not out else 74):
            out.append(cur)
            cur = ch
        else:
            cur += ch
    out.append(cur)
    return "\r\n ".join(out)


def ics_content(data: dict, now: datetime.datetime | None = None) -> str | None:
    """종일 일정 + 알림 2개(3일 전 오전 9시, 당일 오전 9시). 기한이 없으면 None."""
    d = data.get("d_day")
    if not d:
        return None
    day = datetime.date.fromisoformat(d["date"])
    now = now or datetime.datetime.now(datetime.timezone.utc)
    title = _ics_escape(_event_title(data))
    alarm = lambda trigger, desc: [  # noqa: E731
        "BEGIN:VALARM", "ACTION:DISPLAY", f"DESCRIPTION:{_ics_escape(desc)}", f"TRIGGER:{trigger}", "END:VALARM"]
    lines = [
        "BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//easy-notice-mcp//KO", "CALSCALE:GREGORIAN",
        "BEGIN:VEVENT",
        f"UID:{uuid.uuid4()}@easy-notice-mcp",
        f"DTSTAMP:{now:%Y%m%dT%H%M%SZ}",
        f"DTSTART;VALUE=DATE:{day:%Y%m%d}",
        f"DTEND;VALUE=DATE:{day + datetime.timedelta(days=1):%Y%m%d}",
        f"SUMMARY:{title}",
        f"DESCRIPTION:{_ics_escape(_event_details(data))}",
        *alarm("-P2DT15H", f"{_event_title(data)} 3일 전이에요"),   # 3일 전 오전 9시
        *alarm("PT9H", f"오늘이 {_event_title(data)}이에요"),        # 당일 오전 9시
        "END:VEVENT", "END:VCALENDAR",
    ]
    return "\r\n".join(_fold(line) for line in lines) + "\r\n"


def write_ics(data: dict) -> str | None:
    content = ics_content(data)
    if not content:
        return None
    folder = Path(tempfile.mkdtemp(prefix="notice-ics-"))
    path = folder / "납부기한.ics"
    path.write_bytes(content.encode("utf-8"))
    return str(path)


# ---------- 큰 글씨 인쇄 ----------

def print_html(data: dict) -> str:
    """큰 글씨 한 장짜리 인쇄용 페이지."""
    date_text, label = _deadline_text(data)
    sec = []

    def section(title, items):
        if items:
            sec.append(f"<h2>{_e(title)}</h2><ul>" + "".join(f"<li>{_e(i)}</li>" for i in items) + "</ul>")

    if data.get("scam_signals"):
        section("🚨 사기 의심 — 돈을 보내지 마세요", data["scam_signals"])
    section("✅ 해야 할 일", data.get("what_to_do"))
    section("내는 방법", data.get("payment_methods"))
    if data.get("if_missed"):
        section("놓치면", [data["if_missed"]])
    section("어려운 말", [f"{g['term']}: {g['easy']}" for g in data.get("glossary") or []])
    phone = institution_phone(data.get("contact"))
    return f"""<!doctype html><html lang="ko"><head><meta charset="utf-8"><title>{_e(data.get('doc_type'))}</title>
<style>
body{{font-family:'Malgun Gothic','Apple SD Gothic Neo',sans-serif;font-size:22pt;line-height:1.5;margin:1.2cm;color:#000}}
h1{{font-size:30pt;margin:0 0 .3em}} h2{{font-size:24pt;margin:.8em 0 .2em}}
.big{{font-size:28pt;font-weight:800}} .box{{border:3px solid #000;border-radius:12px;padding:.4em .7em;margin:.3em 0}}
small{{font-size:14pt}}
</style></head><body>
<h1>{_e(data.get('doc_type'))}</h1>
<p>{_e(data.get('one_line_summary'))}</p>
<div class="box">📅 언제까지: <span class="big">{_e(date_text)}</span> {_e(label)}</div>
<div class="box">💰 얼마: <span class="big">{_e(_amount_text(data))}</span></div>
{''.join(sec)}
{f'<p>📞 문의: <b>{_e(phone)}</b></p>' if phone else ''}
<p><small>자동으로 정리한 내용입니다. 돈을 내기 전에 고지서 원본이나 기관에 꼭 확인하세요.</small></p>
</body></html>"""
