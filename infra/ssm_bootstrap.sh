#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────────────
# SSM Parameter Store Bootstrap Script
#
# Seed AWS SSM Parameter Store from your local .env file.
# Run ONCE per environment before the first SAM deploy.
#
# Usage:
#   ENV=production bash infra/ssm_bootstrap.sh
#   ENV=staging   bash infra/ssm_bootstrap.sh
#   ENV=development bash infra/ssm_bootstrap.sh   (default)
#
# Prerequisites:
#   - AWS CLI configured with credentials that have ssm:PutParameter permission
#   - Local .env file with all required values
# ─────────────────────────────────────────────────────────────────────────────

set -euo pipefail

ENV="${ENV:-development}"
REGION="${AWS_REGION:-us-east-1}"
PREFIX="/asset-compliance/${ENV}"

echo "Bootstrapping SSM parameters for env: ${ENV} in region: ${REGION}"
echo "Parameter prefix: ${PREFIX}"
echo ""

# Load .env (skip comment lines and blank lines)
if [ ! -f .env ]; then
  echo "ERROR: .env file not found. Copy .env.example to .env and fill in values."
  exit 1
fi

# shellcheck disable=SC2046
export $(grep -v '^#' .env | grep -v '^$' | xargs)

# Define parameters as "name:value:type" triples
# SecureString for secrets, String for non-sensitive config
declare -a PARAMS=(
  "pinecone_api_key:${PINECONE_API_KEY}:SecureString"
  "pinecone_index_name:${PINECONE_INDEX_NAME}:String"
  "pinecone_environment:${PINECONE_ENVIRONMENT}:String"
  "anthropic_api_key:${ANTHROPIC_API_KEY:-}:SecureString"
  "openai_api_key:${OPENAI_API_KEY:-}:SecureString"
  "google_api_key:${GOOGLE_API_KEY:-}:SecureString"
  "xai_api_key:${XAI_API_KEY:-}:SecureString"
  "image_agent_provider:${IMAGE_AGENT_PROVIDER}:String"
  "image_agent_model:${IMAGE_AGENT_MODEL}:String"
  "rule_agent_provider:${RULE_AGENT_PROVIDER}:String"
  "rule_agent_model:${RULE_AGENT_MODEL}:String"
  "verdict_agent_provider:${VERDICT_AGENT_PROVIDER}:String"
  "verdict_agent_model:${VERDICT_AGENT_MODEL}:String"
  "chat_agent_provider:${CHAT_AGENT_PROVIDER}:String"
  "chat_agent_model:${CHAT_AGENT_MODEL}:String"
  "embedding_provider:${EMBEDDING_PROVIDER}:String"
  "embedding_model:${EMBEDDING_MODEL}:String"

  "langchain_api_key:${LANGCHAIN_API_KEY:-}:SecureString"
  "api_secret_key:${API_SECRET_KEY}:SecureString"
)

SUCCEEDED=0
FAILED=0

for param in "${PARAMS[@]}"; do
  IFS=':' read -r name value type <<< "$param"

  # Handle empty params by setting them to a dummy value so AWS SAM deploy doesn't fail
  if [ -z "$value" ]; then
    echo "  WARN  ${PREFIX}/${name} is empty. Bootstrapping with 'not_configured'."
    value="not_configured"
  fi

  if aws ssm put-parameter \
    --region "${REGION}" \
    --name "${PREFIX}/${name}" \
    --value "${value}" \
    --type "${type}" \
    --overwrite \
    --no-cli-pager \
    --output text > /dev/null 2>&1; then
    echo "  ✓  ${PREFIX}/${name} [${type}]"
    SUCCEEDED=$((SUCCEEDED + 1))
  else
    echo "  ✗  FAILED: ${PREFIX}/${name}"
    FAILED=$((FAILED + 1))
  fi
done

echo ""
echo "Bootstrap complete: ${SUCCEEDED} succeeded, ${FAILED} failed"

if [ "${FAILED}" -gt 0 ]; then
  exit 1
fi
