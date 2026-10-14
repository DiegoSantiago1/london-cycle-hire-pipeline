"""Testes da coleta ao vivo: chaves, download com novas tentativas, conferência, gravação.

A amostra em tests/dados/ são as 120 primeiras estações de uma resposta real da API
(03/10/2026), para os testes usarem a forma verdadeira dos dados.
"""

import gzip
import io
import json
import urllib.error
from collections.abc import Callable
from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import pytest

from bicicletas import coleta_api
from bicicletas.coleta_api import (
    MINIMO_ESTACOES,
    DestinoLocal,
    ErroColeta,
    Retrato,
    baixar,
    chave_execucao,
    chave_retrato,
    coletar,
    conferir,
    executar,
)

AMOSTRA = gzip.decompress(
    (Path(__file__).parent / "dados" / "bikepoint_amostra.json.gz").read_bytes()
)
INSTANTE = datetime(2026, 10, 3, 17, 22, 5, tzinfo=UTC)
CTX_LOCAL: dict[str, str | None] = {
    "origem": "local",
    "evento": None,
    "id_execucao": None,
    "tentativa_execucao": None,
}


# ---------------------------------------------------------------- chaves
def test_chave_retrato_no_formato_do_s3() -> None:
    assert chave_retrato(INSTANTE) == (
        "bruto/bikepoint/data=2026-10-03/bikepoint_2026-10-03T17-22-05Z.json.gz"
    )
    assert chave_execucao(INSTANTE) == (
        "bruto/execucoes_coleta/data=2026-10-03/execucao_2026-10-03T17-22-05Z.json"
    )


def test_chave_converte_horario_de_londres_para_utc() -> None:
    # 00:30 de 04/10 no horário de verão de Londres (UTC+1) ainda é 03/10 em UTC.
    bst = datetime(2026, 10, 4, 0, 30, tzinfo=timezone(timedelta(hours=1)))
    assert chave_retrato(bst).startswith(
        "bruto/bikepoint/data=2026-10-03/bikepoint_2026-10-03T23-30"
    )


def test_chave_recusa_horario_sem_fuso() -> None:
    with pytest.raises(ValueError, match="sem fuso"):
        chave_retrato(datetime(2026, 10, 3, 17, 22))


# ---------------------------------------------------------------- download
class _Resposta(io.BytesIO):
    """Imita o objeto devolvido por urlopen (context manager com read())."""


def _abridor(roteiro: list[bytes | Exception]) -> tuple[Callable[..., Any], list[float]]:
    """Abridor falso: cada chamada consome o próximo item do roteiro."""
    chamadas: list[float] = []

    def abrir(pedido: Any, timeout: float) -> _Resposta:
        chamadas.append(timeout)
        item = roteiro.pop(0)
        if isinstance(item, Exception):
            raise item
        return _Resposta(item)

    return abrir, chamadas


def _http(codigo: int) -> urllib.error.HTTPError:
    return urllib.error.HTTPError(coleta_api.URL_BIKEPOINT, codigo, "erro", {}, None)  # type: ignore[arg-type]


def test_baixar_de_primeira() -> None:
    abrir, chamadas = _abridor([b"ok"])
    esperas: list[float] = []
    assert baixar(abrir=abrir, dormir=esperas.append) == b"ok"
    assert len(chamadas) == 1
    assert esperas == []


@pytest.mark.parametrize(
    "criar_falha",
    [
        # Criadas só dentro do teste: um HTTPError criado na coleta do pytest e nunca
        # usado deixaria a resposta aberta (ResourceWarning).
        lambda: _http(503),
        lambda: _http(500),
        lambda: _http(429),
        lambda: urllib.error.URLError("sem rede"),
        lambda: TimeoutError("lento"),
        lambda: ConnectionResetError("caiu"),
    ],
    ids=["503", "500", "429", "sem_rede", "timeout", "conexao_caiu"],
)
def test_falha_temporaria_tenta_de_novo(criar_falha: Callable[[], Exception]) -> None:
    abrir, chamadas = _abridor([criar_falha(), b"ok"])
    esperas: list[float] = []
    assert baixar(abrir=abrir, dormir=esperas.append) == b"ok"
    assert len(chamadas) == 2
    assert esperas == [5.0]


def test_desiste_depois_de_tres_tentativas_com_espera_crescente() -> None:
    abrir, chamadas = _abridor([_http(503), _http(503), _http(503)])
    esperas: list[float] = []
    with pytest.raises(ErroColeta, match=r"falhou 3 vezes.*HTTP 503"):
        baixar(abrir=abrir, dormir=esperas.append)
    assert len(chamadas) == 3
    assert esperas == [5.0, 10.0]  # não espera depois da última


@pytest.mark.parametrize("codigo", [400, 401, 403, 404])
def test_erro_que_nao_e_temporario_nao_tenta_de_novo(codigo: int) -> None:
    abrir, chamadas = _abridor([_http(codigo), b"nunca chega aqui"])
    esperas: list[float] = []
    with pytest.raises(ErroColeta, match=f"HTTP {codigo}"):
        baixar(abrir=abrir, dormir=esperas.append)
    assert len(chamadas) == 1
    assert esperas == []


def test_pedido_tem_timeout() -> None:
    abrir, chamadas = _abridor([b"ok"])
    baixar(abrir=abrir, dormir=lambda _: None)
    assert chamadas == [coleta_api.TIMEOUT_S]


# ---------------------------------------------------------------- conferência
def _estacao(i: int, **sem: bool) -> dict[str, Any]:
    props = [
        {"key": k, "value": "1"}
        for k in ("TerminalName", "NbBikes", "NbEmptyDocks", "NbDocks")
        if not sem.get(k)
    ]
    return {"id": f"BikePoints_{i}", "additionalProperties": props}


def _lista(n: int = MINIMO_ESTACOES, **sem: bool) -> bytes:
    return json.dumps([_estacao(i, **sem) for i in range(n)]).encode()


def test_amostra_real_passa() -> None:
    assert conferir(AMOSTRA) == 120


@pytest.mark.parametrize(
    ("conteudo", "mensagem"),
    [
        (b"<html><body>Service Unavailable</body></html>", "não é JSON"),
        (b"", "não é JSON"),
        (b'{"message": "rate limit"}', "esperava uma lista"),
        (b"[]", "só 0 estações"),
        (b"null", "esperava uma lista"),
        (_lista(MINIMO_ESTACOES - 1), f"só {MINIMO_ESTACOES - 1} estações"),
        (json.dumps([1] * MINIMO_ESTACOES).encode(), "não é uma estação"),
        (json.dumps([{"id": 7}] * MINIMO_ESTACOES).encode(), "não é uma estação"),
        (json.dumps([{"id": "x"}] * MINIMO_ESTACOES).encode(), "sem additionalProperties"),
        (_lista(NbBikes=True), "sem NbBikes"),
        (_lista(TerminalName=True, NbDocks=True), "sem NbDocks, TerminalName"),
    ],
    ids=[
        "html",
        "vazio",
        "objeto",
        "lista_vazia",
        "null",
        "poucas_estacoes",
        "item_nao_dict",
        "id_nao_texto",
        "sem_additional",
        "sem_nbbikes",
        "sem_dois_campos",
    ],
)
def test_resposta_sem_forma_de_bikepoint_e_falha(conteudo: bytes, mensagem: str) -> None:
    with pytest.raises(ErroColeta, match=mensagem):
        conferir(conteudo)


def test_valores_estranhos_passam_porque_julgar_valor_e_papel_do_dbt() -> None:
    dados = json.loads(_lista())
    dados[0]["additionalProperties"][1]["value"] = "-5"
    assert conferir(json.dumps(dados).encode()) == MINIMO_ESTACOES


# ---------------------------------------------------------------- retrato e destino
def test_compressao_e_reproduzivel_e_sem_perda() -> None:
    retrato = coletar(INSTANTE, baixar_fn=lambda: AMOSTRA)
    assert retrato.comprimido() == retrato.comprimido()
    assert gzip.decompress(retrato.comprimido()) == AMOSTRA


def test_destino_local_cria_pastas_e_nunca_sobrescreve(tmp_path: Path) -> None:
    destino = DestinoLocal(tmp_path)
    destino.gravar("bruto/a/b.bin", b"primeiro")
    assert (tmp_path / "bruto/a/b.bin").read_bytes() == b"primeiro"
    with pytest.raises(ErroColeta, match="nunca é sobrescrito"):
        destino.gravar("bruto/a/b.bin", b"segundo")
    assert (tmp_path / "bruto/a/b.bin").read_bytes() == b"primeiro"


class _ErroDoS3(Exception):
    """Imita o ClientError do botocore: o código do erro vem em .response."""

    def __init__(self, codigo: str) -> None:
        super().__init__(codigo)
        self.response = {"Error": {"Code": codigo}}


class S3Falso:
    """Bucket em memória que respeita o If-None-Match: * como o S3 de verdade (412)."""

    def __init__(self, falha: Exception | None = None) -> None:
        self.objetos: dict[tuple[str, str], bytes] = {}
        self.pedidos: list[dict[str, Any]] = []
        self.falha = falha

    def put_object(self, **parametros: Any) -> dict[str, str]:
        self.pedidos.append(parametros)
        if self.falha is not None:
            raise self.falha
        chave = (parametros["Bucket"], parametros["Key"])
        if parametros.get("IfNoneMatch") == "*" and chave in self.objetos:
            raise _ErroDoS3("PreconditionFailed")
        self.objetos[chave] = parametros["Body"]
        return {"ETag": '"x"'}


def test_destino_s3_grava_com_if_none_match_e_nunca_sobrescreve() -> None:
    s3 = S3Falso()
    destino = coleta_api.DestinoS3("balde", s3)
    destino.gravar("bruto/bikepoint/data=2026-10-03/a.json.gz", b"primeiro")
    pedido = s3.pedidos[0]
    assert pedido["IfNoneMatch"] == "*"  # a recusa acontece no próprio S3
    assert pedido["ContentType"] == "application/gzip"
    assert pedido["ChecksumAlgorithm"] == "SHA256"
    with pytest.raises(ErroColeta, match="nunca é sobrescrito"):
        destino.gravar("bruto/bikepoint/data=2026-10-03/a.json.gz", b"segundo")
    assert s3.objetos[("balde", "bruto/bikepoint/data=2026-10-03/a.json.gz")] == b"primeiro"


def test_destino_s3_registro_vai_como_json() -> None:
    s3 = S3Falso()
    coleta_api.DestinoS3("balde", s3).gravar(chave_execucao(INSTANTE), b"{}")
    assert s3.pedidos[0]["ContentType"] == "application/json"


@pytest.mark.parametrize(
    ("falha", "mensagem"),
    [
        (_ErroDoS3("ConditionalRequestConflict"), "nunca é sobrescrito"),
        (_ErroDoS3("AccessDenied"), "S3: falha ao gravar .*AccessDenied"),
        (TimeoutError("lento"), "S3: falha ao gravar .*TimeoutError"),
    ],
)
def test_destino_s3_erros_viram_erro_de_coleta(falha: Exception, mensagem: str) -> None:
    with pytest.raises(ErroColeta, match=mensagem):
        coleta_api.DestinoS3("balde", S3Falso(falha)).gravar("bruto/x.json", b"{}")


# ---------------------------------------------------------------- Lambda
class _ContextoLambda:
    aws_request_id = "req-123"


def test_contexto_lambda_agendada_e_manual() -> None:
    agendada = coleta_api._contexto_lambda({"gatilho": "eventbridge_scheduler"}, _ContextoLambda())
    assert agendada == {
        "origem": "aws_lambda",
        "evento": "eventbridge_scheduler",
        "id_execucao": "req-123",
        "tentativa_execucao": None,
    }
    # teste pelo console, invoke à mão ou gatilho desconhecido: manual (fora da medição)
    for evento in ({}, {"gatilho": "qualquer"}, {"gatilho": None}):
        assert coleta_api._contexto_lambda(evento, None)["evento"] == "manual"


def test_lambda_handler_grava_no_bucket(monkeypatch: pytest.MonkeyPatch) -> None:
    s3 = S3Falso()
    monkeypatch.setenv("BICICLETAS_BUCKET_BRUTO", "balde")
    monkeypatch.setattr(coleta_api, "_cliente_s3", lambda: s3)
    monkeypatch.setattr(coleta_api, "baixar", lambda: AMOSTRA)
    resultado = coleta_api.lambda_handler({"gatilho": "eventbridge_scheduler"}, _ContextoLambda())
    assert resultado["status"] == "sucesso"
    assert resultado["origem"] == "aws_lambda"
    assert resultado["evento"] == "eventbridge_scheduler"
    chaves = sorted(chave for _, chave in s3.objetos)
    assert chaves[0].startswith("bruto/bikepoint/data=")  # retrato e registro, mesmas chaves
    assert chaves[1].startswith("bruto/execucoes_coleta/data=")
    registro = json.loads(s3.objetos[("balde", chaves[1])])
    assert registro["id_execucao"] == "req-123"


def test_lambda_handler_com_falha_grava_registro_e_termina_com_erro(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    s3 = S3Falso()
    monkeypatch.setenv("BICICLETAS_BUCKET_BRUTO", "balde")
    monkeypatch.setattr(coleta_api, "_cliente_s3", lambda: s3)
    monkeypatch.setattr(coleta_api, "baixar", lambda: b"<html>erro</html>")
    with pytest.raises(ErroColeta, match="não é JSON"):
        coleta_api.lambda_handler(None, None)  # evento vazio também funciona
    [(_, chave)] = s3.objetos
    assert chave.startswith("bruto/execucoes_coleta/")
    assert json.loads(s3.objetos[("balde", chave)])["status"] == "falha"


def test_lambda_handler_sem_bucket_configurado(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("BICICLETAS_BUCKET_BRUTO", raising=False)
    with pytest.raises(ErroColeta, match="BICICLETAS_BUCKET_BRUTO"):
        coleta_api.lambda_handler({}, None)


def test_main_ignora_o_bucket_e_grava_na_pasta(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Com o bucket no ambiente, a linha de comando continua gravando só na pasta."""
    monkeypatch.setenv("BICICLETAS_BUCKET_BRUTO", "balde")
    monkeypatch.setattr(coleta_api, "_cliente_s3", lambda: pytest.fail("não devia usar o S3"))
    monkeypatch.setattr(coleta_api, "baixar", lambda: AMOSTRA)
    monkeypatch.delenv("GITHUB_ACTIONS", raising=False)
    assert coleta_api.main(["--destino", str(tmp_path)]) == 0
    assert json.loads(capsys.readouterr().out)["status"] == "sucesso"


# ---------------------------------------------------------------- execução completa
def test_execucao_com_sucesso_grava_retrato_e_registro_com_o_mesmo_carimbo(tmp_path: Path) -> None:
    registro = executar(
        DestinoLocal(tmp_path),
        coletar_fn=lambda inst: coletar(inst, baixar_fn=lambda: AMOSTRA),
        agora=lambda: INSTANTE,
        contexto=CTX_LOCAL,
    )
    retrato = tmp_path / chave_retrato(INSTANTE)
    assert gzip.decompress(retrato.read_bytes()) == AMOSTRA  # byte a byte
    gravado = json.loads((tmp_path / chave_execucao(INSTANTE)).read_text(encoding="utf-8"))
    assert gravado["status"] == registro.status == "sucesso"
    assert gravado["estacoes"] == 120
    assert gravado["chave_retrato"] == chave_retrato(INSTANTE)
    assert gravado["bytes_brutos"] == len(AMOSTRA)
    assert gravado["erro"] is None


def test_execucao_com_falha_grava_registro_e_nao_grava_retrato(tmp_path: Path) -> None:
    def falhar(_: datetime) -> Retrato:
        raise ErroColeta("HTTP 503")

    with pytest.raises(ErroColeta, match="HTTP 503"):
        executar(
            DestinoLocal(tmp_path), coletar_fn=falhar, agora=lambda: INSTANTE, contexto=CTX_LOCAL
        )
    gravado = json.loads((tmp_path / chave_execucao(INSTANTE)).read_text(encoding="utf-8"))
    assert gravado["status"] == "falha"
    assert gravado["erro"] == "HTTP 503"
    assert not (tmp_path / "bruto" / "bikepoint").exists()


def test_contexto_do_github_actions() -> None:
    env = {
        "GITHUB_ACTIONS": "true",
        "GITHUB_EVENT_NAME": "schedule",
        "GITHUB_RUN_ID": "123",
        "GITHUB_RUN_ATTEMPT": "1",
    }
    assert coleta_api._contexto_execucao(env) == {
        "origem": "github_actions",
        "evento": "schedule",
        "id_execucao": "123",
        "tentativa_execucao": "1",
    }
    assert coleta_api._contexto_execucao({})["origem"] == "local"


def test_agendador_externo_conta_como_agendada_e_manual_continua_manual() -> None:
    base = {"GITHUB_ACTIONS": "true", "GITHUB_EVENT_NAME": "workflow_dispatch"}
    externo = coleta_api._contexto_execucao({**base, "COLETA_GATILHO": "agendador_externo"})
    assert externo["evento"] == "agendador_externo"
    for gatilho in ("manual", "", "qualquer coisa"):
        assert coleta_api._contexto_execucao({**base, "COLETA_GATILHO": gatilho})["evento"] == (
            "workflow_dispatch"
        )
    # o gatilho só vale para workflow_dispatch: num push, por exemplo, é ignorado
    push = {
        "GITHUB_ACTIONS": "true",
        "GITHUB_EVENT_NAME": "push",
        "COLETA_GATILHO": "agendador_externo",
    }
    assert coleta_api._contexto_execucao(push)["evento"] == "push"


def test_main_grava_e_imprime_resultado(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(coleta_api, "baixar", lambda: AMOSTRA)
    monkeypatch.delenv("GITHUB_ACTIONS", raising=False)
    assert coleta_api.main(["--destino", str(tmp_path)]) == 0
    saida = json.loads(capsys.readouterr().out)
    assert saida["status"] == "sucesso"
    assert saida["origem"] == "local"
    assert (tmp_path / saida["chave_retrato"]).exists()


def test_main_com_falha_sai_com_codigo_1(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(coleta_api, "baixar", lambda: b"<html>erro</html>")
    assert coleta_api.main(["--destino", str(tmp_path)]) == 1
    assert "não é JSON" in capsys.readouterr().err
    registros = list((tmp_path / "bruto" / "execucoes_coleta").rglob("*.json"))
    assert len(registros) == 1


# ---------------------------------------------------------------- rede (opcional)
@pytest.mark.rede
def test_api_real(tmp_path: Path) -> None:
    """Coleta de verdade na API da TfL: pytest -m rede."""
    registro = executar(DestinoLocal(tmp_path), contexto=CTX_LOCAL)
    assert registro.status == "sucesso"
    assert registro.estacoes is not None and registro.estacoes >= 700
