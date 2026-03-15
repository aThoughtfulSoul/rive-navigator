"""
Rive documentation lookup helpers and ADK tool.
Searches the local Rive docs (source of truth) for relevant information.
"""

from __future__ import annotations

import mimetypes
import re
import threading
from pathlib import Path, PurePosixPath
from typing import Any


RIVE_DOCS_PATH = Path(__file__).parent.parent.parent / "rive-docs"
IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp"}
STEP_VERBS = (
    "add",
    "bind",
    "choose",
    "click",
    "create",
    "define",
    "drag",
    "enter",
    "hold",
    "open",
    "pick",
    "press",
    "select",
    "set",
    "toggle",
    "type",
    "use",
)
STOPWORDS = {
    "a",
    "again",
    "an",
    "and",
    "are",
    "button",
    "click",
    "continue",
    "create",
    "created",
    "creating",
    "current",
    "draw",
    "drawing",
    "for",
    "from",
    "how",
    "i",
    "in",
    "is",
    "make",
    "new",
    "of",
    "on",
    "or",
    "please",
    "rive",
    "step",
    "the",
    "to",
    "try",
    "use",
    "using",
    "with",
}
TERM_ALIASES = {
    "circle": ("ellipse",),
    "ellipse": ("circle",),
    "shape": ("procedural", "shapes"),
    "shapes": ("procedural", "shape"),
}

_docs_index: list[dict[str, Any]] = []
_docs_index_lock = threading.Lock()


def _build_docs_index() -> list[dict[str, Any]]:
    """Builds a cached in-memory index of all markdown docs (thread-safe)."""
    global _docs_index
    if _docs_index:
        return _docs_index

    with _docs_index_lock:
        # Double-check after acquiring lock
        if _docs_index:
            return _docs_index

        docs_path = RIVE_DOCS_PATH
        if not docs_path.exists():
            return []

        for filepath in sorted(docs_path.rglob("*")):
            if not filepath.is_file() or filepath.suffix not in {".mdx", ".md"}:
                continue
            if filepath.name in {"README.md", "CONTRIBUTING.md"}:
                continue

            try:
                content = filepath.read_text(encoding="utf-8", errors="ignore")
            except Exception:
                continue

            meta = _parse_metadata(content)
            rel_path = str(filepath.relative_to(docs_path))
            category = rel_path.split("/")[0] if "/" in rel_path else "general"
            headings = re.findall(r"^#+\s+(.+)$", content, re.MULTILINE)
            sections = _extract_sections(content, rel_path)
            search_content = "\n\n".join(
                section["search_text"] for section in sections if section.get("search_text")
            ).strip() or _normalize_search_content(content)
            image_refs = _extract_image_refs(content, rel_path, meta["title"])
            visual_dependency = _estimate_visual_dependency(
                image_count=len(image_refs),
                search_text=search_content,
                steps=[step for section in sections for step in section.get("steps", [])],
            )

            _docs_index.append(
                {
                    "path": rel_path,
                    "category": category,
                    "title": meta["title"],
                    "description": meta["description"],
                    "headings": headings,
                    "content": content,
                    "search_content": search_content,
                    "sections": sections,
                    "image_refs": image_refs,
                    "visual_dependency": visual_dependency,
                    "path_lower": rel_path.lower(),
                    "title_lower": meta["title"].lower(),
                    "description_lower": meta["description"].lower(),
                    "headings_lower": [heading.lower() for heading in headings],
                }
            )

        return _docs_index


def search_rive_docs(
    query: str,
    category: str = "",
    limit: int = 5,
    preferred_categories: list[str] | None = None,
) -> list[dict[str, Any]]:
    """
    Returns ranked documentation hits without ADK tool wrapper semantics.
    """
    index = _build_docs_index()
    if not index:
        return []

    expanded_query = _expand_query_text(query)
    query_terms = _tokenize(expanded_query)
    if not query_terms:
        return []

    phrase = " ".join(query_terms)
    category_pool = (
        [doc for doc in index if doc["category"] in preferred_categories]
        if preferred_categories and not category
        else None
    )
    results = _rank_docs(
        docs=category_pool if category_pool is not None else index,
        query_terms=query_terms,
        phrase=phrase,
        category=category,
        preferred_categories=preferred_categories or [],
        limit=limit,
    )

    if results or category_pool is None:
        return results

    return _rank_docs(
        docs=index,
        query_terms=query_terms,
        phrase=phrase,
        category=category,
        preferred_categories=preferred_categories or [],
        limit=limit,
    )


def lookup_rive_docs(query: str, category: str = "") -> dict:
    """
    ADK tool wrapper that searches the local Rive docs.
    """
    if not _build_docs_index():
        return {
            "status": "error",
            "message": "Rive docs not found. Ensure rive-docs repo is cloned.",
        }

    preferred_categories = [category] if category else None
    results = search_rive_docs(
        query=query,
        category=category,
        limit=5,
        preferred_categories=preferred_categories,
    )
    if not results:
        return {
            "status": "no_results",
            "message": f"No documentation found for '{query}'. Try broader terms.",
            "suggestion": "Try searching for the general feature name instead of a very specific phrase.",
        }

    return {
        "status": "success",
        "query": query,
        "result_count": len(results),
        "results": [_sanitize_result_for_tool(result) for result in results],
    }


def _parse_metadata(content: str) -> dict[str, str]:
    title = ""
    description = ""

    frontmatter = re.match(r"^---\n(.*?)\n---\n", content, re.DOTALL)
    if frontmatter:
        body = frontmatter.group(1)
        title_match = re.search(r'^title:\s*"?(.*?)"?$', body, re.MULTILINE)
        description_match = re.search(r'^description:\s*"?(.*?)"?$', body, re.MULTILINE)
        if title_match:
            title = title_match.group(1).strip()
        if description_match:
            description = description_match.group(1).strip()

    if not title:
        heading_match = re.search(r"^#\s+(.+)$", content, re.MULTILINE)
        if heading_match:
            title = _normalize_inline_text(heading_match.group(1))

    return {"title": title, "description": description}


def _tokenize(text: str) -> list[str]:
    tokens = re.findall(r"[a-z0-9][a-z0-9+._/-]*", text.lower())
    ordered: list[str] = []
    seen: set[str] = set()
    for token in tokens:
        if token in STOPWORDS or len(token) < 2:
            continue
        if token in seen:
            continue
        seen.add(token)
        ordered.append(token)
        for alias in TERM_ALIASES.get(token, ()):
            if alias in seen:
                continue
            seen.add(alias)
            ordered.append(alias)
    return ordered


def _expand_query_text(text: str) -> str:
    lowered = text.lower()
    extras: list[str] = []

    if "new file" in lowered or "fresh file" in lowered or "blank file" in lowered:
        extras.extend(["artboard", "stage"])
    if "artboard" in lowered:
        extras.extend(["stage", "create artboard"])
    if "circle" in lowered or "ellipse" in lowered:
        extras.extend(["ellipse", "procedural shape"])
    if "rectangle" in lowered or "shape" in lowered:
        extras.append("procedural shape")
    if any(
        term in lowered
        for term in (
            "shortcut",
            "keyboard",
            "select tool",
            "ellipse",
            "circle",
            "rectangle",
            "artboard tool",
            "pen tool",
            "bone tool",
            "switch mode",
            "animate mode",
            "design mode",
        )
    ):
        extras.append("keyboard shortcuts")
    if any(
        term in lowered
        for term in (
            "find artboard",
            "find the artboard",
            "center artboard",
            "center the artboard",
            "lost artboard",
            "lost the artboard",
            "fit artboard",
            "fit the artboard",
            "fit to screen",
            "zoom to fit",
            "zoom-to-fit",
        )
    ):
        extras.extend(["stage", "fit", "screen"])

    if not extras:
        return text
    return f"{text} {' '.join(extras)}"


def _score_doc(
    doc: dict[str, Any],
    query_terms: list[str],
    phrase: str,
    preferred_categories: list[str],
) -> float:
    title = doc["title_lower"]
    description = doc["description_lower"]
    path = doc["path_lower"]
    headings = "\n".join(doc["headings_lower"])
    content = doc["search_content"].lower()

    score = 0.0

    if preferred_categories and doc["category"] in preferred_categories:
        score += 6.0

    if phrase and len(query_terms) > 1:
        if phrase in title:
            score += 18.0
        if phrase in path:
            score += 12.0
        if phrase in headings:
            score += 10.0
        if phrase in description:
            score += 8.0
        if phrase in content:
            score += 4.0

    for term in query_terms:
        term_pattern = rf"(?<![a-z0-9]){re.escape(term)}(?![a-z0-9])"
        if re.search(term_pattern, title):
            score += 8.0
        elif term in title:
            score += 5.0

        if re.search(term_pattern, path):
            score += 5.0
        elif term in path:
            score += 3.0

        heading_hits = len(re.findall(term_pattern, headings))
        score += min(heading_hits, 3) * 3.0

        description_hits = len(re.findall(term_pattern, description))
        score += min(description_hits, 2) * 2.5

        content_hits = len(re.findall(term_pattern, content))
        score += min(content_hits, 6) * 1.0

    query_set = set(query_terms)
    if "artboard" in query_set:
        if "artboards" in path:
            score += 12.0
        if "toolbar" in path:
            score += 3.0
        if "components" in path:
            score -= 6.0
    if "file" in query_set and "artboards" in path:
        score += 6.0
    if query_set & {"circle", "ellipse", "shape", "shapes", "procedural"}:
        if "procedural-shapes" in path:
            score += 12.0
        if "keyboard-shortcuts" in path:
            score += 2.0
    if query_set & {"fill", "stroke", "color"} and "fill-and-stroke" in path:
        score += 10.0
    if query_set & {"artboard"} and query_set & {"fit", "center", "lost", "screen", "zoom"}:
        if "interface-overview/stage" in path:
            score += 14.0
        if "keyboard-shortcuts" in path:
            score += 8.0
    if query_set & {"keyframe", "keyframes", "timeline", "animation", "easing"}:
        if "animate-mode" in path or "timeline" in path:
            score += 12.0
    if query_set & {"state", "machine", "transition", "input", "inputs"}:
        if "state-machine" in path:
            score += 12.0
    if query_set & {"listener", "listeners", "event", "events"}:
        if "listeners" in path or "events" in path:
            score += 10.0

    if "keyboard-shortcuts" in path:
        score += _shortcut_relevance(query_terms, phrase)

    score += min(float(doc.get("visual_dependency", 0.0)), 3.0) * 0.5
    return score


def _rank_docs(
    docs: list[dict[str, Any]],
    query_terms: list[str],
    phrase: str,
    category: str,
    preferred_categories: list[str],
    limit: int,
) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []

    for doc in docs:
        if category and doc["category"] != category:
            continue

        score = _score_doc(doc, query_terms, phrase, preferred_categories)
        if score <= 0:
            continue

        best_section = _choose_best_section(doc, query_terms, phrase)
        snippet_source = (
            best_section.get("search_text", "")
            if best_section
            else doc.get("search_content", "")
        )
        steps = list(best_section.get("steps", [])) if best_section else []
        images = list(best_section.get("images", [])) if best_section else []
        visual_dependency = float(best_section.get("visual_dependency", 0.0)) if best_section else 0.0
        if not images:
            images = list(doc.get("image_refs", []))[:3]
        visual_dependency = max(visual_dependency, float(doc.get("visual_dependency", 0.0)))
        shortcut_steps = _shortcut_steps_for_query(query_terms, phrase)
        if shortcut_steps and (
            "keyboard-shortcuts" in doc["path"]
            or any(
                fragment in doc["path"]
                for fragment in (
                    "procedural-shapes",
                    "artboards",
                    "toolbar",
                    "pen-tool",
                    "components",
                    "bones",
                )
            )
        ):
            steps = _dedupe_items(shortcut_steps + steps, limit=5)

        results.append(
            {
                "path": doc["path"],
                "title": doc["title"],
                "description": doc["description"],
                "category": doc["category"],
                "score": score,
                "section_heading": best_section.get("heading", "") if best_section else "",
                "snippet": _truncate_excerpt(snippet_source, 420),
                "steps": steps[:4],
                "images": images[:3],
                "image_count": len(doc.get("image_refs", [])),
                "visual_dependency": round(visual_dependency, 2),
            }
        )

    results.sort(key=lambda item: item["score"], reverse=True)
    return results[:limit]


def _choose_best_section(
    doc: dict[str, Any],
    query_terms: list[str],
    phrase: str,
) -> dict[str, Any] | None:
    best_section: dict[str, Any] | None = None
    best_score = -1.0

    for section in doc.get("sections", []):
        score = _score_section(section, query_terms, phrase)
        if score > best_score:
            best_score = score
            best_section = section

    return best_section


def _shortcut_relevance(query_terms: list[str], phrase: str) -> float:
    query_set = set(query_terms)
    phrase_lower = phrase.lower()

    if query_set & {"shortcut", "shortcuts", "keyboard", "hotkey", "key", "keys"}:
        return 14.0

    tool_terms = {
        "ellipse",
        "circle",
        "rectangle",
        "artboard",
        "select",
        "translate",
        "move",
        "rotate",
        "scale",
        "pen",
        "bone",
    }
    mode_terms = {"animate", "design", "mode", "switch", "toggle", "timeline"}

    if _shortcut_steps_for_query(query_terms, phrase):
        if (query_set & tool_terms and any(term in phrase_lower for term in ("tool", "select", "shortcut"))) or (
            query_set & mode_terms and "mode" in phrase_lower
        ):
            return 10.0
        return 6.0

    return 0.0


def _shortcut_steps_for_query(query_terms: list[str], phrase: str) -> list[str]:
    query_set = set(query_terms)
    phrase_lower = phrase.lower()
    steps: list[str] = []

    if query_set & {"ellipse", "circle"}:
        steps.append("Use `O` to select the Ellipse tool instead of clicking the toolbar icon.")
    if "rectangle" in query_set:
        steps.append("Use `R` to select the Rectangle tool instead of clicking the toolbar icon.")
    if "artboard tool" in phrase_lower or "create artboard" in phrase_lower:
        steps.append("Use `A` to select the Artboard tool when you need to draw an artboard manually.")
    if "artboard" in query_set and query_set & {"fit", "center", "lost", "screen", "zoom"}:
        steps.append("Use `F` to fit and center the active artboard on screen instead of panning manually.")
    if "pen" in query_set:
        steps.append("Use `P` to select the Pen tool instead of opening the toolbar menu.")
    if "bone" in query_set:
        steps.append("Use `B` to select the Bone tool instead of opening the toolbar menu.")
    if "select tool" in phrase_lower or "return to select" in phrase_lower:
        steps.append("Use `V` to return to the Select tool instead of clicking its icon.")
    if query_set & {"translate", "move"} and "tool" in phrase_lower:
        steps.append("Use `Q` to switch to the Move/Translate tool instead of clicking its icon.")
    if "rotate" in query_set and "tool" in phrase_lower:
        steps.append("Use `W` to switch to the Rotate tool instead of clicking its icon.")
    if "scale" in query_set and "tool" in phrase_lower:
        steps.append("Use `E` to switch to the Scale tool instead of clicking its icon.")
    if (query_set & {"animate", "design", "mode"}) or "switch mode" in phrase_lower:
        steps.append("Use `Tab` to switch between Design and Animate mode instead of clicking the mode toggle.")

    return _dedupe_items(steps, limit=4)


def _score_section(section: dict[str, Any], query_terms: list[str], phrase: str) -> float:
    heading = section.get("heading", "").lower()
    search_text = section.get("search_text", "").lower()
    score = 0.0

    if phrase and phrase in search_text:
        score += 10.0
    if phrase and phrase in heading:
        score += 14.0

    for term in query_terms:
        term_pattern = rf"(?<![a-z0-9]){re.escape(term)}(?![a-z0-9])"
        score += min(len(re.findall(term_pattern, heading)), 3) * 4.0
        score += min(len(re.findall(term_pattern, search_text)), 6) * 1.5

    if any(token in heading for token in ("creating", "create", "overview")):
        score += 4.0
    if section.get("steps"):
        score += min(len(section["steps"]), 4) * 1.5
    if section.get("images"):
        score += min(len(section["images"]), 3) * 1.0

    return score


def _extract_sections(content: str, rel_path: str) -> list[dict[str, Any]]:
    body = _strip_frontmatter(content).strip()
    raw_sections = re.split(r"\n(?=#+\s)", body)
    sections: list[dict[str, Any]] = []

    for raw_section in raw_sections:
        raw_section = raw_section.strip()
        if not raw_section:
            continue

        heading = _extract_heading(raw_section)
        search_text = _normalize_search_content(raw_section).strip()
        images = _extract_image_refs(raw_section, rel_path, heading)
        steps = _extract_section_steps(search_text, heading)

        if len(search_text) < 20 and not images:
            continue

        sections.append(
            {
                "heading": heading,
                "search_text": search_text,
                "steps": steps,
                "images": images,
                "visual_dependency": _estimate_visual_dependency(
                    image_count=len(images),
                    search_text=search_text,
                    steps=steps,
                ),
            }
        )

    if sections:
        return sections

    fallback_text = _normalize_search_content(body).strip()
    fallback_images = _extract_image_refs(body, rel_path, "")
    fallback_steps = _extract_section_steps(fallback_text, "")
    return [
        {
            "heading": "",
            "search_text": fallback_text,
            "steps": fallback_steps,
            "images": fallback_images,
            "visual_dependency": _estimate_visual_dependency(
                image_count=len(fallback_images),
                search_text=fallback_text,
                steps=fallback_steps,
            ),
        }
    ]


def _extract_heading(raw_section: str) -> str:
    match = re.search(r"^#+\s+(.+)$", raw_section, re.MULTILINE)
    if not match:
        return ""
    return _normalize_inline_text(match.group(1))


def _extract_section_steps(search_text: str, heading: str) -> list[str]:
    lines = [line.strip() for line in search_text.splitlines() if line.strip()]
    if heading and lines:
        normalized_heading = heading.lower().rstrip(":")
        if lines[0].lower() == normalized_heading:
            lines = lines[1:]
        elif lines[0].lower().startswith(normalized_heading + " "):
            lines[0] = lines[0][len(heading) :].lstrip(" .:-")

    explicit_steps: list[str] = []
    for line in lines:
        lowered = line.lower()
        if lowered.startswith("step:"):
            explicit_steps.append(_normalize_step_text(line.split(":", 1)[1]))
            continue
        if re.match(r"^\d+\.\s+", line):
            explicit_steps.append(_normalize_step_text(re.sub(r"^\d+\.\s+", "", line)))
            continue
        if re.match(r"^-\s+", line):
            explicit_steps.append(_normalize_step_text(re.sub(r"^-\s+", "", line)))

    explicit_steps = _dedupe_items(explicit_steps, limit=5)
    if explicit_steps:
        return explicit_steps

    sentences = re.split(r"(?<=[.!?])\s+", " ".join(lines))
    fallback_steps: list[str] = []
    heading_lower = heading.lower()
    procedural_heading = any(token in heading_lower for token in ("creating", "create", "how to"))

    for sentence in sentences:
        step = _normalize_step_text(sentence)
        if not step:
            continue
        if procedural_heading:
            if _is_informative_sentence(step):
                fallback_steps.append(step)
        elif _is_procedural_sentence(step):
            fallback_steps.append(step)

    return _dedupe_items(fallback_steps, limit=4)


def _normalize_step_text(text: str) -> str:
    cleaned = _normalize_inline_text(text)
    cleaned = cleaned.strip(" -.;")
    if not cleaned:
        return ""
    if len(cleaned.split()) < 4:
        return ""
    return cleaned


def _is_informative_sentence(sentence: str) -> bool:
    lowered = sentence.lower()
    if lowered.startswith(("read more", "learn more", "note that")):
        return False
    if len(sentence) > 220:
        return False
    return True


def _is_procedural_sentence(sentence: str) -> bool:
    lowered = sentence.lower()
    if not _is_informative_sentence(sentence):
        return False
    if any(lowered.startswith(verb + " ") for verb in STEP_VERBS):
        return True
    if " you can " in f" {lowered} ":
        return True
    return any(f" {verb} " in f" {lowered} " for verb in STEP_VERBS[:8])


def _extract_image_refs(raw_text: str, rel_path: str, section_heading: str) -> list[dict[str, Any]]:
    images: list[dict[str, Any]] = []
    seen: set[str] = set()

    for alt_text, raw_target in re.findall(r"!\[([^\]]*)\]\(([^)]+)\)", raw_text):
        src = raw_target.strip().split()[0].strip("'\"")
        if src in seen:
            continue
        seen.add(src)
        image_ref = _build_image_ref(src, alt_text, section_heading, rel_path)
        if image_ref:
            images.append(image_ref)

    for attrs in re.findall(r"<img\b(.*?)/?>", raw_text, re.DOTALL):
        src_match = re.search(r'src="([^"]+)"', attrs)
        if not src_match:
            continue
        src = src_match.group(1).strip()
        if src in seen:
            continue
        seen.add(src)
        alt_match = re.search(r'alt="([^"]*)"', attrs)
        alt_text = alt_match.group(1).strip() if alt_match else ""
        image_ref = _build_image_ref(src, alt_text, section_heading, rel_path)
        if image_ref:
            images.append(image_ref)

    return images


def _build_image_ref(
    src: str,
    raw_label: str,
    section_heading: str,
    rel_path: str,
) -> dict[str, Any] | None:
    local_path = _resolve_image_path(src, rel_path)
    if not local_path:
        return None

    exists = local_path.exists()
    mime_type = mimetypes.guess_type(str(local_path))[0] or _fallback_mime_type(local_path.suffix.lower())
    size_bytes = local_path.stat().st_size if exists else 0
    label = _select_image_label(raw_label, section_heading, local_path)

    return {
        "src": src,
        "label": label,
        "section_heading": section_heading,
        "local_path": str(local_path),
        "mime_type": mime_type,
        "size_bytes": size_bytes,
        "exists": exists,
    }


def _resolve_image_path(src: str, rel_path: str) -> Path | None:
    clean_src = src.split("?", 1)[0].split("#", 1)[0].strip()
    if not clean_src or clean_src.startswith(("http://", "https://", "data:")):
        return None

    doc_root = RIVE_DOCS_PATH.resolve()
    if clean_src.startswith("/images/"):
        candidate = (RIVE_DOCS_PATH / clean_src.lstrip("/")).resolve()
    elif clean_src.startswith("/"):
        return None
    else:
        relative_doc_dir = (RIVE_DOCS_PATH / PurePosixPath(rel_path).parent).resolve()
        candidate = (relative_doc_dir / PurePosixPath(clean_src)).resolve()

    try:
        candidate.relative_to(doc_root)
    except ValueError:
        return None

    if candidate.suffix.lower() not in IMAGE_EXTENSIONS:
        return None
    return candidate


def _select_image_label(raw_label: str, section_heading: str, local_path: Path) -> str:
    label = _normalize_inline_text(raw_label)
    lower_words = {word.lower() for word in label.split()}
    generic_words = {"image", "gif", "png", "jpg", "jpeg", "webp", "gi", "pn", "img"}

    if not label or lower_words.issubset(generic_words):
        label = section_heading.strip()
    if not label:
        label = local_path.stem.replace("_", " ").replace("-", " ")
    return label.strip()


def _estimate_visual_dependency(image_count: int, search_text: str, steps: list[str]) -> float:
    if image_count <= 0:
        return 0.0

    word_count = len(search_text.split())
    score = float(min(image_count, 4))

    if word_count < 140:
        score += 2.0
    elif word_count < 220:
        score += 1.0

    if len(steps) < 2:
        score += 1.0

    lowered = search_text.lower()
    if any(
        phrase in lowered
        for phrase in (
            "color box",
            "plus button",
            "settings button",
            "dropdown",
            "toggle",
            "inspector",
            "popout",
        )
    ):
        score += 1.0

    return round(score, 2)


def _sanitize_result_for_tool(result: dict[str, Any]) -> dict[str, Any]:
    sanitized = {
        key: value
        for key, value in result.items()
        if key not in {"images"}
    }
    sanitized["image_refs"] = [
        {
            "src": image.get("src", ""),
            "label": image.get("label", ""),
            "section_heading": image.get("section_heading", ""),
            "mime_type": image.get("mime_type", ""),
        }
        for image in result.get("images", [])
    ]
    return sanitized


def _truncate_excerpt(text: str, max_length: int) -> str:
    excerpt = " ".join(text.split())
    if len(excerpt) <= max_length:
        return excerpt
    return excerpt[: max_length - 3].rstrip() + "..."


def _normalize_search_content(content: str) -> str:
    normalized = _strip_frontmatter(content)
    normalized = re.sub(r"^import\s+.+$", "", normalized, flags=re.MULTILINE)
    normalized = _replace_step_components(normalized)
    normalized = re.sub(r"<YouTube\b[^>]*?/?>", "\n", normalized)
    normalized = re.sub(
        r"!\[([^\]]*)\]\(([^)]+)\)",
        " ",
        normalized,
    )
    normalized = re.sub(
        r"<img\b(.*?)/?>",
        " ",
        normalized,
        flags=re.DOTALL,
    )
    normalized = re.sub(r"</?Steps[^>]*>", "\n", normalized)
    normalized = re.sub(r"</?Step[^>]*>", "\n", normalized)
    normalized = re.sub(r"</?[^>]+>", " ", normalized)

    lines: list[str] = []
    for line in normalized.splitlines():
        stripped = line.strip()
        if not stripped:
            lines.append("")
            continue
        if stripped.startswith("#"):
            stripped = re.sub(r"^#+\s*", "", stripped)
        cleaned = _normalize_inline_text(stripped)
        if cleaned:
            lines.append(cleaned)

    return "\n".join(lines)


def _replace_step_components(text: str) -> str:
    def replace_step(match: re.Match[str]) -> str:
        title = _normalize_inline_text(match.group("title"))
        body = _normalize_search_content(match.group("body"))
        body = " ".join(body.split())
        if body:
            return f"\nStep: {title}. {body}\n"
        return f"\nStep: {title}\n"

    return re.sub(
        r"<Step\s+title=\"(?P<title>[^\"]+)\"\s*>(?P<body>.*?)</Step>",
        replace_step,
        text,
        flags=re.DOTALL,
    )


def _extract_attr(attrs: str, key: str) -> str:
    match = re.search(rf'{re.escape(key)}="([^"]*)"', attrs)
    if not match:
        return ""
    return match.group(1)


def _strip_frontmatter(content: str) -> str:
    return re.sub(r"^---\n.*?\n---\n", "", content, flags=re.DOTALL)


def _normalize_inline_text(text: str) -> str:
    normalized = text.replace("\u200b", " ").replace("\u200c", " ").replace("\ufeff", " ")
    normalized = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", normalized)
    normalized = re.sub(r"`([^`]+)`", r"\1", normalized)
    normalized = normalized.replace("*", "").replace("_", " ")
    normalized = re.sub(r"\s+", " ", normalized)
    return normalized.strip()


def _dedupe_items(items: list[str], limit: int) -> list[str]:
    deduped: list[str] = []
    seen: set[str] = set()
    for item in items:
        normalized = " ".join(item.split())
        if not normalized:
            continue
        key = normalized.lower()
        if key in seen:
            continue
        seen.add(key)
        deduped.append(normalized)
        if len(deduped) >= limit:
            break
    return deduped


def _fallback_mime_type(suffix: str) -> str:
    return {
        ".png": "image/png",
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".gif": "image/gif",
        ".webp": "image/webp",
        ".bmp": "image/bmp",
    }.get(suffix, "application/octet-stream")
