#!/bin/bash
# Deploy Instagram MCP server to Cloud Run without exposing secrets in Cloud Run env vars.
# Secrets are stored in Secret Manager and mounted with --set-secrets.
#
# First setup / rotation, preferably without writing secrets into shell history:
#   export PROJECT_ID="your-project"
#   export IG_USER_ID="178..."
#   read -rsp "IG_ACCESS_TOKEN: " IG_ACCESS_TOKEN; export IG_ACCESS_TOKEN; echo
#   read -rsp "MCP_API_KEY: " MCP_API_KEY; export MCP_API_KEY; echo
#   bash deploy.sh --setup-secrets
#
# Later deploys:
#   export PROJECT_ID="your-project"
#   export IG_USER_ID="178..."
#   bash deploy.sh

set -euo pipefail

PROJECT_ID="${PROJECT_ID:?Set PROJECT_ID}"
REGION="${REGION:-europe-west1}"
SERVICE_NAME="${SERVICE_NAME:-instagram-mcp}"
REPOSITORY="${REPOSITORY:-tangibledata-bot}"
IMAGE="$REGION-docker.pkg.dev/$PROJECT_ID/$REPOSITORY/$SERVICE_NAME"
RUNTIME_SA="${RUNTIME_SA:-$SERVICE_NAME-sa@$PROJECT_ID.iam.gserviceaccount.com}"
SETUP_SECRETS="false"

for arg in "$@"; do
  case "$arg" in
    --setup-secrets) SETUP_SECRETS="true" ;;
    *) echo "Unknown arg: $arg" >&2; exit 2 ;;
  esac
done

ensure_secret() {
  local name="$1"
  local value="${2:-}"

  if ! gcloud secrets describe "$name" --project "$PROJECT_ID" >/dev/null 2>&1; then
    if [[ -z "$value" ]]; then
      echo "Secret $name does not exist and no local value was provided." >&2
      exit 1
    fi
    printf "%s" "$value" | gcloud secrets create "$name" \
      --project "$PROJECT_ID" \
      --replication-policy="automatic" \
      --data-file=-
  elif [[ -n "$value" ]]; then
    printf "%s" "$value" | gcloud secrets versions add "$name" \
      --project "$PROJECT_ID" \
      --data-file=-
  fi
}

echo "=== Enable base APIs ==="
gcloud services enable \
  run.googleapis.com \
  cloudbuild.googleapis.com \
  artifactregistry.googleapis.com \
  secretmanager.googleapis.com \
  --project "$PROJECT_ID"

if ! gcloud artifacts repositories describe "$REPOSITORY" \
  --location "$REGION" \
  --project "$PROJECT_ID" >/dev/null 2>&1; then
  echo "=== Create Artifact Registry repository ==="
  gcloud artifacts repositories create "$REPOSITORY" \
    --repository-format=docker \
    --location "$REGION" \
    --description="Tangible Data bot containers" \
    --project "$PROJECT_ID"
fi

if ! gcloud iam service-accounts describe "$RUNTIME_SA" \
  --project "$PROJECT_ID" >/dev/null 2>&1; then
  echo "=== Create runtime service account ==="
  gcloud iam service-accounts create "$SERVICE_NAME-sa" \
    --display-name="Instagram MCP runtime" \
    --project "$PROJECT_ID"
fi

if [[ "$SETUP_SECRETS" == "true" ]]; then
  echo "=== Create/update secrets from local environment ==="
  ensure_secret "${IG_ACCESS_TOKEN_SECRET:-IG_ACCESS_TOKEN}" "${IG_ACCESS_TOKEN:-}"
  ensure_secret "${IG_USER_ID_SECRET:-IG_USER_ID}" "${IG_USER_ID:-}"
  ensure_secret "${MCP_API_KEY_SECRET:-MCP_API_KEY}" "${MCP_API_KEY:-}"
else
  echo "=== Verify secrets exist ==="
  gcloud secrets describe "${IG_ACCESS_TOKEN_SECRET:-IG_ACCESS_TOKEN}" --project "$PROJECT_ID" >/dev/null
  gcloud secrets describe "${IG_USER_ID_SECRET:-IG_USER_ID}" --project "$PROJECT_ID" >/dev/null
  gcloud secrets describe "${MCP_API_KEY_SECRET:-MCP_API_KEY}" --project "$PROJECT_ID" >/dev/null
fi

echo "=== Grant runtime secret access ==="
gcloud secrets add-iam-policy-binding "${IG_ACCESS_TOKEN_SECRET:-IG_ACCESS_TOKEN}" \
  --project "$PROJECT_ID" \
  --member "serviceAccount:$RUNTIME_SA" \
  --role "roles/secretmanager.secretAccessor" >/dev/null

gcloud secrets add-iam-policy-binding "${IG_USER_ID_SECRET:-IG_USER_ID}" \
  --project "$PROJECT_ID" \
  --member "serviceAccount:$RUNTIME_SA" \
  --role "roles/secretmanager.secretAccessor" >/dev/null

gcloud secrets add-iam-policy-binding "${MCP_API_KEY_SECRET:-MCP_API_KEY}" \
  --project "$PROJECT_ID" \
  --member "serviceAccount:$RUNTIME_SA" \
  --role "roles/secretmanager.secretAccessor" >/dev/null

echo "=== Build & push ==="
gcloud builds submit . \
  --tag "$IMAGE" \
  --project "$PROJECT_ID"

echo "=== Deploy to Cloud Run ==="
gcloud run deploy "$SERVICE_NAME" \
  --image "$IMAGE" \
  --region "$REGION" \
  --platform managed \
  --no-allow-unauthenticated \
  --service-account "$RUNTIME_SA" \
  --set-secrets "IG_ACCESS_TOKEN=${IG_ACCESS_TOKEN_SECRET:-IG_ACCESS_TOKEN}:latest,IG_USER_ID=${IG_USER_ID_SECRET:-IG_USER_ID}:latest,MCP_API_KEY=${MCP_API_KEY_SECRET:-MCP_API_KEY}:latest" \
  --project "$PROJECT_ID"

SERVICE_URL=$(gcloud run services describe "$SERVICE_NAME" \
  --region "$REGION" \
  --project "$PROJECT_ID" \
  --format "value(status.url)")

echo ""
echo "=== DONE ==="
echo "MCP URL: $SERVICE_URL/mcp"
echo ""
echo "Use mcp-remote with OAuth client_secret equal to your MCP API key, or configure Authorization: Bearer via your MCP client."
