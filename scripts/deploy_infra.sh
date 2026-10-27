#!/usr/bin/env bash
# Create or update the Azure resources in infra/main.bicep.
#
# Run this yourself after `az login`. It creates billable resources
# (see README "Cost notes"). Re-running is safe but rotates the Postgres
# password and JWT secret; Key Vault is updated in the same deployment and
# the script restarts the app so it picks up the new values.
#
#   RG=finadv-rg LOCATION=eastus2 ./scripts/deploy_infra.sh
set -euo pipefail

RG="${RG:-finadv-rg}"
LOCATION="${LOCATION:-eastus2}"
PREFIX="${PREFIX:-finadv}"
APP="${PREFIX}-api"
REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"

echo "Subscription: $(az account show --query name -o tsv)"
az extension add --name containerapp --upgrade --only-show-errors
az group create --name "$RG" --location "$LOCATION" --output none

OPERATOR_ID="$(az ad signed-in-user show --query id -o tsv)"
OPERATOR_IP="$(curl -fsS https://api.ipify.org)"

# Keep the image CI deployed; only the very first run uses the placeholder
IMAGE="mcr.microsoft.com/k8se/quickstart:latest"
PORT=80
if CURRENT="$(az containerapp show -g "$RG" -n "$APP" --query 'properties.template.containers[0].image' -o tsv 2>/dev/null)" \
   && [[ -n "$CURRENT" && "$CURRENT" != "$IMAGE" ]]; then
  IMAGE="$CURRENT"
  PORT=8000
fi

az deployment group create \
  --resource-group "$RG" \
  --name "finadv-$(date +%Y%m%d%H%M%S)" \
  --template-file "$REPO_ROOT/infra/main.bicep" \
  --parameters prefix="$PREFIX" operatorPrincipalId="$OPERATOR_ID" operatorIpAddress="$OPERATOR_IP" \
               apiImage="$IMAGE" apiTargetPort="$PORT" \
  --query properties.outputs -o json > "$REPO_ROOT/infra/.outputs.json"

out() { python3 -c "import json,sys; print(json.load(open(sys.argv[1]))[sys.argv[2]]['value'])" "$REPO_ROOT/infra/.outputs.json" "$1"; }

if [[ "$IMAGE" != mcr.microsoft.com/* ]]; then
  az containerapp revision restart -g "$RG" -n "$APP" \
    --revision "$(az containerapp show -g "$RG" -n "$APP" --query properties.latestRevisionName -o tsv)" --output none
fi

cat <<MSG

Deployed. API URL: $(out apiUrl)

Set these GitHub repository variables (identifiers, not secrets) so
.github/workflows/deploy.yml can deploy on merge to main:

  gh variable set AZURE_CLIENT_ID --body "$(out githubClientId)"
  gh variable set AZURE_TENANT_ID --body "$(out tenantId)"
  gh variable set AZURE_SUBSCRIPTION_ID --body "$(out subscriptionId)"
  gh variable set AZURE_RESOURCE_GROUP --body "$RG"
  gh variable set AZURE_ACR_NAME --body "$(out acrName)"
  gh variable set AZURE_CONTAINERAPP_NAME --body "$(out containerAppName)"

For the eval against Azure (reads DATABASE-URL from Key Vault with your login):

  export MODEL_PROVIDER=azure_openai AZURE_OPENAI_ENDPOINT=$(out openAiEndpoint)
  export AZURE_SEARCH_ENDPOINT=$(out searchEndpoint)
  export DATABASE_URL="\$(az keyvault secret show --vault-name $(out keyVaultName) -n DATABASE-URL --query value -o tsv)"
MSG
