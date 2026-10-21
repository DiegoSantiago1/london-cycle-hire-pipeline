#!/usr/bin/env bash
# Roda arquivos .sql no Athena e mostra o resultado e quanto foi lido (o que é cobrado).
#
#   bash scripts/athena.sh athena/01_view_estacoes.sql athena/02_view_coletas.sql
#   bash scripts/athena.sh athena/consultas/atraso_agendador.sql
#
# Usa o grupo de trabalho do projeto (infra/athena.tf), que tem limite de bytes lidos por
# consulta. Precisa de credenciais da AWS (aws login, ou o OIDC no GitHub Actions).
set -euo pipefail

[ $# -gt 0 ] || { echo "uso: athena.sh arquivo.sql [mais.sql ...]" >&2; exit 1; }

if [ -n "${AWS:-}" ]; then
  : # os testes trocam o aws por um falso
elif command -v aws >/dev/null 2>&1; then
  AWS=aws
else
  AWS="/c/Program Files/Amazon/AWSCLIV2/aws.exe"
fi
GRUPO="${ATHENA_WORKGROUP:-london-cycle-hire}"
BANCO="${ATHENA_BANCO:-london_cycle_hire}"
REGIAO="${AWS_REGION:-eu-west-2}"
ESPERA="${ESPERA:-2}"
TENTATIVAS="${TENTATIVAS:-150}" # 150 x 2 s = 5 min

for arquivo in "$@"; do
  [ -f "$arquivo" ] || { echo "Arquivo não encontrado: $arquivo" >&2; exit 1; }
  sql="$(tr -d '\r' < "$arquivo")"
  echo "== $arquivo"
  id="$("$AWS" athena start-query-execution --region "$REGIAO" --work-group "$GRUPO" \
    --query-execution-context "Database=$BANCO" --query-string "$sql" \
    --query QueryExecutionId --output text | tr -d '\r')"

  estado=QUEUED
  for _ in $(seq "$TENTATIVAS"); do
    estado="$("$AWS" athena get-query-execution --region "$REGIAO" --query-execution-id "$id" \
      --query QueryExecution.Status.State --output text | tr -d '\r')"
    case "$estado" in SUCCEEDED | FAILED | CANCELLED) break ;; esac
    sleep "$ESPERA"
  done

  if [ "$estado" != SUCCEEDED ]; then
    motivo="$("$AWS" athena get-query-execution --region "$REGIAO" --query-execution-id "$id" \
      --query QueryExecution.Status.StateChangeReason --output text | tr -d '\r')"
    echo "Consulta $id terminou em $estado: $motivo" >&2
    exit 1
  fi

  bytes="$("$AWS" athena get-query-execution --region "$REGIAO" --query-execution-id "$id" \
    --query QueryExecution.Statistics.DataScannedInBytes --output text | tr -d '\r')"
  "$AWS" athena get-query-results --region "$REGIAO" --query-execution-id "$id" \
    --query 'ResultSet.Rows[*].Data[*].VarCharValue' --output text --max-items 1000 | tr -d '\r' || true
  # Na prática o Athena cobra US$ 5 por TB lido (aws.amazon.com/athena/pricing).
  awk -v b="${bytes:-0}" 'BEGIN { printf "-- lidos: %.2f MB (custo aproximado: US$ %.6f)\n", b / 1e6, b / 1e12 * 5 }'
done
