"""
Screenshot analysis tool for the Rive Navigator agent.
Processes screenshots and DOM context from the Chrome extension.
"""

from google.adk.tools import ToolContext


def analyze_screenshot(
    observation: str,
    active_panels: str = "",
    selected_tool: str = "",
    hierarchy_state: str = "",
    tool_context: ToolContext = None,
) -> dict:
    """
    Records and processes the agent's observation of a Rive editor screenshot.
    Called after the agent examines a screenshot sent by the user.

    Args:
        observation (str): Detailed description of what the agent sees in the
            screenshot — UI state, artboard contents, selected objects, etc.
        active_panels (str): Comma-separated list of currently visible panels
            from DOM context (e.g., "Hierarchy, Inspector, Timeline").
        selected_tool (str): The currently active tool from DOM context
            (e.g., "Select", "Pen", "Rectangle").
        hierarchy_state (str): Summary of the hierarchy panel contents from
            DOM context (e.g., "Artboard1 > Group1 > Rectangle1 [selected]").

    Returns:
        dict: Confirmation with step number and recorded context.
    """
    if tool_context:
        # Track step progression
        step = tool_context.state.get("step_count", 0) + 1
        tool_context.state["step_count"] = step

        # Store latest observation for context in future turns
        tool_context.state["last_observation"] = observation

        # Store DOM context if provided
        if active_panels:
            tool_context.state["active_panels"] = active_panels
        if selected_tool:
            tool_context.state["selected_tool"] = selected_tool
        if hierarchy_state:
            tool_context.state["hierarchy_state"] = hierarchy_state

        return {
            "status": "success",
            "step": step,
            "observation": observation,
            "dom_context": {
                "panels": active_panels,
                "tool": selected_tool,
                "hierarchy": hierarchy_state,
            },
        }

    return {
        "status": "success",
        "observation": observation,
    }
