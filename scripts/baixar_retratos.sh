#!/usr/bin/env bash
# Baixa o bruto ao vivo dos últimos N dias (UTC) para uma pasta.
#
#   bash scripts/baixar_retratos.sh 28 retratos
#
# Para cada dia: o pacote diário, se já existe; senão (hoje, ou se o pacote falhou), os
# arquivos soltos da release. Dia sem release (coleta parada) só gera um aviso.
# Chamadas ao GitHub têm até 3 tentativas: a API às vezes responde HTTP 500 (medido em
# 03/10/2026, no job diário), e um erro passageiro não pode derrubar a página.
# Precisa de GH_TOKEN e GH_REPO no ambiente.
set -euo pipefail

dias="${1:?uso: baixar_retratos.sh <dias> <pasta>}"
pasta="${2:?uso: baixar_retratos.sh <dias> <pasta>}"
GH="${GH:-gh}"
ESPERA="${ESPERA:-5}" # segundos; os testes usam 0
if ! [[ "$dias" =~ ^[0-9]+$ ]] || [ "$dias" -lt 1 ] || [ "$dias" -gt 400 ]; then
  echo "Número de dias inválido: $dias" >&2
  exit 1
fi
mkdir -p "$pasta"

tentar() {
  local n
  for n in 1 2 3; do
    if "$@"; then
      return 0
    fi
    echo "Aviso: falhou (tentativa $n de 3): $*" >&2
    if [ "$n" -lt 3 ]; then sleep $((ESPERA * n)); fi
  done
  return 1
}

# Uma listagem só (em vez de uma consulta por dia): um erro passageiro aqui não pode
# virar "dia sem coleta".
listar() { "$GH" release list --limit 1000 --json tagName --jq '.[].tagName' > "$pasta/.tags"; }
tentar listar
tags="$(cat "$pasta/.tags")"
rm -f "$pasta/.tags"

for ((i = 0; i < dias; i++)); do
  dia="$(date -u -d "-$i day" +%F)"
  tag="bruto-bikepoint-$dia"
  if ! grep -qx "$tag" <<<"$tags"; then
    echo "Aviso: sem release em $dia (nenhuma coleta registrada)." >&2
    continue
  fi
  nomes_arquivo() { "$GH" release view "$tag" --json assets --jq '.assets[].name' > "$pasta/.nomes"; }
  tentar nomes_arquivo
  if grep -qx "pacote_bikepoint_$dia.tar" "$pasta/.nomes"; then
    tentar "$GH" release download "$tag" --dir "$pasta" --pattern "pacote_bikepoint_$dia.tar" --skip-existing
  else
    tentar "$GH" release download "$tag" --dir "$pasta" --skip-existing \
      --pattern 'bikepoint_*.json.gz' --pattern 'execucao_*.json'
  fi
  rm -f "$pasta/.nomes"
done
echo "Baixado em $pasta: $(find "$pasta" -type f | wc -l) arquivos."
