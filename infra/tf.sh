#!/usr/bin/env bash
# Roda o Terraform num container, com as credenciais temporárias do `aws login`.
#
#   bash infra/tf.sh init
#   bash infra/tf.sh plan -out=plano.tfplan
#   bash infra/tf.sh apply plano.tfplan
#
# Por que em container (D46): nesta máquina o antivírus intercepta até a conexão local
# (127.0.0.1) entre o Terraform e o provedor da AWS, e o Terraform nativo falha com
# "x509: certificate signed by unknown authority". Dentro do container essa conexão não
# passa pelo Windows. Em outra máquina, `terraform` direto na pasta infra/ funciona igual.
#
# Credenciais: `aws configure export-credentials` entrega as credenciais temporárias da
# sessão do `aws login` (sem chave de acesso guardada). Elas vão para o container por um
# arquivo apagado ao sair, e nunca aparecem na linha de comando.
set -euo pipefail

infra="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
raiz="$(dirname "$infra")"
IMAGEM="hashicorp/terraform:1.16.5"

if command -v aws >/dev/null 2>&1; then
  AWS_CLI="${AWS_CLI:-aws}"
else
  AWS_CLI="${AWS_CLI:-/c/Program Files/Amazon/AWSCLIV2/aws.exe}"
fi

# No Git Bash do Windows o docker.exe precisa de caminhos do Windows (C:/...).
caminho() { if command -v cygpath >/dev/null 2>&1; then cygpath -m "$1"; else echo "$1"; fi; }

mkdir -p "$infra/.build"
credenciais="$infra/.build/credenciais.env"
trap 'rm -f "$credenciais"' EXIT
if ! "$AWS_CLI" configure export-credentials --format env-no-export 2>/dev/null | tr -d '\r' > "$credenciais" \
  || ! grep -q '^AWS_SESSION_TOKEN=' "$credenciais"; then
  echo "Sem sessão da AWS ativa: rode 'aws login' e tente de novo." >&2
  exit 1
fi

opcoes=(--rm -i --env-file "$(caminho "$credenciais")" -e AWS_REGION=eu-west-2
  -v "$(caminho "$raiz"):/repo" -w /repo/infra)
# Certificados extras (o antivírus desta máquina): o provedor da AWS usa AWS_CA_BUNDLE.
pacote_ca="$HOME/.aws/ca-bundle.pem"
if [ -f "$pacote_ca" ]; then
  opcoes+=(-v "$(caminho "$pacote_ca"):/certs/ca.pem:ro" -e AWS_CA_BUNDLE=/certs/ca.pem)
fi
if [ -t 0 ] && [ -t 1 ]; then opcoes+=(-t); fi

MSYS_NO_PATHCONV=1 docker run "${opcoes[@]}" "$IMAGEM" "$@"
