-- Em que hora do dia (horário de Londres) as estações mais ficam sem bicicleta,
-- separando dias úteis e fim de semana. Só estações em operação.
SELECT
    CASE WHEN day_of_week(coletado_em_londres) IN (6, 7) THEN 'fim de semana' ELSE 'dia útil' END AS tipo_dia,
    hour(coletado_em_londres) AS hora,
    count(*) AS observacoes,
    round(100.0 * count_if(vazia) / count(*), 1) AS pct_vazias,
    round(100.0 * count_if(cheia) / count(*), 1) AS pct_cheias
FROM estacoes
WHERE em_operacao
GROUP BY 1, 2
ORDER BY 1, 2
