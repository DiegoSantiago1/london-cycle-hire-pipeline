"""Agregados das viagens: exportar (PC -> repositório) e carregar (repositório -> banco).

Uso:
    python -m bicicletas.agregados exportar   # marts.agg_* -> dados/agregados/*.csv (no PC)
    python -m bicicletas.agregados carregar   # dados/agregados/*.csv -> schema agregados

Por que existe (D16): as 41 milhões de viagens ficam no PC. O job diário do GitHub
Actions só precisa dos resumos (alguns MB), versionados no repositório. Os dois
ambientes carregam os mesmos CSVs, então o dbt diário roda igual nos dois.
A exportação é determinística (ordem fixa): o diff do git só mostra mudança real.
"""

from __future__ import annotations

import argparse
import csv
import io
import sys
from dataclasses import dataclass
from pathlib import Path

import psycopg

from bicicletas.banco import Conexao, conectar
from bicicletas.config import RAIZ_PROJETO, ConfigError, carregar_config_banco

PASTA = RAIZ_PROJETO / "dados" / "agregados"


@dataclass(frozen=True)
class Tabela:
    nome: str
    colunas: tuple[str, ...]
    ordem: str


TABELAS = (
    Tabela(
        "demanda_estacao_hora",
        ("terminal", "dia_semana", "hora", "retiradas_media", "devolucoes_media"),
        "terminal, dia_semana, hora",
    ),
    Tabela(
        "fluxos_hora", ("hora", "posicao", "origem", "destino", "viagens_media"), "hora, posicao"
    ),
    Tabela(
        "viagens_mes",
        ("mes", "viagens", "duracao_mediana_min", "pct_eletricas", "dias_incompletos"),
        "mes",
    ),
    Tabela("estacoes_viagens", ("terminal", "nome", "retiradas_12m", "devolucoes_12m"), "terminal"),
)

CONSULTA_METADADOS = """
    SELECT chave, valor FROM (
        SELECT 'janela_inicio' AS chave, inicio_janela::text AS valor
            FROM intermediario.int_janela_viagens
        UNION ALL SELECT 'janela_fim', fim_janela::text FROM intermediario.int_janela_viagens
        UNION ALL SELECT 'viagens_total', count(*)::text FROM staging.stg_viagens
        UNION ALL SELECT 'viagens_primeira', min(inicio_local)::date::text FROM staging.stg_viagens
        UNION ALL SELECT 'viagens_ultima', max(inicio_local)::date::text FROM staging.stg_viagens
        UNION ALL SELECT 'arquivos', count(*)::text FROM controle.arquivos_viagens
        UNION ALL SELECT 'ultima_publicacao_tfl',
            to_char(max(publicado_em) AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS"Z"')
            FROM controle.arquivos_viagens
        UNION ALL SELECT 'arquivo_mais_recente', max(arquivo) FILTER (
            WHERE publicado_em = (SELECT max(publicado_em) FROM controle.arquivos_viagens))
            FROM controle.arquivos_viagens
    ) m ORDER BY chave
"""


class ErroAgregados(RuntimeError):
    """CSV de agregados ausente ou com cabeçalho inesperado."""


def _copiar_para_csv(con: Conexao, consulta: str) -> bytes:
    saida = io.BytesIO()
    with con.cursor().copy(f"COPY ({consulta}) TO STDOUT WITH (FORMAT csv, HEADER true)") as copia:
        for bloco in copia:
            saida.write(bloco)
    return saida.getvalue()


def exportar(con: Conexao, pasta: Path = PASTA) -> dict[str, int]:
    pasta.mkdir(parents=True, exist_ok=True)
    linhas: dict[str, int] = {}
    for t in TABELAS:
        consulta = f"SELECT {', '.join(t.colunas)} FROM marts.agg_{t.nome} ORDER BY {t.ordem}"  # noqa: S608 (nomes constantes)
        dados = _copiar_para_csv(con, consulta)
        (pasta / f"{t.nome}.csv").write_bytes(dados)
        linhas[t.nome] = dados.count(b"\n") - 1
    (pasta / "metadados.csv").write_bytes(_copiar_para_csv(con, CONSULTA_METADADOS))
    return linhas


def carregar(con: Conexao, pasta: Path = PASTA) -> dict[str, int]:
    """Substitui o conteúdo do schema agregados pelos CSVs, tudo numa transação."""
    linhas: dict[str, int] = {}
    tabelas = [*TABELAS, Tabela("metadados", ("chave", "valor"), "chave")]
    with con.transaction():
        for t in tabelas:
            caminho = pasta / f"{t.nome}.csv"
            if not caminho.exists():
                raise ErroAgregados(f"falta {caminho}: rode 'agregados exportar' no PC")
            dados = caminho.read_bytes()
            cabecalho = next(csv.reader(io.StringIO(dados.decode("utf-8"))), [])
            if tuple(cabecalho) != t.colunas:
                raise ErroAgregados(
                    f"{caminho.name}: cabeçalho {cabecalho}, esperado {list(t.colunas)}"
                )
            con.execute(f"TRUNCATE agregados.{t.nome}")
            comando = (
                f"COPY agregados.{t.nome} ({', '.join(t.colunas)}) "
                "FROM STDIN WITH (FORMAT csv, HEADER true)"
            )
            with con.cursor().copy(comando) as copia:
                copia.write(dados)
            linhas[t.nome] = dados.count(b"\n") - 1
    return linhas


def main(argumentos: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Exporta ou carrega os agregados das viagens.")
    parser.add_argument("acao", choices=["exportar", "carregar"])
    args = parser.parse_args(argumentos)
    try:
        with conectar(carregar_config_banco()) as con:
            con.autocommit = True
            linhas = exportar(con) if args.acao == "exportar" else carregar(con)
    except (ConfigError, ErroAgregados) as erro:
        print(f"Erro: {erro}", file=sys.stderr)
        return 1
    except psycopg.Error as erro:
        print(f"Erro no banco: {erro}", file=sys.stderr)
        return 1
    for nome, n in linhas.items():
        print(f"  {nome}: {n:,} linhas")
    return 0


if __name__ == "__main__":
    sys.exit(main())
