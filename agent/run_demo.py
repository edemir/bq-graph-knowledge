#!/usr/bin/env python3
"""Runs the 9-question multi-turn walkthrough against root_agent."""

import asyncio
import sys
from pathlib import Path

from google.adk.runners import InMemoryRunner
from google.genai import types

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from agent.agent import bigquery_mcp, knowledge_catalog_mcp, root_agent

DEMO_QUESTIONS = [
    ("Q1", "For Enterprise customers, how much did we sell in Accessories and what was the total shipping on those orders?"),
    ("Q2", "What is our return rate by customer segment?"),
    ("Q3", "How many paying customers do we have in each segment, and how many in each product category within Enterprise?"),
    ("Q4", "By customer segment, show me GMV alongside total support tickets and total resolution hours."),
    ("Q5", "For Enterprise, what is the average support resolution hours per order?"),
    ("Q6", "Which Enterprise customer had a refunded order, and what support tickets did they open?"),
    ("Q7", "What is our net profit margin after warehouse rent and shipping costs by segment?"),
    ("Q8", "For Enterprise orders over $500, what was the total gross revenue and total shipping?"),
    ("Q9", "For every customer segment, compare total GMV, return rate, paying customers, Hardware sales, shipping on orders that included Accessories, and support resolution hours per dollar of GMV, without dropping customers who have not ordered yet."),
]


async def main() -> None:
    runner = InMemoryRunner(agent=root_agent, app_name="commerce_graph_demo")
    session = await runner.session_service.create_session(
        app_name="commerce_graph_demo", user_id="analyst"
    )
    try:
        for qid, question in DEMO_QUESTIONS:
            print(f"\n{'=' * 72}\n{qid}: {question}")
            final_text = ""
            async for event in runner.run_async(
                user_id="analyst",
                session_id=session.id,
                new_message=types.Content(
                    role="user", parts=[types.Part.from_text(text=question)]
                ),
            ):
                if event.content and event.content.parts:
                    for part in event.content.parts:
                        if part.function_call:
                            fc = part.function_call
                            args = dict(fc.args) if fc.args else {}
                            if fc.name == "execute_sql_readonly":
                                print(f"  [MCP] {fc.name}:\n{args.get('query', '')}")
                            else:
                                print(f"  [MCP] {fc.name}({list(args.keys())})")
                        elif part.text and event.is_final_response():
                            final_text += part.text
            print(f"\n{final_text.strip()}")
    finally:
        await knowledge_catalog_mcp.close()
        await bigquery_mcp.close()


if __name__ == "__main__":
    asyncio.run(main())
