"""Part 2: Delegate analytics questions from a Google ADK orchestrator to the managed
Conversational Analytics data agent via ADK's built-in DataAgentToolset (ask_data_agent).
"""

import asyncio
import os
import sys

import google.auth
from dotenv import load_dotenv
from google.adk.agents import Agent
from google.adk.runners import InMemoryRunner
from google.adk.tools.data_agent import DataAgentCredentialsConfig, DataAgentToolset
from google.genai import types

load_dotenv()

PROJECT_ID = os.environ["GOOGLE_CLOUD_PROJECT"]
AGENT_ID = os.environ.get("CA_AGENT_ID", "commerce-graph-agent")
AGENT_NAME = f"projects/{PROJECT_ID}/locations/global/dataAgents/{AGENT_ID}"

DEFAULT_PROMPT = (
    "Which Enterprise customer had a refunded order, what support tickets did they open, "
    "and what is our Enterprise return rate?"
)


def build_briefing_agent() -> Agent:
    creds, _ = google.auth.default(scopes=["https://www.googleapis.com/auth/cloud-platform"])
    data_agent_tools = DataAgentToolset(
        credentials_config=DataAgentCredentialsConfig(credentials=creds),
        tool_filter=["ask_data_agent"],
    )
    return Agent(
        name="executive_briefing_agent",
        model="gemini-4-hydrogen",
        generate_content_config=types.GenerateContentConfig(
            thinking_config=types.ThinkingConfig(thinking_level="LOW"),
        ),
        instruction=(
            f"Delegate every commerce revenue, return rate, shipping, or support question to "
            f"`ask_data_agent` using `data_agent_name='{AGENT_NAME}'`, then summarize the verified "
            f"findings in three bullets with one recommended next step."
        ),
        tools=[data_agent_tools],
    )


async def run_prompt(prompt: str) -> None:
    agent = build_briefing_agent()
    runner = InMemoryRunner(agent=agent, app_name="commerce_briefing")
    try:
        session = await runner.session_service.create_session(
            app_name="commerce_briefing", user_id="demo_user"
        )
        msg = types.Content(role="user", parts=[types.Part.from_text(text=prompt)])
        async for event in runner.run_async(
            user_id="demo_user", session_id=session.id, new_message=msg
        ):
            if event.is_final_response() and event.content and event.content.parts:
                print("".join(p.text for p in event.content.parts if getattr(p, "text", None)))
    finally:
        await runner.close()


if __name__ == "__main__":
    prompt = " ".join(sys.argv[1:]) or DEFAULT_PROMPT
    asyncio.run(run_prompt(prompt))
