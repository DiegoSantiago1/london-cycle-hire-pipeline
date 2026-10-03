{#
  Onde a operação deveria agir primeiro: estações ordenadas pela demanda perdida
  estimada (viagens perdidas + devoluções barradas) nos últimos 7 dias observados.
  Com menos de 7 dias de coleta, usa o que existe; a página mostra o período.
#}
{{ config(tags=['diario']) }}

with periodo as (
    -- últimos 7 dias, mas nunca antes do primeiro dia realmente observado
    select greatest(max(data_local) - 6, min(data_local)) as desde, max(data_local) as ate
    from {{ ref('fct_ocupacao_hora') }}
),

soma as (
    select
        m.estacao_id,
        sum(m.viagens_perdidas) as viagens_perdidas,
        sum(m.devolucoes_barradas) as devolucoes_barradas,
        sum(m.minutos_vazia) / 60.0 as horas_vazia,
        sum(m.minutos_cheia) / 60.0 as horas_cheia,
        sum(m.minutos_observados) / 60.0 as horas_observadas
    from {{ ref('mart_demanda_perdida') }} m, periodo p
    where m.data_local between p.desde and p.ate
    group by 1
)

select
    rank() over (order by s.viagens_perdidas + s.devolucoes_barradas desc) as posicao,
    e.terminal,
    e.estacao_id,
    e.nome,
    e.lat,
    e.lon,
    e.docas,
    round(s.viagens_perdidas::numeric, 1) as viagens_perdidas,
    round(s.devolucoes_barradas::numeric, 1) as devolucoes_barradas,
    round((s.viagens_perdidas + s.devolucoes_barradas)::numeric, 1) as demanda_perdida,
    round(s.horas_vazia::numeric, 1) as horas_vazia,
    round(s.horas_cheia::numeric, 1) as horas_cheia,
    round(s.horas_observadas::numeric, 1) as horas_observadas,
    p.desde,
    p.ate
from soma s
join {{ ref('dim_estacoes') }} e using (estacao_id)
cross join periodo p
