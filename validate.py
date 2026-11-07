"""Claude 출력 검증·정규화.

structured outputs로 형식은 보장되지만, 값이 어긋날 수 있다(숫자를 "12,000원" 문자열로 주거나,
빈 문자열을 null 대신 넣는 등). 또 테스트·다른 경로로 들어온 값도 같은 기준으로 맞춘다. 결과를 쓰기 전에 스키마 기준으로
한 번 더 맞춘다. 필수 문자열이 비어 있으면 결과를 신뢰할 수 없으므로 오류로 처리한다.
"""
from __future__ import annotations

import math
import re

from errors import ToolError

_NUM_RE = re.compile(r"-?\d[\d,]*(?:\.\d+)?")


def _types(spec: dict) -> list[str]:
    t = spec.get("type", "string")
    return t if isinstance(t, list) else [t]


def _round_half_up(n: float) -> int:
    """사사오입 (src/lib/validate.ts의 Math.floor(n + 0.5)와 동일)."""
    return int(math.floor(n + 0.5))


def _to_int(v):
    if isinstance(v, bool):
        return None
    if isinstance(v, int):
        return v
    if isinstance(v, float):
        return _round_half_up(v) if math.isfinite(v) else None
    if isinstance(v, str):
        m = _NUM_RE.search(v)
        if not m:
            return None
        try:
            n = float(m.group().replace(",", ""))
        except ValueError:
            return None
        return _round_half_up(n) if math.isfinite(n) else None
    return None


def _coerce(v, spec: dict, path: str, required: bool):
    types = _types(spec)
    nullable = "null" in types
    base = next((t for t in types if t != "null"), "string")

    if base == "array":
        if v is None:
            return []
        if not isinstance(v, list):
            v = [v]
        item_spec = spec.get("items", {"type": "string"})
        out = []
        for i, item in enumerate(v):
            c = _coerce_item(item, item_spec, f"{path}[{i}]")
            if c is not None:
                out.append(c)
        return out

    if base == "integer":
        n = _to_int(v)
        if n is None or n < 0:
            if nullable or not required:
                return None
            raise ToolError(f"결과의 '{path}' 값이 올바르지 않습니다. 다시 시도해주세요.")
        return n

    if base == "string":
        s = v.strip() if isinstance(v, str) else (str(v) if isinstance(v, (int, float)) and not isinstance(v, bool) else None)
        if s in ("", "null", "None"):
            s = None
        if s is None:
            if nullable or not required:
                return None
            raise ToolError(f"결과에 '{path}' 항목이 없습니다. 다시 시도해주세요.")
        enum = spec.get("enum")
        if enum and s not in enum:
            lowered = {e.lower(): e for e in enum}
            s = lowered.get(s.lower(), spec.get("default", enum[-1]))
        return s

    if base == "object":
        return _coerce_object(v, spec, path) if isinstance(v, dict) else None

    return v


def _coerce_item(item, spec: dict, path: str):
    """배열 원소: 잘못된 원소는 오류 대신 버린다."""
    try:
        return _coerce(item, spec, path, required=True)
    except ToolError:
        return None


def _coerce_object(data: dict, schema: dict, path: str = "") -> dict:
    props = schema.get("properties", {})
    required = set(schema.get("required", []))
    out = {}
    for key, spec in props.items():
        sub = f"{path}.{key}" if path else key
        out[key] = _coerce(data.get(key), spec, sub, key in required)
    return out


def normalize(data: dict, schema: dict) -> dict:
    """스키마에 정의된 키만 남기고 타입을 맞춘다. 필수 값이 없으면 ToolError."""
    if not isinstance(data, dict):
        raise ToolError("Claude 응답 형식이 올바르지 않습니다. 다시 시도해주세요.")
    return _coerce_object(data, schema)


# structured outputs가 받지 않는 키워드 (SDK 문서의 JSON Schema 제약)
_UNSUPPORTED = {"default", "minimum", "maximum", "multipleOf", "minLength", "maxLength", "minItems", "maxItems"}


def to_api_schema(schema):
    """output_config.format용 스키마: 모든 object에 additionalProperties: false, 미지원 키워드 제거.

    원본 스키마(enum 기본값 등)는 normalize()에서 그대로 쓰고, API에는 이 사본을 보낸다.
    """
    if isinstance(schema, list):
        return [to_api_schema(s) for s in schema]
    if not isinstance(schema, dict):
        return schema
    out = {k: to_api_schema(v) for k, v in schema.items() if k not in _UNSUPPORTED}
    if out.get("properties") is not None:  # properties의 키는 필드 이름이라 위 필터와 무관
        out["properties"] = {k: to_api_schema(v) for k, v in schema["properties"].items()}
    types = out.get("type")
    if types == "object" or (isinstance(types, list) and "object" in types):
        out["additionalProperties"] = False
    return out
