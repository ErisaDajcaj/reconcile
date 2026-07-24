"""Ingest agent: the LLM maps headers, deterministic code coerces values.

The model is asked exactly one question per file -- "which source header feeds
which canonical field?" -- and answers with header names only. It never sees a
task where it could produce a number.
"""

import csv
from pathlib import Path

from .llm import LLMClient, LLMError
from .parse import (
    ORDER_COLUMNS,
    PAYOUT_COLUMNS,
    identity_mapping,
    parse_orders,
    parse_payouts,
)
from .schema import ColumnMapping, OrderLine, PayoutLine

MIN_MAPPING_CONFIDENCE = 0.9

_SYSTEM = (
    "You map the column headers of a CSV onto a fixed canonical schema. "
    "Every header you return must be one of the source headers, copied verbatim. "
    "Never invent a header, never read or interpret data values, never return a "
    "number you computed. If a required field has no plausible source header, "
    "leave it out and lower your confidence. "
    "`confidence` is a number on a 0.0-1.0 scale (0.0 = no confidence, "
    "1.0 = certain), never a percentage or any other scale."
)


class MappingError(ValueError):
    """Headers could not be mapped with confidence. Fail closed: reject the job."""


def _mapping_schema(target_fields: set[str]) -> dict:
    return {
        "type": "object",
        "properties": {
            "mapping": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "field": {"type": "string", "enum": sorted(target_fields)},
                        "header": {"type": "string"},
                    },
                    "required": ["field", "header"],
                    "additionalProperties": False,
                },
            },
            "confidence": {"type": "number"},
        },
        "required": ["mapping", "confidence"],
        "additionalProperties": False,
    }


def _is_number(value) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def infer_mapping(
    headers,
    target_fields,
    client: LLMClient | None,
    *,
    min_confidence: float = MIN_MAPPING_CONFIDENCE,
) -> ColumnMapping:
    headers = list(headers)
    target = set(target_fields)

    # Deterministic short-circuit: the common case stays free and model-free.
    if target <= set(headers):
        return identity_mapping(target)

    if client is None:
        raise MappingError(
            f"headers {sorted(headers)} are not canonical and no LLM client was supplied"
        )

    user = (
        "Canonical fields: " + ", ".join(sorted(target)) + "\n"
        "Source headers: " + ", ".join(headers)
    )
    try:
        out = client.structured(system=_SYSTEM, user=user, schema=_mapping_schema(target))
    except LLMError as exc:
        raise MappingError(f"header mapping failed: {exc}") from exc

    pairs = out.get("mapping")
    confidence = out.get("confidence")
    if not isinstance(pairs, list) or not _is_number(confidence):
        raise MappingError(f"malformed mapping response: {out!r}")
    if not 0.0 <= confidence <= 1.0:
        raise MappingError(f"mapping confidence {confidence} outside valid range [0.0, 1.0]")
    if confidence < min_confidence:
        raise MappingError(
            f"mapping confidence {confidence} below threshold {min_confidence}"
        )

    fields: dict[str, str] = {}
    seen_headers: dict[str, str] = {}
    for pair in pairs:
        if not isinstance(pair, dict):
            continue
        field, header = pair.get("field"), pair.get("header")
        if not isinstance(field, str) or not isinstance(header, str):
            raise MappingError(f"malformed mapping pair: {pair!r}")
        if field not in target:
            continue
        if header not in headers:
            raise MappingError(f"mapping references unknown header: {header!r}")
        if field in fields:
            raise MappingError(f"field mapped more than once: {field!r}")
        if header in seen_headers:
            raise MappingError(
                f"header {header!r} mapped to more than one field: "
                f"{seen_headers[header]!r} and {field!r}"
            )
        fields[field] = header
        seen_headers[header] = field

    missing = sorted(target - fields.keys())
    if missing:
        raise MappingError(f"required field(s) left unmapped: {missing}")
    return ColumnMapping(fields=fields)


def read_headers(path) -> list[str]:
    with Path(path).open(newline="", encoding="utf-8") as fh:
        return next(csv.reader(fh), [])


def load_payouts(path, client: LLMClient | None = None) -> list[PayoutLine]:
    mapping = infer_mapping(read_headers(path), PAYOUT_COLUMNS, client)
    return parse_payouts(path, mapping)


def load_orders(path, client: LLMClient | None = None) -> list[OrderLine]:
    mapping = infer_mapping(read_headers(path), ORDER_COLUMNS, client)
    return parse_orders(path, mapping)
