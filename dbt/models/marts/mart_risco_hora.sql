{#
  Para o mapa: em cada hora do dia (Londres), que fração do tempo observado a estação
  passou vazia e cheia, nos últimos 7 dias observados. Dias úteis e fim de semana
  separados: o padrão casa -> trabalho só existe nos dias úteis.
#}
{{ config(tags=['diario']) }}

with periodo as (
    -- últimos 7 dias, mas nunca antes do primeiro dia realmente observado
    select greatest(max(data_local) - 6, min(data_local)) as desde, max(data_local) as ate
    from {{ ref('fct_ocupacao_hora') }}
)

select
    o.estacao_id,
    o.terminal,
    case when o.dia_semana <= 5 then 'util' else 'fim_de_semana' end as tipo_dia,
    o.hora,
    round(sum(o.minutos_observados)::numeric, 1) as minutos_observados,
    round((sum(o.minutos_vazia) / nullif(sum(o.minutos_observados), 0))::numeric, 4) as pct_vazia,
    round((sum(o.minutos_cheia) / nullif(sum(o.minutos_observados), 0))::numeric, 4) as pct_cheia
from {{ ref('fct_ocupacao_hora') }} o, periodo p
where o.data_local between p.desde and p.ate
group by 1, 2, 3, 4
