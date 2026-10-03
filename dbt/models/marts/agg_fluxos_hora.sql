{#
  Principais fluxos origem -> destino por hora de saída, em dias úteis (o padrão casa ->
  trabalho que cria o problema de rebalanceamento). Média de viagens por dia útil na
  janela de 12 meses; as 20 maiores por hora. Ida e volta na mesma estação fica de fora:
  não move bicicleta entre estações.
#}
{{ config(tags=['viagens']) }}

with janela as (
    select * from {{ ref('int_janela_viagens') }}
),

dias_uteis as (
    select count(*) as n
    from janela, generate_series(inicio_janela, fim_janela - 1, interval '1 day') as d
    where extract(isodow from d) <= 5
),

pares as (
    select
        extract(hour from inicio_local)::int as hora,
        estacao_inicio_terminal as origem,
        estacao_fim_terminal as destino,
        count(*) as n
    from {{ ref('stg_viagens') }}, janela
    where inicio_local >= inicio_janela and inicio_local < fim_janela
      and extract(isodow from inicio_local) <= 5
      and estacao_inicio_terminal is not null
      and estacao_fim_terminal is not null
      and estacao_inicio_terminal <> estacao_fim_terminal
    group by 1, 2, 3
),

ordenados as (
    select
        *,
        row_number() over (partition by hora order by n desc, origem, destino) as posicao
    from pares
)

select
    hora,
    posicao,
    origem,
    destino,
    round(n::numeric / (select n from dias_uteis), 3) as viagens_media
from ordenados
where posicao <= 20
