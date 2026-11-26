#!/usr/bin/env bash
# Idempotent deployment script for Agent Runtime on Gemini Enterprise Agent Platform.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
AGENT_DIR="${SCRIPT_DIR}/agent_under_test"

PROJECT_ID="${GOOGLE_CLOUD_PROJECT:?Set GOOGLE_CLOUD_PROJECT}"
REGION="${AGENT_ENGINE_REGION:-us-central1}"
BQ_LOCATION="${BQ_LOCATION:-us}"
BQ_DATASET="${BQ_DATASET:-commerce_bench}"
MODEL_ID="${MODEL_ID:-gemini-3.5-flash-lite}"
AGENT_ENGINE_ID="${AGENT_ENGINE_ID:-}"
SA_NAME="${AGENT_SA_NAME:-bq-graph-agent-sa}"
SA_EMAIL="${SA_NAME}@${PROJECT_ID}.iam.gserviceaccount.com"

ADK_BIN="${ADK_BIN:-adk}"

echo "==> Enabling required APIs on ${PROJECT_ID}..."
gcloud services enable \
  aiplatform.googleapis.com \
  bigquery.googleapis.com \
  dataplex.googleapis.com \
  telemetry.googleapis.com \
  --project="${PROJECT_ID}" --quiet

echo "==> Ensuring runtime service account ${SA_EMAIL}..."
if ! gcloud iam service-accounts describe "${SA_EMAIL}" --project="${PROJECT_ID}" >/dev/null 2>&1; then
  gcloud iam service-accounts create "${SA_NAME}" \
    --display-name="BigQuery Semantic Graph ADK Agent Runtime SA" \
    --project="${PROJECT_ID}" --quiet
  sleep 5
fi

ROLES=(
  "roles/aiplatform.user"
  "roles/bigquery.jobUser"
  "roles/bigquery.dataViewer"
  "roles/dataplex.catalogViewer"
  "roles/dataplex.dataScanDataViewer"
  "roles/telemetry.writer"
  "roles/logging.logWriter"
  "roles/serviceusage.serviceUsageConsumer"
)
for role in "${ROLES[@]}"; do
  gcloud projects add-iam-policy-binding "${PROJECT_ID}" \
    --member="serviceAccount:${SA_EMAIL}" \
    --role="${role}" \
    --condition=None \
    --quiet >/dev/null
done

ENV_FILE="$(mktemp /tmp/agent_engine_env.XXXXXX)"
cleanup() {
  rm -f "${ENV_FILE}"
}
trap cleanup EXIT

cat > "${ENV_FILE}" <<EOF
BQ_LOCATION=${BQ_LOCATION}
BQ_DATASET=${BQ_DATASET}
MODEL_ID=${MODEL_ID}
OTEL_INSTRUMENTATION_GENAI_CAPTURE_MESSAGE_CONTENT=SPAN_AND_EVENT
ADK_CAPTURE_MESSAGE_CONTENT_IN_SPANS=true
EOF

DEPLOY_ARGS=(
  deploy agent_engine
  --project="${PROJECT_ID}"
  --region="${REGION}"
  --display_name="${DISPLAY_NAME:-BigQuery Semantic Graph Analyst}"
  --service_account="${SA_EMAIL}"
  --env_file="${ENV_FILE}"
  --otel_to_cloud
)
if [[ -n "${AGENT_ENGINE_ID}" ]]; then
  DEPLOY_ARGS+=(--agent_engine_id="${AGENT_ENGINE_ID}")
fi
DEPLOY_ARGS+=("${AGENT_DIR}")

echo "==> Deploying ${AGENT_DIR} to Agent Runtime (${PROJECT_ID} / ${REGION})..."
(cd /tmp && "${ADK_BIN}" "${DEPLOY_ARGS[@]}")
