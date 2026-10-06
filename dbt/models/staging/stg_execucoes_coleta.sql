{#
  Execuções da coleta. Agendada = cron do GitHub (schedule) ou agendador externo, que
  chama o workflow pela API nos mesmos minutos. Para as agendadas, o horário previsto é o
  último horário do cron (minutos 7, 22, 37 e 52) até o início; o atraso é a diferença.
  Execução que atrasa mais de 15 min cai na janela seguinte: o atraso fica subestimado
  nesses casos raros, mas a execução "faltante" aparece na contagem de janelas sem coleta.
#}
{{ config(tags=['diario']) }}

with base as (
    select
        arquivo,
        iniciado_em::timestamptz as iniciado_em,
        terminado_em::timestamptz as terminado_em,
        status,
        origem,
        evento,
        id_execucao,
        estacoes::integer as estacoes,
        bytes_comprimidos::integer as bytes_comprimidos,
        erro
    from {{ source('bruto', 'execucoes_coleta') }}
)

select
    *,
    coalesce(evento in ('schedule', 'agendador_externo'), false) as agendada,
    case when evento in ('schedule', 'agendador_externo') then
        date_trunc('hour', iniciado_em)
        + make_interval(mins => case
            when extract(minute from iniciado_em) >= 52 then 52
            when extract(minute from iniciado_em) >= 37 then 37
            when extract(minute from iniciado_em) >= 22 then 22
            when extract(minute from iniciado_em) >= 7 then 7
            else -8 end)
    end as previsto_em
from base
