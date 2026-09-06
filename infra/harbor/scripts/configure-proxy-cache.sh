#!/usr/bin/env bash
set -euo pipefail

# Configure Harbor proxy cache projects and upstream registry endpoints.
# Run manually after Harbor is deployed and healthy.

HARBOR_URL="${HARBOR_URL:-https://harbor.durp.info}"
HARBOR_USER="${HARBOR_USER:-admin}"
HARBOR_PASSWORD="${HARBOR_PASSWORD:-}"

if [[ -z "$HARBOR_PASSWORD" ]]; then
  echo "ERROR: HARBOR_PASSWORD is required." >&2
  echo "Set HARBOR_URL, HARBOR_USER, and HARBOR_PASSWORD, then re-run." >&2
  exit 1
fi

API_BASE="${HARBOR_URL%/}/api/v2.0"
AUTH="${HARBOR_USER}:${HARBOR_PASSWORD}"

curl_api() {
  curl -k -s -u "$AUTH" "$@"
}

curl_api_status() {
  curl -k -s -o /dev/null -w '%{http_code}' -u "$AUTH" "$@"
}

get_registry_id_by_name() {
  local name="$1"
  curl_api "${API_BASE}/registries?name=${name}" | jq -r '.[] | select(.name == "'"${name}"'") | .id // empty'
}

create_registry() {
  local name="$1"
  local url="$2"
  local provider="$3"

  local existing_id
  existing_id="$(get_registry_id_by_name "$name" || true)"
  if [[ -n "$existing_id" ]]; then
    echo "Registry '${name}' already exists (id: ${existing_id})."
    echo "$existing_id"
    return
  fi

  echo "Creating registry endpoint '${name}' ..."
  local response
  response="$(curl_api -X POST \
    -H 'Content-Type: application/json' \
    -d "{\"name\":\"${name}\",\"url\":\"${url}\",\"provider\":\"${provider}\",\"description\":\"Proxy cache upstream for ${name}\",\"insecure\":true}" \
    "${API_BASE}/registries")"

  local new_id
  new_id="$(echo "$response" | jq -r '.id // empty')"
  if [[ -n "$new_id" && "$new_id" != 'null' ]]; then
    echo "Registry '${name}' created (id: ${new_id})."
    echo "$new_id"
    return
  fi

  echo "ERROR: Failed to create registry '${name}'." >&2
  echo "Response: ${response}" >&2
  exit 1
}

project_exists() {
  local name="$1"
  local count
  count="$(curl_api "${API_BASE}/projects?name=${name}" | jq -r '[.[]? | select(.name == "'"${name}"'")] | length')"
  [[ "$count" -gt 0 ]]
}

create_proxy_project() {
  local name="$1"
  local registry_id="$2"

  if project_exists "$name"; then
    echo "Project '${name}' already exists. Skipping."
    return
  fi

  echo "Creating proxy cache project '${name}' ..."
  local status
  status="$(curl_api_status -X POST \
    -H 'Content-Type: application/json' \
    -d "{\"project_name\":\"${name}\",\"metadata\":{\"public\":\"false\",\"prevent_vul\":\"false\"},\"registry_id\":${registry_id}}" \
    "${API_BASE}/projects")"

  if [[ "$status" == '201' || "$status" == '200' ]]; then
    echo "Project '${name}' created successfully."
  else
    echo "ERROR: Failed to create project '${name}' (HTTP ${status})." >&2
    exit 1
  fi
}

echo "Configuring Harbor proxy cache at ${HARBOR_URL} ..."

# Ensure jq is available
if ! command -v jq >/dev/null 2>&1; then
  echo "ERROR: jq is required but not installed." >&2
  exit 1
fi

DOCKERHUB_ID="$(create_registry 'dockerhub' 'https://hub.docker.com' 'docker-hub')"
GHCR_ID="$(create_registry 'ghcr' 'https://ghcr.io' 'docker-registry')"
QUAY_ID="$(create_registry 'quay' 'https://quay.io' 'quay')"

create_proxy_project 'dockerhub-proxy' "$DOCKERHUB_ID"
create_proxy_project 'ghcr-proxy' "$GHCR_ID"
create_proxy_project 'quay-proxy' "$QUAY_ID"

echo "Harbor proxy cache configuration complete."
