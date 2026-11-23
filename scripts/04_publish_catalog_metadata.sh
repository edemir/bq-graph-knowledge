#!/usr/bin/env bash
set -euo pipefail

PROJ="${GOOGLE_CLOUD_PROJECT:?Set GOOGLE_CLOUD_PROJECT first}"
LOC="${DATASCAN_LOCATION:-us-central1}"
DATASET="${BQ_DATASET:-demo}"

gcloud services enable \
  bigquery.googleapis.com \
  dataplex.googleapis.com \
  cloudaicompanion.googleapis.com \
  geminidataanalytics.googleapis.com \
  aiplatform.googleapis.com \
  --project="$PROJ"

for tbl in customers orders order_items support_tickets; do
  slug="${tbl//_/-}"

  if ! gcloud dataplex datascans describe "prof-${slug}" --project="$PROJ" --location="$LOC" >/dev/null 2>&1; then
    gcloud dataplex datascans create data-profile "prof-${slug}" \
      --project="$PROJ" --location="$LOC" \
      --data-source-resource="//bigquery.googleapis.com/projects/${PROJ}/datasets/${DATASET}/tables/${tbl}" \
      --sampling-percent=100 --enable-catalog-publishing
  fi
  gcloud dataplex datascans run "prof-${slug}" --project="$PROJ" --location="$LOC"

  if ! gcloud dataplex datascans describe "ins-${slug}" --project="$PROJ" --location="$LOC" >/dev/null 2>&1; then
    gcloud dataplex datascans create data-documentation "ins-${slug}" \
      --project="$PROJ" --location="$LOC" \
      --data-source-resource="//bigquery.googleapis.com/projects/${PROJ}/datasets/${DATASET}/tables/${tbl}" \
      --enable-catalog-publishing
  fi
  gcloud dataplex datascans run "ins-${slug}" --project="$PROJ" --location="$LOC"
done

if ! gcloud dataplex datascans describe "ins-ds-${DATASET}" --project="$PROJ" --location="$LOC" >/dev/null 2>&1; then
  gcloud dataplex datascans create data-documentation "ins-ds-${DATASET}" \
    --project="$PROJ" --location="$LOC" \
    --data-source-resource="//bigquery.googleapis.com/projects/${PROJ}/datasets/${DATASET}" \
    --enable-catalog-publishing
fi
gcloud dataplex datascans run "ins-ds-${DATASET}" --project="$PROJ" --location="$LOC"
