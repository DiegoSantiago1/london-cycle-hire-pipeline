"""Pacote diário: junta os arquivos de um dia (UTC) num .tar, byte a byte, com manifesto.

Por que existe: o job diário precisa de 28 dias de retratos. Baixar ~96 arquivos por dia
seriam ~2.700 downloads por execução; com o pacote são 28. O pacote não substitui os
originais (eles continuam na release): é uma cópia empacotada, conferida por hash.

Só biblioteca padrão, como a coleta: roda no Actions sem instalar nada.

Uso (com os arquivos da release do dia já baixados numa pasta):
    python -m bicicletas.pacote_diario --dia 2026-10-03 --pasta baixados/ --saida pacote.tar
"""

from __future__ import annotations

import argparse
import gzip
import hashlib
import io
import json
import re
import sys
import tarfile
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

from bicicletas.coleta_api import ErroColeta, conferir

_NOME = re.compile(
    r"(?P<tipo>bikepoint|execucao)_(?P<dia>\d{4}-\d{2}-\d{2})T(?P<h>\d{2})-(?P<m>\d{2})-(?P<s>\d{2})Z"
    r"\.(?:json\.gz|json)"
)
MANIFESTO = "manifesto.json"


class ErroPacote(RuntimeError):
    """O pacote não pode ser montado sem perder ou corromper o bruto."""


def _instante(nome: str) -> datetime:
    m = _NOME.fullmatch(nome)
    if m is None:
        raise ErroPacote(f"nome fora do padrão: {nome}")
    return datetime.fromisoformat(f"{m['dia']}T{m['h']}:{m['m']}:{m['s']}+00:00")


def arquivos_do_dia(pasta: Path, dia: date) -> list[Path]:
    """Retratos e registros de execução do dia, em ordem de nome (= ordem de horário).

    Arquivo com nome fora do padrão na pasta é erro, e não é ignorado em silêncio: pode
    ser um retrato com nome corrompido.
    """
    escolhidos = []
    for caminho in sorted(pasta.iterdir()):
        if not caminho.is_file():
            continue
        if _NOME.fullmatch(caminho.name) is None:
            raise ErroPacote(f"arquivo inesperado na pasta: {caminho.name}")
        if _instante(caminho.name).date() == dia:
            escolhidos.append(caminho)
    return escolhidos


def _conferir_arquivo(caminho: Path) -> dict[str, Any]:
    dados = caminho.read_bytes()
    if caminho.name.startswith("bikepoint_"):
        try:
            estacoes = conferir(gzip.decompress(dados))
        except (OSError, EOFError, ErroColeta) as erro:
            raise ErroPacote(f"{caminho.name} corrompido: {erro}") from erro
    else:
        try:
            json.loads(dados)
        except ValueError as erro:
            raise ErroPacote(f"{caminho.name} não é JSON: {erro}") from erro
        estacoes = None
    return {
        "nome": caminho.name,
        "bytes": len(dados),
        "sha256": hashlib.sha256(dados).hexdigest(),
        "estacoes": estacoes,
    }


def _membro(nome: str, tamanho: int, instante: datetime) -> tarfile.TarInfo:
    """Cabeçalho determinístico: mesmo conteúdo, mesmo .tar (rodar de novo dá o mesmo hash)."""
    info = tarfile.TarInfo(nome)
    info.size = tamanho
    info.mtime = int(instante.timestamp())
    info.mode = 0o644
    info.uid = info.gid = 0
    info.uname = info.gname = ""
    return info


def montar_pacote(pasta: Path, dia: date, saida: Path) -> dict[str, Any]:
    """Monta o .tar do dia e devolve o manifesto. Recusa dia vazio e arquivo corrompido."""
    arquivos = arquivos_do_dia(pasta, dia)
    retratos = [a for a in arquivos if a.name.startswith("bikepoint_")]
    if not retratos:
        raise ErroPacote(f"nenhum retrato de {dia} em {pasta}")
    itens = [_conferir_arquivo(a) for a in arquivos]
    manifesto = {
        "dia": dia.isoformat(),
        "retratos": len(retratos),
        "execucoes": len(arquivos) - len(retratos),
        "arquivos": itens,
    }
    corpo_manifesto = (json.dumps(manifesto, ensure_ascii=False, indent=2) + "\n").encode()
    meia_noite = datetime(dia.year, dia.month, dia.day, tzinfo=UTC)
    # "x": falha se o pacote já existir (não sobrescreve). Fica FORA do try de propósito:
    # se o pacote já existe, o except abaixo não pode apagá-lo.
    tar = tarfile.open(saida, "x", format=tarfile.PAX_FORMAT)  # noqa: SIM115 (fechado no with)
    try:
        with tar:
            tar.addfile(
                _membro(MANIFESTO, len(corpo_manifesto), meia_noite), io.BytesIO(corpo_manifesto)
            )
            for caminho in arquivos:
                dados = caminho.read_bytes()
                tar.addfile(
                    _membro(caminho.name, len(dados), _instante(caminho.name)), io.BytesIO(dados)
                )
        verificar_pacote(saida, manifesto)
    except BaseException:
        # Pacote pela metade ou que não confere não pode ficar para trás e ser publicado.
        saida.unlink(missing_ok=True)
        raise
    return manifesto


def verificar_pacote(pacote: Path, manifesto: dict[str, Any]) -> None:
    """Relê o .tar e confere cada arquivo contra o hash do manifesto."""
    esperados = {item["nome"]: item["sha256"] for item in manifesto["arquivos"]}
    encontrados: dict[str, str] = {}
    with tarfile.open(pacote, "r") as tar:
        for membro in tar.getmembers():
            if membro.name == MANIFESTO:
                continue
            extraido = tar.extractfile(membro)
            if extraido is None:
                raise ErroPacote(f"{membro.name} não é um arquivo comum")
            encontrados[membro.name] = hashlib.sha256(extraido.read()).hexdigest()
    if encontrados != esperados:
        raise ErroPacote("o pacote não confere com o manifesto")


def conferir_dia_encerrado(dia: date, hoje: date) -> None:
    """Só empacota dia que já terminou (UTC).

    Um pacote de hoje sairia incompleto, e o job das 03:17 o veria como "já existe" e
    pularia: o pacote daquele dia ficaria sem as coletas do resto do dia.
    """
    if dia >= hoje:
        raise ErroPacote(
            f"{dia} ainda não terminou em UTC (hoje é {hoje}): pacote sairia incompleto"
        )


def main(argumentos: list[str] | None = None, hoje: date | None = None) -> int:
    parser = argparse.ArgumentParser(description="Empacota os retratos de um dia (UTC).")
    parser.add_argument("--dia", required=True, type=date.fromisoformat)
    parser.add_argument("--pasta", required=True, type=Path)
    parser.add_argument("--saida", required=True, type=Path)
    args = parser.parse_args(argumentos)
    try:
        conferir_dia_encerrado(args.dia, hoje or datetime.now(UTC).date())
        manifesto = montar_pacote(args.pasta, args.dia, args.saida)
    except ErroPacote as erro:
        print(f"ERRO no pacote: {erro}", file=sys.stderr)
        return 1
    except FileExistsError:
        print(f"ERRO no pacote: {args.saida} já existe (não sobrescreve).", file=sys.stderr)
        return 1
    print(
        f"{args.saida.name}: {manifesto['retratos']} retratos e "
        f"{manifesto['execucoes']} registros de execução de {manifesto['dia']}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
