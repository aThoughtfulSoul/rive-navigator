"""
Prompt and runtime-context helpers for the Rive Navigator agent.
"""

from __future__ import annotations

from typing import Any

from .tools.rive_docs_lookup import search_rive_docs

BASE_AGENT_POLICY = """You are Rive UI Navigator, an expert assistant for the Rive editor.

Your job is to help users understand the current editor state, build multi-step Rive workflows,
and safely guide or automate changes in the editor.

Core operating rules:
- The server may provide RUNTIME CONTEXT blocks containing the current mode, task state,
  procedure cards, and relevant Rive docs. Use that context first.
- When a task is active, prioritize the current step over the overall task goal.
- Rely on the screenshot for current UI state. Use Rive docs for procedure grounding.
- If the user is not in an active task, answer normally and do not emit ACTION or CURSOR tags.
- In collaborative task mode, guide the user and emit at most one CURSOR tag at the end.
- In agentic task mode, explain briefly and emit at most one ACTION tag at the end.
- Never emit both ACTION and CURSOR tags in the same response.
- Use percentages from 0 to 100 for any coordinates. Never use pixels.
- If the target is visually unclear, say so instead of guessing.
- Prefer keyboard shortcuts over clicking small toolbar icons.
- If a standard Rive shortcut exists for the exact tool or mode change, default to a `key` ACTION unless text input is active or that shortcut already failed.
- Never rename timelines or state machines. Leave their default names unchanged and continue with the functional setup.
- If a task step asks to rename a timeline or state machine, skip that rename portion instead of repeating clicks or double-clicks.
- When editing Inspector values, prefer the atomic `type` action with coordinates.
- Never use Cmd+A or Ctrl+A to select text in the editor.
- If an action appears to fail, change strategy instead of repeating it.
- Keep agentic responses short because the user is watching the UI, not reading prose.

Tool usage:
- Use `start_task` to create a granular step list when a workflow should become a task.
- Use `advance_task` to move next/back/skip/end once the current step is resolved.
- Use `verify_step` after checking whether a task step is complete from the screenshot.
- Use `analyze_screenshot` when a screenshot observation materially affects your next move.
- Use `lookup_rive_docs` when the provided runtime guidance is insufficient or ambiguous.

Output rules:
- Put any ACTION or CURSOR tag at the end of the response.
- The ONLY accepted CURSOR format is:
  <!--CURSOR:{"x":12.3,"y":45.6,"label":"Element name"}-->
- The ONLY accepted ACTION format is:
  <!--ACTION:{"type":"click","x":12.3,"y":45.6,"label":"Element name"}-->
- The ONLY accepted key ACTION format is:
  <!--ACTION:{"type":"key","key":"o","label":"Select Ellipse tool"}-->
- For modified shortcuts, use:
  <!--ACTION:{"type":"key","key":"k","modifiers":"meta","label":"Open search"}-->
- For drag actions, use this exact shape:
  <!--ACTION:{"type":"drag","x1":40.0,"y1":35.0,"x2":55.0,"y2":48.0,"label":"Drag target"}-->
- Do not use XML tags like <ACTION>...</ACTION> or markdown code fences for structured output.
- For actions, the field name must be `type`, never `action`.
- For drag actions, use `x1`/`y1`/`x2`/`y2`, not `to_x`/`to_y`.
- Use `type:"key"` for standard shortcuts like `O`, `R`, `A`, `V`, `Tab`, or modified shortcuts.
- In ask mode, provide no tag.
- In collaborative mode, provide at most one CURSOR tag and no ACTION tag.
- In agentic mode, provide at most one ACTION tag and no CURSOR tag.
"""

OUTPUT_CONTRACTS = {
    "ask": [
        "Answer directly. Do not emit ACTION or CURSOR tags.",
    ],
    "collaborative": [
        "Guide the user step by step.",
        "Emit at most one CURSOR tag at the end of the response using exactly this format: <!--CURSOR:{\"x\":12.3,\"y\":45.6,\"label\":\"Element name\"}-->.",
        "Do not emit ACTION tags.",
    ],
    "agentic": [
        "Perform at most one action this turn.",
        "Emit exactly zero or one ACTION tag at the end of the response using exactly this format: <!--ACTION:{\"type\":\"click\",\"x\":12.3,\"y\":45.6,\"label\":\"Element name\"}-->.",
        "When a shortcut is the default path, emit a key action like <!--ACTION:{\"type\":\"key\",\"key\":\"o\",\"label\":\"Select Ellipse tool\"}--> instead of clicking a toolbar icon.",
        "For drag actions, emit <!--ACTION:{\"type\":\"drag\",\"x1\":40.0,\"y1\":35.0,\"x2\":55.0,\"y2\":48.0,\"label\":\"Drag target\"}-->.",
        "Do not emit CURSOR tags.",
    ],
}

PROCEDURE_CARDS = {
    "core-editor-ops": """Core Rive editor operations for basic creation tasks:
- New File is typically in the top-right controls.
- Create an artboard first. Use the Artboard tool with `A` when needed.
- Use `O` for Ellipse and `R` for Rectangle instead of clicking toolbar icons.
- After selecting a shape tool, drag on the canvas center area to create the shape.
- Use `V` to return to Select so you can reposition or resize objects.
- The canvas is usually the center of the screen, roughly x 20-80 and y 10-70.
- The Inspector is on the right, roughly x 86-100, and contains size, position, Fill, and Stroke.
- For a simple shape task: create file if needed, create artboard, choose shape tool by shortcut, drag on canvas, then set Fill/Stroke in the Inspector.
- Verify each basic step visually before moving on.""",
    "file-startup": """Starting a new Rive file:
- If the screenshot already shows the new-file stage with presets or size fields, do not click New File again.
- In that new-file stage, the fastest next step is usually the stage-level Create Artboard button.
- If you are still in the normal editor workspace, the New File control is usually in the top-right.
- After clicking New File, wait for the new-file stage before attempting artboard or shape creation.""",
    "artboard-creation": """Creating an artboard:
- In a fresh file, leave the default size or preset as-is unless the step explicitly asks for custom dimensions.
- Use the on-stage Create Artboard button when it is visible.
- Alternative: press `A` for the Artboard tool, then drag on the stage to define bounds.
- If an artboard is already visible and active, avoid creating a duplicate unless the task explicitly asks for another one.""",
    "shape-creation": """Creating basic shapes:
- Basic vector shapes are procedural shapes.
- Use `O` for Ellipse and `R` for Rectangle instead of opening the create menu.
- Click and drag inside the active artboard to create the shape.
- Hold `Shift` while dragging when the task specifically asks for a perfect circle or square.
- If a shape does not appear, verify that an artboard exists and is active before trying again.""",
    "tool-shortcuts": """Use keyboard shortcuts instead of toolbar clicks whenever possible.
- Tool shortcuts: V Select, Q Move, W Rotate, E Scale, R Rectangle, O Ellipse, P Pen, T Text, A Artboard, B Bone.
- Mode shortcuts: Tab toggles Design/Animate, F zoom-to-fit, Cmd/Ctrl+K opens search.
- For undo and grouping, use key actions with modifiers instead of toolbar clicks.""",
    "artboard-fit": """Finding or centering an artboard:
- If the goal is to find, center, or recover a lost artboard, use `F` with a `key` action instead of panning manually.
- Preferred action: <!--ACTION:{"type":"key","key":"f","label":"Fit artboard to screen"}-->
- `F` fits the active selection to the screen. If a child object is selected, it may fit that object instead of the artboard.
- If the artboard is already centered and visible, verify it and move on instead of repeating `F`.""",
    "shortcut-priority": """Shortcut-first action policy:
- If a known Rive shortcut can complete the step, default to a `key` action instead of clicking a toolbar icon or menu.
- Examples: <!--ACTION:{"type":"key","key":"o","label":"Select Ellipse tool"}-->, <!--ACTION:{"type":"key","key":"a","label":"Select Artboard tool"}-->, <!--ACTION:{"type":"key","key":"Tab","label":"Switch to Animate mode"}-->
- Only click the toolbar or menus when no shortcut exists, the shortcut already failed, or the screenshot shows text-editing focus that would capture the key.
- After selecting a tool by shortcut, the next action is usually on the stage or canvas, not on the toolbar again.""",
    "coordinate-sanity": """All coordinates must be viewport percentages from 0 to 100.
- Left panel is usually x 0-14.
- Inspector is usually x 86-100.
- Bottom-left animation list is usually x 0-13 and y 76-100.
- If a coordinate is outside 0-100, it is wrong and should not be used.""",
    "inspector-editing": """When editing Inspector values, use the atomic `type` action.
- Preferred: {"type":"type","x":92.5,"y":18.5,"text":"100","label":"Set width to 100"}
- Do not click the field first, then send separate key events.
- Never use Cmd+A/Ctrl+A to select text in the editor.""",
    "color-editing": """To change colors:
- Select the object first.
- Use the Inspector Fill or Stroke section on the right.
- After changing a color, verify the canvas actually changed before advancing.""",
    "mode-switching": """Rive has Design mode and Animate mode.
- Design mode is for creating and styling shapes.
- Animate mode is for timelines, keyframes, and state machines.
- Use Tab when you need to switch modes quickly.""",
    "rename-safety": """Rename safety:
- Never rename timelines or state machines. That flow is too flaky and can cause loops.
- If a step asks to rename a timeline or state machine, skip the rename portion and continue with the functional work, such as duration, inputs, transitions, or keyframes.
- Only use rename interactions for safer objects when the name change is truly necessary and the editable text field is visibly active.""",
    "keyframes": """Keyframe workflow:
- Be in Animate mode.
- Select a timeline.
- Move the playhead.
- Change a property in the Inspector or on the stage.
- Verify the keyframe was created before advancing.""",
    "state-machine-transitions": """Creating state-machine transitions:
- Hover just outside a state's edge to reveal the connector dot.
- Do not drag from the center of the state, because that only repositions it.
- Once the connector dot appears, drag from the dot to the target state.
- Verify the arrow exists before moving on.""",
    "state-machine-inputs": """State-machine inputs and conditions:
- Select the state machine in the animations list.
- Use the Inputs area to create Boolean, Number, or Trigger inputs.
- Select a transition arrow, then add conditions in the Inspector.""",
}


def build_runtime_context(
    user_message: str,
    task_mode: str,
    session_state: dict[str, Any] | None = None,
) -> str:
    return build_runtime_package(
        user_message=user_message,
        task_mode=task_mode,
        session_state=session_state,
    )["text"]


def build_runtime_package(
    user_message: str,
    task_mode: str,
    session_state: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """
    Builds the per-turn context and related doc metadata injected by the server.
    """
    state = session_state or {}
    task_active = bool(state.get("task:active"))
    effective_mode = task_mode if task_active else "ask"
    doc_hits = _lookup_runtime_docs(user_message, state)
    doc_visuals = _select_doc_visuals(doc_hits, user_message, state)

    sections = [
        "[RUNTIME CONTEXT]",
        _format_mode_block(effective_mode, state),
        _format_task_block(state),
        _format_step_focus(state),
        _format_output_contract(effective_mode),
    ]

    procedure_cards = _select_procedure_cards(
        text=" ".join(
            filter(
                None,
                [
                    user_message,
                    state.get("task:name", ""),
                    state.get("task:current_step_name", ""),
                    state.get("last_action_label", ""),
                    state.get("last_validation_error", ""),
                ],
            )
        ),
        effective_mode=effective_mode,
    )
    if procedure_cards:
        sections.append(_format_procedure_cards(procedure_cards))

    if doc_hits:
        sections.append(_format_doc_hits(doc_hits))

    if doc_visuals:
        sections.append(_format_doc_visuals(doc_visuals))

    return {
        "text": "\n\n".join(section for section in sections if section.strip()),
        "doc_hits": doc_hits,
        "doc_visuals": doc_visuals,
    }


def _build_doc_query(user_message: str, state: dict[str, Any]) -> str:
    parts = [
        user_message,
        state.get("task:name", ""),
        state.get("task:current_step_name", ""),
        state.get("task:last_feedback", ""),
        state.get("task:last_verification_feedback", ""),
        state.get("last_action_label", ""),
    ]
    return " ".join(part.strip() for part in parts if isinstance(part, str) and part.strip())


def _build_doc_queries(user_message: str, state: dict[str, Any]) -> list[str]:
    raw_queries: list[str] = []
    current_step = str(state.get("task:current_step_name", "")).strip()
    last_validation = str(state.get("last_validation_error", "")).strip()
    last_feedback = str(state.get("task:last_feedback", "")).strip()
    last_verification_feedback = str(state.get("task:last_verification_feedback", "")).strip()
    task_name = str(state.get("task:name", "")).strip()
    user_text = user_message.strip()

    if state.get("task:active") and current_step:
        raw_queries.extend(_expand_doc_queries(current_step))
    if last_validation:
        raw_queries.extend(_expand_doc_queries(last_validation))
    if last_feedback:
        raw_queries.extend(_expand_doc_queries(last_feedback))
    if last_verification_feedback:
        raw_queries.extend(_expand_doc_queries(last_verification_feedback))
    if user_text and not _is_generic_follow_up(user_text):
        raw_queries.extend(_expand_doc_queries(user_text))
    if task_name and (not state.get("task:active") or not current_step):
        raw_queries.extend(_expand_doc_queries(task_name))

    if not raw_queries:
        fallback = _build_doc_query(user_message, state)
        if fallback:
            raw_queries.append(fallback)

    deduped: list[str] = []
    seen: set[str] = set()
    for query in raw_queries:
        normalized = " ".join(query.split())
        if not normalized:
            continue
        key = normalized.lower()
        if key in seen:
            continue
        seen.add(key)
        deduped.append(normalized)
        if len(deduped) >= 5:
            break
    return deduped


def _expand_doc_queries(text: str) -> list[str]:
    normalized = " ".join(text.split())
    lowered = normalized.lower()
    queries = [normalized]

    if "new file" in lowered or "fresh file" in lowered or "blank file" in lowered:
        queries.extend(
            [
                "new file create artboard on stage",
                "artboards create artboard in new file",
            ]
        )
    if "artboard" in lowered:
        queries.extend(
            [
                "artboards create artboard stage button",
                "artboard tool shortcut A stage",
                "keyboard shortcuts artboard tool A",
            ]
        )
    if any(term in lowered for term in ("circle", "ellipse")):
        queries.extend(
            [
                "procedural shapes ellipse circle artboard",
                "ellipse tool procedural shapes",
                "keyboard shortcuts ellipse tool O",
            ]
        )
    elif any(term in lowered for term in ("shape", "shapes", "rectangle", "procedural")):
        queries.extend(
            [
                "procedural shapes in artboard",
                "shape tools rectangle ellipse artboard",
                "keyboard shortcuts rectangle ellipse tools",
            ]
        )
    if any(term in lowered for term in ("fill", "stroke", "color", "hex", "swatch")):
        queries.append("fill and stroke inspector")
    if any(term in lowered for term in ("timeline", "keyframe", "animate")):
        queries.append("animate mode keyframe timeline")
    if any(term in lowered for term in ("switch mode", "animate mode", "design mode", "toggle mode", "tab")):
        queries.append("keyboard shortcuts switch mode Tab")
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
        queries.extend(
            [
                "stage fit artboard to screen F",
                "keyboard shortcuts fit selection to screen F",
            ]
        )

    return queries


def _is_generic_follow_up(text: str) -> bool:
    lowered = " ".join(text.lower().split())
    generic_messages = {
        "continue",
        "again",
        "try again",
        "try again please",
        "please continue",
        "resume",
        "keep going",
        "[resumed] continue from where you left off. here is the current state.",
    }
    return lowered in generic_messages


def _lookup_runtime_docs(user_message: str, state: dict[str, Any]) -> list[dict[str, Any]]:
    merged: dict[str, dict[str, Any]] = {}
    for priority, query in enumerate(_build_doc_queries(user_message, state)):
        hits = search_rive_docs(
            query=query,
            limit=2,
            preferred_categories=_preferred_categories(query),
        )
        for hit in hits:
            adjusted_hit = dict(hit)
            adjusted_hit["score"] = float(hit.get("score", 0)) - (priority * 1.5)
            existing = merged.get(adjusted_hit["path"])
            if existing is None or adjusted_hit["score"] > float(existing.get("score", 0)):
                merged[adjusted_hit["path"]] = adjusted_hit

    ranked = sorted(merged.values(), key=lambda item: float(item.get("score", 0)), reverse=True)
    return ranked[:3]


def _preferred_categories(query: str) -> list[str]:
    q = query.lower()
    if any(term in q for term in ("runtime", "react", "flutter", "android", "ios", "unity", "unreal", "web")):
        return ["runtimes", "game-runtimes", "snippets"]
    if any(term in q for term in ("script", "api", "mcp", "protocol")):
        return ["scripting", "api-reference", "editor"]
    return ["editor", "tutorials", "getting-started"]


def _format_mode_block(effective_mode: str, state: dict[str, Any]) -> str:
    lines = [
        "[CURRENT MODE]",
        f"- Effective mode: {effective_mode}",
        f"- Requested task mode: {state.get('task_mode', 'collaborative')}",
    ]
    if state.get("last_action_label"):
        lines.append(f"- Last action label: {state.get('last_action_label')}")
    if state.get("last_validation_error"):
        lines.append(f"- Last validation issue: {state.get('last_validation_error')}")
    return "\n".join(lines)


def _format_task_block(state: dict[str, Any]) -> str:
    if not state.get("task:active"):
        lines = [
            "[TASK STATE]",
            "- No active task.",
        ]
        if state.get("last_observation"):
            lines.append(f"- Last observation: {_truncate(state.get('last_observation', ''), 220)}")
        return "\n".join(lines)

    completed_steps = state.get("task:completed_steps", "[]")
    lines = [
        "[TASK STATE]",
        f"- Task: {state.get('task:name', '')}",
        f"- Current step: {state.get('task:current_step', 0)}/{state.get('task:total_steps', 0)}",
        f"- Step name: {state.get('task:current_step_name', '')}",
        f"- Last transition: {state.get('task:last_direction', 'start')}",
        f"- Last verification: {state.get('task:last_verification', 'not_started')}",
    ]
    if state.get("task:last_feedback"):
        lines.append(f"- Last feedback: {_truncate(state.get('task:last_feedback', ''), 220)}")
    if state.get("task:last_verification_feedback"):
        lines.append(
            f"- Last verification feedback: {_truncate(state.get('task:last_verification_feedback', ''), 220)}"
        )
    if state.get("last_observation"):
        lines.append(f"- Last observation: {_truncate(state.get('last_observation', ''), 220)}")
    lines.append(f"- Completed steps payload: {_truncate(str(completed_steps), 180)}")
    return "\n".join(lines)


def _format_step_focus(state: dict[str, Any]) -> str:
    if not state.get("task:active"):
        return ""

    current_step = str(state.get("task:current_step_name", "")).strip()
    if not current_step:
        return ""

    lines = [
        "[STEP FOCUS]",
        f"- Primary objective: {current_step}",
        "- Solve only this step before planning later steps.",
        "- If the screenshot already shows the step is complete, verify it and advance instead of repeating the previous action.",
    ]
    if _is_blocked_rename_step(current_step):
        lines.append("- Timeline and state-machine renames are unsupported. Skip the rename portion and continue with the remaining functional work.")
    return "\n".join(lines)


def _format_output_contract(effective_mode: str) -> str:
    rules = OUTPUT_CONTRACTS.get(effective_mode, OUTPUT_CONTRACTS["ask"])
    lines = ["[OUTPUT CONTRACT]"]
    lines.extend(f"- {rule}" for rule in rules)
    return "\n".join(lines)


def _select_procedure_cards(text: str, effective_mode: str) -> list[tuple[str, str]]:
    lowered = text.lower()
    selected: list[str] = []

    if effective_mode in {"collaborative", "agentic"}:
        selected.extend(["core-editor-ops", "shortcut-priority", "tool-shortcuts", "coordinate-sanity"])

    keyword_map = [
        ("file-startup", ("new file", "fresh file", "blank file", "create file")),
        ("artboard-creation", ("artboard", "create artboard", "preset", "create artboard button")),
        (
            "artboard-fit",
            (
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
            ),
        ),
        ("shape-creation", ("shape", "shapes", "circle", "ellipse", "rectangle", "procedural")),
        ("inspector-editing", ("width", "height", "opacity", "rotation", "inspector", "x ", " y", "position", "type")),
        ("color-editing", ("fill", "stroke", "color", "hex", "swatch")),
        ("state-machine-transitions", ("transition", "connector", "any state", "entry", "exit")),
        ("state-machine-inputs", ("input", "condition", "boolean", "trigger", "number")),
        ("keyframes", ("keyframe", "playhead", "timeline", "animation")),
        ("mode-switching", ("animate mode", "design mode", "switch mode", "toggle mode", "tab")),
        ("rename-safety", ("rename", "renaming", "doubleclick", "editable text", "timeline 1", "state machine")),
    ]

    scored_matches: list[tuple[int, str]] = []
    for card_name, keywords in keyword_map:
        match_count = sum(1 for keyword in keywords if keyword in lowered)
        if match_count > 0:
            scored_matches.append((match_count, card_name))

    scored_matches.sort(key=lambda item: item[0], reverse=True)
    selected.extend(card_name for _, card_name in scored_matches)

    deduped: list[tuple[str, str]] = []
    seen: set[str] = set()
    for name in selected:
        if name in seen:
            continue
        seen.add(name)
        deduped.append((name, PROCEDURE_CARDS[name]))
        if len(deduped) >= 8:
            break

    return deduped


def _format_procedure_cards(cards: list[tuple[str, str]]) -> str:
    lines = ["[PROCEDURE CARDS]"]
    for name, body in cards:
        lines.append(f"{name}:")
        lines.append(body)
    return "\n".join(lines)


def _format_doc_hits(doc_hits: list[dict[str, Any]]) -> str:
    lines = ["[RELEVANT RIVE DOCS]"]
    for idx, hit in enumerate(doc_hits, start=1):
        lines.append(f"{idx}. {hit.get('path', '')} - {hit.get('title', '')}")
        section_heading = _truncate(hit.get("section_heading", ""), 100)
        if section_heading:
            lines.append(f"   Section: {section_heading}")
        steps = hit.get("steps", []) or []
        for step_idx, step in enumerate(steps[:3], start=1):
            lines.append(f"   Step {step_idx}: {_truncate(step, 180)}")
        if not steps:
            snippet = _truncate(hit.get("snippet", ""), 320)
            if snippet:
                lines.append(f"   {snippet}")
        images = hit.get("images", []) or []
        if images:
            labels = ", ".join(
                _truncate(image.get("label", ""), 40)
                for image in images[:2]
                if image.get("label")
            )
            if labels:
                lines.append(f"   Visual refs: {labels}")
    return "\n".join(lines)


def _select_doc_visuals(
    doc_hits: list[dict[str, Any]],
    user_message: str,
    state: dict[str, Any],
) -> list[dict[str, Any]]:
    reference_text = " ".join(
        filter(
            None,
            [
                user_message,
                str(state.get("task:current_step_name", "")),
                str(state.get("last_validation_error", "")),
            ],
        )
    ).lower()
    likely_visual = any(
        term in reference_text
        for term in (
            "artboard",
            "fill",
            "stroke",
            "color",
            "gradient",
            "inspector",
            "dropdown",
            "button",
            "list",
            "converter",
        )
    )

    selected: list[dict[str, Any]] = []
    for hit in doc_hits:
        if not hit.get("images"):
            continue
        if not likely_visual and float(hit.get("visual_dependency", 0.0)) < 4.0:
            continue
        for image in hit["images"]:
            if not image.get("exists"):
                continue
            selected.append(
                {
                    "doc_path": hit.get("path", ""),
                    "doc_title": hit.get("title", ""),
                    "section_heading": hit.get("section_heading", ""),
                    **image,
                }
            )
            break
        if len(selected) >= 1:
            break
    return selected


def _format_doc_visuals(doc_visuals: list[dict[str, Any]]) -> str:
    lines = ["[ATTACHED DOC VISUALS]"]
    for visual in doc_visuals:
        label = visual.get("label", "") or visual.get("section_heading", "") or visual.get("doc_title", "")
        lines.append(
            f"- Attached reference image from {visual.get('doc_path', '')}: {_truncate(label, 100)}"
        )
    return "\n".join(lines)


def _truncate(text: str, limit: int) -> str:
    text = " ".join(text.split())
    if len(text) <= limit:
        return text
    return text[: limit - 3].rstrip() + "..."


def _is_blocked_rename_step(text: str) -> bool:
    lowered = " ".join(text.lower().split())
    has_target = any(target in lowered for target in ("timeline", "state machine", "state-machine", "statemachine"))
    has_rename_intent = any(term in lowered for term in ("rename", "renaming", "renamed"))
    return has_target and has_rename_intent
