#!/bin/bash
# Deploy Instagram MCP server to Cloud Run
# Usage: source .env && bash deploy.sh

PROJECT_ID="${PROJECT_ID:?Set PROJECT_ID}"
REGION="us-central1"
SERVICE_NAME="instagram-mcp"
IMAGE="$REGION-docker.pkg.dev/$PROJECT_ID/tangibledata-bot/$SERVICE_NAME"

set -e

echo "=== Build & push ==="
gcloud builds submit . \
  --tag $IMAGE \
  --project $PROJECT_ID

echo "=== Deploy to Cloud Run ==="
gcloud run deploy $SERVICE_NAME \
  --image $IMAGE \
  --region $REGION \
  --platform managed \
  --no-allow-unauthenticated \
  --set-env-vars "IG_ACCESS_TOKEN=$IG_ACCESS_TOKEN,IG_USER_ID=$IG_USER_ID" \
  --project $PROJECT_ID

SERVICE_URL=$(gcloud run services describe $SERVICE_NAME \
  --region $REGION \
  --project $PROJECT_ID \
  --format "value(status.url)")

echo ""
echo "=== DONE ==="
echo "MCP URL: $SERVICE_URL/mcp"
echo ""
echo "Añade esto a tu claude_desktop_config.json:"
echo '{
  "mcpServers": {
    "instagram-mcp": {
      "command": "npx",
      "args": [
        "mcp-remote",
        "'$SERVICE_URL'/mcp"
      ]
    }
  }
}'
