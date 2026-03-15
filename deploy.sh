#!/bin/bash
# Automated deployment script for Rive Navigator → Google Cloud Run
# Usage: ./deploy.sh

set -e

PROJECT_ID="${GCP_PROJECT_ID:-}"
REGION="${GCP_REGION:-us-central1}"
SERVICE_NAME="rive-navigator"

if [ -z "$PROJECT_ID" ]; then
  echo "Error: GCP_PROJECT_ID environment variable is required."
  echo "Usage: GCP_PROJECT_ID=your-project-id ./deploy.sh"
  exit 1
fi

if [ -z "$GOOGLE_API_KEY" ]; then
  echo "Error: GOOGLE_API_KEY environment variable is required."
  echo "Usage: GOOGLE_API_KEY=your-key GCP_PROJECT_ID=your-project-id ./deploy.sh"
  exit 1
fi

echo "Deploying ${SERVICE_NAME} to Cloud Run..."
echo "  Project:  ${PROJECT_ID}"
echo "  Region:   ${REGION}"

gcloud config set project "$PROJECT_ID"

gcloud run deploy "$SERVICE_NAME" \
  --source . \
  --region "$REGION" \
  --allow-unauthenticated \
  --set-env-vars "GOOGLE_API_KEY=${GOOGLE_API_KEY}"

echo ""
echo "Deployment complete! Update the extension's Backend API URL in chrome://extensions → Rive UI Navigator → Details → Extension options."
