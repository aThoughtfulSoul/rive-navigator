"""
Utilities for cleaning traced SVG output before importing into Rive.
"""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from typing import Any


SVG_NS = "http://www.w3.org/2000/svg"
XLINK_NS = "http://www.w3.org/1999/xlink"
DROP_TAGS = {"script", "foreignObject", "image", "metadata", "style"}
DROP_ATTRS = {
    "filter",
    "mask",
    "clip-path",
    "vector-effect",
    "font-family",
    "font-size",
}
COMPLEXITY_LIMITS = {
    "path_count": 320,
    "element_count": 700,
}

ET.register_namespace("", SVG_NS)
ET.register_namespace("xlink", XLINK_NS)


class SvgSanitizationError(RuntimeError):
    """Raised when SVG output is invalid or too complex for the import flow."""


def sanitize_svg_document(raw_svg: str) -> tuple[str, dict[str, Any]]:
    if not raw_svg or not raw_svg.strip():
        raise SvgSanitizationError("The vectorizer returned an empty SVG document.")

    try:
        root = ET.fromstring(raw_svg)
    except ET.ParseError as exc:
        raise SvgSanitizationError("The traced SVG could not be parsed.") from exc

    if _local_name(root.tag) != "svg":
        raise SvgSanitizationError("The traced document is not an SVG root.")

    removed_tags = 0
    removed_attrs = 0
    path_count = 0
    element_count = 0

    for parent, child in list(_iter_with_parent(root)):
        child_name = _local_name(child.tag)
        if child_name in DROP_TAGS:
            parent.remove(child)
            removed_tags += 1
            continue

        element_count += 1
        if child_name in {"path", "polygon", "polyline", "rect", "circle", "ellipse", "line"}:
            path_count += 1

        removed_attrs += _sanitize_attributes(child)

    removed_attrs += _sanitize_attributes(root, is_root=True)
    _ensure_viewbox(root)

    if path_count > COMPLEXITY_LIMITS["path_count"] or element_count > COMPLEXITY_LIMITS["element_count"]:
        raise SvgSanitizationError(
            "The traced SVG is too complex for a reliable first-pass Rive import. "
            "Try a simpler, flatter asset prompt."
        )

    svg_text = ET.tostring(root, encoding="unicode")
    stats = {
        "path_count": path_count,
        "element_count": element_count,
        "removed_tags": removed_tags,
        "removed_attributes": removed_attrs,
        "view_box": root.attrib.get("viewBox", ""),
    }
    return svg_text, stats


def _iter_with_parent(root: ET.Element):
    for parent in root.iter():
        for child in list(parent):
            yield parent, child


def _local_name(tag: str) -> str:
    return tag.split("}", 1)[1] if "}" in tag else tag


def _sanitize_attributes(element: ET.Element, is_root: bool = False) -> int:
    removed = 0
    for attr_name in list(element.attrib):
        local_name = attr_name.split("}", 1)[1] if "}" in attr_name else attr_name
        attr_value = element.attrib.get(attr_name, "")

        if local_name in DROP_ATTRS:
            element.attrib.pop(attr_name, None)
            removed += 1
            continue

        if local_name == "transform" and ("skewX" in attr_value or "skewY" in attr_value):
            element.attrib.pop(attr_name, None)
            removed += 1
            continue

        if not is_root and local_name in {"width", "height"}:
            continue

    if is_root:
        element.attrib.setdefault("version", "1.1")

    return removed


def _ensure_viewbox(root: ET.Element) -> None:
    if root.attrib.get("viewBox"):
        return

    width = _parse_svg_length(root.attrib.get("width"))
    height = _parse_svg_length(root.attrib.get("height"))

    if width is None or width <= 0:
        width = 1024.0
        root.attrib["width"] = "1024"
    if height is None or height <= 0:
        height = 1024.0
        root.attrib["height"] = "1024"

    root.attrib["viewBox"] = f"0 0 {_format_number(width)} {_format_number(height)}"


def _parse_svg_length(value: str | None) -> float | None:
    if not value:
        return None
    match = re.match(r"^\s*([0-9]+(?:\.[0-9]+)?)", value)
    if not match:
        return None
    try:
        return float(match.group(1))
    except ValueError:
        return None


def _format_number(value: float) -> str:
    rounded = round(value, 3)
    if rounded.is_integer():
        return str(int(rounded))
    return str(rounded)
