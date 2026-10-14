"""Coleta ao vivo: um retrato da API BikePoint da TfL, guardado intocado no bruto.

Só biblioteca padrão, de propósito (docs/DECISOES.md D24): roda no GitHub Actions sem
instalar nada e roda na AWS Lambda sem empacotar dependências. O único extra é o boto3,
que já vem no runtime Python da Lambda e só é importado lá (destino S3). Por isso este
módulo não importa bicicletas.config (que usa dotenv e SQLAlchemy).

Uso:
    python -m bicicletas.coleta_api --destino saida/    (pasta local; GitHub Actions)
    lambda_handler(event, context)                      (AWS Lambda; grava no S3, D45)

Cada execução grava dois arquivos, com chaves no formato do S3 (D5):
    bruto/bikepoint/data=AAAA-MM-DD/bikepoint_AAAA-MM-DDTHH-MM-SSZ.json.gz
        a resposta da API byte a byte, comprimida (o bruto intocado);
    bruto/execucoes_coleta/data=AAAA-MM-DD/execucao_AAAA-MM-DDTHH-MM-SSZ.json
        o registro da execução (sucesso ou falha, quem disparou, quantas estações).
        O GitHub apaga o histórico de execuções depois de 90 dias; este registro fica
        para sempre e é a base da medição do atraso do agendador.
"""

from __future__ import annotations

import argparse
import gzip
import hashlib
import importlib
import json
import os
import sys
import time
import urllib.error
import urllib.request
from collections.abc import Callable, Mapping
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Protocol

URL_BIKEPOINT = "https://api.tfl.gov.uk/BikePoint"
PREFIXO_RETRATOS = "bruto/bikepoint"
PREFIXO_EXECUCOES = "bruto/execucoes_coleta"
USER_AGENT = "london-cycle-hire-pipeline (+https://github.com/DiegoSantiago1)"

# Medido em 03/10/2026: 799 estações. Menos que isso pode ser real (estações fora de
# serviço), então não impede a gravação; abaixo deste piso, a resposta é tratada como
# quebrada (ex.: a API devolvendo uma lista quase vazia durante uma falha).
MINIMO_ESTACOES = 100
# Toda estação da API tem estes campos em additionalProperties (medido: 799 de 799).
CAMPOS_ESTACAO = ("NbBikes", "NbEmptyDocks", "NbDocks", "TerminalName")

TENTATIVAS = 3
ESPERA_BASE_S = 5.0
TIMEOUT_S = 30.0
# Erros HTTP que valem nova tentativa: excesso de requisições e falhas do servidor.
# Os demais 4xx (404, 403...) não melhoram tentando de novo.
_HTTP_TEMPORARIO = {408, 429, 500, 502, 503, 504}


class ErroColeta(RuntimeError):
    """A coleta falhou: rede, HTTP ou resposta sem a forma esperada."""


class Destino(Protocol):
    """Onde o bruto é gravado: uma pasta local (GitHub Actions) ou um bucket S3 (Lambda)."""

    def gravar(self, chave: str, dados: bytes) -> None: ...


class ClienteS3(Protocol):
    """O pedaço do cliente S3 do boto3 que a coleta usa (os testes passam um falso)."""

    def put_object(self, **parametros: Any) -> Any: ...


@dataclass(frozen=True)
class DestinoLocal:
    raiz: Path

    def gravar(self, chave: str, dados: bytes) -> None:
        caminho = self.raiz / chave
        caminho.parent.mkdir(parents=True, exist_ok=True)
        # "xb": cria o arquivo e falha se ele já existir. O bruto nunca é sobrescrito.
        try:
            with caminho.open("xb") as arquivo:
                arquivo.write(dados)
        except FileExistsError:
            raise ErroColeta(f"{chave} já existe: o bruto nunca é sobrescrito.") from None


# Respostas do S3 quando o If-None-Match falha: o objeto já existe (412) ou outra gravação
# do mesmo nome está em andamento (409).
_S3_JA_EXISTE = {"PreconditionFailed", "ConditionalRequestConflict"}


@dataclass(frozen=True)
class DestinoS3:
    """Bucket S3 com as mesmas chaves da pasta local (D5).

    If-None-Match: * faz o próprio S3 recusar a gravação se a chave já existe: a regra
    "o bruto nunca é sobrescrito" vale no servidor, e não só no código (D45). O
    versionamento do bucket e a política do IAM (a Lambda só tem PutObject) completam a
    proteção.
    """

    bucket: str
    cliente: ClienteS3

    def gravar(self, chave: str, dados: bytes) -> None:
        tipo = "application/gzip" if chave.endswith(".gz") else "application/json"
        try:
            self.cliente.put_object(
                Bucket=self.bucket,
                Key=chave,
                Body=dados,
                ContentType=tipo,
                IfNoneMatch="*",
                ChecksumAlgorithm="SHA256",
            )
        except Exception as erro:
            # Sem importar o botocore: o ClientError traz o código em erro.response.
            resposta = getattr(erro, "response", None)
            codigo = resposta.get("Error", {}).get("Code") if isinstance(resposta, dict) else None
            if codigo in _S3_JA_EXISTE:
                raise ErroColeta(f"{chave} já existe: o bruto nunca é sobrescrito.") from None
            motivo = codigo or type(erro).__name__
            raise ErroColeta(f"S3: falha ao gravar {chave}: {motivo}") from erro


@dataclass(frozen=True)
class Retrato:
    coletado_em: datetime
    conteudo: bytes
    estacoes: int

    def chave(self) -> str:
        return chave_retrato(self.coletado_em)

    def comprimido(self) -> bytes:
        # mtime=0: o mesmo conteúdo gera sempre os mesmos bytes (hash reproduzível).
        return gzip.compress(self.conteudo, compresslevel=9, mtime=0)

    def sha256(self) -> str:
        return hashlib.sha256(self.conteudo).hexdigest()


def _utc(instante: datetime) -> datetime:
    if instante.tzinfo is None:
        raise ValueError("instante sem fuso: use um datetime com tzinfo (UTC).")
    return instante.astimezone(UTC)


def _carimbo(instante: datetime) -> tuple[str, str]:
    """(data, carimbo) em UTC: ('2026-10-03', '2026-10-03T17-22-05Z'). Sem ':' no nome,
    que o Windows não aceita em arquivo."""
    u = _utc(instante)
    return f"{u:%Y-%m-%d}", f"{u:%Y-%m-%dT%H-%M-%SZ}"


def chave_retrato(instante: datetime) -> str:
    data, carimbo = _carimbo(instante)
    return f"{PREFIXO_RETRATOS}/data={data}/bikepoint_{carimbo}.json.gz"


def chave_execucao(instante: datetime) -> str:
    data, carimbo = _carimbo(instante)
    return f"{PREFIXO_EXECUCOES}/data={data}/execucao_{carimbo}.json"


type Abridor = Callable[..., Any]


def baixar(
    url: str = URL_BIKEPOINT,
    *,
    tentativas: int = TENTATIVAS,
    espera_base: float = ESPERA_BASE_S,
    timeout: float = TIMEOUT_S,
    abrir: Abridor = urllib.request.urlopen,
    dormir: Callable[[float], None] = time.sleep,
) -> bytes:
    """Baixa a URL com novas tentativas e espera crescente (5 s, 10 s...) em falhas temporárias."""
    pedido = urllib.request.Request(  # noqa: S310 (URL fixa https, não vem de usuário)
        url, headers={"User-Agent": USER_AGENT, "Accept": "application/json"}
    )
    ultimo_erro = ""
    for tentativa in range(1, tentativas + 1):
        try:
            with abrir(pedido, timeout=timeout) as resposta:
                corpo: bytes = resposta.read()
                return corpo
        except urllib.error.HTTPError as erro:
            ultimo_erro = f"HTTP {erro.code}"
            erro.close()  # o HTTPError carrega a resposta aberta; sem isso, vaza o recurso
            if erro.code not in _HTTP_TEMPORARIO:
                raise ErroColeta(f"{url}: {ultimo_erro} (não é temporário)") from erro
        except (urllib.error.URLError, TimeoutError, ConnectionError) as erro:
            ultimo_erro = f"{type(erro).__name__}: {erro}"
        if tentativa < tentativas:
            dormir(espera_base * 2 ** (tentativa - 1))
    raise ErroColeta(f"{url}: falhou {tentativas} vezes; último erro: {ultimo_erro}")


def conferir(conteudo: bytes) -> int:
    """Confere se a resposta tem a forma de BikePoint e devolve o número de estações.

    Resposta sem essa forma (página HTML de erro, lista vazia, objeto) é falha de coleta
    e não vai para o bruto: o trecho inicial aparece no log como evidência (D25). Uma
    resposta com a forma certa é gravada como veio, mesmo com valores estranhos: julgar
    os valores é papel dos testes do dbt.
    """
    trecho = conteudo[:200].decode("utf-8", errors="replace")
    try:
        dados = json.loads(conteudo)
    except ValueError:
        raise ErroColeta(f"resposta não é JSON: {trecho!r}") from None
    if not isinstance(dados, list):
        raise ErroColeta(f"esperava uma lista de estações, veio {type(dados).__name__}: {trecho!r}")
    if len(dados) < MINIMO_ESTACOES:
        raise ErroColeta(f"só {len(dados)} estações (mínimo {MINIMO_ESTACOES}): {trecho!r}")
    for posicao, estacao in enumerate(dados):
        if not isinstance(estacao, dict) or not isinstance(estacao.get("id"), str):
            raise ErroColeta(f"item {posicao} não é uma estação com 'id'")
        propriedades = estacao.get("additionalProperties")
        if not isinstance(propriedades, list):
            raise ErroColeta(f"estação {estacao['id']} sem additionalProperties")
        chaves = {p.get("key") for p in propriedades if isinstance(p, dict)}
        faltando = [c for c in CAMPOS_ESTACAO if c not in chaves]
        if faltando:
            raise ErroColeta(f"estação {estacao['id']} sem {', '.join(faltando)}")
    return len(dados)


def coletar(instante: datetime, baixar_fn: Callable[[], bytes] | None = None) -> Retrato:
    """Baixa e confere um retrato. O instante (início da execução) dá nome ao arquivo."""
    # Resolvido na hora da chamada (e não no default): os testes trocam o baixar do módulo.
    conteudo = (baixar_fn or baixar)()
    return Retrato(coletado_em=_utc(instante), conteudo=conteudo, estacoes=conferir(conteudo))


@dataclass(frozen=True)
class Execucao:
    """Registro de uma execução da coleta (vai para bruto/execucoes_coleta)."""

    iniciado_em: str
    terminado_em: str
    status: str  # "sucesso" ou "falha"
    origem: str  # "github_actions", "aws_lambda" ou "local"
    # "schedule", "agendador_externo", "eventbridge_scheduler" (agendadas) ou
    # "workflow_dispatch"/"manual" (disparos à mão)...
    evento: str | None
    id_execucao: str | None
    tentativa_execucao: str | None
    chave_retrato: str | None = None
    estacoes: int | None = None
    bytes_brutos: int | None = None
    bytes_comprimidos: int | None = None
    sha256: str | None = None
    erro: str | None = None


def _contexto_execucao(env: Mapping[str, str]) -> dict[str, str | None]:
    """Quem disparou: variáveis padrão do GitHub Actions; sem elas, execução local.

    O agendador externo chama o workflow pela API (evento workflow_dispatch) com
    gatilho=agendador_externo: o registro grava "agendador_externo", para a medição tratar
    essa execução como agendada e não como manual."""
    if env.get("GITHUB_ACTIONS") == "true":
        evento = env.get("GITHUB_EVENT_NAME")
        if evento == "workflow_dispatch" and env.get("COLETA_GATILHO") == "agendador_externo":
            evento = "agendador_externo"
        return {
            "origem": "github_actions",
            "evento": evento,
            "id_execucao": env.get("GITHUB_RUN_ID"),
            "tentativa_execucao": env.get("GITHUB_RUN_ATTEMPT"),
        }
    return {"origem": "local", "evento": None, "id_execucao": None, "tentativa_execucao": None}


# Gatilhos aceitos no evento da Lambda. O EventBridge Scheduler manda
# {"gatilho": "eventbridge_scheduler"} (infra/scheduler.tf); qualquer outra coisa, como um
# teste pelo console ou pelo `aws lambda invoke`, é tratada como manual.
_GATILHOS_LAMBDA = {"eventbridge_scheduler"}


def _contexto_lambda(event: Mapping[str, Any], context: Any) -> dict[str, str | None]:
    """Quem disparou a Lambda: o agendador (conta como agendada) ou alguém à mão."""
    gatilho = event.get("gatilho")
    return {
        "origem": "aws_lambda",
        "evento": gatilho if gatilho in _GATILHOS_LAMBDA else "manual",
        "id_execucao": getattr(context, "aws_request_id", None),
        "tentativa_execucao": None,
    }


def executar(
    destino: Destino,
    *,
    coletar_fn: Callable[[datetime], Retrato] | None = None,
    agora: Callable[[], datetime] = lambda: datetime.now(UTC),
    contexto: dict[str, str | None] | None = None,
) -> Execucao:
    """Uma execução completa: coleta, grava o retrato e grava o registro (sucesso ou falha).

    O registro é gravado mesmo quando a coleta falha; a falha é relançada depois, para
    a execução terminar com erro (job vermelho no Actions, alarme na Lambda).
    """
    inicio = agora()
    ctx = contexto if contexto is not None else _contexto_execucao(os.environ)
    base: dict[str, Any] = {"iniciado_em": _utc(inicio).isoformat(), **ctx}
    try:
        # O mesmo instante dá nome ao retrato e ao registro: os dois se encontram pelo nome.
        retrato = (coletar_fn or coletar)(inicio)
        comprimido = retrato.comprimido()
        destino.gravar(retrato.chave(), comprimido)
    except ErroColeta as erro:
        registro = Execucao(
            **base, terminado_em=_utc(agora()).isoformat(), status="falha", erro=str(erro)
        )
        destino.gravar(chave_execucao(inicio), _json(registro))
        raise
    registro = Execucao(
        **base,
        terminado_em=_utc(agora()).isoformat(),
        status="sucesso",
        chave_retrato=retrato.chave(),
        estacoes=retrato.estacoes,
        bytes_brutos=len(retrato.conteudo),
        bytes_comprimidos=len(comprimido),
        sha256=retrato.sha256(),
    )
    destino.gravar(chave_execucao(inicio), _json(registro))
    return registro


def _json(registro: Execucao) -> bytes:
    return (json.dumps(asdict(registro), ensure_ascii=False, indent=2) + "\n").encode("utf-8")


def _cliente_s3() -> ClienteS3:
    """Cliente S3 do boto3, que vem no runtime Python da Lambda. Importado só aqui: no
    GitHub Actions e nos testes o boto3 não existe e não faz falta."""
    boto3 = importlib.import_module("boto3")
    cliente: ClienteS3 = boto3.client("s3")
    return cliente


def lambda_handler(event: dict[str, Any] | None, context: Any) -> dict[str, Any]:
    """Ponto de entrada da AWS Lambda (infra/lambda.tf).

    Grava no bucket de BICICLETAS_BUCKET_BRUTO. Uma falha de coleta é relançada depois
    de gravar o registro: a invocação termina com erro e o alarme do CloudWatch avisa.
    """
    bucket = os.environ.get("BICICLETAS_BUCKET_BRUTO")
    if not bucket:
        raise ErroColeta("BICICLETAS_BUCKET_BRUTO não definida.")
    evento = event if isinstance(event, dict) else {}
    destino = DestinoS3(bucket, _cliente_s3())
    return asdict(executar(destino, contexto=_contexto_lambda(evento, context)))


def main(argumentos: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Coleta um retrato da API BikePoint da TfL.")
    parser.add_argument("--destino", required=True, type=Path, help="pasta raiz do bruto")
    args = parser.parse_args(argumentos)
    try:
        resultado = asdict(executar(DestinoLocal(args.destino)))
    except ErroColeta as erro:
        print(f"ERRO na coleta: {erro}", file=sys.stderr)
        return 1
    print(json.dumps(resultado, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
