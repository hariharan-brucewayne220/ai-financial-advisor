#!/usr/bin/env bash
# Delete everything infra/main.bicep created, then purge the soft-deleted
# Key Vault and Azure OpenAI account so nothing lingers (or blocks a
# redeploy with the same names).
#
#   RG=finadv-rg ./scripts/teardown.sh
set -euo pipefail

RG="${RG:-finadv-rg}"

if ! az group show --name "$RG" --output none 2>/dev/null; then
  echo "Resource group $RG not found; nothing to delete."
  exit 0
fi

LOCATION="$(az group show --name "$RG" --query location -o tsv)"
KV="$(az keyvault list -g "$RG" --query '[0].name' -o tsv)"
AOAI="$(az cognitiveservices account list -g "$RG" --query '[0].name' -o tsv)"

echo "Deleting resource group $RG (this takes a few minutes)..."
az group delete --name "$RG" --yes

if [[ -n "$KV" ]]; then
  echo "Purging soft-deleted Key Vault $KV"
  az keyvault purge --name "$KV" --location "$LOCATION"
fi
if [[ -n "$AOAI" ]]; then
  echo "Purging soft-deleted Azure OpenAI account $AOAI"
  az cognitiveservices account purge --name "$AOAI" --resource-group "$RG" --location "$LOCATION"
fi

rm -f "$(cd "$(dirname "$0")/.." && pwd)/infra/.outputs.json"

echo "Remaining resources in the subscription:"
az resource list --query "[].{name:name, type:type, rg:resourceGroup}" -o table
