#!/bin/bash
# Safely rotate the Instagram Graph API access token in Secret Manager.
# Does not put the token in shell history. Creates a new Cloud Run revision so
# instances pick up the latest secret version.

set -euo pipefail

PROJECT_ID="${PROJECT_ID:-instagram-mcp-prod}"
REGION="${REGION:-europe-west1}"
SERVICE_NAME="${SERVICE_NAME:-instagram-mcp}"
IG_ACCESS_TOKEN_SECRET="${IG_ACCESS_TOKEN_SECRET:-IG_ACCESS_TOKEN}"

read -rsp "Nuevo IG_ACCESS_TOKEN: " NEW_IG_ACCESS_TOKEN
echo

if [[ -z "$NEW_IG_ACCESS_TOKEN" ]]; then
  echo "Token vacío; abortando." >&2
  exit 1
fi

printf "%s" "$NEW_IG_ACCESS_TOKEN" | gcloud secrets versions add "$IG_ACCESS_TOKEN_SECRET" \
  --project "$PROJECT_ID" \
  --data-file=-

unset NEW_IG_ACCESS_TOKEN

echo "Nueva versión añadida a Secret Manager: $IG_ACCESS_TOKEN_SECRET"
echo "Forzando nueva revisión de Cloud Run para cargar latest..."

gcloud run services update "$SERVICE_NAME" \
  --region "$REGION" \
  --project "$PROJECT_ID" \
  --update-secrets "IG_ACCESS_TOKEN=$IG_ACCESS_TOKEN_SECRET:latest"

echo "OK. Servicio actualizado."
