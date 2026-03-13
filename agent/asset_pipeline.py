"""
Preview-generation and raster-to-SVG pipeline for generated assets.
"""

from __future__ import annotations

import base64
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

from .svg_sanitizer import SvgSanitizationError, sanitize_svg_document


DEFAULT_LOCAL_ASSET_ROOT = Path(__file__).parent.parent / "generated_assets"
ASSET_ROOT = Path(
    os.getenv(
        "ASSET_ROOT_DIR",
        "/tmp/rive_navigator_assets" if os.getenv("K_SERVICE") else str(DEFAULT_LOCAL_ASSET_ROOT),
    )
)
DEFAULT_ASSET_PREVIEW_MODEL = os.getenv("ASSET_PREVIEW_MODEL", "gemini-3-pro-image-preview")
STYLE_PRESETS = {
    "sticker": "flat sticker-style vector illustration, isolated subject, clean silhouette, minimal shading, plain background",
    "icon": "clean flat app icon, simple geometry, isolated symbol, minimal detail, plain background",
    "mascot": "simple vector mascot, bold silhouette, separated color regions, minimal shading, plain background",
    "logo": "simple vector logo mark, crisp shapes, minimal detail, plain background",
}
MAX_PREVIEW_BYTES = 8_000_000


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

    raw_svg_path = asset_dir / "vectorized.svg"
    _run_vectorizer(preview_path, raw_svg_path)

    raw_svg = raw_svg_path.read_text(encoding="utf-8", errors="ignore")
    sanitized_svg, stats = sanitize_svg_document(raw_svg)
    sanitized_path = asset_dir / "sanitized.svg"
    sanitized_path.write_text(sanitized_svg, encoding="utf-8")

    metadata["vectorized_filename"] = raw_svg_path.name
    metadata["sanitized_filename"] = sanitized_path.name
    metadata["stats"] = stats
    _write_metadata(asset_dir, metadata)

    return {
        "asset_id": asset_id,
        "sanitized_svg": sanitized_svg,
        "stats": stats,
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


def _asset_dir(asset_id: str) -> Path:
    asset_id = (asset_id or "").strip()
    if not asset_id:
        raise AssetNotFoundError("Missing asset_id.")
    return ASSET_ROOT / asset_id


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
