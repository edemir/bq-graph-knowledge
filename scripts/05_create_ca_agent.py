"""Part 2: Create (or update) a persistent BigQuery Conversational Analytics data agent
grounded solely on demo.CommerceGraph via BigQueryPropertyGraphReference.
"""

import os

from dotenv import load_dotenv
from google.api_core import exceptions
from google.cloud import geminidataanalytics_v1 as gda
from google.protobuf import field_mask_pb2

load_dotenv()

PROJECT_ID = os.environ["GOOGLE_CLOUD_PROJECT"]
DATASET_ID = os.environ.get("BQ_DATASET", "demo")
GRAPH_ID = os.environ.get("BQ_GRAPH_NAME", "CommerceGraph")
AGENT_ID = os.environ.get("CA_AGENT_ID", "commerce-graph-agent")

SYSTEM_INSTRUCTION = """You are a commerce analytics assistant grounded only on the attached BigQuery property graph.
Answer using the graph's defined measures, dimensions, and relationships.
Before filtering on any string dimension, run a SELECT DISTINCT query on that column first to verify exact literal values (never assume singular/plural forms or casing).
Never COALESCE a ratio to 0 when its denominator is 0 or absent (keep undefined ratios as NULL).
Return exact numbers and concise answers.
If a question asks for a metric or attribute that does not exist in the graph, state clearly what is missing and do not approximate or fabricate it; answer only the grounded parts."""


def main() -> None:
    client = gda.DataAgentServiceClient()
    parent = f"projects/{PROJECT_ID}/locations/global"
    agent_name = f"{parent}/dataAgents/{AGENT_ID}"

    graph_ref = gda.BigQueryPropertyGraphReference(
        project_id=PROJECT_ID,
        dataset_id=DATASET_ID,
        property_graph_id=GRAPH_ID,
    )

    published_context = gda.Context(
        system_instruction=SYSTEM_INSTRUCTION,
        datasource_references=gda.DatasourceReferences(
            bq=gda.BigQueryTableReferences(
                property_graph_references=[graph_ref],
            )
        ),
    )

    agent = gda.DataAgent(
        name=agent_name,
        display_name="Commerce Graph Agent",
        description="Managed Conversational Analytics data agent grounded on CommerceGraph.",
        data_analytics_agent=gda.DataAnalyticsAgent(
            published_context=published_context,
        ),
    )

    try:
        resp = client.create_data_agent_sync(
            request=gda.CreateDataAgentRequest(
                parent=parent,
                data_agent_id=AGENT_ID,
                data_agent=agent,
            )
        )
        print("Created:", resp.name)
    except exceptions.AlreadyExists:
        resp = client.update_data_agent_sync(
            request=gda.UpdateDataAgentRequest(
                data_agent=agent,
                update_mask=field_mask_pb2.FieldMask(
                    paths=[
                        "display_name",
                        "description",
                        "data_analytics_agent.published_context",
                    ]
                ),
            )
        )
        print("Updated existing agent:", resp.name)


if __name__ == "__main__":
    main()
