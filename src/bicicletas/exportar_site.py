"""Exporta os marts para site/dados/painel.json, o arquivo que a página lê.

Uso:
    python -m bicicletas.exportar_site

Roda depois do `dbt build` (que para tudo se um teste falha). Mesmo assim, o exportador
confere o mínimo antes de gravar e se recusa se faltar dado essencial: uma página com
números errados é pior que a página de ontem (lição do Projeto 3).
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

import psycopg
from psycopg.rows import dict_row

from bicicletas.config import RAIZ_PROJETO, ConfigError, carregar_config_banco

SAIDA = RAIZ_PROJETO / "site" / "dados" / "painel.json"
MINIMO_ESTACOES = 500
TOP_RANKING = 25


class ErroExportacao(RuntimeError):
    """Dado essencial ausente: a página não é atualizada."""


def _json(valor: object) -> object:
    if isinstance(valor, Decimal):
        return float(valor)
    if isinstance(valor, datetime):
        return valor.astimezone(UTC).isoformat().replace("+00:00", "Z")
    if isinstance(valor, date):
        return valor.isoformat()
    raise TypeError(f"tipo não serializável: {type(valor).__name__}")


def _linhas(con: psycopg.Connection[dict[str, Any]], sql: str) -> list[dict[str, Any]]:
    return con.execute(sql).fetchall()


def montar_painel(
    con: psycopg.Connection[dict[str, Any]],
    agora: datetime,
    minimo_estacoes: int = MINIMO_ESTACOES,
) -> dict[str, Any]:
    estacoes = _linhas(
        con,
        """
        SELECT terminal AS t, nome AS n, lat AS la, lon AS lo, docas AS d,
               retiradas_12m AS r12, devolucoes_12m AS d12
        FROM marts.dim_estacoes WHERE em_operacao ORDER BY terminal
        """,
    )
    if len(estacoes) < minimo_estacoes:
        raise ErroExportacao(f"só {len(estacoes)} estações em operação (mínimo {minimo_estacoes})")

    risco: dict[str, dict[str, list[float | None]]] = {}
    for r in _linhas(
        con,
        "SELECT terminal, tipo_dia, hora, pct_vazia, pct_cheia FROM marts.mart_risco_hora",
    ):
        item = risco.setdefault(
            r["terminal"],
            {k: [None] * 24 for k in ("util_v", "util_c", "fds_v", "fds_c")},
        )
        prefixo = "util" if r["tipo_dia"] == "util" else "fds"
        item[f"{prefixo}_v"][r["hora"]] = r["pct_vazia"]
        item[f"{prefixo}_c"][r["hora"]] = r["pct_cheia"]

    ranking = _linhas(
        con,
        f"""
        SELECT posicao, terminal, nome, lat, lon, docas, viagens_perdidas, devolucoes_barradas,
               demanda_perdida, horas_vazia, horas_cheia, horas_observadas, desde, ate
        FROM marts.mart_ranking_estacoes WHERE demanda_perdida > 0
        ORDER BY posicao, terminal LIMIT {TOP_RANKING}
        """,  # noqa: S608 (constante)
    )
    # Ranking vazio é um estado real (nos primeiros dias de coleta ainda não há perda
    # estimada) e não impede a publicação; a página explica. Essenciais são os agregados.

    # perfil típico de dia útil (média seg-sex) de cada estação, dos agregados das viagens
    perfil: dict[str, dict[str, list[float]]] = {}
    for r in _linhas(
        con,
        """
        SELECT terminal, hora, avg(retiradas_media) AS ret, avg(devolucoes_media) AS dev
        FROM agregados.demanda_estacao_hora WHERE dia_semana <= 5
        GROUP BY 1, 2
        """,
    ):
        tipico = perfil.setdefault(r["terminal"], {"ret": [0.0] * 24, "dev": [0.0] * 24})
        tipico["ret"][r["hora"]] = round(float(r["ret"]), 2)
        tipico["dev"][r["hora"]] = round(float(r["dev"]), 2)

    fluxos = _linhas(
        con,
        "SELECT hora, posicao, origem, destino, viagens_media FROM agregados.fluxos_hora "
        "ORDER BY hora, posicao",
    )
    tendencia = _linhas(con, "SELECT * FROM agregados.viagens_mes ORDER BY mes")
    if not perfil or not fluxos:
        raise ErroExportacao(
            "agregados das viagens vazios: rode 'python -m bicicletas.agregados carregar'"
        )
    metadados = {
        r["chave"]: r["valor"] for r in _linhas(con, "SELECT chave, valor FROM agregados.metadados")
    }
    saude = _linhas(con, "SELECT * FROM marts.mart_saude_coleta ORDER BY dia DESC LIMIT 30")
    frescor = _linhas(con, "SELECT * FROM marts.mart_frescor_api ORDER BY dia DESC LIMIT 30")
    coleta = _linhas(
        con,
        """
        SELECT min(coletado_em) AS desde, max(coletado_em) AS ultima,
               round(extract(epoch from max(coletado_em) - min(coletado_em)) / 3600.0, 1)
                   AS horas_coleta,
               count(DISTINCT arquivo) AS retratos,
               count(DISTINCT (coletado_em AT TIME ZONE 'Europe/London')::date) AS dias
        FROM staging.stg_retratos
        """,
    )[0]
    resumo = _linhas(
        con,
        """
        SELECT
            count(*) AS estacoes,
            count(*) FILTER (WHERE horas_vazia >= 1) AS vazias_1h,
            count(*) FILTER (WHERE horas_cheia >= 1) AS cheias_1h,
            round(sum(viagens_perdidas), 0) AS viagens_perdidas,
            round(sum(devolucoes_barradas), 0) AS devolucoes_barradas,
            round(sum(horas_vazia), 0) AS horas_vazia,
            round(sum(horas_cheia), 0) AS horas_cheia,
            min(desde) AS desde, max(ate) AS ate
        FROM marts.mart_ranking_estacoes
        """,
    )[0]
    return {
        "gerado_em": agora,
        "coleta": coleta,
        "resumo": resumo,
        "estacoes": estacoes,
        "risco": risco,
        "ranking": ranking,
        "perfil": perfil,
        "fluxos": fluxos,
        "tendencia": tendencia,
        "viagens": metadados,
        "saude": saude,
        "frescor": frescor,
    }


def main(argumentos: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Gera site/dados/painel.json a partir dos marts.")
    parser.add_argument("--saida", type=Path, default=SAIDA)
    args = parser.parse_args(argumentos)
    try:
        config = carregar_config_banco()
        with psycopg.connect(
            host=config.host,
            port=config.porta,
            dbname=config.nome,
            user=config.usuario,
            password=config.senha,
            connect_timeout=5,
            row_factory=dict_row,
        ) as con:
            painel = montar_painel(con, datetime.now(UTC))
    except (ConfigError, ErroExportacao) as erro:
        print(f"Exportação recusada: {erro}", file=sys.stderr)
        return 1
    except psycopg.Error as erro:
        print(f"Erro no banco: {erro}", file=sys.stderr)
        return 1
    args.saida.parent.mkdir(parents=True, exist_ok=True)
    texto = json.dumps(painel, default=_json, ensure_ascii=False, separators=(",", ":"))
    args.saida.write_text(texto, encoding="utf-8", newline="\n")
    print(f"{args.saida}: {len(texto) / 1024:.0f} KB, {len(painel['estacoes'])} estações")
    return 0


if __name__ == "__main__":
    sys.exit(main())
