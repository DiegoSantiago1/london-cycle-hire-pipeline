"""Testes da camada do Athena (D50): o executor scripts/athena.sh contra um `aws` falso e
as garantias dos arquivos SQL (views só criam views, consultas só leem, o padrão do nome
do arquivo bate com o que a coleta grava)."""

import os
import re
import subprocess
from datetime import UTC, datetime
from pathlib import Path

import pytest

from bicicletas.coleta_api import chave_retrato

from .test_scripts import _bash, _posix

RAIZ = Path(__file__).resolve().parents[1]
PASTA_SQL = RAIZ / "athena"

AWS_FALSO = r"""#!/usr/bin/env bash
# aws falso: só entende os comandos do Athena que o athena.sh usa.
set -euo pipefail
echo "$*" >> "$AWS_ESTADO/chamadas.log"
[ "$1" = athena ] || exit 2
acao="$2"; shift 2
case "$acao" in
  start-query-execution)
    while [ $# -gt 0 ]; do
      case "$1" in
        --query-string)
          n=$(find "$AWS_ESTADO" -name 'sql_*.txt' | wc -l)
          printf '%s' "$2" > "$AWS_ESTADO/sql_$n.txt"; shift 2 ;;
        *) shift ;;
      esac
    done
    echo "id-123" ;;
  get-query-execution)
    q=""
    while [ $# -gt 0 ]; do case "$1" in --query) q="$2"; shift 2 ;; *) shift ;; esac; done
    case "$q" in
      QueryExecution.Status.State)
        n=$(cat "$AWS_ESTADO/.consultas_estado" 2>/dev/null || echo 0)
        echo $((n + 1)) > "$AWS_ESTADO/.consultas_estado"
        if [ "$n" -lt "${RODANDO_ATE:-1}" ]; then echo RUNNING
        else echo "${ESTADO_FINAL:-SUCCEEDED}"; fi ;;
      QueryExecution.Status.StateChangeReason) echo "SYNTAX_ERROR: line 1:8: mismatched input" ;;
      QueryExecution.Statistics.DataScannedInBytes) echo 52428800 ;;
    esac ;;
  get-query-results) printf 'data\tcoletas\n2026-10-20\t96\n' ;;
  *) exit 2 ;;
esac
"""


@pytest.fixture
def ambiente_athena(tmp_path: Path) -> dict[str, str]:
    estado = tmp_path / "aws"
    estado.mkdir()
    aws = tmp_path / "aws_falso"
    aws.write_text(AWS_FALSO, encoding="utf-8", newline="\n")
    aws.chmod(0o755)
    return {**os.environ, "AWS": _posix(aws), "AWS_ESTADO": _posix(estado), "ESPERA": "0"}


def _rodar(*args: str, env: dict[str, str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(  # noqa: S603 (comando montado só pelo teste)
        [_bash(), _posix(RAIZ / "scripts" / "athena.sh"), *args],
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
        cwd=RAIZ,
    )


# ---------------------------------------------------------------- scripts/athena.sh
def test_roda_a_consulta_espera_e_mostra_resultado_e_custo(
    ambiente_athena: dict[str, str],
) -> None:
    arquivo = "athena/consultas/atraso_agendador.sql"
    r = _rodar(arquivo, env=ambiente_athena)
    assert r.returncode == 0, r.stderr
    assert "2026-10-20\t96" in r.stdout
    assert "lidos: 52.43 MB" in r.stdout
    estado = Path(ambiente_athena["AWS_ESTADO"])
    # O SQL chega ao Athena exatamente como está no arquivo (sem \r do Windows).
    enviado = (estado / "sql_0.txt").read_text(encoding="utf-8")
    assert enviado == (RAIZ / arquivo).read_text(encoding="utf-8").replace("\r", "").rstrip("\n")
    chamadas = (estado / "chamadas.log").read_text(encoding="utf-8")
    assert "--work-group london-cycle-hire" in chamadas
    assert "Database=london_cycle_hire" in chamadas
    # Esperou a consulta sair de RUNNING antes de pedir o resultado.
    assert chamadas.count("QueryExecution.Status.State") == 2


def test_varios_arquivos_rodam_em_ordem(ambiente_athena: dict[str, str]) -> None:
    ambiente_athena["RODANDO_ATE"] = "0"
    r = _rodar("athena/01_view_estacoes.sql", "athena/02_view_coletas.sql", env=ambiente_athena)
    assert r.returncode == 0, r.stderr
    estado = Path(ambiente_athena["AWS_ESTADO"])
    assert "VIEW estacoes" in (estado / "sql_0.txt").read_text(encoding="utf-8")
    assert "VIEW coletas" in (estado / "sql_1.txt").read_text(encoding="utf-8")


def test_consulta_com_erro_falha_e_mostra_o_motivo(ambiente_athena: dict[str, str]) -> None:
    ambiente_athena["ESTADO_FINAL"] = "FAILED"
    r = _rodar("athena/consultas/atraso_agendador.sql", env=ambiente_athena)
    assert r.returncode == 1
    assert "FAILED" in r.stderr
    assert "SYNTAX_ERROR" in r.stderr


def test_consulta_que_nunca_termina_falha(ambiente_athena: dict[str, str]) -> None:
    ambiente_athena |= {"RODANDO_ATE": "999", "TENTATIVAS": "3"}
    r = _rodar("athena/consultas/atraso_agendador.sql", env=ambiente_athena)
    assert r.returncode == 1
    assert "RUNNING" in r.stderr


def test_arquivo_inexistente(ambiente_athena: dict[str, str]) -> None:
    r = _rodar("athena/nao_existe.sql", env=ambiente_athena)
    assert r.returncode == 1
    assert "não encontrado" in r.stderr


def test_sem_argumentos(ambiente_athena: dict[str, str]) -> None:
    r = _rodar(env=ambiente_athena)
    assert r.returncode == 1
    assert "uso:" in r.stderr


# ---------------------------------------------------------------- arquivos SQL
def _sem_comentarios(sql: str) -> str:
    return "\n".join(linha for linha in sql.splitlines() if not linha.lstrip().startswith("--"))


@pytest.mark.parametrize("arquivo", sorted(PASTA_SQL.glob("0*.sql")), ids=lambda p: p.name)
def test_arquivos_de_view_so_criam_views(arquivo: Path) -> None:
    sql = _sem_comentarios(arquivo.read_text(encoding="utf-8")).strip()
    assert sql.upper().startswith("CREATE OR REPLACE VIEW ")


CONSULTAS = sorted((PASTA_SQL / "consultas").glob("*.sql"))


@pytest.mark.parametrize("arquivo", CONSULTAS, ids=lambda p: p.name)
def test_consultas_so_leem(arquivo: Path) -> None:
    sql = _sem_comentarios(arquivo.read_text(encoding="utf-8")).strip().upper()
    assert sql.startswith(("SELECT", "WITH"))
    proibidas = r"\b(INSERT|UPDATE|DELETE|DROP|ALTER|CREATE|MSCK|UNLOAD)\b"
    assert re.search(proibidas, sql) is None


def test_existem_consultas() -> None:
    assert len(CONSULTAS) >= 4


def test_padrao_do_nome_bate_com_a_chave_gravada_pela_coleta() -> None:
    """Se a coleta mudar o nome do arquivo, as views perderiam o horário: este teste quebra."""
    for nome in ("01_view_estacoes.sql", "02_view_coletas.sql"):
        sql = (PASTA_SQL / nome).read_text(encoding="utf-8")
        padrao = re.search(r"regexp_extract\(\"\$path\", '([^']+)', 1\)", sql)
        assert padrao is not None, nome
        instante = datetime(2026, 10, 21, 0, 4, 5, tzinfo=UTC)
        achado = re.search(padrao.group(1), chave_retrato(instante))
        assert achado is not None
        lido = datetime.strptime(achado.group(1), "%Y-%m-%dT%H-%M-%S")
        assert lido == instante.replace(tzinfo=None)


@pytest.mark.parametrize(
    ("minuto", "segundo", "atraso"),
    [
        (23, 46, 106),  # 22:23:46, primeira coleta agendada da Lambda: janela das 22:22
        (37, 20, 20),
        (7, 0, 0),
        (2, 0, 600),  # antes do minuto 7: pertence à janela do minuto 52 da hora anterior
        (51, 59, 899),
    ],
)
def test_formula_do_atraso_na_view_de_coletas(minuto: int, segundo: int, atraso: int) -> None:
    """A mesma conta da view `coletas`, com os operadores do SQL (o % do Trino mantém o sinal)."""
    sql = (PASTA_SQL / "02_view_coletas.sql").read_text(encoding="utf-8")
    formula = (
        "((minute(coletado_em_utc) * 60 + second(coletado_em_utc) - 7 * 60) % 900 + 900) % 900"
    )
    assert formula in sql

    def resto_trino(a: int, b: int) -> int:  # resto com o sinal do dividendo, como no SQL
        return int(abs(a) % b * (1 if a >= 0 else -1))

    x = minuto * 60 + segundo - 7 * 60
    assert resto_trino(resto_trino(x, 900) + 900, 900) == atraso
