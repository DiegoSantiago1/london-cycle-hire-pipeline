-- Quanto o EventBridge Scheduler atrasa e quantas coletas chegam por dia (esperado: 96).
-- Compara com o cron do GitHub Actions, que em 11 a 13/10/2026 rodou só 4 a 5 vezes por dia.
SELECT
    data,
    count(*) AS coletas,
    round(approx_percentile(atraso_segundos, 0.5), 1) AS atraso_mediano_s,
    round(approx_percentile(atraso_segundos, 0.9), 1) AS atraso_p90_s,
    max(atraso_segundos) AS atraso_maximo_s
FROM coletas
GROUP BY data
ORDER BY data
