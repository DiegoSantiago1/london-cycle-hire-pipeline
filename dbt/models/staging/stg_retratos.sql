{#
  Retratos da API tipados: uma linha por estação por coleta.
  "vazia" e "cheia" não usam NbDocks: medido em 03/10/2026, em 625 de 799 estações
  bicicletas + vagas != docas (docas fora de serviço), D18.
#}
{{ config(tags=['diario']) }}

select
    arquivo,
    coletado_em,
    estacao_id,
    terminal,
    trim(nome) as nome,
    lat::numeric(9, 6) as lat,
    lon::numeric(9, 6) as lon,
    instalada::boolean as instalada,
    bloqueada::boolean as bloqueada,
    temporaria::boolean as temporaria,
    bicicletas::integer as bicicletas,
    vagas_livres::integer as vagas_livres,
    docas::integer as docas,
    classicas::integer as classicas,
    eletricas::integer as eletricas,
    atualizado_em::timestamptz as atualizado_em,
    bicicletas::integer = 0 as vazia,
    vagas_livres::integer = 0 as cheia,
    classicas::integer = 0 and bicicletas::integer > 0 as sem_classica,
    instalada::boolean and not bloqueada::boolean as em_operacao
from {{ source('bruto', 'retratos') }}
