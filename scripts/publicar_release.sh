#!/usr/bin/env bash
# Publica os arquivos da coleta na release do dia (UTC) correspondente.
#
#   bash scripts/publicar_release.sh saida
#
# Cada arquivo em saida/bruto/<fonte>/data=AAAA-MM-DD/ vai para a release com a tag
# bruto-bikepoint-AAAA-MM-DD (criada se ainda não existir). O nome do arquivo já traz
# o tipo e o horário, então a chave completa do bruto pode ser reconstruída a partir dele.
# Precisa de GH_TOKEN e GH_REPO no ambiente (o workflow define os dois).
set -euo pipefail

pasta="${1:?uso: publicar_release.sh <pasta>}"
GH="${GH:-gh}" # os testes trocam o gh por um falso

shopt -s nullglob
arquivos=("$pasta"/bruto/*/data=*/*)
if [ ${#arquivos[@]} -eq 0 ]; then
  echo "Nada para publicar em $pasta."
  exit 0
fi

for arquivo in "${arquivos[@]}"; do
  particao="$(basename "$(dirname "$arquivo")")"
  dia="${particao#data=}"
  if ! [[ "$dia" =~ ^[0-9]{4}-[0-9]{2}-[0-9]{2}$ ]]; then
    echo "Partição fora do padrão: $arquivo" >&2
    exit 1
  fi
  tag="bruto-bikepoint-$dia"
  if ! "$GH" release view "$tag" >/dev/null 2>&1; then
    # --latest=false: a release de dados não deve aparecer como "Latest" do projeto.
    "$GH" release create "$tag" --latest=false \
      --title "Bruto BikePoint $dia (UTC)" \
      --notes "Retratos da API BikePoint da TfL coletados a cada 15 minutos em $dia (UTC), guardados como vieram, e o registro de cada execução. Powered by TfL Open Data."
  fi
  # Sem --clobber: o bruto nunca é sobrescrito; um nome repetido faz o upload falhar.
  "$GH" release upload "$tag" "$arquivo"
  echo "Publicado: $tag/$(basename "$arquivo")"
done
