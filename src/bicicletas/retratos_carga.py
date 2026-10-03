"""Carga dos retratos da API (e dos registros de execução) em bruto.retratos.

Uso:
    python -m bicicletas.retratos_carga --pasta baixados/

A pasta pode ter os arquivos soltos (bikepoint_*.json.gz, execucao_*.json, como na
release do dia) e/ou pacotes diários (pacote_bikepoint_*.tar). O mesmo arquivo pode
aparecer solto e dentro do pacote: é carregado uma vez só.

Incremental e idempotente: arquivo já carregado com o mesmo SHA-256 é pulado. O bruto é
imutável, então o mesmo nome com conteúdo diferente é recusado.
"""

from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import re
import sys
import tarfile
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

import psycopg

from bicicletas.banco import Conexao, conectar
from bicicletas.config import ConfigError, carregar_config_banco

_NOME = re.compile(
    r"(?P<tipo>bikepoint|execucao)_(?P<d>\d{4}-\d{2}-\d{2})T(?P<h>\d{2})-(?P<m>\d{2})-(?P<s>\d{2})Z"
    r"\.(?:json\.gz|json)"
)
# Chave em additionalProperties -> coluna de bruto.retratos.
PROPRIEDADES = {
    "TerminalName": "terminal",
    "Installed": "instalada",
    "Locked": "bloqueada",
    "Temporary": "temporaria",
    "InstallDate": "data_instalacao",
    "RemovalDate": "data_remocao",
    "NbBikes": "bicicletas",
    "NbEmptyDocks": "vagas_livres",
    "NbDocks": "docas",
    "NbStandardBikes": "classicas",
    "NbEBikes": "eletricas",
}
COLUNAS_RETRATO = (
    "estacao_id",
    "nome",
    "lat",
    "lon",
    *PROPRIEDADES.values(),
    "atualizado_em",
)
CAMPOS_EXECUCAO = (
    "iniciado_em",
    "terminado_em",
    "status",
    "origem",
    "evento",
    "id_execucao",
    "tentativa_execucao",
    "chave_retrato",
    "estacoes",
    "bytes_brutos",
    "bytes_comprimidos",
    "sha256",
    "erro",
)


class ErroRetratos(RuntimeError):
    """Arquivo do bruto ao vivo inválido ou em conflito com o que já foi carregado."""


def instante(nome: str) -> datetime:
    m = _NOME.fullmatch(nome)
    if m is None:
        raise ErroRetratos(f"nome fora do padrão: {nome}")
    return datetime.fromisoformat(f"{m['d']}T{m['h']}:{m['m']}:{m['s']}+00:00")


def arquivos_da_pasta(pasta: Path) -> Iterator[tuple[str, bytes]]:
    """(nome, conteúdo) de cada arquivo do bruto na pasta, soltos e dentro dos pacotes."""
    vistos: dict[str, str] = {}

    def registrar(nome: str, dados: bytes) -> bool:
        soma = hashlib.sha256(dados).hexdigest()
        if nome in vistos:
            if vistos[nome] != soma:
                raise ErroRetratos(f"{nome} aparece com conteúdos diferentes na pasta")
            return False
        vistos[nome] = soma
        return True

    for caminho in sorted(pasta.iterdir()):
        if caminho.name.startswith("pacote_bikepoint_") and caminho.suffix == ".tar":
            with tarfile.open(caminho) as tar:
                for membro in tar.getmembers():
                    if membro.name == "manifesto.json" or not membro.isfile():
                        continue
                    extraido = tar.extractfile(membro)
                    if extraido is None:
                        continue
                    dados = extraido.read()
                    if registrar(membro.name, dados):
                        yield membro.name, dados
        elif _NOME.fullmatch(caminho.name):
            dados = caminho.read_bytes()
            if registrar(caminho.name, dados):
                yield caminho.name, dados


def linhas_do_retrato(conteudo_gz: bytes) -> list[tuple[str | None, ...]]:
    try:
        estacoes = json.loads(gzip.decompress(conteudo_gz))
    except (OSError, EOFError, ValueError) as erro:
        raise ErroRetratos(f"retrato ilegível: {erro}") from erro
    if not isinstance(estacoes, list):
        raise ErroRetratos("retrato não é uma lista de estações")
    linhas = []
    for estacao in estacoes:
        props: dict[str, Any] = {
            str(p.get("key")): p
            for p in estacao.get("additionalProperties", [])
            if isinstance(p, dict)
        }
        valores = {
            coluna: _texto(props.get(chave, {}).get("value"))
            for chave, coluna in PROPRIEDADES.items()
        }
        linhas.append(
            (
                _texto(estacao.get("id")),
                _texto(estacao.get("commonName")),
                _texto(estacao.get("lat")),
                _texto(estacao.get("lon")),
                *valores.values(),
                _texto(props.get("NbBikes", {}).get("modified")),
            )
        )
    return linhas


def _texto(valor: object) -> str | None:
    return None if valor is None else str(valor)


@dataclass
class Resumo:
    retratos: int = 0
    execucoes: int = 0
    iguais: int = 0
    linhas: int = 0


def carregar_arquivo(con: Conexao, nome: str, dados: bytes, resumo: Resumo) -> None:
    soma = hashlib.sha256(dados).hexdigest()
    quando = instante(nome)
    anterior = con.execute(
        "SELECT sha256 FROM controle.arquivos_retratos WHERE arquivo = %s", (nome,)
    ).fetchone()
    if anterior is not None:
        if anterior[0] != soma:
            raise ErroRetratos(f"{nome} já foi carregado com outro conteúdo: o bruto é imutável")
        resumo.iguais += 1
        return
    tipo = "retrato" if nome.startswith("bikepoint_") else "execucao"
    if tipo == "retrato":
        linhas = linhas_do_retrato(dados)
    else:
        try:
            registro = json.loads(dados)
        except ValueError as erro:
            raise ErroRetratos(f"{nome} não é JSON: {erro}") from erro
        linhas = [tuple(_texto(registro.get(c)) for c in CAMPOS_EXECUCAO)]
    with con.transaction():
        con.execute(
            "INSERT INTO controle.arquivos_retratos (arquivo, tipo, coletado_em, sha256, linhas) "
            "VALUES (%s, %s, %s, %s, %s)",
            (nome, tipo, quando, soma, len(linhas)),
        )
        if tipo == "retrato":
            colunas = ", ".join(("arquivo", "coletado_em", *COLUNAS_RETRATO))
            with con.cursor().copy(f"COPY bruto.retratos ({colunas}) FROM STDIN") as copia:
                for linha in linhas:
                    copia.write_row((nome, quando, *linha))
            resumo.retratos += 1
            resumo.linhas += len(linhas)
        else:
            colunas = ", ".join(("arquivo", *CAMPOS_EXECUCAO))
            marcadores = ", ".join(["%s"] * (len(CAMPOS_EXECUCAO) + 1))
            con.execute(
                f"INSERT INTO bruto.execucoes_coleta ({colunas}) VALUES ({marcadores})",  # noqa: S608 (colunas constantes)
                (nome, *linhas[0]),
            )
            resumo.execucoes += 1


def carregar_pasta(con: Conexao, pasta: Path) -> Resumo:
    resumo = Resumo()
    for nome, dados in arquivos_da_pasta(pasta):
        carregar_arquivo(con, nome, dados, resumo)
    return resumo


def main(argumentos: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Carrega retratos e execuções em bruto.")
    parser.add_argument("--pasta", required=True, type=Path)
    args = parser.parse_args(argumentos)
    try:
        config = carregar_config_banco()
        with conectar(config) as con:
            con.autocommit = True  # cada arquivo na sua própria transação
            resumo = carregar_pasta(con, args.pasta)
    except (ConfigError, ErroRetratos, OSError) as erro:
        print(f"Erro: {erro}", file=sys.stderr)
        return 1
    except psycopg.OperationalError as erro:
        print(f"Erro: banco inacessível ({erro}).", file=sys.stderr)
        return 1
    except psycopg.Error as erro:
        # Ex.: tabela inexistente (migração não aplicada): mensagem, não traceback.
        print(f"Erro no banco: {erro} (rodou as migrações?)", file=sys.stderr)
        return 1
    print(
        f"{resumo.retratos} retratos ({resumo.linhas:,} linhas de estação) e "
        f"{resumo.execucoes} execuções carregados; {resumo.iguais} já estavam no banco."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
