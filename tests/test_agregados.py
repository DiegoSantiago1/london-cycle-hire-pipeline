"""Testes da carga dos agregados (CSV do repositório -> schema agregados)."""

from pathlib import Path

import psycopg
import pytest

from bicicletas.agregados import TABELAS, ErroAgregados, carregar
from bicicletas.banco import Conexao

CSV_VALIDOS = {
    "demanda_estacao_hora": (
        "terminal,dia_semana,hora,retiradas_media,devolucoes_media\n"
        "001023,1,8,2.5000,0.7500\n001023,1,9,1.0000,0.2500\n"
    ),
    "fluxos_hora": "hora,posicao,origem,destino,viagens_media\n8,1,001023,001018,3.200\n",
    "viagens_mes": (
        "mes,viagens,duracao_mediana_min,pct_eletricas,dias_incompletos\n"
        "2025-06-01,1000,14.2,0.1200,0\n"
    ),
    "estacoes_viagens": (
        'terminal,nome,retiradas_12m,devolucoes_12m\n001023,"River Street, Clerkenwell",900,850\n'
    ),
    "metadados": "chave,valor\njanela_fim,2026-06-01\nviagens_total,41376421\n",
}


def _pasta(tmp_path: Path, **trocas: str) -> Path:
    for nome, conteudo in {**CSV_VALIDOS, **trocas}.items():
        (tmp_path / f"{nome}.csv").write_text(conteudo, encoding="utf-8", newline="\n")
    return tmp_path


def test_todas_as_tabelas_tem_csv_de_teste() -> None:
    assert {t.nome for t in TABELAS} | {"metadados"} == CSV_VALIDOS.keys()


@pytest.mark.integracao
def test_carrega_todos_os_csvs(bd: Conexao, tmp_path: Path) -> None:
    linhas = carregar(bd, _pasta(tmp_path))
    assert linhas["demanda_estacao_hora"] == 2
    nome = bd.execute("SELECT nome FROM agregados.estacoes_viagens").fetchone()
    assert nome == ("River Street, Clerkenwell",)  # vírgula dentro de aspas


@pytest.mark.integracao
def test_carregar_de_novo_substitui_sem_duplicar(bd: Conexao, tmp_path: Path) -> None:
    carregar(bd, _pasta(tmp_path))
    carregar(bd, _pasta(tmp_path))
    assert bd.execute("SELECT count(*) FROM agregados.demanda_estacao_hora").fetchone() == (2,)


@pytest.mark.integracao
def test_cabecalho_errado_e_recusado_e_nada_muda(bd: Conexao, tmp_path: Path) -> None:
    carregar(bd, _pasta(tmp_path))
    ruim = tmp_path / "ruim"
    ruim.mkdir()
    _pasta(ruim, viagens_mes="mes,viagens\n2025-06-01,1000\n")
    with pytest.raises(ErroAgregados, match="cabeçalho"):
        carregar(bd, ruim)
    # a transação desfez o TRUNCATE das tabelas anteriores
    assert bd.execute("SELECT count(*) FROM agregados.demanda_estacao_hora").fetchone() == (2,)


@pytest.mark.integracao
def test_csv_faltando_e_recusado(bd: Conexao, tmp_path: Path) -> None:
    _pasta(tmp_path)
    (tmp_path / "fluxos_hora.csv").unlink()
    with pytest.raises(ErroAgregados, match="falta"):
        carregar(bd, tmp_path)


@pytest.mark.integracao
def test_valor_invalido_e_barrado_pelo_banco(bd: Conexao, tmp_path: Path) -> None:
    ruim = (
        "terminal,dia_semana,hora,retiradas_media,devolucoes_media\n"
        "1023,8,8,2.5,0.75\n"  # terminal sem zeros e dia da semana 8
    )
    with pytest.raises(psycopg.errors.CheckViolation):
        carregar(bd, _pasta(tmp_path, demanda_estacao_hora=ruim))
