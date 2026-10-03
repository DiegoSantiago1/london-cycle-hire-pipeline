"""Download incremental dos arquivos de viagens da TfL (bucket público cycling.data.tfl.gov.uk).

Uso:
    python -m bicicletas.viagens_download            # baixa o que é novo ou mudou
    python -m bicicletas.viagens_download --listar   # só mostra o que baixaria

Os arquivos vão para $BICICLETAS_DADOS/bruto/viagens/ (fora do OneDrive, D15). Ao lado de
cada CSV fica um recibo <arquivo>.recibo.json com o ETag e a data de publicação do S3,
o tamanho e o SHA-256. O recibo é o que torna o download incremental:
- ETag igual ao do recibo e arquivo íntegro: não baixa de novo;
- ETag diferente: a TfL republicou o arquivo; baixa a versão nova.
O ETag do S3 só detecta mudança: nos arquivos grandes ele não é o MD5 do conteúdo
(upload "multipart", medido em 141 de 148 arquivos). A integridade é conferida pelo
tamanho anunciado e pelo SHA-256 calculado aqui.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from collections.abc import Callable, Iterator
from dataclasses import asdict, dataclass
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

URL_LISTAGEM = "https://s3-eu-west-1.amazonaws.com/cycling.data.tfl.gov.uk/"
URL_ARQUIVOS = "https://cycling.data.tfl.gov.uk/"
PREFIXO = "usage-stats/"
SUBPASTA = Path("bruto") / "viagens"
USER_AGENT = "london-cycle-hire-pipeline (+https://github.com/DiegoSantiago1)"
INICIO_PADRAO = date(2022, 1, 1)  # D14
_NS = {"s": "http://s3.amazonaws.com/doc/2006-03-01/"}
_MESES = {
    m: i
    for i, m in enumerate(
        ("jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"), 1
    )
}
# "29Dec2021-04Jan2022", "10Jan16-23Jan16", "01Aug2024-14Aug2024": dia, mês (3 letras ou
# mais), ano com 2 ou 4 dígitos.
_PERIODO = re.compile(
    r"(\d{1,2})([A-Za-z]{3})[a-z]*(\d{4}|\d{2})-(\d{1,2})([A-Za-z]{3})[a-z]*(\d{4}|\d{2})"
)

type Abridor = Callable[..., Any]


class ErroDownload(RuntimeError):
    """Listagem ou download falhou, ou o arquivo baixado não confere."""


@dataclass(frozen=True)
class ObjetoTfl:
    chave: str  # usage-stats/444JourneyDataExtract17May2026-31May2026.csv
    tamanho: int
    etag: str
    publicado_em: str  # LastModified do S3, ISO 8601 em UTC

    @property
    def nome(self) -> str:
        return self.chave.removeprefix(PREFIXO)


@dataclass(frozen=True)
class Recibo:
    arquivo: str
    etag: str
    publicado_em: str
    bytes: int
    sha256: str
    baixado_em: str


def periodo_do_nome(nome: str) -> tuple[date, date] | None:
    """Datas de início e fim pelo nome do arquivo; None se o nome não tem período."""
    m = _PERIODO.search(nome)
    if m is None:
        return None

    def montar(dia: str, mes: str, ano: str) -> date:
        a = int(ano)
        return date(a + 2000 if a < 100 else a, _MESES[mes.lower()], int(dia))

    try:
        return montar(*m.group(1, 2, 3)), montar(*m.group(4, 5, 6))
    except KeyError, ValueError:
        return None


def _abrir_padrao(url: str, timeout: float = 60) -> Any:
    pedido = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})  # noqa: S310
    return urllib.request.urlopen(pedido, timeout=timeout)  # noqa: S310 (URL fixa https)


def listar(abrir: Abridor = _abrir_padrao) -> list[ObjetoTfl]:
    """Todos os objetos do prefixo usage-stats/ (a listagem do S3 vem em páginas de 1.000)."""
    objetos: list[ObjetoTfl] = []
    token: str | None = None
    while True:
        consulta = {"list-type": "2", "prefix": PREFIXO}
        if token:
            consulta["continuation-token"] = token
        with abrir(URL_LISTAGEM + "?" + urllib.parse.urlencode(consulta)) as resposta:
            raiz = ET.fromstring(resposta.read())  # noqa: S314 (XML do S3 da TfL)
        for item in raiz.findall("s:Contents", _NS):

            def campo(nome: str, item: ET.Element = item) -> str:
                elemento = item.find(f"s:{nome}", _NS)
                if elemento is None or elemento.text is None:
                    raise ErroDownload(f"listagem sem {nome}")
                return elemento.text

            objetos.append(
                ObjetoTfl(
                    chave=campo("Key"),
                    tamanho=int(campo("Size")),
                    etag=campo("ETag").strip('"'),
                    publicado_em=campo("LastModified"),
                )
            )
        proximo = raiz.find("s:NextContinuationToken", _NS)
        if proximo is None or not proximo.text:
            return objetos
        token = proximo.text


def selecionar(objetos: list[ObjetoTfl], desde: date = INICIO_PADRAO) -> list[ObjetoTfl]:
    """CSVs cujo período termina em `desde` ou depois, em ordem de período."""
    escolhidos = []
    for objeto in objetos:
        if not objeto.nome.endswith(".csv") or "/" in objeto.nome:
            continue
        periodo = periodo_do_nome(objeto.nome)
        if periodo is not None and periodo[1] >= desde:
            escolhidos.append((periodo, objeto))
    return [objeto for _, objeto in sorted(escolhidos, key=lambda par: (par[0], par[1].nome))]


def caminho_recibo(csv: Path) -> Path:
    return csv.with_name(csv.name + ".recibo.json")


def ler_recibo(csv: Path) -> Recibo | None:
    try:
        return Recibo(**json.loads(caminho_recibo(csv).read_text(encoding="utf-8")))
    except FileNotFoundError:
        return None
    except (ValueError, TypeError) as erro:
        raise ErroDownload(f"recibo inválido de {csv.name}: {erro}") from erro


def precisa_baixar(objeto: ObjetoTfl, pasta: Path) -> bool:
    destino = pasta / objeto.nome
    recibo = ler_recibo(destino)
    if recibo is None or not destino.exists():
        return True
    # ETag mudou = republicado. Tamanho diferente = cópia local corrompida ou incompleta.
    return recibo.etag != objeto.etag or destino.stat().st_size != recibo.bytes


def _blocos(resposta: Any, tamanho: int = 1 << 20) -> Iterator[bytes]:
    while bloco := resposta.read(tamanho):
        yield bloco


def baixar(
    objeto: ObjetoTfl,
    pasta: Path,
    abrir: Abridor = _abrir_padrao,
    agora: Callable[[], datetime] = lambda: datetime.now(UTC),
) -> Recibo:
    """Baixa para um arquivo .parcial e só troca pelo definitivo depois de conferir.

    Uma queda no meio do download nunca deixa um CSV pela metade com cara de completo.
    """
    pasta.mkdir(parents=True, exist_ok=True)
    destino = pasta / objeto.nome
    parcial = destino.with_name(destino.name + ".parcial")
    soma = hashlib.sha256()
    recebidos = 0
    try:
        with (
            abrir(URL_ARQUIVOS + urllib.parse.quote(objeto.chave)) as resposta,
            parcial.open("wb") as saida,
        ):
            for bloco in _blocos(resposta):
                saida.write(bloco)
                soma.update(bloco)
                recebidos += len(bloco)
        if recebidos != objeto.tamanho:
            raise ErroDownload(
                f"{objeto.nome}: recebidos {recebidos} bytes, a listagem anunciava {objeto.tamanho}"
            )
        recibo = Recibo(
            arquivo=objeto.nome,
            etag=objeto.etag,
            publicado_em=objeto.publicado_em,
            bytes=recebidos,
            sha256=soma.hexdigest(),
            baixado_em=agora().isoformat(),
        )
        os.replace(parcial, destino)
    except BaseException:
        parcial.unlink(missing_ok=True)
        raise
    corpo = json.dumps(asdict(recibo), ensure_ascii=False, indent=2) + "\n"
    caminho_recibo(destino).write_text(corpo, encoding="utf-8", newline="\n")
    return recibo


def pasta_viagens(env: dict[str, str] | None = None) -> Path:
    from bicicletas.config import ConfigError, carregar_env

    ambiente = env if env is not None else carregar_env()
    raiz = ambiente.get("BICICLETAS_DADOS", "").strip()
    if not raiz:
        raise ConfigError(
            "BICICLETAS_DADOS não definida (pasta dos dados brutos, fora do OneDrive)."
        )
    return Path(raiz) / SUBPASTA


def main(argumentos: list[str] | None = None) -> int:
    from bicicletas.config import ConfigError

    parser = argparse.ArgumentParser(description="Baixa os arquivos de viagens novos ou mudados.")
    parser.add_argument("--desde", type=date.fromisoformat, default=INICIO_PADRAO)
    parser.add_argument("--listar", action="store_true", help="só mostra o que baixaria")
    args = parser.parse_args(argumentos)
    try:
        pasta = pasta_viagens()
        objetos = selecionar(listar(), args.desde)
    except (ConfigError, ErroDownload, OSError) as erro:
        print(f"Erro: {erro}", file=sys.stderr)
        return 1
    pendentes = [o for o in objetos if precisa_baixar(o, pasta)]
    total = sum(o.tamanho for o in pendentes)
    print(
        f"{len(objetos)} arquivos desde {args.desde}; {len(pendentes)} a baixar "
        f"({total / 1e6:,.0f} MB) em {pasta}",
        flush=True,
    )
    if args.listar:
        for objeto in pendentes:
            print(f"  {objeto.nome}  ({objeto.tamanho / 1e6:.0f} MB)")
        return 0
    for i, objeto in enumerate(pendentes, 1):
        try:
            recibo = baixar(objeto, pasta)
        except (ErroDownload, OSError) as erro:
            print(f"Erro em {objeto.nome}: {erro}", file=sys.stderr)
            return 1
        print(f"  [{i}/{len(pendentes)}] {recibo.arquivo}  {recibo.bytes / 1e6:.0f} MB", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
