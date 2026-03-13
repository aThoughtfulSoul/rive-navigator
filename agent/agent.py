"""
Rive UI Navigator - ADK Agent
Helps designers and developers build animations and UI with the Rive editor.
"""

from google.adk.agents import Agent

from .prompting import BASE_AGENT_POLICY
from .tools.rive_docs_lookup import lookup_rive_docs
from .tools.screenshot_analyzer import analyze_screenshot
from .tools.task_manager import advance_task, start_task, verify_step

DEFAULT_MODEL = "gemini-3-flash-preview"
SUPPORTED_MODELS = {
    DEFAULT_MODEL,
    "gemini-3.1-pro-preview",
}
AGENT_TOOLS = [analyze_screenshot, lookup_rive_docs, start_task, advance_task, verify_step]


def build_agent(model_name: str = DEFAULT_MODEL) -> Agent:
    return Agent(
        name="rive_navigator",
        model=model_name,
        description="Analyzes Rive editor screenshots and safely guides or performs editor actions.",
        instruction=BASE_AGENT_POLICY,
        tools=AGENT_TOOLS,
    )


root_agent = build_agent(DEFAULT_MODEL)
