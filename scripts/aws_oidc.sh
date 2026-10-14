#!/usr/bin/env bash
# Entra na AWS pelo OIDC do GitHub Actions, sem chave guardada em lugar nenhum (D48).
#
#   bash scripts/aws_oidc.sh
#
# 1. Pede ao GitHub um token OIDC assinado, com audiência sts.amazonaws.com (o job precisa
#    de `permissions: id-token: write`).
# 2. Troca o token por credenciais temporárias (1 h) do papel AWS_ROLE_ARN. A AWS confere a
#    assinatura do GitHub e as condições do papel (só este repositório, só a branch main;
#    infra/github_oidc.tf). Essa troca não exige credencial: o token é a prova.
# 3. Grava as credenciais em $GITHUB_ENV para os passos seguintes, mascaradas no log.
#
# Precisa de AWS_ROLE_ARN e AWS_REGION no ambiente.
set -euo pipefail

: "${AWS_ROLE_ARN:?AWS_ROLE_ARN não definida (variável do repositório)}"
: "${AWS_REGION:?AWS_REGION não definida (variável do repositório)}"
: "${GITHUB_ENV:?rode dentro do GitHub Actions}"
if [ -z "${ACTIONS_ID_TOKEN_REQUEST_URL:-}" ] || [ -z "${ACTIONS_ID_TOKEN_REQUEST_TOKEN:-}" ]; then
  echo "O job não pode pedir token OIDC: falta 'permissions: id-token: write'." >&2
  exit 1
fi

token="$(curl --silent --show-error --fail --retry 3 \
  -H "Authorization: Bearer $ACTIONS_ID_TOKEN_REQUEST_TOKEN" \
  "$ACTIONS_ID_TOKEN_REQUEST_URL&audience=sts.amazonaws.com" | jq -r '.value')"
echo "::add-mask::$token"

credenciais="$(aws sts assume-role-with-web-identity \
  --role-arn "$AWS_ROLE_ARN" \
  --role-session-name "github-${GITHUB_RUN_ID:-local}" \
  --web-identity-token "$token" \
  --duration-seconds 3600 \
  --query 'Credentials.[AccessKeyId,SecretAccessKey,SessionToken]' \
  --output text)"
read -r chave segredo sessao <<<"$credenciais"
for valor in "$chave" "$segredo" "$sessao"; do echo "::add-mask::$valor"; done
{
  echo "AWS_ACCESS_KEY_ID=$chave"
  echo "AWS_SECRET_ACCESS_KEY=$segredo"
  echo "AWS_SESSION_TOKEN=$sessao"
  echo "AWS_REGION=$AWS_REGION"
} >> "$GITHUB_ENV"
echo "Na AWS como o papel ${AWS_ROLE_ARN##*/} (credenciais temporárias, 1 h)."
