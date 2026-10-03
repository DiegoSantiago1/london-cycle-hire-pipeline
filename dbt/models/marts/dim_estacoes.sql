{#
  Cadastro das estações pelo retrato mais recente de cada uma, com o volume de viagens
  dos últimos 12 meses publicados (dos agregados).
#}
{{ config(tags=['diario']) }}

with ultimo as (
    select distinct on (estacao_id) *
    from {{ ref('stg_retratos') }}
    order by estacao_id, coletado_em desc
)

select
    u.estacao_id,
    u.terminal,
    u.nome,
    u.lat,
    u.lon,
    u.docas,
    u.em_operacao,
    u.temporaria,
    u.coletado_em as visto_em,
    coalesce(e.retiradas_12m, 0) as retiradas_12m,
    coalesce(e.devolucoes_12m, 0) as devolucoes_12m
from ultimo u
left join {{ source('agregados', 'estacoes_viagens') }} e using (terminal)
