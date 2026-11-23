"""Part 2: Query the managed Conversational Analytics data agent via DataChatServiceClient.chat."""

import os
import sys

from dotenv import load_dotenv
from google.cloud import geminidataanalytics_v1 as gda

load_dotenv()

PROJECT_ID = os.environ["GOOGLE_CLOUD_PROJECT"]
AGENT_ID = os.environ.get("CA_AGENT_ID", "commerce-graph-agent")
AGENT_NAME = f"projects/{PROJECT_ID}/locations/global/dataAgents/{AGENT_ID}"

DEFAULT_QUESTIONS = [
    "For Enterprise customers, how much did we sell in Accessories and what was the total shipping on those orders?",
    "Which Enterprise customer had a refunded order, and what support tickets did they open?",
]


def ask(chat_client: gda.DataChatServiceClient, question: str) -> None:
    print(f"\n=== Question ===\n{question}\n")
    req = gda.ChatRequest(
        parent=f"projects/{PROJECT_ID}/locations/global",
        messages=[gda.Message(user_message=gda.UserMessage(text=question))],
        data_agent_context=gda.DataAgentContext(data_agent=AGENT_NAME),
    )
    for msg in chat_client.chat(request=req):
        sm = msg.system_message
        if not sm:
            continue
        if sm.data and sm.data.generated_sql:
            print("SQL:\n" + sm.data.generated_sql.strip() + "\n")
        if sm.text and sm.text.text_type == gda.TextMessage.TextType.FINAL_RESPONSE:
            print("Answer:\n" + "".join(sm.text.parts).strip())


def main() -> None:
    questions = sys.argv[1:] or DEFAULT_QUESTIONS
    chat_client = gda.DataChatServiceClient()
    for q in questions:
        ask(chat_client, q)


if __name__ == "__main__":
    main()
