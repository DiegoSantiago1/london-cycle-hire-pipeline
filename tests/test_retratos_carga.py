"""Testes da carga dos retratos: soltos e em pacote, idempotência, imutabilidade, recusas."""

import gzip
import json
from datetime import date
from pathlib import Path

import pytest

from bicicletas.banco import Conexao
from bicicletas.pacote_diario import montar_pacote
from bicicletas.retratos_carga import (
    COLUNAS_RETRATO,
    ErroRetratos,
    Resumo,
    arquivos_da_pasta,
    carregar_arquivo,
    carregar_pasta,
    linhas_do_retrato,
)

from .test_coleta_api import AMOSTRA

RETRATO = "bikepoint_2026-10-03T17-22-05Z.json.gz"
EXECUCAO = "execucao_2026-10-03T17-22-05Z.json"
REGISTRO = {
    "iniciado_em": "2026-10-03T17:22:05+00:00",
    "status": "sucesso",
    "evento": "schedule",
    "estacoes": 120,
}


def _pasta(tmp_path: Path) -> Path:
    pasta = tmp_path / "baixados"
    pasta.mkdir()
    (pasta / RETRATO).write_bytes(gzip.compress(AMOSTRA, mtime=0))
    (pasta / EXECUCAO).write_text(json.dumps(REGISTRO), encoding="utf-8")
    return pasta


# ---------------------------------------------------------------- unitários
def test_linhas_do_retrato_real() -> None:
    linhas = linhas_do_retrato(gzip.compress(AMOSTRA, mtime=0))
    assert len(linhas) == 120
    primeira = dict(zip(COLUNAS_RETRATO, linhas[0], strict=True))
    assert primeira["estacao_id"] == "BikePoints_1"
    assert primeira["terminal"] == "001023"
    assert primeira["bicicletas"] is not None and primeira["bicicletas"].isdigit()
    assert primeira["atualizado_em"] is not None and primeira["atualizado_em"].endswith("Z")
    assert float(primeira["lat"] or 0) > 51


@pytest.mark.parametrize("conteudo", [b"nao e gzip", gzip.compress(b"{}"), gzip.compress(b"[")])
def test_retrato_ilegivel(conteudo: bytes) -> None:
    with pytest.raises(ErroRetratos):
        linhas_do_retrato(conteudo)


def test_arquivo_solto_e_no_pacote_aparece_uma_vez(tmp_path: Path) -> None:
    pasta = _pasta(tmp_path)
    montar_pacote(pasta, date(2026, 10, 3), pasta / "pacote_bikepoint_2026-10-03.tar")
    nomes = [n for n, _ in arquivos_da_pasta(pasta)]
    assert sorted(nomes) == [RETRATO, EXECUCAO]


def test_mesmo_nome_com_conteudos_diferentes_na_pasta(tmp_path: Path) -> None:
    pasta = _pasta(tmp_path)
    montar_pacote(pasta, date(2026, 10, 3), tmp_path / "pacote_bikepoint_2026-10-03.tar")
    (tmp_path / "pacote_bikepoint_2026-10-03.tar").rename(pasta / "pacote_bikepoint_2026-10-03.tar")
    (pasta / EXECUCAO).write_text('{"status": "outro"}', encoding="utf-8")
    with pytest.raises(ErroRetratos, match="conteúdos diferentes"):
        list(arquivos_da_pasta(pasta))


# ---------------------------------------------------------------- integração
@pytest.mark.integracao
def test_carrega_retrato_e_execucao(bd: Conexao, tmp_path: Path) -> None:
    resumo = carregar_pasta(bd, _pasta(tmp_path))
    assert (resumo.retratos, resumo.execucoes, resumo.linhas) == (1, 1, 120)
    linha = bd.execute(
        "SELECT count(*), min(coletado_em)::text FROM bruto.retratos WHERE arquivo = %s",
        (RETRATO,),
    ).fetchone()
    assert linha == (120, "2026-10-03 18:22:05+01")  # sessão em Europe/London (BST)
    status = bd.execute(
        "SELECT status, evento FROM bruto.execucoes_coleta WHERE arquivo = %s", (EXECUCAO,)
    ).fetchone()
    assert status == ("sucesso", "schedule")


@pytest.mark.integracao
def test_carregar_de_novo_nao_duplica(bd: Conexao, tmp_path: Path) -> None:
    pasta = _pasta(tmp_path)
    carregar_pasta(bd, pasta)
    resumo = carregar_pasta(bd, pasta)
    assert (resumo.retratos, resumo.execucoes, resumo.iguais) == (0, 0, 2)
    total = bd.execute("SELECT count(*) FROM bruto.retratos").fetchone()
    assert total == (120,)


@pytest.mark.integracao
def test_conteudo_diferente_para_nome_ja_carregado_e_recusado(bd: Conexao, tmp_path: Path) -> None:
    carregar_pasta(bd, _pasta(tmp_path))
    with pytest.raises(ErroRetratos, match="imutável"):
        carregar_arquivo(bd, EXECUCAO, b'{"status": "falha"}', Resumo())


@pytest.mark.integracao
def test_falha_no_meio_nao_deixa_controle_orfao(bd: Conexao) -> None:
    with pytest.raises(ErroRetratos):
        carregar_arquivo(bd, RETRATO, b"quebrado", Resumo())
    assert bd.execute("SELECT count(*) FROM controle.arquivos_retratos").fetchone() == (0,)
