"""
Guidance tool for suggesting next steps based on current editor state.
"""

from google.adk.tools import ToolContext


def suggest_next_steps(
    current_task: str,
    completed_steps: str = "",
    user_goal: str = "",
    tool_context: ToolContext = None,
) -> dict:
    """
    Generates contextual next-step suggestions based on what the user is doing
    in the Rive editor. Call this when the user seems stuck or asks "what next?"

    Args:
        current_task (str): What the user is currently working on.
            Examples: "creating a button animation", "setting up a state machine",
            "rigging a character with bones".
        completed_steps (str): Steps the user has already completed in this task.
            Helps avoid repeating guidance.
        user_goal (str): The end goal the user is trying to achieve, if known.
            Examples: "animated loading spinner", "interactive toggle switch",
            "character walk cycle".

    Returns:
        dict: Structured next steps with descriptions and tips.
    """
    context = {
        "current_task": current_task,
        "completed_steps": completed_steps,
        "user_goal": user_goal,
    }

    # Pull state from session if available
    if tool_context:
        context["last_observation"] = tool_context.state.get("last_observation", "")
        context["active_panels"] = tool_context.state.get("active_panels", "")
        context["selected_tool"] = tool_context.state.get("selected_tool", "")
        context["step_count"] = tool_context.state.get("step_count", 0)

        # Track that we gave guidance
        tool_context.state["last_guidance_task"] = current_task

    return {
        "status": "success",
        "context": context,
        "note": "Use this context along with Rive documentation to provide specific, actionable next steps.",
    }
