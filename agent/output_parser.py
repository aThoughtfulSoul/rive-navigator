"""
Server-side parsing and validation for model-emitted ACTION and CURSOR tags.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any


ALLOWED_ACTION_TYPES = {"click", "doubleclick", "drag", "hover", "key", "type", "wait"}
ALLOWED_MODIFIERS = {"meta", "ctrl", "shift", "alt"}
TAG_PATTERNS = {
    "ACTION": re.compile(r"<!--ACTION:\s*(\{.*?\})\s*-->", re.DOTALL),
    "CURSOR": re.compile(r"<!--CURSOR:\s*(\{.*?\})\s*-->", re.DOTALL),
}
LEGACY_TAG_PATTERNS = {
    "ACTION": re.compile(r"<ACTION>\s*(\{.*?\})\s*</ACTION>", re.DOTALL | re.IGNORECASE),
    "CURSOR": re.compile(r"<CURSOR>\s*(\{.*?\})\s*</CURSOR>", re.DOTALL | re.IGNORECASE),
}


@dataclass
class ParsedAgentOutput:
    cleaned_text: str
    action: dict[str, Any] | None = None
    cursor: dict[str, Any] | None = None
    warnings: list[str] = field(default_factory=list)


def parse_agent_output(text: str, task_mode: str, task_active: bool) -> ParsedAgentOutput:
    """
    Parses and validates model output based on the current mode.
    """
    action_matches = _find_tag_matches(text, "ACTION")
    cursor_matches = _find_tag_matches(text, "CURSOR")
    cleaned_text = _strip_tags(text).strip()
    warnings: list[str] = []

    if len(action_matches) + len(cursor_matches) > 1:
        warnings.append("Blocked output because multiple ACTION/CURSOR tags were emitted.")
        return ParsedAgentOutput(cleaned_text=cleaned_text, warnings=warnings)

    if not task_active:
        if action_matches or cursor_matches:
            warnings.append("Dropped ACTION/CURSOR output because no task is active.")
        return ParsedAgentOutput(cleaned_text=cleaned_text, warnings=warnings)

    if task_mode == "agentic":
        if cursor_matches:
            warnings.append("Dropped CURSOR tag in agentic mode.")
        if not action_matches:
            return ParsedAgentOutput(cleaned_text=cleaned_text, warnings=warnings)
        try:
            action = _validate_action(_load_tag_payload(action_matches[0], "ACTION"))
            return ParsedAgentOutput(cleaned_text=cleaned_text, action=action, warnings=warnings)
        except ValueError as exc:
            warnings.append(f"Blocked invalid ACTION tag: {exc}")
            return ParsedAgentOutput(cleaned_text=cleaned_text, warnings=warnings)

    if task_mode == "collaborative":
        if action_matches:
            warnings.append("Dropped ACTION tag in collaborative mode.")
        if not cursor_matches:
            return ParsedAgentOutput(cleaned_text=cleaned_text, warnings=warnings)
        try:
            cursor = _validate_cursor(_load_tag_payload(cursor_matches[0], "CURSOR"))
            return ParsedAgentOutput(cleaned_text=cleaned_text, cursor=cursor, warnings=warnings)
        except ValueError as exc:
            warnings.append(f"Blocked invalid CURSOR tag: {exc}")
            return ParsedAgentOutput(cleaned_text=cleaned_text, warnings=warnings)

    warnings.append(f"Unknown task mode '{task_mode}'. Dropping structured output.")
    return ParsedAgentOutput(cleaned_text=cleaned_text, warnings=warnings)


def _strip_tags(text: str) -> str:
    cleaned = text
    for pattern in list(TAG_PATTERNS.values()) + list(LEGACY_TAG_PATTERNS.values()):
        cleaned = pattern.sub("", cleaned)
    return cleaned


def _find_tag_matches(text: str, tag_name: str) -> list[re.Match[str]]:
    matches = list(TAG_PATTERNS[tag_name].finditer(text))
    if matches:
        return matches
    return list(LEGACY_TAG_PATTERNS[tag_name].finditer(text))


def _load_tag_payload(match: re.Match[str], tag_name: str) -> dict[str, Any]:
    try:
        payload = json.loads(match.group(1))
    except json.JSONDecodeError as exc:
        raise ValueError(f"{tag_name} payload is not valid JSON") from exc
    if not isinstance(payload, dict):
        raise ValueError(f"{tag_name} payload must be an object")
    return payload


def _validate_cursor(data: dict[str, Any]) -> dict[str, Any]:
    return {
        "x": _normalize_percent(data.get("x"), "x"),
        "y": _normalize_percent(data.get("y"), "y"),
        "label": _normalize_label(data.get("label", "")),
    }


def _validate_action(data: dict[str, Any]) -> dict[str, Any]:
    action_type = str(data.get("type") or data.get("action") or "").strip().lower()
    if action_type not in ALLOWED_ACTION_TYPES:
        raise ValueError(f"unsupported action type '{action_type}'")

    validated: dict[str, Any] = {
        "type": action_type,
        "label": _normalize_label(data.get("label", action_type)),
    }

    if action_type in {"click", "doubleclick", "hover"}:
        validated["x"] = _normalize_percent(data.get("x"), "x")
        validated["y"] = _normalize_percent(data.get("y"), "y")
        return validated

    if action_type == "drag":
        start_x, start_y, end_x, end_y = _extract_drag_points(data)
        validated["x1"] = _normalize_percent(start_x, "x1")
        validated["y1"] = _normalize_percent(start_y, "y1")
        validated["x2"] = _normalize_percent(end_x, "x2")
        validated["y2"] = _normalize_percent(end_y, "y2")
        return validated

    if action_type == "key":
        key = str(data.get("key", "")).strip()
        if not key:
            raise ValueError("key action requires a non-empty 'key'")
        validated["key"] = _normalize_key(key)
        if "a" == validated["key"] and any(mod in _parse_modifiers(data.get("modifiers")) for mod in ("meta", "ctrl")):
            raise ValueError("Cmd+A/Ctrl+A is blocked because it is unsafe in the Rive editor")
        modifiers = _parse_modifiers(data.get("modifiers"))
        if modifiers:
            validated["modifiers"] = ",".join(modifiers)
        return validated

    if action_type == "type":
        text = str(data.get("text", "")).strip()
        if not text:
            raise ValueError("type action requires non-empty 'text'")
        has_x = data.get("x") is not None
        has_y = data.get("y") is not None
        if has_x != has_y:
            raise ValueError("type action must provide both x and y or neither")
        if has_x and has_y:
            validated["x"] = _normalize_percent(data.get("x"), "x")
            validated["y"] = _normalize_percent(data.get("y"), "y")
        validated["text"] = text
        return validated

    if action_type == "wait":
        duration = data.get("duration", 500)
        try:
            duration_int = int(duration)
        except (TypeError, ValueError) as exc:
            raise ValueError("wait duration must be an integer") from exc
        if duration_int < 100:
            duration_int = 100
        if duration_int > 5000:
            duration_int = 5000
        validated["duration"] = duration_int
        return validated

    raise ValueError(f"unsupported action type '{action_type}'")


def _normalize_percent(value: Any, field_name: str) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field_name} must be a number") from exc

    if not -0.5 <= number <= 100.5:
        raise ValueError(f"{field_name} must be between 0 and 100")

    clamped = min(max(number, 0.0), 100.0)
    return round(clamped, 2)


def _extract_drag_points(data: dict[str, Any]) -> tuple[Any, Any, Any, Any]:
    start = data.get("start") if isinstance(data.get("start"), dict) else {}
    end = data.get("end") if isinstance(data.get("end"), dict) else {}

    start_x = _first_present(
        data,
        "x1",
        "x",
        "from_x",
        "start_x",
        fallback=start.get("x"),
    )
    start_y = _first_present(
        data,
        "y1",
        "y",
        "from_y",
        "start_y",
        fallback=start.get("y"),
    )
    end_x = _first_present(
        data,
        "x2",
        "to_x",
        "end_x",
        fallback=end.get("x"),
    )
    end_y = _first_present(
        data,
        "y2",
        "to_y",
        "end_y",
        fallback=end.get("y"),
    )
    return start_x, start_y, end_x, end_y


def _first_present(data: dict[str, Any], *keys: str, fallback: Any = None) -> Any:
    for key in keys:
        value = data.get(key)
        if value is not None:
            return value
    return fallback


def _normalize_label(value: Any) -> str:
    label = str(value or "").strip()
    if len(label) <= 120:
        return label
    return label[:117].rstrip() + "..."


def _normalize_key(key: str) -> str:
    lowered = key.lower()
    aliases = {
        "cmd": "meta",
        "command": "meta",
        "control": "ctrl",
        "esc": "Escape",
        "spacebar": "Space",
        "return": "Enter",
    }
    if lowered in aliases:
        return aliases[lowered]
    if len(key) == 1:
        return lowered
    named_keys = {
        "enter": "Enter",
        "escape": "Escape",
        "backspace": "Backspace",
        "tab": "Tab",
        "space": "Space",
        "delete": "Delete",
        "arrowup": "ArrowUp",
        "arrowdown": "ArrowDown",
        "arrowleft": "ArrowLeft",
        "arrowright": "ArrowRight",
    }
    return named_keys.get(lowered, key)


def _parse_modifiers(value: Any) -> list[str]:
    if value is None:
        return []

    raw_parts = [part.strip().lower() for part in str(value).split(",") if part.strip()]
    aliases = {
        "cmd": "meta",
        "command": "meta",
        "control": "ctrl",
        "option": "alt",
    }
    normalized: list[str] = []
    seen: set[str] = set()
    for part in raw_parts:
        part = aliases.get(part, part)
        if part not in ALLOWED_MODIFIERS:
            raise ValueError(f"unsupported modifier '{part}'")
        if part in seen:
            continue
        seen.add(part)
        normalized.append(part)
    return normalized
