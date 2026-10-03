{#
  Dias da janela de 12 meses com dados completos. Dia com menos de 2.000 viagens é
  buraco nos arquivos da TfL (medido: 05/08/2025, com 188, contra 20 a 35 mil num dia
  normal) e sai do numerador e do denominador das médias por dia (D42).
#}
{{ config(tags=['viagens']) }}

with janela as (
    select * from {{ ref('int_janela_viagens') }}
)

select
    inicio_local::date as dia,
    extract(isodow from inicio_local::date)::int as dia_semana,
    count(*) as viagens
from {{ ref('stg_viagens') }}, janela
where inicio_local >= inicio_janela and inicio_local < fim_janela
group by 1, 2
having count(*) >= 2000
