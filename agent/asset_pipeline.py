"""
Preview-generation and raster-to-SVG pipeline for generated assets.
"""

from __future__ import annotations

import base64
from collections import Counter, deque
import importlib.util
import json
import mimetypes
import os
import shutil
import subprocess
import uuid
from pathlib import Path
from typing import Any

from google.genai import types

from .svg_sanitizer import sanitize_svg_document


DEFAULT_LOCAL_ASSET_ROOT = Path(__file__).parent.parent / "generated_assets"
ASSET_ROOT = Path(
    os.getenv(
        "ASSET_ROOT_DIR",
        "/tmp/rive_navigator_assets" if os.getenv("K_SERVICE") else str(DEFAULT_LOCAL_ASSET_ROOT),
    )
)
DEFAULT_ASSET_PREVIEW_MODEL = os.getenv("ASSET_PREVIEW_MODEL", "gemini-3-pro-image-preview")
STYLE_PRESETS = {
    "sticker": (
        "flat sticker-style vector illustration, isolated subject, clean silhouette, minimal shading, "
        "single solid background color, no backdrop"
    ),
    "icon": (
        "clean flat app icon, simple geometry, isolated symbol, minimal detail, "
        "single solid background color, no backdrop"
    ),
    "mascot": (
        "simple vector mascot, bold silhouette, separated color regions, minimal shading, "
        "single solid background color, no backdrop"
    ),
    "logo": (
        "simple vector logo mark, crisp shapes, minimal detail, "
        "single solid background color, no backdrop"
    ),
}
MAX_PREVIEW_BYTES = 8_000_000
BACKGROUND_BUCKET_SIZE = 16
BACKGROUND_COLOR_TOLERANCE = 40
BACKGROUND_OPAQUE_ALPHA = 224
BACKGROUND_EDGE_RATIO_THRESHOLD = 0.55
BACKGROUND_CORNER_MATCH_THRESHOLD = 3
MIN_BACKGROUND_REMOVAL_RATIO = 0.04
CROP_PADDING_PX = 12


class AssetPipelineError(RuntimeError):
    """Raised when the preview/vectorization pipeline cannot complete."""


class AssetNotFoundError(AssetPipelineError):
    """Raised when a referenced asset_id does not exist on disk."""


def create_asset_preview(
    prompt: str,
    style: str,
    image_client: Any,
) -> dict[str, Any]:
    normalized_prompt = " ".join(prompt.split()).strip()
    if not normalized_prompt:
        raise AssetPipelineError("Asset prompt cannot be empty.")
    if image_client is None:
        raise AssetPipelineError("Gemini image generation is not configured on the backend.")

    asset_id = f"asset_{uuid.uuid4().hex[:12]}"
    asset_dir = _asset_dir(asset_id)
    asset_dir.mkdir(parents=True, exist_ok=True)

    style_key = style if style in STYLE_PRESETS else "sticker"
    generation_prompt = _build_generation_prompt(normalized_prompt, style_key)

    response = image_client.models.generate_content(
        model=DEFAULT_ASSET_PREVIEW_MODEL,
        contents=generation_prompt,
        config=types.GenerateContentConfig(
            response_modalities=["IMAGE", "TEXT"],
            image_config=types.ImageConfig(
                aspect_ratio="1:1",
            ),
        ),
    )

    image_bytes, mime_type, revised_prompt = _extract_image_response(response)
    if len(image_bytes) <= 0 or len(image_bytes) > MAX_PREVIEW_BYTES:
        raise AssetPipelineError("Generated preview image size was invalid.")

    extension = _mime_to_extension(mime_type)
    preview_filename = f"preview{extension}"
    preview_path = asset_dir / preview_filename
    preview_path.write_bytes(image_bytes)

    metadata = {
        "asset_id": asset_id,
        "style": style_key,
        "original_prompt": normalized_prompt,
        "generation_prompt": generation_prompt,
        "revised_prompt": revised_prompt or normalized_prompt,
        "preview_filename": preview_filename,
        "preview_mime_type": mime_type,
        "preview_model": DEFAULT_ASSET_PREVIEW_MODEL,
    }
    _write_metadata(asset_dir, metadata)

    return {
        "asset_id": asset_id,
        "preview_data_url": f"data:{mime_type};base64,{base64.b64encode(image_bytes).decode('ascii')}",
        "revised_prompt": metadata["revised_prompt"],
        "model": DEFAULT_ASSET_PREVIEW_MODEL,
    }


def vectorize_asset(asset_id: str) -> dict[str, Any]:
    asset_dir = _asset_dir(asset_id)
    metadata = _read_metadata(asset_dir)
    preview_filename = metadata.get("preview_filename", "")
    if not preview_filename:
        raise AssetPipelineError("The stored asset metadata is missing the preview image.")

    preview_path = asset_dir / preview_filename
    if not preview_path.exists():
        raise AssetPipelineError("The generated preview file could not be found.")

    trace_input_path, trace_cleanup = _prepare_trace_input(preview_path, asset_dir)
    raw_svg_path = asset_dir / "vectorized.svg"
    _run_vectorizer(trace_input_path, raw_svg_path)

    raw_svg = raw_svg_path.read_text(encoding="utf-8", errors="ignore")
    sanitized_svg, stats = sanitize_svg_document(raw_svg)
    sanitized_path = asset_dir / "sanitized.svg"
    sanitized_path.write_text(sanitized_svg, encoding="utf-8")

    metadata["vectorized_filename"] = raw_svg_path.name
    metadata["sanitized_filename"] = sanitized_path.name
    metadata["trace_cleanup"] = trace_cleanup
    metadata["stats"] = stats
    _write_metadata(asset_dir, metadata)

    return {
        "asset_id": asset_id,
        "sanitized_svg": sanitized_svg,
        "stats": stats,
        "trace_cleanup": trace_cleanup,
    }


def _build_generation_prompt(prompt: str, style: str) -> str:
    style_description = STYLE_PRESETS.get(style, STYLE_PRESETS["sticker"])
    return (
        "Generate a clean concept image for later SVG tracing.\n"
        f"Subject: {prompt}\n"
        f"Style: {style_description}.\n"
        "Requirements:\n"
        "- centered isolated subject\n"
        "- bold readable silhouette\n"
        "- no text or typography\n"
        "- no photorealism\n"
        "- no background scene\n"
        "- use one flat solid background color only, with no gradient, texture, or scene\n"
        "- keep the subject fully separated from the edges so the background can be removed cleanly\n"
        "- no floor, shadow plate, border card, or framing device around the subject\n"
        "- keep details minimal so tracing remains clean\n"
        "- aim for large color regions that can become vector paths"
    )


def _extract_image_response(response: Any) -> tuple[bytes, str, str]:
    image_bytes = b""
    mime_type = "image/png"
    text_parts: list[str] = []

    parts = []
    candidates = getattr(response, "candidates", None) or []
    for candidate in candidates:
        content = getattr(candidate, "content", None)
        if content and getattr(content, "parts", None):
            parts.extend(content.parts)

    if not parts and getattr(response, "parts", None):
        parts.extend(response.parts)

    for part in parts:
        if getattr(part, "text", None):
            text_parts.append(part.text.strip())

        inline_data = getattr(part, "inline_data", None)
        if inline_data and getattr(inline_data, "data", None):
            raw_data = inline_data.data
            if isinstance(raw_data, bytes):
                image_bytes = raw_data
            elif isinstance(raw_data, str):
                image_bytes = base64.b64decode(raw_data)
            mime_type = inline_data.mime_type or mime_type
            break

    if not image_bytes:
        raise AssetPipelineError(
            "Gemini did not return an image preview. Try simplifying the prompt or try again."
        )

    revised_prompt = " ".join(part for part in text_parts if part).strip()
    return image_bytes, mime_type, revised_prompt


def _run_vectorizer(input_path: Path, output_path: Path) -> None:
    if _vectorize_with_python_module(input_path, output_path):
        return
    if _vectorize_with_cli(input_path, output_path):
        return
    raise AssetPipelineError(
        "Vectorizer is not installed. Install `vtracer` to enable PNG-to-SVG conversion."
    )


def _vectorize_with_python_module(input_path: Path, output_path: Path) -> bool:
    if importlib.util.find_spec("vtracer") is None:
        return False

    import vtracer

    vtracer.convert_image_to_svg_py(
        str(input_path),
        str(output_path),
        colormode="color",
        hierarchical="stacked",
        mode="spline",
        filter_speckle=4,
        color_precision=6,
        layer_difference=12,
        corner_threshold=60,
        length_threshold=4.0,
        max_iterations=10,
        splice_threshold=45,
        path_precision=3,
    )
    return output_path.exists()


def _vectorize_with_cli(input_path: Path, output_path: Path) -> bool:
    command = shutil.which("vtracer")
    if not command:
        return False

    completed = subprocess.run(
        [
            command,
            "--input",
            str(input_path),
            "--output",
            str(output_path),
            "--colormode",
            "color",
            "--mode",
            "spline",
            "--filter_speckle",
            "4",
            "--color_precision",
            "6",
            "--gradient_step",
            "12",
            "--corner_threshold",
            "60",
            "--segment_length",
            "4.0",
            "--max_iterations",
            "10",
            "--splice_threshold",
            "45",
            "--path_precision",
            "3",
        ],
        check=False,
        capture_output=True,
        text=True,
    )
    if completed.returncode != 0:
        raise AssetPipelineError(
            completed.stderr.strip() or "The vectorizer failed while tracing the preview image."
        )
    return output_path.exists()


def _prepare_trace_input(preview_path: Path, asset_dir: Path) -> tuple[Path, dict[str, Any]]:
    cleanup: dict[str, Any] = {
        "used_cleaned_preview": False,
        "background_removed": False,
        "cropped_to_content": False,
        "reason": "not_needed",
        "trace_input_filename": preview_path.name,
    }

    image_module = _load_pillow_image_module()
    if image_module is None:
        cleanup["reason"] = "pillow_not_installed"
        return preview_path, cleanup

    try:
        image = image_module.open(preview_path).convert("RGBA")
    except Exception:
        cleanup["reason"] = "preview_unreadable"
        return preview_path, cleanup

    detection = _detect_edge_background(image)
    cleanup.update(
        {
            "edge_background_ratio": detection["ratio"],
            "corner_matches": detection["corner_matches"],
            "candidate_color": list(detection["color"]) if detection["color"] else None,
        }
    )
    if not detection["should_remove"] or detection["color"] is None:
        cropped_image, crop_box = _crop_to_content_bounds(image, padding=CROP_PADDING_PX)
        if cropped_image is None:
            cleanup["reason"] = "background_not_detected"
            return preview_path, cleanup

        cropped_path = asset_dir / "preview_trace.png"
        cropped_image.save(cropped_path)
        cleanup.update(
            {
                "used_cleaned_preview": True,
                "cropped_to_content": True,
                "reason": "cropped_existing_alpha",
                "trace_input_filename": cropped_path.name,
                "crop_box": list(crop_box),
            }
        )
        return cropped_path, cleanup

    cleaned_image, removed_pixels = _erase_edge_connected_background(
        image=image,
        target_color=detection["color"],
        tolerance=BACKGROUND_COLOR_TOLERANCE,
    )
    removed_ratio = removed_pixels / max(1, image.width * image.height)
    cleanup["removed_pixel_ratio"] = round(removed_ratio, 4)
    if removed_pixels <= 0 or removed_ratio < MIN_BACKGROUND_REMOVAL_RATIO:
        cleanup["reason"] = "background_not_detected"
        return preview_path, cleanup

    if cleaned_image.getchannel("A").getbbox() is None:
        cleanup["reason"] = "cleanup_removed_everything"
        return preview_path, cleanup

    trace_image = cleaned_image
    crop_box = None
    cropped_image, crop_box = _crop_to_content_bounds(cleaned_image, padding=CROP_PADDING_PX)
    if cropped_image is not None:
        trace_image = cropped_image

    cleaned_path = asset_dir / "preview_trace.png"
    trace_image.save(cleaned_path)
    cleanup.update(
        {
            "used_cleaned_preview": True,
            "background_removed": True,
            "cropped_to_content": cropped_image is not None,
            "reason": "background_removed_and_cropped" if cropped_image is not None else "background_removed",
            "trace_input_filename": cleaned_path.name,
        }
    )
    if crop_box is not None:
        cleanup["crop_box"] = list(crop_box)
    return cleaned_path, cleanup


def _load_pillow_image_module():
    try:
        from PIL import Image
    except ImportError:
        return None
    return Image


def _detect_edge_background(image) -> dict[str, Any]:
    edge_pixels: list[tuple[int, int, int]] = []
    bucket_counts: Counter[tuple[int, int, int]] = Counter()
    bucket_pixels: dict[tuple[int, int, int], list[tuple[int, int, int]]] = {}
    pixels = image.load()

    for x, y in _iter_border_points(image.width, image.height):
        red, green, blue, alpha = pixels[x, y]
        if alpha < BACKGROUND_OPAQUE_ALPHA:
            continue
        rgb = (red, green, blue)
        edge_pixels.append(rgb)
        bucket = _bucketize_color(rgb)
        bucket_counts[bucket] += 1
        bucket_pixels.setdefault(bucket, []).append(rgb)

    if not edge_pixels or not bucket_counts:
        return {"should_remove": False, "ratio": 0.0, "corner_matches": 0, "color": None}

    dominant_bucket, dominant_count = bucket_counts.most_common(1)[0]
    dominant_pixels = bucket_pixels[dominant_bucket]
    candidate_color = tuple(
        round(sum(pixel[index] for pixel in dominant_pixels) / len(dominant_pixels))
        for index in range(3)
    )
    dominant_ratio = dominant_count / len(edge_pixels)

    corner_matches = sum(
        1
        for x, y in _corner_points(image.width, image.height)
        if pixels[x, y][3] >= BACKGROUND_OPAQUE_ALPHA
        and _rgb_close(pixels[x, y][:3], candidate_color, BACKGROUND_COLOR_TOLERANCE)
    )
    should_remove = dominant_ratio >= BACKGROUND_EDGE_RATIO_THRESHOLD and (
        corner_matches >= BACKGROUND_CORNER_MATCH_THRESHOLD or dominant_ratio >= 0.72
    )
    return {
        "should_remove": should_remove,
        "ratio": round(dominant_ratio, 4),
        "corner_matches": corner_matches,
        "color": candidate_color,
    }


def _erase_edge_connected_background(
    image,
    target_color: tuple[int, int, int],
    tolerance: int,
):
    pixels = image.load()
    width, height = image.size
    visited = bytearray(width * height)
    queue: deque[tuple[int, int]] = deque()

    def enqueue(x: int, y: int) -> None:
        index = y * width + x
        if visited[index]:
            return
        visited[index] = 1
        if pixels[x, y][3] < 8:
            return
        if not _rgb_close(pixels[x, y][:3], target_color, tolerance):
            return
        queue.append((x, y))

    for x, y in _iter_border_points(width, height):
        enqueue(x, y)

    removed_pixels = 0
    while queue:
        x, y = queue.popleft()
        red, green, blue, _ = pixels[x, y]
        pixels[x, y] = (red, green, blue, 0)
        removed_pixels += 1

        if x > 0:
            enqueue(x - 1, y)
        if x + 1 < width:
            enqueue(x + 1, y)
        if y > 0:
            enqueue(x, y - 1)
        if y + 1 < height:
            enqueue(x, y + 1)

    return image, removed_pixels


def _bucketize_color(color: tuple[int, int, int]) -> tuple[int, int, int]:
    return tuple(component // BACKGROUND_BUCKET_SIZE for component in color)


def _rgb_close(left: tuple[int, int, int], right: tuple[int, int, int], tolerance: int) -> bool:
    return all(abs(left[index] - right[index]) <= tolerance for index in range(3))


def _crop_to_content_bounds(image, padding: int):
    alpha = image.getchannel("A")
    bbox = alpha.getbbox()
    if bbox is None:
        return None, None

    left, top, right, bottom = bbox
    if left <= 0 and top <= 0 and right >= image.width and bottom >= image.height:
        return None, None

    crop_box = (
        max(0, left - padding),
        max(0, top - padding),
        min(image.width, right + padding),
        min(image.height, bottom + padding),
    )
    return image.crop(crop_box), crop_box


def _iter_border_points(width: int, height: int):
    if width <= 0 or height <= 0:
        return

    seen: set[tuple[int, int]] = set()
    for x in range(width):
        point = (x, 0)
        if point not in seen:
            seen.add(point)
            yield point
        if height > 1:
            point = (x, height - 1)
            if point not in seen:
                seen.add(point)
                yield point
    for y in range(height):
        point = (0, y)
        if point not in seen:
            seen.add(point)
            yield point
        if width > 1:
            point = (width - 1, y)
            if point not in seen:
                seen.add(point)
                yield point


def _corner_points(width: int, height: int) -> list[tuple[int, int]]:
    if width <= 0 or height <= 0:
        return []
    return [
        (0, 0),
        (max(0, width - 1), 0),
        (0, max(0, height - 1)),
        (max(0, width - 1), max(0, height - 1)),
    ]


def _asset_dir(asset_id: str) -> Path:
    asset_id = (asset_id or "").strip()
    if not asset_id:
        raise AssetNotFoundError("Missing asset_id.")
    resolved = (ASSET_ROOT / asset_id).resolve()
    if not str(resolved).startswith(str(ASSET_ROOT.resolve())):
        raise AssetNotFoundError("Invalid asset_id.")
    return resolved


def _read_metadata(asset_dir: Path) -> dict[str, Any]:
    metadata_path = asset_dir / "metadata.json"
    if not metadata_path.exists():
        raise AssetNotFoundError("The referenced asset could not be found.")
    try:
        return json.loads(metadata_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise AssetPipelineError("The stored asset metadata is invalid.") from exc


def _write_metadata(asset_dir: Path, metadata: dict[str, Any]) -> None:
    asset_dir.mkdir(parents=True, exist_ok=True)
    (asset_dir / "metadata.json").write_text(
        json.dumps(metadata, indent=2, sort_keys=True),
        encoding="utf-8",
    )


def _mime_to_extension(mime_type: str) -> str:
    guessed = mimetypes.guess_extension(mime_type or "") or ".png"
    if guessed == ".jpe":
        return ".jpg"
    if guessed == ".svgz":
        return ".svg"
    return guessed
