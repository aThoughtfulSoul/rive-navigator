"""
Task management tool for guided step-by-step workflows.
Handles task creation, step tracking, progress verification, and navigation.
"""

import json
import re
from google.adk.tools import ToolContext


BLOCKED_RENAME_TARGETS = ("timeline", "state machine", "state-machine", "statemachine")
RENAME_TERMS = ("rename", "renaming", "renamed")
IMPORTED_ASSET_TERMS = ("svg", "import", "imported", "paste", "pasted", "asset")
FIT_CENTER_TERMS = ("scale down", "resize", "fit inside", "fit within", "center", "centre")
ANIMATION_STEP_TERMS = (
    "animate",
    "animation",
    "keyframe",
    "playhead",
    "timeline",
    "bounce",
    "move",
    "position",
    "rotation",
    "opacity",
)
IMPORTED_ASSET_FIT_STEP = (
    "Scale the imported SVG down so it fits fully inside the artboard, center it, and press F so the full artboard and asset are clearly framed before animating. After switching to Animate mode, press F again if the workspace changed the visible canvas area."
)


def start_task(
    task_name: str,
    steps: list[str],
    tool_context: ToolContext = None,
) -> dict:
    """
    Starts a new guided task with a structured step plan.
    Call this when the user wants to build something specific in Rive
    and would benefit from step-by-step guidance.

    Args:
        task_name (str): Short name for the task.
            Examples: "Animated Toggle Switch", "Loading Spinner",
            "Character Walk Cycle", "Interactive Button".
        steps (list[str]): Ordered list of steps to complete the task.
            Each step should be a single, discrete action.
            Example: ["Create a 300x200 artboard", "Draw the track shape
            with Rectangle tool", "Set corner radius to 50",
            "Add a circle for the knob", "Create a boolean input called isOn",
            "Set up Entry state and two animation states",
            "Add transitions with the isOn condition",
            "Add easing to keyframes"]

    Returns:
        dict: Task state with step count and current step info.
    """
    if not tool_context:
        return {"status": "error", "message": "No tool context available"}

    if not steps or len(steps) == 0:
        return {"status": "error", "message": "Task must have at least one step"}

    sanitized_steps, skipped_steps = _sanitize_task_steps(task_name, steps)
    if not sanitized_steps:
        return {
            "status": "error",
            "message": "Task only contained unsupported timeline/state-machine rename steps.",
            "skipped_steps": skipped_steps,
        }

    # Store task state
    tool_context.state["task:active"] = True
    tool_context.state["task:name"] = task_name
    tool_context.state["task:steps"] = json.dumps(sanitized_steps)
    tool_context.state["task:current_step"] = 1
    tool_context.state["task:total_steps"] = len(sanitized_steps)
    tool_context.state["task:current_step_name"] = sanitized_steps[0]
    tool_context.state["task:completed_steps"] = json.dumps([])
    tool_context.state["task:started_at"] = str(tool_context.state.get("step_count", 0))
    tool_context.state["task:last_direction"] = "start"
    tool_context.state["task:last_feedback"] = ""
    tool_context.state["task:last_verification"] = "not_started"
    tool_context.state["task:last_verification_feedback"] = ""
    tool_context.state["task:last_completed_step"] = ""
    tool_context.state["task:skipped_unsupported_steps"] = json.dumps(skipped_steps)

    message = (
        f"Task '{task_name}' started with {len(sanitized_steps)} steps. Guide the user through step 1."
    )
    if skipped_steps:
        message += " Unsupported timeline/state-machine rename steps were removed automatically."

    return {
        "status": "success",
        "task_name": task_name,
        "total_steps": len(sanitized_steps),
        "current_step": 1,
        "current_step_name": sanitized_steps[0],
        "all_steps": sanitized_steps,
        "skipped_steps": skipped_steps,
        "message": message,
    }


def advance_task(
    direction: str = "next",
    tool_context: ToolContext = None,
) -> dict:
    """
    Moves to the next or previous step in the current task, or ends the task.

    Args:
        direction (str): Where to move. Options:
            - "next": Advance to the next step
            - "back": Go back to the previous step
            - "skip": Skip current step and move to next
            - "end": End the task and return to ask mode

    Returns:
        dict: Updated task state with new current step info.
    """
    if not tool_context:
        return {"status": "error", "message": "No tool context available"}

    if not tool_context.state.get("task:active"):
        return {"status": "error", "message": "No active task. Start one with start_task."}

    steps = json.loads(tool_context.state.get("task:steps", "[]"))
    current = tool_context.state.get("task:current_step", 1)
    total = tool_context.state.get("task:total_steps", 0)
    completed = json.loads(tool_context.state.get("task:completed_steps", "[]"))

    if direction == "end":
        # End the task
        tool_context.state["task:active"] = False
        tool_context.state["task:last_direction"] = "end"
        return {
            "status": "task_ended",
            "task_name": tool_context.state.get("task:name", ""),
            "steps_completed": len(completed),
            "total_steps": total,
            "message": "Task ended. Back to ask mode — feel free to ask anything!",
        }

    if direction == "back":
        if current <= 1:
            return {
                "status": "at_beginning",
                "current_step": 1,
                "current_step_name": steps[0] if steps else "",
                "message": "Already at the first step.",
            }
        current -= 1
        tool_context.state["task:last_direction"] = "back"

    elif direction in ("next", "skip"):
        # Mark current step as completed
        if direction == "next" and current <= len(steps):
            step_name = steps[current - 1] if current <= len(steps) else ""
            if step_name not in completed:
                completed.append(step_name)
                tool_context.state["task:completed_steps"] = json.dumps(completed)
            tool_context.state["task:last_completed_step"] = step_name

        current += 1
        tool_context.state["task:last_direction"] = direction

        # Check if task is complete
        if current > total:
            tool_context.state["task:active"] = False
            return {
                "status": "task_complete",
                "task_name": tool_context.state.get("task:name", ""),
                "steps_completed": len(completed),
                "total_steps": total,
                "message": f"Task '{tool_context.state.get('task:name', '')}' is complete! "
                           f"All {total} steps done. Great work! Back to ask mode.",
            }

    # Update state
    tool_context.state["task:current_step"] = current
    current_step_name = steps[current - 1] if current <= len(steps) else ""
    tool_context.state["task:current_step_name"] = current_step_name

    return {
        "status": "success",
        "current_step": current,
        "total_steps": total,
        "current_step_name": current_step_name,
        "steps_completed": len(completed),
        "remaining_steps": [steps[i] for i in range(current - 1, len(steps))],
        "message": f"Now on step {current}/{total}: {current_step_name}",
    }


def verify_step(
    observation: str,
    step_complete: bool,
    feedback: str = "",
    tool_context: ToolContext = None,
) -> dict:
    """
    Verifies whether the current task step has been completed based on
    the screenshot observation. Call this after examining a new screenshot
    when in task mode and the user indicates they've finished a step.

    Args:
        observation (str): What the agent sees in the current screenshot
            relevant to the current step. Be specific about what's present
            or missing.
        step_complete (bool): Whether the step appears to be successfully
            completed based on the screenshot.
        feedback (str): Specific feedback for the user. If complete,
            acknowledge what they did well. If incomplete, explain what
            still needs to be done.

    Returns:
        dict: Verification result with guidance on how to proceed.
    """
    if not tool_context:
        return {"status": "error", "message": "No tool context available"}

    if not tool_context.state.get("task:active"):
        return {"status": "error", "message": "No active task to verify."}

    current = tool_context.state.get("task:current_step", 1)
    total = tool_context.state.get("task:total_steps", 0)
    current_step_name = tool_context.state.get("task:current_step_name", "")

    # Update observation
    tool_context.state["last_observation"] = observation
    step_count = tool_context.state.get("step_count", 0) + 1
    tool_context.state["step_count"] = step_count
    tool_context.state["task:last_feedback"] = feedback
    tool_context.state["task:last_verification_feedback"] = feedback

    if step_complete:
        tool_context.state["task:last_verification"] = "verified"
        return {
            "status": "step_verified",
            "step": current,
            "step_name": current_step_name,
            "total_steps": total,
            "observation": observation,
            "feedback": feedback,
            "message": f"Step {current}/{total} verified! Call advance_task with 'next' to proceed.",
            "next_action": "Call advance_task(direction='next') then give instructions for the next step.",
        }
    else:
        tool_context.state["task:last_verification"] = "incomplete"
        return {
            "status": "step_incomplete",
            "step": current,
            "step_name": current_step_name,
            "total_steps": total,
            "observation": observation,
            "feedback": feedback,
            "message": f"Step {current}/{total} needs adjustment. Guide the user on what to fix.",
            "next_action": "Provide specific guidance on what the user needs to do to complete this step.",
        }


def _sanitize_task_steps(task_name: str, steps: list[str]) -> tuple[list[str], list[str]]:
    sanitized: list[str] = []
    skipped: list[str] = []

    for step in steps:
        cleaned = _rewrite_or_drop_blocked_step(step)
        if cleaned:
            sanitized.append(cleaned)
        else:
            skipped.append(step)

    sanitized = _inject_imported_asset_fit_step(task_name, sanitized)
    return sanitized, skipped


def _inject_imported_asset_fit_step(task_name: str, steps: list[str]) -> list[str]:
    if not steps:
        return steps

    combined = " ".join([task_name, *steps]).lower()
    if not any(term in combined for term in IMPORTED_ASSET_TERMS):
        return steps

    if any(any(term in step.lower() for term in FIT_CENTER_TERMS) for step in steps):
        return steps

    insert_index = None
    for index, step in enumerate(steps):
        lowered = step.lower()
        if any(term in lowered for term in IMPORTED_ASSET_TERMS):
            insert_index = index + 1
            break

    if insert_index is None:
        for index, step in enumerate(steps):
            lowered = step.lower()
            if any(term in lowered for term in ANIMATION_STEP_TERMS):
                insert_index = index
                break

    if insert_index is None:
        insert_index = 0

    return steps[:insert_index] + [IMPORTED_ASSET_FIT_STEP] + steps[insert_index:]


def _rewrite_or_drop_blocked_step(step: str) -> str | None:
    normalized = " ".join(str(step).split()).strip()
    if not normalized:
        return None
    if not _is_blocked_rename_step(normalized):
        return normalized

    clauses = re.split(r"(?i)\s+(?:and|then)\s+|,\s*", normalized)
    kept_clauses = [
        clause.strip(" .")
        for clause in clauses
        if clause.strip() and not _is_blocked_rename_step(clause)
    ]
    if not kept_clauses:
        return None

    rewritten = " and ".join(kept_clauses).strip()
    if rewritten and rewritten[0].islower():
        rewritten = rewritten[0].upper() + rewritten[1:]
    if rewritten and rewritten[-1] not in ".!?":
        rewritten += "."
    return rewritten


def _is_blocked_rename_step(step: str) -> bool:
    lowered = step.lower()
    has_target = any(target in lowered for target in BLOCKED_RENAME_TARGETS)
    has_rename_intent = any(term in lowered for term in RENAME_TERMS)
    return has_target and has_rename_intent
