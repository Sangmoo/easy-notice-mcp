"""운영자 키 무료 사용 한도 검증: IP당 하루 5건, 전체 하루 한도, 실패 시 반환, 날짜 바뀜, IP 판별."""
import datetime
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import quota as q  # noqa: E402
from errors import ToolError  # noqa: E402


@pytest.fixture
def clock():
    state = {"day": datetime.date(2026, 11, 7)}
    return state


@pytest.fixture
def fq(clock, monkeypatch):
    monkeypatch.delenv("FREE_DAILY_PER_USER", raising=False)
    monkeypatch.delenv("FREE_DAILY_TOTAL", raising=False)
    return q.FreeQuota(today=lambda: clock["day"])


def test_per_user_limit_is_five(fq):
    for i in range(5):
        assert fq.remaining("1.1.1.1") == 5 - i
        fq.reserve("1.1.1.1")
    assert fq.remaining("1.1.1.1") == 0
    with pytest.raises(ToolError, match="5번을 모두 쓰셨어요"):
        fq.check("1.1.1.1")
    with pytest.raises(ToolError, match="5번을 모두 쓰셨어요"):
        fq.reserve("1.1.1.1")
    assert fq.remaining("2.2.2.2") == 5  # 다른 사람은 영향 없음


def test_release_returns_failed_request(fq):
    fq.reserve("1.1.1.1")
    fq.release("1.1.1.1")
    assert fq.remaining("1.1.1.1") == 5
    fq.release("9.9.9.9")  # 쓴 적 없는 사람은 그대로
    assert fq.remaining("9.9.9.9") == 5


def test_total_limit(fq, monkeypatch):
    monkeypatch.setenv("FREE_DAILY_TOTAL", "3")
    for ip in ("1.1.1.1", "2.2.2.2", "3.3.3.3"):
        fq.reserve(ip)
    assert fq.remaining("4.4.4.4") == 0
    with pytest.raises(ToolError, match="전체 무료 사용량"):
        fq.reserve("4.4.4.4")


def test_resets_next_day(fq, clock):
    for _ in range(5):
        fq.reserve("1.1.1.1")
    clock["day"] = datetime.date(2026, 11, 8)
    assert fq.remaining("1.1.1.1") == 5


def test_env_override(fq, monkeypatch):
    monkeypatch.setenv("FREE_DAILY_PER_USER", "2")
    fq.reserve("1.1.1.1")
    fq.reserve("1.1.1.1")
    with pytest.raises(ToolError, match="2번을 모두"):
        fq.check("1.1.1.1")
    monkeypatch.setenv("FREE_DAILY_PER_USER", "abc")  # 잘못된 값은 기본 5
    assert q.per_user_limit() == 5


@pytest.mark.parametrize("headers, peer, ip", [
    ({}, "203.0.113.9", "203.0.113.9"),
    ({"X-Forwarded-For": "211.234.10.20"}, "10.0.0.2", "211.234.10.20"),
    # 사용자가 앞쪽에 가짜 IP를 넣어도, 프록시가 오른쪽에 붙인 실제 IP를 쓴다
    ({"x-forwarded-for": "1.2.3.4, 211.234.10.20"}, "10.0.0.2", "211.234.10.20"),
    # 오른쪽 끝이 내부 프록시 주소면 건너뛴다
    ({"x-forwarded-for": "211.234.10.20, 10.0.0.7"}, "10.0.0.2", "211.234.10.20"),
    ({"x-forwarded-for": "garbage, 10.0.0.7"}, "10.0.0.2", "10.0.0.2"),
    ({}, None, "unknown"),
])
def test_client_ip(headers, peer, ip):
    assert q.client_ip(headers, peer) == ip
