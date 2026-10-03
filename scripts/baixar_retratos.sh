#!/usr/bin/env bash
# Baixa o bruto ao vivo dos últimos N dias (UTC) para uma pasta.
#
#   bash scripts/baixar_retratos.sh 28 retratos
#
# Para cada dia: o pacote diário, se já existe; senão (hoje, ou se o pacote falhou), os
# arquivos soltos da release. Dia sem release (coleta parada) só gera um aviso.
# Precisa de GH_TOKEN e GH_REPO no ambiente.
set -euo pipefail

dias="${1:?uso: baixar_retratos.sh <dias> <pasta>}"
pasta="${2:?uso: baixar_retratos.sh <dias> <pasta>}"
GH="${GH:-gh}"
if ! [[ "$dias" =~ ^[0-9]+$ ]] || [ "$dias" -lt 1 ] || [ "$dias" -gt 400 ]; then
  echo "Número de dias inválido: $dias" >&2
  exit 1
fi
mkdir -p "$pasta"

for ((i = 0; i < dias; i++)); do
  dia="$(date -u -d "-$i day" +%F)"
  tag="bruto-bikepoint-$dia"
  if ! nomes="$("$GH" release view "$tag" --json assets --jq '.assets[].name' 2>/dev/null)"; then
    echo "Aviso: sem release em $dia (nenhuma coleta registrada)." >&2
    continue
  fi
  if grep -qx "pacote_bikepoint_$dia.tar" <<<"$nomes"; then
    "$GH" release download "$tag" --dir "$pasta" --pattern "pacote_bikepoint_$dia.tar" --skip-existing
  else
    "$GH" release download "$tag" --dir "$pasta" --skip-existing \
      --pattern 'bikepoint_*.json.gz' --pattern 'execucao_*.json'
  fi
done
echo "Baixado em $pasta: $(find "$pasta" -type f | wc -l) arquivos."
