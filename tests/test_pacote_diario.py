"""Testes do pacote diário: seleção do dia, integridade, determinismo e recusas."""

import gzip
import hashlib
import json
import tarfile
from datetime import UTC, date, datetime
from pathlib import Path

import pytest

from bicicletas.pacote_diario import (
    MANIFESTO,
    ErroPacote,
    arquivos_do_dia,
    main,
    montar_pacote,
    verificar_pacote,
)

from .test_coleta_api import AMOSTRA

DIA = date(2026, 10, 3)


def _retrato(pasta: Path, hora: str, conteudo: bytes = AMOSTRA) -> Path:
    caminho = pasta / f"bikepoint_{hora}.json.gz"
    caminho.write_bytes(gzip.compress(conteudo, mtime=0))
    return caminho


def _execucao(pasta: Path, hora: str) -> Path:
    caminho = pasta / f"execucao_{hora}.json"
    caminho.write_text(json.dumps({"status": "sucesso"}), encoding="utf-8")
    return caminho


@pytest.fixture
def pasta(tmp_path: Path) -> Path:
    p = tmp_path / "baixados"
    p.mkdir()
    _retrato(p, "2026-10-03T00-07-12Z")
    _execucao(p, "2026-10-03T00-07-12Z")
    _retrato(p, "2026-10-03T23-52-40Z")
    _execucao(p, "2026-10-03T23-52-40Z")
    # Vizinhos de outros dias: não podem entrar no pacote de 03/10.
    _retrato(p, "2026-10-02T23-59-59Z")
    _retrato(p, "2026-10-04T00-00-00Z")
    return p


def test_seleciona_so_o_dia_em_ordem(pasta: Path) -> None:
    nomes = [a.name for a in arquivos_do_dia(pasta, DIA)]
    assert nomes == [
        "bikepoint_2026-10-03T00-07-12Z.json.gz",
        "bikepoint_2026-10-03T23-52-40Z.json.gz",
        "execucao_2026-10-03T00-07-12Z.json",
        "execucao_2026-10-03T23-52-40Z.json",
    ]


def test_pacote_guarda_os_arquivos_byte_a_byte(pasta: Path, tmp_path: Path) -> None:
    saida = tmp_path / "pacote.tar"
    manifesto = montar_pacote(pasta, DIA, saida)
    assert manifesto["retratos"] == 2
    assert manifesto["execucoes"] == 2
    with tarfile.open(saida) as tar:
        nomes = tar.getnames()
        assert nomes[0] == MANIFESTO
        for nome in nomes[1:]:
            extraido = tar.extractfile(nome)
            assert extraido is not None
            assert extraido.read() == (pasta / nome).read_bytes()
        info = tar.getmember("bikepoint_2026-10-03T23-52-40Z.json.gz")
        assert info.mtime == int(datetime(2026, 10, 3, 23, 52, 40, tzinfo=UTC).timestamp())


def test_pacote_e_deterministico(pasta: Path, tmp_path: Path) -> None:
    # Rodar de novo com os mesmos arquivos gera exatamente o mesmo pacote (idempotente).
    montar_pacote(pasta, DIA, tmp_path / "a.tar")
    montar_pacote(pasta, DIA, tmp_path / "b.tar")
    hash_a = hashlib.sha256((tmp_path / "a.tar").read_bytes()).hexdigest()
    hash_b = hashlib.sha256((tmp_path / "b.tar").read_bytes()).hexdigest()
    assert hash_a == hash_b


def test_nao_sobrescreve_pacote_existente(pasta: Path, tmp_path: Path) -> None:
    saida = tmp_path / "pacote.tar"
    saida.write_bytes(b"ja existe")
    with pytest.raises(FileExistsError):
        montar_pacote(pasta, DIA, saida)
    assert saida.read_bytes() == b"ja existe"


def test_dia_sem_retratos_e_recusado(pasta: Path, tmp_path: Path) -> None:
    with pytest.raises(ErroPacote, match="nenhum retrato"):
        montar_pacote(pasta, date(2026, 10, 10), tmp_path / "p.tar")


def test_retrato_corrompido_e_recusado(pasta: Path, tmp_path: Path) -> None:
    (pasta / "bikepoint_2026-10-03T12-07-00Z.json.gz").write_bytes(b"\x1f\x8b nao e gzip")
    with pytest.raises(ErroPacote, match="corrompido"):
        montar_pacote(pasta, DIA, tmp_path / "p.tar")


def test_retrato_truncado_e_recusado(pasta: Path, tmp_path: Path) -> None:
    inteiro = gzip.compress(AMOSTRA, mtime=0)
    (pasta / "bikepoint_2026-10-03T12-07-00Z.json.gz").write_bytes(inteiro[: len(inteiro) // 2])
    with pytest.raises(ErroPacote, match="corrompido"):
        montar_pacote(pasta, DIA, tmp_path / "p.tar")


def test_retrato_sem_forma_de_bikepoint_e_recusado(pasta: Path, tmp_path: Path) -> None:
    _retrato(pasta, "2026-10-03T12-07-00Z", b"[]")
    with pytest.raises(ErroPacote, match="corrompido"):
        montar_pacote(pasta, DIA, tmp_path / "p.tar")


def test_execucao_que_nao_e_json_e_recusada(pasta: Path, tmp_path: Path) -> None:
    (pasta / "execucao_2026-10-03T12-07-00Z.json").write_text("{quebrado", encoding="utf-8")
    with pytest.raises(ErroPacote, match="não é JSON"):
        montar_pacote(pasta, DIA, tmp_path / "p.tar")


@pytest.mark.parametrize(
    "nome",
    ["bikepoint_2026-10-03.json.gz", "outro.txt", "bikepoint_2026-10-03T12-07-00Z.json.gz.1"],
)
def test_arquivo_com_nome_fora_do_padrao_e_recusado(pasta: Path, nome: str) -> None:
    (pasta / nome).write_bytes(b"x")
    with pytest.raises(ErroPacote, match="inesperado"):
        arquivos_do_dia(pasta, DIA)


def test_verificacao_pega_manifesto_que_nao_confere(pasta: Path, tmp_path: Path) -> None:
    saida = tmp_path / "pacote.tar"
    manifesto = montar_pacote(pasta, DIA, saida)
    manifesto["arquivos"][0]["sha256"] = "0" * 64
    with pytest.raises(ErroPacote, match="não confere"):
        verificar_pacote(saida, manifesto)


def test_main(pasta: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    saida = tmp_path / "pacote.tar"
    assert main(["--dia", "2026-10-03", "--pasta", str(pasta), "--saida", str(saida)]) == 0
    assert "2 retratos" in capsys.readouterr().out
    assert (
        main(["--dia", "2026-10-10", "--pasta", str(pasta), "--saida", str(tmp_path / "x.tar")])
        == 1
    )


def test_pacote_que_nao_confere_e_apagado(
    pasta: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from bicicletas import pacote_diario

    def falhar(*_: object) -> None:
        raise ErroPacote("o pacote não confere com o manifesto")

    monkeypatch.setattr(pacote_diario, "verificar_pacote", falhar)
    saida = tmp_path / "pacote.tar"
    with pytest.raises(ErroPacote):
        montar_pacote(pasta, DIA, saida)
    assert not saida.exists()


def test_main_com_pacote_existente(
    pasta: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    saida = tmp_path / "pacote.tar"
    saida.write_bytes(b"x")
    assert main(["--dia", "2026-10-03", "--pasta", str(pasta), "--saida", str(saida)]) == 1
    assert "já existe" in capsys.readouterr().err
