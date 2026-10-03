{#
  Quão "fresco" é o dado da API (D29): a API serve de cache, então mede-se a idade da
  contagem de cada estação no momento da coleta (coletado_em - atualizado_em) e quantos
  retratos consecutivos de uma estação trazem a mesma atualização (nada mudou).
#}
{{ config(tags=['diario']) }}

with r as (
    select
        estacao_id,
        coletado_em,
        atualizado_em,
        lag(atualizado_em) over (partition by estacao_id order by coletado_em) as anterior
    from {{ ref('stg_retratos') }}
)

select
    (coletado_em at time zone 'UTC')::date as dia,
    count(*) as observacoes,
    round((percentile_cont(0.5) within group (
        order by extract(epoch from coletado_em - atualizado_em) / 60.0))::numeric, 1)
        as idade_mediana_min,
    round((percentile_cont(0.9) within group (
        order by extract(epoch from coletado_em - atualizado_em) / 60.0))::numeric, 1)
        as idade_p90_min,
    round(avg(case when anterior is null then null
                   when atualizado_em = anterior then 1.0 else 0.0 end)::numeric, 4)
        as pct_sem_mudanca
from r
group by 1
