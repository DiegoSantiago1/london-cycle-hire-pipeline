"""Carga incremental dos CSVs de viagens em bruto.viagens.

Uso:
    python -m bicicletas.viagens_carga            # carrega o que é novo ou mudou
    python -m bicicletas.viagens_carga --forcar   # recarrega tudo

Regras (docs/DECISOES.md D19 e D31):
- Cada coluna é reconhecida pelo NOME, em qualquer ordem. O arquivo precisa usar só um
  dos dois vocabulários da TfL (antigo, até set/2022; novo, depois). Coluna desconhecida,
  repetida ou obrigatória faltando: o arquivo é recusado (é assim que uma mudança de
  formato da fonte aparece, em vez de virar dado errado em silêncio).
- Linha com número de campos diferente do cabeçalho: o arquivo é recusado.
- Cada arquivo é carregado numa transação: apaga as linhas daquele arquivo, insere de
  novo e registra a versão em controle.arquivos_viagens. Rodar duas vezes não duplica;
  arquivo republicado (SHA-256 diferente) substitui a versão anterior; uma falha no meio
  desfaz tudo e deixa a versão anterior intacta.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import io
import sys
import time
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

import psycopg

from bicicletas.banco import Conexao, conectar
from bicicletas.config import ConfigError, carregar_config_banco
from bicicletas.viagens_download import ErroDownload, ler_recibo, pasta_viagens

# Coluna da TfL -> coluna de bruto.viagens.
ANTIGO = {
    "Rental Id": "numero",
    "Duration": "duracao_s",
    "Bike Id": "bicicleta",
    "End Date": "fim",
    "EndStation Id": "estacao_fim_numero",
    "EndStation Name": "estacao_fim_nome",
    "Start Date": "inicio",
    "StartStation Id": "estacao_inicio_numero",
    "StartStation Name": "estacao_inicio_nome",
}
NOVO = {
    "Number": "numero",
    "Start date": "inicio",
    "Start station number": "estacao_inicio_numero",
    "Start station": "estacao_inicio_nome",
    "End date": "fim",
    "End station number": "estacao_fim_numero",
    "End station": "estacao_fim_nome",
    "Bike number": "bicicleta",
    "Bike model": "modelo",
    "Total duration": "duracao_texto",
    "Total duration (ms)": "duracao_ms",
}
VOCABULARIOS = {"antigo": ANTIGO, "novo": NOVO}
# Medido em 03/10/2026: o arquivo 325 (jul/2022) veio sem "EndStation Id"; o destino
# dele só pode ser ligado pelo nome da estação (feito no dbt).
OPCIONAIS = {"antigo": {"EndStation Id"}, "novo": set()}
COLUNAS_BRUTO = (
    "numero",
    "inicio",
    "fim",
    "estacao_inicio_numero",
    "estacao_inicio_nome",
    "estacao_fim_numero",
    "estacao_fim_nome",
    "bicicleta",
    "modelo",
    "duracao_s",
    "duracao_texto",
    "duracao_ms",
)


class ErroCarga(RuntimeError):
    """O arquivo não pode ser carregado sem risco de dado errado."""


@dataclass(frozen=True)
class Formato:
    vocabulario: str
    # Para cada coluna de bruto.viagens, a posição no CSV (None = coluna não veio).
    posicoes: dict[str, int | None]
    campos: int
    cabecalho: str


def reconhecer_cabecalho(campos: list[str]) -> Formato:
    nomes = [c.strip() for c in campos]
    if len(set(nomes)) != len(nomes):
        raise ErroCarga(f"cabeçalho com coluna repetida: {nomes}")
    candidatos = [v for v, mapa in VOCABULARIOS.items() if set(nomes) <= mapa.keys()]
    if not candidatos:
        conhecidos = ANTIGO.keys() | NOVO.keys()
        desconhecidas = [n for n in nomes if n not in conhecidos]
        if desconhecidas:
            raise ErroCarga(f"coluna desconhecida: {desconhecidas} (a TfL mudou o formato?)")
        raise ErroCarga(f"cabeçalho mistura os vocabulários antigo e novo: {nomes}")
    vocabulario = candidatos[0]
    mapa = VOCABULARIOS[vocabulario]
    faltando = [c for c in mapa if c not in nomes and c not in OPCIONAIS[vocabulario]]
    if faltando:
        raise ErroCarga(f"faltam colunas obrigatórias ({vocabulario}): {faltando}")
    posicao_por_destino = {mapa[nome]: i for i, nome in enumerate(nomes)}
    return Formato(
        vocabulario=vocabulario,
        posicoes={c: posicao_por_destino.get(c) for c in COLUNAS_BRUTO},
        campos=len(nomes),
        cabecalho=",".join(nomes),
    )


def ler_csv(conteudo: bytes) -> tuple[Formato, Iterator[tuple[int, list[str | None]]]]:
    """Reconhece o cabeçalho e devolve as linhas já na ordem de COLUNAS_BRUTO.

    O iterador levanta ErroCarga na primeira linha com número errado de campos (dentro
    da transação, o que desfaz a carga do arquivo).
    """
    try:
        texto = conteudo.decode("utf-8-sig")
    except UnicodeDecodeError as erro:
        raise ErroCarga(f"arquivo não é UTF-8 (byte {erro.start})") from erro
    leitor = csv.reader(io.StringIO(texto, newline=""), strict=True)
    try:
        cabecalho = next(leitor)
    except StopIteration:
        raise ErroCarga("arquivo vazio") from None
    formato = reconhecer_cabecalho(cabecalho)

    def linhas() -> Iterator[tuple[int, list[str | None]]]:
        try:
            for campos in leitor:
                numero = leitor.line_num
                if len(campos) != formato.campos:
                    raise ErroCarga(
                        f"linha {numero}: {len(campos)} campos, o cabeçalho tem {formato.campos}"
                    )
                yield (
                    numero,
                    [
                        None if (p := formato.posicoes[c]) is None or campos[p] == "" else campos[p]
                        for c in COLUNAS_BRUTO
                    ],
                )
        except csv.Error as erro:
            raise ErroCarga(f"linha {leitor.line_num}: CSV malformado ({erro})") from erro

    return formato, linhas()


@dataclass(frozen=True)
class Resultado:
    arquivo: str
    situacao: str  # "carregado", "recarregado" ou "igual"
    linhas: int
    segundos: float


def carregar_arquivo(con: Conexao, csv_path: Path, forcar: bool = False) -> Resultado:
    """Carrega um CSV (com o recibo do download ao lado) numa única transação."""
    inicio = time.perf_counter()
    recibo = ler_recibo(csv_path)
    if recibo is None:
        raise ErroCarga(f"{csv_path.name} sem recibo: baixe com bicicletas.viagens_download")
    conteudo = csv_path.read_bytes()
    sha256 = hashlib.sha256(conteudo).hexdigest()
    if sha256 != recibo.sha256:
        raise ErroCarga(f"{csv_path.name} não confere com o recibo (arquivo local alterado?)")

    anterior = con.execute(
        "SELECT sha256 FROM controle.arquivos_viagens WHERE arquivo = %s", (csv_path.name,)
    ).fetchone()
    if anterior is not None and anterior[0] == sha256 and not forcar:
        return Resultado(csv_path.name, "igual", 0, time.perf_counter() - inicio)

    formato, linhas = ler_csv(conteudo)
    with con.transaction():
        con.execute("DELETE FROM bruto.viagens WHERE arquivo = %s", (csv_path.name,))
        con.execute(
            """
            INSERT INTO controle.arquivos_viagens
                (arquivo, etag, bytes, sha256, publicado_em, vocabulario, cabecalho, linhas)
            VALUES (%s, %s, %s, %s, %s, %s, %s, 0)
            ON CONFLICT (arquivo) DO UPDATE SET
                etag = EXCLUDED.etag, bytes = EXCLUDED.bytes, sha256 = EXCLUDED.sha256,
                publicado_em = EXCLUDED.publicado_em, vocabulario = EXCLUDED.vocabulario,
                cabecalho = EXCLUDED.cabecalho, linhas = 0, carregado_em = now()
            """,
            (
                csv_path.name,
                recibo.etag,
                recibo.bytes,
                sha256,
                recibo.publicado_em,
                formato.vocabulario,
                formato.cabecalho,
            ),
        )
        total = 0
        colunas = ", ".join(("arquivo", "linha", *COLUNAS_BRUTO))
        with con.cursor().copy(f"COPY bruto.viagens ({colunas}) FROM STDIN") as copia:
            for numero, valores in linhas:
                copia.write_row((csv_path.name, numero, *valores))
                total += 1
        con.execute(
            "UPDATE controle.arquivos_viagens SET linhas = %s WHERE arquivo = %s",
            (total, csv_path.name),
        )
    situacao = "carregado" if anterior is None else "recarregado"
    return Resultado(csv_path.name, situacao, total, time.perf_counter() - inicio)


def main(argumentos: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Carrega os CSVs de viagens em bruto.viagens.")
    parser.add_argument("--forcar", action="store_true", help="recarrega mesmo sem mudança")
    args = parser.parse_args(argumentos)
    try:
        pasta = pasta_viagens()
        config = carregar_config_banco()
    except ConfigError as erro:
        print(f"Erro: {erro}", file=sys.stderr)
        return 1
    arquivos = sorted(pasta.glob("*.csv"))
    print(f"{len(arquivos)} arquivos em {pasta}", flush=True)
    erros = 0
    try:
        with conectar(config) as con:
            # autocommit: cada con.transaction() de carregar_arquivo vira uma transação de
            # verdade (sem isso, o primeiro SELECT abriria uma transação implícita e cada
            # arquivo seria só um savepoint dentro dela, sem commit).
            con.autocommit = True
            for csv_path in arquivos:
                try:
                    r = carregar_arquivo(con, csv_path, forcar=args.forcar)
                except (ErroCarga, ErroDownload) as erro:
                    erros += 1
                    print(f"  RECUSADO {csv_path.name}: {erro}", file=sys.stderr, flush=True)
                    continue
                if r.situacao != "igual":
                    print(
                        f"  {r.situacao:11s} {r.arquivo}  {r.linhas:>9,} linhas  "
                        f"{r.segundos:5.1f} s",
                        flush=True,
                    )
    except psycopg.OperationalError as erro:
        print(f"Erro: banco inacessível ({erro}).", file=sys.stderr)
        return 1
    except psycopg.Error as erro:
        # Ex.: tabela inexistente (migração não aplicada): mensagem, não traceback.
        print(f"Erro no banco: {erro} (rodou as migrações?)", file=sys.stderr)
        return 1
    print(f"Fim: {len(arquivos) - erros} arquivos ok, {erros} recusados.")
    return 1 if erros else 0


if __name__ == "__main__":
    sys.exit(main())
