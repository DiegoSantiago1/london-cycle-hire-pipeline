"""Testes do download incremental: nomes, listagem paginada, recibo, republicação, falhas."""

import hashlib
import io
import json
from collections.abc import Callable
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

import pytest

from bicicletas.viagens_download import (
    ErroDownload,
    ObjetoTfl,
    baixar,
    caminho_recibo,
    ler_recibo,
    listar,
    periodo_do_nome,
    precisa_baixar,
    selecionar,
)

AGORA = datetime(2026, 10, 3, 20, 0, tzinfo=UTC)


@pytest.mark.parametrize(
    ("nome", "esperado"),
    [
        ("444JourneyDataExtract17May2026-31May2026.csv", (date(2026, 5, 17), date(2026, 5, 31))),
        ("298JourneyDataExtract29Dec2021-04Jan2022.csv", (date(2021, 12, 29), date(2022, 1, 4))),
        ("01aJourneyDataExtract10Jan16-23Jan16.csv", (date(2016, 1, 10), date(2016, 1, 23))),
        ("cyclehireusagestats-2014.zip", None),
        ("02aJourneyDataExtract07Fe16-20Feb2016.csv", None),  # "Fe": nome quebrado real
        ("1JourneyDataExtract31Feb2022-01Mar2022.csv", None),  # data impossível
    ],
)
def test_periodo_do_nome(nome: str, esperado: tuple[date, date] | None) -> None:
    assert periodo_do_nome(nome) == esperado


def _objeto(nome: str, tamanho: int = 3, etag: str = "e1") -> ObjetoTfl:
    return ObjetoTfl(f"usage-stats/{nome}", tamanho, etag, "2026-06-09T10:00:00.000Z")


def test_selecionar_filtra_por_fim_do_periodo_e_ordena() -> None:
    objetos = [
        _objeto("300JourneyDataExtract12Jan2022-18Jan2022.csv"),
        _objeto("298JourneyDataExtract29Dec2021-04Jan2022.csv"),  # termina em 2022: entra
        _objeto("297JourneyDataExtract22Dec2021-28Dec2021.csv"),  # só 2021: fica fora
        _objeto("2016TripDataZip.zip"),
        _objeto(""),  # o próprio prefixo "usage-stats/"
    ]
    nomes = [o.nome for o in selecionar(objetos, date(2022, 1, 1))]
    assert nomes == [
        "298JourneyDataExtract29Dec2021-04Jan2022.csv",
        "300JourneyDataExtract12Jan2022-18Jan2022.csv",
    ]


# ---------------------------------------------------------------- S3 falso
def _pagina(chaves: list[tuple[str, int, str]], proximo: str | None) -> bytes:
    itens = "".join(
        f"<Contents><Key>usage-stats/{k}</Key><LastModified>2026-06-09T10:00:00.000Z"
        f"</LastModified><ETag>&quot;{e}&quot;</ETag><Size>{s}</Size></Contents>"
        for k, s, e in chaves
    )
    token = f"<NextContinuationToken>{proximo}</NextContinuationToken>" if proximo else ""
    return (
        '<?xml version="1.0"?><ListBucketResult xmlns="http://s3.amazonaws.com/doc/2006-03-01/">'
        f"{itens}{token}</ListBucketResult>"
    ).encode()


def _s3(respostas: dict[str, bytes | Exception]) -> tuple[Callable[..., Any], list[str]]:
    pedidas: list[str] = []

    def abrir(url: str, timeout: float = 60) -> io.BytesIO:
        pedidas.append(url)
        for trecho, resposta in respostas.items():
            if trecho in url:
                if isinstance(resposta, Exception):
                    raise resposta
                return io.BytesIO(resposta)
        raise AssertionError(f"URL inesperada: {url}")

    return abrir, pedidas


def test_listar_segue_a_paginacao_do_s3() -> None:
    abrir, pedidas = _s3(
        {
            "continuation-token=PAG2": _pagina([("b.csv", 20, "e2")], None),
            "list-type=2": _pagina([("a.csv", 10, "e1")], "PAG2"),
        }
    )
    objetos = listar(abrir)
    assert [(o.nome, o.tamanho, o.etag) for o in objetos] == [
        ("a.csv", 10, "e1"),
        ("b.csv", 20, "e2"),
    ]
    assert len(pedidas) == 2


def test_listagem_sem_campo_obrigatorio_e_erro() -> None:
    xml = (
        b'<ListBucketResult xmlns="http://s3.amazonaws.com/doc/2006-03-01/">'
        b"<Contents><Key>usage-stats/a.csv</Key></Contents></ListBucketResult>"
    )
    abrir, _ = _s3({"list-type=2": xml})
    with pytest.raises(ErroDownload, match="sem Size"):
        listar(abrir)


# ---------------------------------------------------------------- download e recibo
def test_baixa_grava_recibo_com_sha256(tmp_path: Path) -> None:
    abrir, _ = _s3({"a.csv": b"abc"})
    recibo = baixar(_objeto("a.csv"), tmp_path, abrir, agora=lambda: AGORA)
    assert (tmp_path / "a.csv").read_bytes() == b"abc"
    assert recibo.sha256 == hashlib.sha256(b"abc").hexdigest()
    gravado = json.loads(caminho_recibo(tmp_path / "a.csv").read_text(encoding="utf-8"))
    assert gravado["etag"] == "e1"
    assert gravado["bytes"] == 3
    assert ler_recibo(tmp_path / "a.csv") == recibo


def test_download_truncado_nao_deixa_arquivo_nem_recibo(tmp_path: Path) -> None:
    abrir, _ = _s3({"a.csv": b"ab"})  # a listagem anunciou 3 bytes
    with pytest.raises(ErroDownload, match="recebidos 2 bytes"):
        baixar(_objeto("a.csv", tamanho=3), tmp_path, abrir)
    assert list(tmp_path.iterdir()) == []


def test_queda_no_meio_nao_deixa_parcial(tmp_path: Path) -> None:
    class Quebra(io.BytesIO):
        def read(self, n: int | None = -1) -> bytes:
            raise ConnectionResetError("caiu")

    def abrir(url: str, timeout: float = 60) -> io.BytesIO:
        return Quebra(b"")

    with pytest.raises(ConnectionResetError):
        baixar(_objeto("a.csv"), tmp_path, abrir)
    assert list(tmp_path.iterdir()) == []


def test_falha_no_download_novo_preserva_a_versao_anterior(tmp_path: Path) -> None:
    abrir, _ = _s3({"a.csv": b"abc"})
    baixar(_objeto("a.csv"), tmp_path, abrir)
    abrir_ruim, _ = _s3({"a.csv": b"x"})
    with pytest.raises(ErroDownload):
        baixar(_objeto("a.csv", tamanho=3, etag="e2"), tmp_path, abrir_ruim)
    assert (tmp_path / "a.csv").read_bytes() == b"abc"
    recibo = ler_recibo(tmp_path / "a.csv")
    assert recibo is not None and recibo.etag == "e1"


def test_precisa_baixar(tmp_path: Path) -> None:
    objeto = _objeto("a.csv")
    assert precisa_baixar(objeto, tmp_path)  # nunca baixado
    abrir, _ = _s3({"a.csv": b"abc"})
    baixar(objeto, tmp_path, abrir)
    assert not precisa_baixar(objeto, tmp_path)  # igual: não baixa de novo
    assert precisa_baixar(_objeto("a.csv", etag="e2"), tmp_path)  # republicado
    (tmp_path / "a.csv").write_bytes(b"ab")
    assert precisa_baixar(objeto, tmp_path)  # cópia local corrompida
    (tmp_path / "a.csv").unlink()
    assert precisa_baixar(objeto, tmp_path)  # recibo sem arquivo


def test_recibo_corrompido_e_erro(tmp_path: Path) -> None:
    (tmp_path / "a.csv").write_bytes(b"abc")
    caminho_recibo(tmp_path / "a.csv").write_text("{quebrado", encoding="utf-8")
    with pytest.raises(ErroDownload, match="recibo inválido"):
        ler_recibo(tmp_path / "a.csv")
