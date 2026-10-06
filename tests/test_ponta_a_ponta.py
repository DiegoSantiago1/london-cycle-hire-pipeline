"""Ponta a ponta no banco de teste: bruto -> dbt (viagens) -> agregados -> dbt (diário) -> painel.

Usa as amostras reais de viagens e retratos sintéticos feitos a partir da amostra real
da API, com estados conhecidos (uma estação vazia, outra cheia), para conferir os
números que saem do outro lado. Grava de verdade no banco de teste (o dbt precisa de
dados confirmados) e limpa tudo no fim.
"""

import gzip
import json
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import psycopg
import pytest
from psycopg.rows import dict_row

from bicicletas import agregados
from bicicletas.banco import conectar
from bicicletas.config import ConfigBanco
from bicicletas.dbt_rodar import rodar
from bicicletas.exportar_site import ErroExportacao, montar_painel
from bicicletas.retratos_carga import carregar_pasta
from bicicletas.viagens_carga import carregar_arquivo

from .test_agregados import CSV_VALIDOS
from .test_coleta_api import AMOSTRA
from .test_viagens_carga import AMOSTRAS, VARIANTES, preparar

pytestmark = pytest.mark.integracao

# Segunda-feira, 05/10/2026. 07:07 UTC = 08:07 em Londres (horário de verão).
INICIO = datetime(2026, 10, 5, 7, 7, tzinfo=UTC)
LIMPAR = (
    "TRUNCATE controle.arquivos_viagens, controle.arquivos_retratos, "
    "agregados.demanda_estacao_hora, agregados.fluxos_hora, agregados.viagens_mes, "
    "agregados.estacoes_viagens, agregados.metadados CASCADE"
)


def _retrato(estacoes: list[dict[str, Any]], vazia: str, cheia: str) -> bytes:
    """Cópia da amostra real com uma estação vazia e outra cheia."""
    copia = json.loads(json.dumps(estacoes))
    for estacao in copia:
        props = {p["key"]: p for p in estacao["additionalProperties"]}
        docas = int(props["NbDocks"]["value"])
        if estacao["id"] == vazia:
            bicicletas, vagas = 0, docas
        elif estacao["id"] == cheia:
            bicicletas, vagas = docas, 0
        else:
            bicicletas, vagas = docas // 2, docas - docas // 2
        props["NbBikes"]["value"] = str(bicicletas)
        props["NbEmptyDocks"]["value"] = str(vagas)
        props["NbStandardBikes"]["value"] = str(bicicletas)
        props["NbEBikes"]["value"] = "0"
    return gzip.compress(json.dumps(copia).encode(), mtime=0)


@pytest.fixture
def ambiente(banco_teste: ConfigBanco, monkeypatch: pytest.MonkeyPatch) -> Iterator[ConfigBanco]:
    # O logger do dbt deixa o dbt.log aberto entre execuções no mesmo processo
    # (ResourceWarning interno do dbt); nos testes, sem log em arquivo.
    monkeypatch.setenv("DBT_LOG_LEVEL_FILE", "none")
    with conectar(banco_teste) as con:
        con.execute(LIMPAR)
    try:
        yield banco_teste
    finally:
        with conectar(banco_teste) as con:
            con.execute(LIMPAR)


def test_pipeline_inteiro(ambiente: ConfigBanco, tmp_path: Path) -> None:
    # 1. bruto das viagens: as 6 variantes reais
    with conectar(ambiente) as con:
        con.autocommit = True
        for i, variante in enumerate(VARIANTES):
            nome = f"9{i}JourneyDataExtract01Jan2026-02Jan2026.csv"
            carregar_arquivo(
                con, preparar(tmp_path / "viagens", nome, (AMOSTRAS / variante).read_bytes())
            )

    # 2. dbt das viagens (o que roda no PC) e exportação dos agregados
    assert rodar(["build", "--target", "teste", "--select", "tag:viagens"]) == 0
    with conectar(ambiente) as con:
        con.autocommit = True
        assert con.execute("SELECT count(*) FROM staging.stg_viagens").fetchone() == (24,)
        datas_ok = con.execute(
            "SELECT count(*) FROM staging.stg_viagens WHERE inicio IS NULL OR fim IS NULL"
        ).fetchone()
        assert datas_ok == (0,)  # os dois formatos de data foram entendidos
        agregados.exportar(con, tmp_path / "exportados")
    assert (tmp_path / "exportados" / "demanda_estacao_hora.csv").exists()

    # 3. agregados conhecidos (estação 001023: 2,5 retiradas às 8h de segunda) e retratos
    for nome, conteudo in CSV_VALIDOS.items():
        (tmp_path / "agregados" / f"{nome}.csv").parent.mkdir(exist_ok=True)
        (tmp_path / "agregados" / f"{nome}.csv").write_text(
            conteudo, encoding="utf-8", newline="\n"
        )
    estacoes = json.loads(AMOSTRA)
    pasta = tmp_path / "retratos"
    pasta.mkdir()
    for k in range(4):
        quando = INICIO + timedelta(minutes=15 * k)
        carimbo = f"{quando:%Y-%m-%dT%H-%M-%SZ}"
        (pasta / f"bikepoint_{carimbo}.json.gz").write_bytes(
            _retrato(estacoes, vazia="BikePoints_1", cheia="BikePoints_2")
        )
        registro = {
            "iniciado_em": (quando + timedelta(minutes=2)).isoformat(),
            "terminado_em": (quando + timedelta(minutes=2, seconds=1)).isoformat(),
            "status": "sucesso",
            "origem": "github_actions",
            # o cron do GitHub e o agendador externo se alternam: os dois contam como agendada
            "evento": "schedule" if k % 2 == 0 else "agendador_externo",
            "estacoes": len(estacoes),
        }
        (pasta / f"execucao_{carimbo}.json").write_text(json.dumps(registro), encoding="utf-8")
    with conectar(ambiente) as con:
        con.autocommit = True
        agregados.carregar(con, tmp_path / "agregados")
        resumo = carregar_pasta(con, pasta)
    assert (resumo.retratos, resumo.execucoes) == (4, 4)

    # 4. dbt diário (o que roda no Actions)
    assert rodar(["build", "--target", "teste", "--select", "tag:diario"]) == 0

    # 5. números que saem do outro lado
    with psycopg.connect(
        host=ambiente.host,
        port=ambiente.porta,
        dbname=ambiente.nome,
        user=ambiente.usuario,
        password=ambiente.senha,
        row_factory=dict_row,
    ) as con:
        ocupacao = con.execute(
            "SELECT hora, minutos_observados, minutos_vazia, minutos_cheia "
            "FROM marts.fct_ocupacao_hora WHERE estacao_id = 'BikePoints_1'"
        ).fetchall()
        # 3 intervalos de 15 min (o 4º retrato ainda não tem sucessor), às 8h em Londres
        assert [
            (r["hora"], float(r["minutos_observados"]), float(r["minutos_vazia"])) for r in ocupacao
        ] == [(8, 45.0, 45.0)]
        with pytest.raises(ErroExportacao, match="mínimo 500"):
            montar_painel(con, datetime.now(UTC))  # amostra tem 120 estações
        painel = montar_painel(con, datetime.now(UTC), minimo_estacoes=100)

    primeiro = painel["ranking"][0]
    assert primeiro["terminal"] == "001023"
    assert float(primeiro["viagens_perdidas"]) == pytest.approx(1.9)  # 45/60 h x 2,5
    assert float(primeiro["horas_vazia"]) == pytest.approx(0.8)
    assert painel["risco"]["001023"]["util_v"][8] == pytest.approx(1.0)
    assert painel["risco"]["001023"]["util_v"][9] is None  # sem observação, não é "vazia"
    cheia = next(e for e in painel["estacoes"] if e["t"] == "001018")
    assert painel["risco"][cheia["t"]]["util_c"][8] == pytest.approx(1.0)
    saude = painel["saude"][0]
    assert saude["janelas"] == 4
    assert saude["janelas_com_sucesso"] == 4
    assert float(saude["atraso_mediano_min"]) == pytest.approx(2.0)
    assert painel["viagens"]["viagens_total"] == "41376421"
