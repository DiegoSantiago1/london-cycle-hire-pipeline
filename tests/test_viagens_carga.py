"""Testes da carga das viagens: as 6 variantes reais, idempotência, republicação e recusas.

As amostras em tests/dados/viagens/ são o cabeçalho e as 4 primeiras linhas de arquivos
reais da TfL, uma por variante de cabeçalho medida em 03/10/2026.
"""

import hashlib
import json
from pathlib import Path

import pytest

from bicicletas.banco import Conexao
from bicicletas.viagens_carga import (
    COLUNAS_BRUTO,
    ErroCarga,
    carregar_arquivo,
    ler_csv,
    reconhecer_cabecalho,
)

AMOSTRAS = Path(__file__).parent / "dados" / "viagens"
VARIANTES = sorted(p.name for p in AMOSTRAS.glob("*.csv"))


def preparar(pasta: Path, nome: str, conteudo: bytes, etag: str = "etag-1") -> Path:
    """Grava o CSV e o recibo que o download deixaria ao lado dele."""
    pasta.mkdir(parents=True, exist_ok=True)
    caminho = pasta / nome
    caminho.write_bytes(conteudo)
    recibo = {
        "arquivo": nome,
        "etag": etag,
        "publicado_em": "2026-06-09T10:00:00.000Z",
        "bytes": len(conteudo),
        "sha256": hashlib.sha256(conteudo).hexdigest(),
        "baixado_em": "2026-10-03T20:00:00+00:00",
    }
    (pasta / f"{nome}.recibo.json").write_text(json.dumps(recibo), encoding="utf-8")
    return caminho


# ---------------------------------------------------------------- unitários (sem banco)
def test_existem_as_seis_variantes_medidas() -> None:
    assert len(VARIANTES) == 6


@pytest.mark.parametrize("variante", VARIANTES)
def test_cada_variante_real_cai_nas_colunas_certas(variante: str) -> None:
    formato, linhas = ler_csv((AMOSTRAS / variante).read_bytes())
    lidas = list(linhas)
    assert len(lidas) == 4
    assert [n for n, _ in lidas] == [2, 3, 4, 5]  # número da linha no arquivo
    primeira = dict(zip(COLUNAS_BRUTO, lidas[0][1], strict=True))
    assert primeira["numero"] is not None and primeira["numero"].isdigit()
    assert primeira["estacao_inicio_nome"] and "," in primeira["estacao_inicio_nome"]
    assert primeira["inicio"] and primeira["fim"]
    if formato.vocabulario == "novo":
        assert primeira["modelo"] in {"CLASSIC", "PBSC_EBIKE"}
        assert primeira["duracao_ms"] is not None and primeira["duracao_ms"].isdigit()
        assert primeira["duracao_s"] is None
    else:
        assert primeira["duracao_s"] is not None and primeira["duracao_s"].isdigit()
        assert primeira["modelo"] is None


def test_colunas_em_outra_ordem_caem_no_mesmo_lugar() -> None:
    # novo_ordem_a.csv traz "Start station" antes de "Start station number".
    _, linhas = ler_csv((AMOSTRAS / "novo_ordem_a.csv").read_bytes())
    valores = dict(zip(COLUNAS_BRUTO, next(linhas)[1], strict=True))
    assert valores["estacao_inicio_numero"] is not None
    assert valores["estacao_inicio_numero"].isdigit()
    assert valores["estacao_inicio_nome"] is not None
    assert not valores["estacao_inicio_nome"].isdigit()


def test_arquivo_sem_id_de_destino_fica_com_destino_so_pelo_nome() -> None:
    _, linhas = ler_csv((AMOSTRAS / "antigo_sem_id_destino.csv").read_bytes())
    valores = dict(zip(COLUNAS_BRUTO, next(linhas)[1], strict=True))
    assert valores["estacao_fim_numero"] is None
    assert valores["estacao_fim_nome"]


@pytest.mark.parametrize(
    ("cabecalho", "mensagem"),
    [
        (["Number", "Start date", "Rider age"], "desconhecida"),
        (["Rental Id", "Number"], "mistura"),
        (["Number", "Number"], "repetida"),
        (["Number", "Start date"], "faltam colunas obrigatórias"),
    ],
    ids=["coluna_nova", "mistura", "repetida", "falta"],
)
def test_cabecalho_hostil_e_recusado(cabecalho: list[str], mensagem: str) -> None:
    with pytest.raises(ErroCarga, match=mensagem):
        reconhecer_cabecalho(cabecalho)


def test_espacos_em_volta_do_nome_da_coluna_sao_tolerados() -> None:
    novo = (AMOSTRAS / "novo.csv").read_bytes().split(b"\r\n")[0].decode()
    nomes = [f" {n.strip(chr(34))} " for n in novo.split(",")]
    assert reconhecer_cabecalho(nomes).vocabulario == "novo"


@pytest.mark.parametrize(
    ("conteudo", "mensagem"),
    [
        (b"", "vazio"),
        (b"\xff\xfeN\x00u\x00", "não é UTF-8"),
    ],
)
def test_arquivo_vazio_ou_com_encoding_errado(conteudo: bytes, mensagem: str) -> None:
    with pytest.raises(ErroCarga, match=mensagem):
        ler_csv(conteudo)


def test_linha_com_campo_a_mais_recusa_o_arquivo() -> None:
    conteudo = (AMOSTRAS / "antigo.csv").read_bytes() + b"1,2,3,4,5,6,7,8,9,10\r\n"
    _, linhas = ler_csv(conteudo)
    with pytest.raises(ErroCarga, match="linha 6: 10 campos"):
        list(linhas)


def test_linha_truncada_recusa_o_arquivo() -> None:
    conteudo = (AMOSTRAS / "novo.csv").read_bytes() + b'"999","2026-01-01 10:00"\r\n'
    _, linhas = ler_csv(conteudo)
    with pytest.raises(ErroCarga, match="linha 6: 2 campos"):
        list(linhas)


def test_aspas_sem_fechar_recusa_o_arquivo() -> None:
    conteudo = (AMOSTRAS / "novo.csv").read_bytes() + b'"999,"2026-01-01\r\n'
    _, linhas = ler_csv(conteudo)
    with pytest.raises(ErroCarga):
        list(linhas)


def test_cabecalho_com_bom_e_aceito() -> None:
    formato, _ = ler_csv(b"\xef\xbb\xbf" + (AMOSTRAS / "antigo.csv").read_bytes())
    assert formato.vocabulario == "antigo"


# ---------------------------------------------------------------- integração (banco)


def _contar(bd: Conexao, arquivo: str) -> int:
    linha = bd.execute(
        "SELECT count(*) FROM bruto.viagens WHERE arquivo = %s", (arquivo,)
    ).fetchone()
    assert linha is not None
    return int(linha[0])


@pytest.mark.integracao
@pytest.mark.parametrize("variante", VARIANTES)
def test_carga_de_cada_variante(bd: Conexao, tmp_path: Path, variante: str) -> None:
    nome = f"9{VARIANTES.index(variante)}JourneyDataExtract01Jan2026-02Jan2026.csv"
    caminho = preparar(tmp_path, nome, (AMOSTRAS / variante).read_bytes())
    r = carregar_arquivo(bd, caminho)
    assert (r.situacao, r.linhas) == ("carregado", 4)
    assert _contar(bd, nome) == 4
    controle = bd.execute(
        "SELECT linhas, etag, vocabulario FROM controle.arquivos_viagens WHERE arquivo = %s",
        (nome,),
    ).fetchone()
    assert controle is not None
    assert controle[0] == 4
    assert controle[1] == "etag-1"


@pytest.mark.integracao
def test_rodar_duas_vezes_nao_duplica(bd: Conexao, tmp_path: Path) -> None:
    caminho = preparar(tmp_path, "1JourneyDataExtract.csv", (AMOSTRAS / "novo.csv").read_bytes())
    assert carregar_arquivo(bd, caminho).situacao == "carregado"
    assert carregar_arquivo(bd, caminho).situacao == "igual"
    assert _contar(bd, caminho.name) == 4


@pytest.mark.integracao
def test_forcar_recarrega_sem_duplicar(bd: Conexao, tmp_path: Path) -> None:
    caminho = preparar(tmp_path, "1JourneyDataExtract.csv", (AMOSTRAS / "novo.csv").read_bytes())
    carregar_arquivo(bd, caminho)
    r = carregar_arquivo(bd, caminho, forcar=True)
    assert (r.situacao, r.linhas) == ("recarregado", 4)
    assert _contar(bd, caminho.name) == 4


@pytest.mark.integracao
def test_arquivo_republicado_substitui_a_versao_anterior(bd: Conexao, tmp_path: Path) -> None:
    original = (AMOSTRAS / "novo.csv").read_bytes()
    caminho = preparar(tmp_path, "1JourneyDataExtract.csv", original)
    carregar_arquivo(bd, caminho)
    # A TfL republica o arquivo sem a última linha (ETag e conteúdo novos).
    republicado = b"\r\n".join(original.split(b"\r\n")[:4]) + b"\r\n"
    preparar(tmp_path, caminho.name, republicado, etag="etag-2")
    r = carregar_arquivo(bd, caminho)
    assert (r.situacao, r.linhas) == ("recarregado", 3)
    assert _contar(bd, caminho.name) == 3
    etag = bd.execute(
        "SELECT etag FROM controle.arquivos_viagens WHERE arquivo = %s", (caminho.name,)
    ).fetchone()
    assert etag == ("etag-2",)


@pytest.mark.integracao
def test_falha_no_meio_desfaz_e_mantem_a_versao_anterior(bd: Conexao, tmp_path: Path) -> None:
    original = (AMOSTRAS / "novo.csv").read_bytes()
    caminho = preparar(tmp_path, "1JourneyDataExtract.csv", original)
    carregar_arquivo(bd, caminho)
    # Versão nova com uma linha quebrada no fim: a carga começa, falha e precisa desfazer.
    quebrado = original + b'"1","2"\r\n'
    preparar(tmp_path, caminho.name, quebrado, etag="etag-2")
    with pytest.raises(ErroCarga, match="linha 6"):
        carregar_arquivo(bd, caminho)
    assert _contar(bd, caminho.name) == 4  # a versão anterior continua inteira
    etag = bd.execute(
        "SELECT etag FROM controle.arquivos_viagens WHERE arquivo = %s", (caminho.name,)
    ).fetchone()
    assert etag == ("etag-1",)


@pytest.mark.integracao
def test_arquivo_sem_recibo_e_recusado(bd: Conexao, tmp_path: Path) -> None:
    caminho = tmp_path / "1JourneyDataExtract.csv"
    caminho.write_bytes((AMOSTRAS / "novo.csv").read_bytes())
    with pytest.raises(ErroCarga, match="sem recibo"):
        carregar_arquivo(bd, caminho)


@pytest.mark.integracao
def test_arquivo_alterado_depois_do_download_e_recusado(bd: Conexao, tmp_path: Path) -> None:
    caminho = preparar(tmp_path, "1JourneyDataExtract.csv", (AMOSTRAS / "novo.csv").read_bytes())
    caminho.write_bytes(caminho.read_bytes() + b"\r\n")
    with pytest.raises(ErroCarga, match="não confere com o recibo"):
        carregar_arquivo(bd, caminho)


@pytest.mark.integracao
def test_banco_recusa_nome_de_arquivo_hostil(bd: Conexao, tmp_path: Path) -> None:
    import psycopg

    # Conteúdo válido: a recusa tem de vir do CHECK do banco, não da leitura do CSV.
    conteudo = (AMOSTRAS / "novo.csv").read_bytes()
    caminho = preparar(tmp_path, "x'; DROP TABLE bruto.viagens; --.csv", conteudo)
    with pytest.raises(psycopg.errors.CheckViolation):
        carregar_arquivo(bd, caminho)
