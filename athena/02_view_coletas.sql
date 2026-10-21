-- View `coletas`: uma linha por retrato, com o atraso em relação ao horário agendado (D50).
--
-- O EventBridge Scheduler dispara a Lambda nos minutos 7, 22, 37 e 52 de cada hora (UTC).
-- O nome do arquivo guarda o instante em que a coleta começou; o atraso é a distância até
-- o último horário agendado (sempre entre 0 e 15 minutos, porque as janelas são de 15 min).
CREATE OR REPLACE VIEW coletas AS
WITH arquivos AS (
    SELECT DISTINCT
        data,
        "$path" AS arquivo,
        date_parse(
            regexp_extract("$path", 'bikepoint_([0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}-[0-9]{2}-[0-9]{2})Z', 1),
            '%Y-%m-%dT%H-%i-%s'
        ) AS coletado_em_utc
    FROM retratos
)
SELECT
    data,
    coletado_em_utc,
    -- segundos desde o minuto 7 da hora, "dobrados" em janelas de 15 min (900 s)
    ((minute(coletado_em_utc) * 60 + second(coletado_em_utc) - 7 * 60) % 900 + 900) % 900 AS atraso_segundos,
    arquivo
FROM arquivos
