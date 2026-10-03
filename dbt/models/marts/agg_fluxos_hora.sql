{#
  Principais fluxos origem -> destino por hora de saída, em dias úteis (o padrão casa ->
  trabalho que cria o problema de rebalanceamento). Média de viagens por dia útil
  completo na janela de 12 meses (D42); as 20 maiores por hora. Ida e volta na mesma
  estação fica de fora: não move bicicleta entre estações.
#}
{{ config(tags=['viagens']) }}

with dias_uteis as (
    select dia from {{ ref('int_dias_validos') }} where dia_semana <= 5
),

pares as (
    select
        extract(hour from v.inicio_local)::int as hora,
        v.estacao_inicio_terminal as origem,
        v.estacao_fim_terminal as destino,
        count(*) as n
    from {{ ref('stg_viagens') }} v
    join dias_uteis d on d.dia = v.inicio_local::date
    where v.estacao_inicio_terminal is not null
      and v.estacao_fim_terminal is not null
      and v.estacao_inicio_terminal <> v.estacao_fim_terminal
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
    round(n::numeric / (select count(*) from dias_uteis), 3) as viagens_media
from ordenados
where posicao <= 20
