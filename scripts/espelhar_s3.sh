#!/usr/bin/env bash
# Baixa do S3 o bruto ao vivo de um dia (UTC), mantendo as chaves como caminho.
#
#   bash scripts/espelhar_s3.sh 2026-10-14 saida
#
# Resultado: saida/bruto/bikepoint/data=2026-10-14/... e saida/bruto/execucoes_coleta/...,
# o mesmo formato que a coleta local deixa. Assim o publicar_release.sh espelha o dia na
# release pública (cópia fora da AWS) e o job diário carrega o dia sem esperar o pacote.
# Precisa de BRUTO_BUCKET e de credenciais da AWS (scripts/aws_oidc.sh) no ambiente.
set -euo pipefail

dia="${1:?uso: espelhar_s3.sh AAAA-MM-DD <pasta>}"
pasta="${2:?uso: espelhar_s3.sh AAAA-MM-DD <pasta>}"
AWS="${AWS:-aws}" # os testes trocam o aws por um falso
: "${BRUTO_BUCKET:?BRUTO_BUCKET não definida (variável do repositório)}"
if ! [[ "$dia" =~ ^[0-9]{4}-[0-9]{2}-[0-9]{2}$ ]]; then
  echo "Dia inválido: $dia (use AAAA-MM-DD)" >&2
  exit 1
fi

for fonte in bikepoint execucoes_coleta; do
  # Prefixo vazio (dia sem coleta na Lambda) não é erro: o cp não copia nada.
  "$AWS" s3 cp --recursive --only-show-errors \
    "s3://$BRUTO_BUCKET/bruto/$fonte/data=$dia/" "$pasta/bruto/$fonte/data=$dia/"
done
# Dia sem nada no S3: a pasta nem é criada, e o find falharia (com pipefail, derrubaria o job).
total=0
if [ -d "$pasta/bruto" ]; then
  total="$(find "$pasta/bruto" -path "*/data=$dia/*" -type f | wc -l)"
fi
echo "S3 → $pasta: $total arquivos de $dia."
