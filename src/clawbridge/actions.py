"""Fixed JSON action schemas; no caller-selected code or filesystem paths."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any

MAX_BODY_BYTES = 64 * 1024
LABEL = re.compile(r"[A-Za-z0-9._:-]{1,128}\Z")


class InvalidRequestError(ValueError):
    """A request rejected before app execution."""


def correlation_id(value: str | None) -> str | None:
    """Validate an optional caller label, which is never an idempotency key."""
    if value is not None and not LABEL.fullmatch(value):
        raise InvalidRequestError("Invalid correlation ID")
    return value


def json_object(raw: bytes | str) -> dict[str, Any]:
    """Decode one bounded JSON object and reject ambiguous duplicate keys."""

    def pairs(items: list[tuple[str, Any]]) -> dict[str, Any]:
        result = {}
        for key, value in items:
            if key in result:
                raise InvalidRequestError("Duplicate JSON field")
            result[key] = value
        return result

    def constant(_value: str) -> None:
        raise InvalidRequestError("Non-finite JSON number")

    if len(raw) > MAX_BODY_BYTES:
        raise InvalidRequestError("Request body is too large")
    try:
        value = json.loads(raw, object_pairs_hook=pairs, parse_constant=constant)
    except (ValueError, UnicodeError, RecursionError) as exc:
        raise InvalidRequestError("Request body must be a JSON object") from exc
    if not isinstance(value, dict):
        raise InvalidRequestError("Request body must be a JSON object")
    return value


@dataclass(frozen=True)
class Action:
    """A build-time action definition with a small flat parameter schema."""

    name: str
    mutation: bool = False
    fields: dict[str, type | tuple[type, ...]] = field(default_factory=dict)
    required: frozenset[str] = frozenset()
    nonempty: frozenset[str] = frozenset()

    def validate(self, params: dict[str, Any]) -> dict[str, Any]:
        """Validate types and limits before journalling or starting a worker."""
        if not isinstance(params, dict) or set(params) - self.fields.keys() or self.required - params.keys():
            raise InvalidRequestError("Unsupported or missing action parameters")
        for key, value in params.items():
            allowed = self.fields[key]
            types = allowed if isinstance(allowed, tuple) else (allowed,)
            if type(value) not in types:
                raise InvalidRequestError("Invalid action parameter type")
            if isinstance(value, str) and (len(value) > 32768 or "\x00" in value):
                raise InvalidRequestError("Invalid action text parameter")
            if isinstance(value, list) and (len(value) > 1000 or any(type(item) is not str or len(item) > 32768 or "\x00" in item for item in value)):
                raise InvalidRequestError("Invalid action list parameter")
            if (key in self.required and value is None) or (key in self.nonempty and value == ""):
                raise InvalidRequestError("Required action parameter is empty")
        try:
            size = len(json.dumps(params, allow_nan=False).encode())
        except (ValueError, TypeError, RecursionError) as exc:
            raise InvalidRequestError("Invalid action parameters") from exc
        if size > MAX_BODY_BYTES:
            raise InvalidRequestError("Request body is too large")
        return dict(params)
