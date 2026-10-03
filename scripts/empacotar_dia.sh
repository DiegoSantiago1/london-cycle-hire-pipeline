#!/usr/bin/env bash
# Monta o pacote de um dia (UTC) a partir da release dele e anexa na mesma release.
#
#   bash scripts/empacotar_dia.sh 2026-10-03
#
# Idempotente: se o pacote já está na release, não faz nada.
# Precisa de GH_TOKEN e GH_REPO no ambiente (o workflow define os dois).
set -euo pipefail

dia="${1:?uso: empacotar_dia.sh AAAA-MM-DD}"
GH="${GH:-gh}"
PYTHON="${PYTHON:-python}"
if ! [[ "$dia" =~ ^[0-9]{4}-[0-9]{2}-[0-9]{2}$ ]]; then
  echo "Dia inválido: $dia (use AAAA-MM-DD)" >&2
  exit 1
fi

tag="bruto-bikepoint-$dia"
pacote="pacote_bikepoint_$dia.tar"

if ! "$GH" release view "$tag" >/dev/null 2>&1; then
  echo "Release $tag não existe: nenhuma coleta registrada em $dia." >&2
  exit 1
fi
if "$GH" release view "$tag" --json assets --jq '.assets[].name' | grep -qx "$pacote"; then
  echo "$pacote já está na release $tag. Nada a fazer."
  exit 0
fi

trabalho="$(mktemp -d)"
trap 'rm -rf "$trabalho"' EXIT
"$GH" release download "$tag" --dir "$trabalho/baixados" \
  --pattern 'bikepoint_*.json.gz' --pattern 'execucao_*.json'
"$PYTHON" -m bicicletas.pacote_diario --dia "$dia" --pasta "$trabalho/baixados" \
  --saida "$trabalho/$pacote"
"$GH" release upload "$tag" "$trabalho/$pacote"
echo "Publicado: $tag/$pacote"
