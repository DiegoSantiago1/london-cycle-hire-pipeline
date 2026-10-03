{#
  Demanda perdida estimada por estação e hora (D17):
    viagens perdidas    = horas vazia × retiradas típicas naquela estação, dia e hora
    devoluções barradas = horas cheia × devoluções típicas naquela estação, dia e hora
  "Típicas" vem das viagens dos 12 meses publicados mais recentes (agregados).

  Limitação, dita na página: é uma estimativa conservadora. As viagens históricas só
  aconteceram quando havia bicicleta, então a taxa típica já subestima a procura real
  nos horários em que a estação costuma esvaziar.
#}
{{ config(tags=['diario']) }}

select
    o.estacao_id,
    o.terminal,
    o.data_local,
    o.dia_semana,
    o.hora,
    o.minutos_observados,
    o.minutos_vazia,
    o.minutos_cheia,
    coalesce(d.retiradas_media, 0) as retiradas_tipicas_hora,
    coalesce(d.devolucoes_media, 0) as devolucoes_tipicas_hora,
    round(o.minutos_vazia / 60.0 * coalesce(d.retiradas_media, 0), 4) as viagens_perdidas,
    round(o.minutos_cheia / 60.0 * coalesce(d.devolucoes_media, 0), 4) as devolucoes_barradas
from {{ ref('fct_ocupacao_hora') }} o
left join {{ source('agregados', 'demanda_estacao_hora') }} d
    on d.terminal = o.terminal and d.dia_semana = o.dia_semana and d.hora = o.hora
