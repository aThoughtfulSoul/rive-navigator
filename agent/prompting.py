"""
Prompt and runtime-context helpers for the Rive Navigator agent.
"""

from __future__ import annotations

import logging
from typing import Any

from .tools.rive_docs_lookup import search_rive_docs

logger = logging.getLogger(__name__)

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
- For basic shape creation, a failed drag does not mean the shortcut failed. Keep using `O` for Ellipse and `R` for Rectangle unless the screenshot clearly shows the wrong tool is active or text input focus would capture the key.
- If drawing a basic shape fails, recover by reselecting the artboard or clicking blank stage, pressing the shape shortcut again, and retrying the drag inside the artboard before falling back to toolbar clicks.
- Never use `Shift+L` or wrap/convert objects into Layouts (Row, Column, Layout containers) unless the task explicitly asks for a responsive layout. If an object unexpectedly changes its name to "Column", "Row", or "Layout", or its children become distorted, immediately undo with Cmd/Ctrl+Z.
- Never rename timelines or state machines. Leave their default names unchanged and continue with the functional setup.
- If a task step asks to rename a timeline or state machine, skip that rename portion instead of repeating clicks or double-clicks.
- When editing Inspector values, prefer the atomic `type` action with coordinates.
- Never use Cmd+A or Ctrl+A to select text in the editor.
- If an action appears to fail, change strategy instead of repeating it.
- Do not assume an object is selected unless the screenshot shows a clear selection cue such as stage handles, a changed Inspector, or an obvious hierarchy highlight.
- If hierarchy selection is visually ambiguous or repeated clicks do not clearly change the screenshot, click the visible object on the stage/canvas instead of repeating the hierarchy click.
- For procedural shapes like Ellipse or Rectangle, prefer selecting the parent shape object, not a child `Path`, when changing opacity, position, scale, size, or keyframes.
- Only select a child `Path` when the task explicitly requires path/node editing or converting/editing vector points.
- If the object to animate is much larger than the artboard or mostly outside it, scale it down to fit and center it before starting animation, unless the task explicitly requires an off-artboard position.
- SVGs imported via the asset pipeline already have their origin at bottom-center (ideal for bounce/drop/jump). Do not attempt to move the origin with Freeze mode — it requires too much dexterity and is error-prone for the agent.
- Before keyframing bounce, position, or scale changes, make sure the relevant artboard and moving object are fully visible on screen. If they are not clearly framed, use `F` first.
- After switching to Animate mode with `Tab`, re-check the framing. If the timeline or Animate workspace changed what is visible, click a blank stage/artboard area if needed, then use `F` before continuing so the full motion area is back in view.
- If the canvas is zoomed into a corner, the artboard is lost, or the relevant object is off-screen, use `F` as the first recovery action before manual zooming or panning.
- If `F` frames the wrong selection, select the intended artboard or object and press `F` again instead of adjusting the zoom controls manually.
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
- For hover actions (to reveal tooltips before clicking), use:
  <!--ACTION:{"type":"hover","x":12.3,"y":45.6,"label":"Hover interpolation icon"}-->
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
        "IMPORTANT: Before emitting a new ACTION, first state in one sentence whether the previous action succeeded or failed based on the screenshot. If it failed, change strategy instead of repeating the same action.",
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
- If the goal is to find, center, or recover a lost artboard or off-screen object, use `F` with a `key` action instead of panning manually.
- Preferred action: <!--ACTION:{"type":"key","key":"f","label":"Fit artboard to screen"}-->
- `F` fits the active selection to the screen. If a child object is selected, it may fit that object instead of the artboard.
- If `F` frames the wrong thing, change the selection, then press `F` again instead of manually changing the zoom level.
- If you just switched to Animate mode and the wrong panel or control has focus, click a blank part of the stage/artboard first, then press `F`.
- Before bounce, position, or scale keyframing, use `F` if the full motion area is not clearly visible.
- If the artboard is already centered and visible, verify it and move on instead of repeating `F`.""",
    "shortcut-priority": """Shortcut-first action policy:
- If a known Rive shortcut can complete the step, default to a `key` action instead of clicking a toolbar icon or menu.
- Examples: <!--ACTION:{"type":"key","key":"o","label":"Select Ellipse tool"}-->, <!--ACTION:{"type":"key","key":"a","label":"Select Artboard tool"}-->, <!--ACTION:{"type":"key","key":"Tab","label":"Switch to Animate mode"}-->
- Only click the toolbar or menus when no shortcut exists, the shortcut already failed, or the screenshot shows text-editing focus that would capture the key.
- For Ellipse and Rectangle, a failed draw attempt does not count as the shortcut failing. Keep `O` or `R` as the default unless the screenshot clearly shows the wrong tool is active.
- After selecting a tool by shortcut, the next action is usually on the stage or canvas, not on the toolbar again.""",
    "shape-draw-recovery": """Basic shape draw recovery:
- For Ellipse and Rectangle, keep using `O` or `R` even after a failed drag unless the screenshot clearly shows the wrong tool is active.
- If the shape drag did not create anything, first make sure the artboard is active. Click the artboard or a blank area of the stage if needed, then press the shape shortcut again.
- Retry the drag fully inside the visible artboard bounds instead of switching to the toolbar or create menu.
- Only fall back to clicking the toolbar/menu for Ellipse or Rectangle if repeated screenshots clearly show that the shortcut did not activate the correct tool.""",
    "coordinate-sanity": """All coordinates must be viewport percentages from 0 to 100.
- Left panel is usually x 0-14.
- Inspector is usually x 86-100.
- Bottom-left animation list is usually x 0-13 and y 76-100.
- If a coordinate is outside 0-100, it is wrong and should not be used.""",
    "inspector-editing": """When editing Inspector values, use the atomic `type` action.
- Preferred: {"type":"type","x":92.5,"y":18.5,"text":"100","label":"Set width to 100"}
- Do not click the field first, then send separate key events.
- Never use Cmd+A/Ctrl+A to select text in the editor.""",
    "opacity-editing": """Opacity editing:
- Prefer the main layer/group opacity only when the whole object should fade.
- Use fill opacity only when the step explicitly targets the fill appearance instead of the whole object.
- After one opacity edit attempt, if the screenshot does not visibly change, do not keep bouncing between layer opacity and fill opacity fields.
- Reassess whether the correct object is selected, whether a dialog is blocking the Inspector, or whether path-edit mode is still active.
- If a modal or edit-mode control like "Done Editing" is visible, exit that mode before trying opacity again.""",
    "selection-recovery": """Selection recovery:
- Do not assume a hierarchy click worked unless the screenshot clearly changes.
- Clear selection cues include stage handles/bounds, an obvious selected row highlight, or Inspector properties that match the intended object.
- For imported SVGs and generic groups, clicking the visible object on the stage often selects the group more reliably than clicking a subtle hierarchy row.
- If repeated hierarchy clicks do not visibly change selection, switch to clicking the object on the stage/canvas instead of trying the same hierarchy action again.
- Before editing position, size, keyframes, or colors, verify the intended object is actually selected.""",
    "shape-parent-selection": """Procedural shape parent selection:
- When the hierarchy shows a parent procedural shape like `Ellipse` with a child `Path`, select the parent `Ellipse` for normal property edits.
- Do not switch to the child `Path` when the goal is opacity, fill, stroke, scale, position, or keyframe changes on the whole shape.
- Select the child `Path` only for true path editing, node manipulation, or when the task explicitly says to edit the path itself.
- If controls like `Done Editing` or `Convert to Custom Path` appear unexpectedly, you likely selected the child path or entered edit mode. Exit that mode and reselect the parent shape.""",
    "imported-asset-fit": """Imported asset fit and centering:
- Imported SVGs often land much larger than the artboard.
- Before animating an imported SVG or pasted asset, make sure the whole object fits inside the artboard and is visible.
- If it is too large or mostly off-artboard, scale it down first, then center it in the artboard.
- After fitting and centering the imported asset, use `F` if needed so the full artboard and object are clearly framed before keyframing.
- If you later switch to Animate mode and the workspace changes the visible canvas area, use `F` again before editing keyframes.
- Before animating, set the origin correctly for the animation type (see the animation-origin procedure card).
- Do not start keyframing an imported asset until it is visibly placed and sized correctly.""",
    "animation-framing": """Animation framing before keyframes:
- Do not keyframe bounce, position, or scale changes while working partially off-screen or zoomed into one corner.
- Before keyframing a moving object, make sure the full artboard and the object's travel path are clearly visible.
- If the motion area is not fully visible, use `F` first. If `F` frames the wrong selection, select the artboard or animated object and press `F` again.
- After pressing `Tab` into Animate mode, check the framing again. The animation workspace can hide part of the canvas, so click a blank stage/artboard area if needed, then use `F` before keyframing if anything is cropped or off-screen.
- Avoid making keyframe judgments while effectively working blind.""",
    "timeline-keyframe-navigation": """Timeline and keyframe navigation:
- When easing or editing keys, prefer timeline shortcuts before drag-selecting the same region repeatedly.
- Use `U` to reveal keys for the current selection.
- Use Cmd/Ctrl + `,` or `.` to skip to keys on the selected row; without a selected row it skips through all keys.
- Use `,` and `.` to move the playhead, and Alt/Option + `,` or `.` to move selected keys.
- If drag-selecting keyframes does not clearly change the screenshot, stop repeating it and use `U` or skip-to-keys shortcuts instead.
- After changing interpolation/easing once, verify the selection or interpolation UI actually changed before clicking the same easing control again.""",
    "shadow-bounce": """Shadow setup for a bounce animation:
- For a simple ground shadow, use Scale X, Scale Y, and opacity to sell the bounce. Do not use rotation unless the task explicitly asks for an angled or rotating shadow.
- If the step says the shadow should be at minimum scale/opacity, edit Scale X/Y and opacity fields, not Rotation.
- The usual pattern is: small and faint when the ball is high, larger and darker when the ball is low.
- Verify you are editing the shadow ellipse itself before changing scale or opacity.""",
    "color-editing": """To change colors:
- Select the object first.
- Use the Inspector Fill or Stroke section on the right.
- After changing a color, verify the canvas actually changed before advancing.""",
    "mode-switching": """Rive has Design mode and Animate mode.
- Design mode is for creating and styling shapes.
- Animate mode is for timelines, keyframes, and state machines.
- Use Tab when you need to switch modes quickly.
- After switching into Animate mode, re-check the canvas framing. If the timeline/workspace causes the artboard or animated object to be partially hidden, click a blank stage/artboard area if needed, then use `F` before continuing.""",
    "rename-safety": """Rename safety:
- Never rename timelines or state machines. That flow is too flaky and can cause loops.
- If a step asks to rename a timeline or state machine, skip the rename portion and continue with the functional work, such as duration, inputs, transitions, or keyframes.
- Only use rename interactions for safer objects when the name change is truly necessary and the editable text field is visibly active.""",
    "keyframes": """Keyframe workflow:
- Be in Animate mode.
- Select a timeline.
- If the canvas framing changed after switching modes, click blank stage if needed and use `F` before keyframing.
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
    "keyframe-selection": """Keyframe selection:
- Keyframe diamonds on the timeline are very small targets. Do not click them directly unless you are certain of the exact coordinate.
- Preferred method: Use `U` to reveal keys for the current property selection, then use Cmd/Ctrl + `,` or `.` to skip to the previous/next keyframe.
- To select all keyframes on a row, click the row label area in the timeline, then use Cmd/Ctrl + A.
- After selecting keyframes, verify the selection highlight in the timeline before applying easing or other changes.
- If drag-selecting a keyframe region fails or is ambiguous, fall back to keyboard navigation with `U` and skip-to-keys shortcuts.
- Never click blindly at small timeline targets more than once. If the first click does not visibly select a keyframe, switch to keyboard shortcuts.""",
    "animation-origin": """Origin/pivot for imported SVGs:
- SVGs imported via the asset pipeline already have their origin pre-set to BOTTOM-CENTER. This is ideal for bounce, drop, and jump animations — the object's base stays anchored to the ground/shadow contact point.
- For scale or rotation animations that need a center origin, the agent only needs to drag the origin up by half the object's height — much shorter and easier than from the default top-left.
- Do NOT attempt to move the origin using Freeze mode (`Y`). Dragging the origin arrows requires too much precision and is unreliable for the agent.
- If the origin appears wrong after import, ask the user to reposition it manually rather than attempting Freeze mode.""",
    "interpolation-selection": """Selecting interpolation/easing type:
- Interpolation icons in the timeline/Inspector are small and have NO text labels. You cannot identify them by sight alone.
- NEVER click an interpolation icon without first hovering to confirm its identity.
- Required workflow:
  1. First, select the keyframe(s) you want to change interpolation for.
  2. Hover over the interpolation icon you think is correct using a hover action:
     <!--ACTION:{"type":"hover","x":12.3,"y":45.6,"label":"Hover interpolation icon"}-->
  3. Wait for the tooltip text to appear (the system adds a delay automatically).
  4. In the next turn, read the tooltip text from the screenshot to confirm which interpolation type this icon represents (e.g., "Linear", "Cubic", "Hold", etc.).
  5. If it is the correct type, click it. If not, hover the next icon instead.
- Common interpolation types in Rive: Linear, Cubic (smooth ease), Hold (step/instant).
- This hover-then-confirm pattern prevents accidentally setting the wrong easing, which is hard to notice and debug later.""",
    "layout-safety": """Avoiding accidental Layout conversion:
- Rive has Layout containers (Layout, Row, Column) that use flex rules to auto-arrange children. These are for responsive UI design, NOT for animation work.
- NEVER press `Shift+L` during animation tasks — it wraps the selection in a Layout container.
- NEVER click the "Layout selection" button in the Inspector unless the task explicitly requires a responsive layout.
- NEVER right-click and select "Wrap in" > "Layout" on SVGs, shapes, or groups being animated.
- If an object's name unexpectedly changes to "Column", "Row", or "Layout", or if children become distorted/rearranged, this means the object was accidentally wrapped in a Layout container. Immediately undo with Cmd/Ctrl+Z.
- After undoing, verify the object's original name and visual appearance are restored before continuing.""",
    "closing-keyframe": """Creating a closing/looping keyframe:
- To close a loop (last keyframe matches the first), do NOT copy-paste the first keyframe. Paste is unreliable because it depends on playhead position, selection state, and panel focus.
- Instead, move the playhead to the final frame, then manually set each property value in the Inspector to match the first keyframe's values.
- You already know what the initial values are because you set them. Type them directly into the Inspector fields at the final frame position.
- This is the same workflow used for every other keyframe and is always reliable.""",
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

    # In agentic mode, cap doc hits to reduce token bloat — the agent is
    # watching the live screenshot and rarely needs more than one doc reference.
    if effective_mode == "agentic" and len(doc_hits) > 1:
        doc_hits = doc_hits[:1]

    # Skip doc visuals entirely in agentic mode to avoid sending large images
    # every turn when common terms like "artboard" or "inspector" appear.
    if effective_mode == "agentic":
        doc_visuals: list[dict[str, Any]] = []
    else:
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
    queries = _build_doc_queries(user_message, state)
    logger.debug("[doc-lookup] queries=%s", queries)

    merged: dict[str, dict[str, Any]] = {}
    for priority, query in enumerate(queries):
        cats = _preferred_categories(query)
        hits = search_rive_docs(
            query=query,
            limit=2,
            preferred_categories=cats,
        )
        logger.debug(
            "[doc-lookup] q=%d %r  cats=%s  hits=%s",
            priority,
            query,
            cats,
            [(h.get("path", "?"), round(float(h.get("score", 0)), 1)) for h in hits],
        )
        for hit in hits:
            adjusted_hit = dict(hit)
            adjusted_hit["score"] = float(hit.get("score", 0)) - (priority * 1.5)
            existing = merged.get(adjusted_hit["path"])
            if existing is None or adjusted_hit["score"] > float(existing.get("score", 0)):
                merged[adjusted_hit["path"]] = adjusted_hit

    ranked = sorted(merged.values(), key=lambda item: float(item.get("score", 0)), reverse=True)
    result = ranked[:3]
    logger.debug(
        "[doc-lookup] final=%s",
        [(r.get("path", "?"), round(float(r.get("score", 0)), 1)) for r in result],
    )
    return result


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
                "zoomed in",
                "zoomed into",
                "off-screen",
                "off screen",
                "out of view",
                "lost view",
                "canvas is stuck",
                "top right",
                "corner",
            ),
        ),
        ("shape-creation", ("shape", "shapes", "circle", "ellipse", "rectangle", "procedural")),
        ("shape-draw-recovery", ("draw shadow ellipse", "draw ellipse", "draw rectangle", "failed drag", "did not create", "didn't create", "shape did not appear", "artboard is active", "select ellipse tool", "select rectangle tool")),
        ("inspector-editing", ("width", "height", "opacity", "rotation", "inspector", "x ", " y", "position", "type")),
        ("opacity-editing", ("opacity", "fill opacity", "layer opacity", "done editing", "convert to custom path", "path edit")),
        ("shape-parent-selection", ("path", "child path", "done editing", "convert to custom path", "custom path", "path edit", "node editing", "vector points")),
        ("selection-recovery", ("select", "selected", "selection", "group", "hierarchy", "svg", "imported asset", "imported svg")),
        ("imported-asset-fit", ("svg", "import", "imported", "paste", "pasted", "asset", "off artboard", "too large", "too big", "not visible", "outside artboard", "center it", "scale down")),
        ("animation-framing", ("bounce", "bouncing", "keyframe", "keyframes", "position", "travel path", "easing", "animate", "animation")),
        ("timeline-keyframe-navigation", ("easing", "interpolation", "keyframe", "keyframes", "timeline", "reveal keys", "skip to keys", "move playhead", "selected keys")),
        ("shadow-bounce", ("shadow", "shadow ellipse", "minimum scale", "minimum opacity", "scale x", "scale y", "bounce shadow")),
        ("color-editing", ("fill", "stroke", "color", "hex", "swatch")),
        ("state-machine-transitions", ("transition", "connector", "any state", "entry", "exit")),
        ("state-machine-inputs", ("input", "condition", "boolean", "trigger", "number")),
        ("keyframes", ("keyframe", "playhead", "timeline", "animation")),
        ("mode-switching", ("animate mode", "design mode", "switch mode", "toggle mode", "tab")),
        ("rename-safety", ("rename", "renaming", "doubleclick", "editable text", "timeline 1", "state machine")),
        ("keyframe-selection", ("keyframe", "keyframes", "select keyframe", "select keyframes", "select key", "select keys", "easing", "interpolation", "diamond", "drag-select")),
        ("closing-keyframe", ("loop", "looping", "closing keyframe", "final keyframe", "last keyframe", "end keyframe", "match first", "copy keyframe", "paste keyframe", "same as first", "return to", "back to original", "reset position")),
        ("layout-safety", ("layout", "column", "row", "wrap in", "distorted", "rearranged", "shift+l")),
        ("interpolation-selection", ("interpolation", "easing", "cubic", "linear", "hold", "ease in", "ease out", "smooth")),
        ("animation-origin", ("origin", "pivot", "anchor", "bounce", "drop", "jump", "swing", "pendulum", "spin", "import", "imported", "svg", "animate", "animation")),
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
            "gradient",
            "converter",
            "blend mode",
            "mesh",
            "joystick",
            "constraints",
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
