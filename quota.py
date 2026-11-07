"""운영자 키(Space Secret)로 무료 사용할 때의 하루 한도.

- 한 사람(IP)당 하루 FREE_DAILY_PER_USER건 (기본 5)
- 전체 하루 FREE_DAILY_TOTAL건 (기본 300)
- 날짜는 한국 시간 기준으로 바뀐다.
- Claude 호출 직전에 1건을 예약하고, 호출이 실패하면 돌려준다 (비용이 안 든 요청은 세지 않음).

카운터는 메모리에 있어 Space가 다시 시작되면 초기화된다. 최종 안전장치는 Anthropic 콘솔의 월 사용 한도다.
IP는 기록·로그로 남기지 않고 하루 단위 카운터의 키로만 쓴다.
"""
from __future__ import annotations

import datetime
import ipaddress
import os
import threading
from collections import defaultdict

from errors import ToolError

KST = datetime.timezone(datetime.timedelta(hours=9))

MSG_USER_LIMIT = (
    "오늘 무료로 쓸 수 있는 {limit}번을 모두 쓰셨어요. 내일 다시 써 주세요. "
    "(가족이 '더보기 설정'에 Anthropic 키를 넣어 주면 제한 없이 쓸 수 있어요)"
)
MSG_TOTAL_LIMIT = "오늘은 전체 무료 사용량이 다 찼어요. 내일 다시 써 주세요."


def _env_int(name: str, default: int) -> int:
    try:
        return max(0, int(os.getenv(name, str(default))))
    except ValueError:
        return default


def per_user_limit() -> int:
    return _env_int("FREE_DAILY_PER_USER", 5)


def total_limit() -> int:
    return _env_int("FREE_DAILY_TOTAL", 300)


def _today() -> datetime.date:
    return datetime.datetime.now(KST).date()


class FreeQuota:
    def __init__(self, today=_today):
        self._today = today
        self._lock = threading.Lock()
        self._date = None
        self._users: dict[str, int] = defaultdict(int)
        self._total = 0

    def _roll(self) -> None:
        today = self._today()
        if self._date != today:
            self._date, self._users, self._total = today, defaultdict(int), 0

    def remaining(self, user: str) -> int:
        with self._lock:
            self._roll()
            return max(0, min(per_user_limit() - self._users[user], total_limit() - self._total))

    def check(self, user: str) -> None:
        """예약 없이 남았는지만 확인 (파일을 읽기 전에 빨리 알려 주려고)."""
        with self._lock:
            self._roll()
            self._raise_if_exhausted(user)

    def reserve(self, user: str) -> None:
        with self._lock:
            self._roll()
            self._raise_if_exhausted(user)
            self._users[user] += 1
            self._total += 1

    def release(self, user: str) -> None:
        with self._lock:
            if self._users.get(user, 0) > 0:
                self._users[user] -= 1
                self._total = max(0, self._total - 1)

    def _raise_if_exhausted(self, user: str) -> None:
        if self._total >= total_limit():
            raise ToolError(MSG_TOTAL_LIMIT)
        if self._users[user] >= per_user_limit():
            raise ToolError(MSG_USER_LIMIT.format(limit=per_user_limit()))


quota = FreeQuota()


def client_ip(headers: dict, peer: str | None) -> str:
    """요청한 사람의 IP.

    X-Forwarded-For는 앞쪽 값을 사용자가 마음대로 넣을 수 있으므로,
    오른쪽(프록시가 붙인 쪽)부터 보며 처음 나오는 공인 IP를 쓴다. 없으면 접속 주소.
    """
    xff = ""
    for k, v in (headers or {}).items():
        if k.lower() == "x-forwarded-for":
            xff = v
            break
    for part in reversed([p.strip() for p in xff.split(",") if p.strip()]):
        try:
            if ipaddress.ip_address(part).is_global:
                return part
        except ValueError:
            continue
    return peer or "unknown"
