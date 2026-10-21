-- As 15 estações que passaram mais tempo sem bicicleta nos últimos 7 dias.
-- O filtro em `data` é uma constante (calculada de current_date, em UTC): com a projeção
-- de partições, o Athena só lê as pastas desses dias (conferido pelos bytes lidos).
SELECT
    terminal,
    nome,
    count(*) AS retratos,
    round(100.0 * count_if(vazia) / count(*), 1) AS pct_tempo_vazia,
    round(100.0 * count_if(cheia) / count(*), 1) AS pct_tempo_cheia
FROM estacoes
WHERE em_operacao
  AND data >= CAST(current_date - INTERVAL '7' DAY AS VARCHAR)
GROUP BY terminal, nome
ORDER BY pct_tempo_vazia DESC, retratos DESC
LIMIT 15
