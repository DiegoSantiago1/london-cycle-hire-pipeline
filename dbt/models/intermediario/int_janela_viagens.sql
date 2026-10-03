{#
  Janela das análises por estação: os 12 meses completos mais recentes de viagens
  publicadas (D32). Todos no formato novo, com número de estação compatível com a API.
#}
{{ config(tags=['viagens']) }}

with fim as (
    select date_trunc('month', max(inicio_local)) as fim_janela
    from {{ ref('stg_viagens') }}
)

select
    (fim_janela - interval '12 months')::date as inicio_janela,
    fim_janela::date as fim_janela
from fim
