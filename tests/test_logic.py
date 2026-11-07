"""Python 쪽 데이터 검증. 같은 fixture를 tests/logic.test.ts가 TypeScript 쪽에 적용한다.

실행: python -m pytest -q
"""
import datetime
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from errors import ToolError  # noqa: E402
from logic import d_day_info, finalize, mask, render  # noqa: E402
from prompts import LEVEL_GUIDE, NOTICE_SCHEMA  # noqa: E402
from validate import normalize  # noqa: E402

CASES = json.loads((ROOT / "tests" / "fixtures" / "cases.json").read_text(encoding="utf-8"))
TODAY = datetime.date.fromisoformat(CASES["today"])


@pytest.mark.parametrize("case", CASES["mask"], ids=lambda c: str(c["input"])[:30])
def test_mask(case):
    assert mask(case["input"]) == case["expected"]


@pytest.mark.parametrize("case", CASES["d_day"], ids=lambda c: str(c["deadline"]))
def test_d_day(case):
    assert d_day_info(case["deadline"], TODAY) == case["expected"]


@pytest.mark.parametrize("case", CASES["finalize"], ids=lambda c: c["name"])
def test_finalize(case):
    if case.get("error"):
        with pytest.raises(ToolError):
            normalize(case["input"], NOTICE_SCHEMA)
        return
    data = finalize(normalize(case["input"], NOTICE_SCHEMA), TODAY)
    assert data == case["expected"]
    if "render" in case:
        assert render(data) == case["render"]


def test_render_scam_and_original_deadline():
    case = CASES["finalize"][1]
    text = render(finalize(normalize(case["input"], NOTICE_SCHEMA), TODAY))
    assert text.index("🚨 사기 의심 신호") < text.index("해야 할 일")
    assert "### 📅 기한: 2026-02-30" in text  # 해석 못 한 날짜는 원문 그대로
    assert "원본 확인 필요" in text


def test_schema_and_levels():
    props = NOTICE_SCHEMA["properties"]
    assert set(NOTICE_SCHEMA["required"]) <= set(props)
    assert list(LEVEL_GUIDE) == ["아주 쉽게", "보통"]
