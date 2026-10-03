{#
  Tendência mensal de todas as viagens carregadas (os dois formatos): volume, duração
  mediana, participação das elétricas (só existe no formato novo; as primeiras viagens
  elétricas aparecem em 14/09/2022) e dias incompletos.

  Dia incompleto: menos de 2.000 viagens, contra 20 a 35 mil num dia normal (medido em
  03/10/2026: 10 e 11/09/2022, na troca do sistema de dados da TfL, e 05/08/2025). É
  buraco nos dados, não dia sem demanda; a página avisa nesses meses.
  Mês incompleto nas pontas fica de fora (a primeira e a última semana dos arquivos).
#}
{{ config(tags=['viagens']) }}

with por_dia as (
    select inicio_local::date as dia, count(*) as n
    from {{ ref('stg_viagens') }}
    where inicio_local >= '2022-01-01'
    group by 1
),

por_mes as (
    select
        date_trunc('month', inicio_local)::date as mes,
        count(*) as viagens,
        percentile_cont(0.5) within group (order by duracao_s) / 60.0 as duracao_mediana_min,
        avg(case when modelo = 'PBSC_EBIKE' then 1.0 when modelo is not null then 0.0 end)
            as pct_eletricas,
        min(inicio_local) as primeira,
        max(inicio_local) as ultima
    from {{ ref('stg_viagens') }}
    where inicio_local >= '2022-01-01'
    group by 1
),

incompletos as (
    select date_trunc('month', dia)::date as mes, count(*) filter (where n < 2000) as dias
    from por_dia
    group by 1
)

select
    m.mes,
    m.viagens,
    round(m.duracao_mediana_min::numeric, 1) as duracao_mediana_min,
    round(m.pct_eletricas::numeric, 4) as pct_eletricas,
    coalesce(i.dias, 0) as dias_incompletos
from por_mes m
left join incompletos i using (mes)
-- mês completo: tem viagens nos primeiros e nos últimos dias do mês
where m.primeira < m.mes + interval '1 day'
  and m.ultima >= m.mes + interval '1 month' - interval '1 day'
