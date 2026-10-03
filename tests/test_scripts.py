"""Testes dos scripts de publicação, rodando o bash de verdade contra um `gh` falso.

O gh falso guarda as releases numa pasta (uma subpasta por tag), então dá para conferir
o que foi criado e anexado sem tocar no GitHub.
"""

import gzip
import os
import shutil
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

import pytest

from bicicletas.coleta_api import chave_execucao, chave_retrato

from .test_coleta_api import AMOSTRA, INSTANTE

RAIZ = Path(__file__).resolve().parents[1]

GH_FALSO = r"""#!/usr/bin/env bash
# gh falso: releases = pastas em $GH_ESTADO; cada chamada fica registrada em chamadas.log
set -euo pipefail
echo "$*" >> "$GH_ESTADO/chamadas.log"
[ "$1" = "release" ] || exit 2
acao="$2"; tag="$3"; shift 3
case "$acao" in
  view)
    [ -d "$GH_ESTADO/$tag" ] || exit 1
    if [ "${1:-}" = "--json" ]; then ls "$GH_ESTADO/$tag"; fi ;;
  create)
    mkdir "$GH_ESTADO/$tag" ;;
  upload)
    destino="$GH_ESTADO/$tag/$(basename "$1")"
    [ -e "$destino" ] && { echo "já existe" >&2; exit 1; }
    cp "$1" "$destino" ;;
  download)
    dir=""; padroes=()
    while [ $# -gt 0 ]; do
      case "$1" in
        --dir) dir="$2"; shift 2 ;;
        --pattern) padroes+=("$2"); shift 2 ;;
        *) shift ;;
      esac
    done
    mkdir -p "$dir"
    shopt -s nullglob
    for p in "${padroes[@]}"; do for f in "$GH_ESTADO/$tag"/$p; do cp "$f" "$dir/"; done; done ;;
  *) exit 2 ;;
esac
"""


def _bash() -> str:
    """Bash do Git no Windows (o bash.exe do System32 é o WSL, outro sistema de arquivos)."""
    if sys.platform != "win32":
        caminho = shutil.which("bash")
        assert caminho is not None, "bash não encontrado"
        return caminho
    for candidato in (
        Path(os.environ.get("PROGRAMFILES", r"C:\Program Files")) / "Git" / "bin" / "bash.exe",
        Path(os.environ.get("LOCALAPPDATA", "")) / "Programs" / "Git" / "bin" / "bash.exe",
    ):
        if candidato.exists():
            return str(candidato)
    pytest.fail("Git Bash não encontrado (precisa do Git for Windows).", pytrace=False)


def _posix(caminho: Path | str) -> str:
    return str(caminho).replace("\\", "/")


@pytest.fixture
def ambiente(tmp_path: Path) -> dict[str, str]:
    estado = tmp_path / "releases"
    estado.mkdir()
    gh = tmp_path / "gh"
    gh.write_text(GH_FALSO, encoding="utf-8", newline="\n")
    gh.chmod(0o755)
    return {
        **os.environ,
        "GH": _posix(gh),
        "GH_ESTADO": _posix(estado),
        "PYTHON": _posix(sys.executable),
        # No Windows o Python escreve em cp1252 quando a saída é um pipe; no Linux já é UTF-8.
        "PYTHONUTF8": "1",
    }


def _rodar(script: str, *args: str, env: dict[str, str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(  # noqa: S603 (comando montado só pelo teste)
        [_bash(), _posix(RAIZ / "scripts" / script), *args],
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
        cwd=RAIZ,
    )


def _saida_da_coleta(pasta: Path) -> None:
    """Imita a pasta que a coleta deixa: um retrato e um registro de execução."""
    for chave, dados in (
        (chave_retrato(INSTANTE), gzip.compress(AMOSTRA, mtime=0)),
        (chave_execucao(INSTANTE), b'{"status": "sucesso"}'),
    ):
        arquivo = pasta / chave
        arquivo.parent.mkdir(parents=True, exist_ok=True)
        arquivo.write_bytes(dados)


def _estado(env: dict[str, str]) -> Path:
    return Path(env["GH_ESTADO"])


# ---------------------------------------------------------------- publicar_release.sh
def test_publica_criando_a_release_do_dia(tmp_path: Path, ambiente: dict[str, str]) -> None:
    _saida_da_coleta(tmp_path / "saida")
    r = _rodar("publicar_release.sh", _posix(tmp_path / "saida"), env=ambiente)
    assert r.returncode == 0, r.stderr
    release = _estado(ambiente) / "bruto-bikepoint-2026-10-03"
    assert sorted(p.name for p in release.iterdir()) == [
        "bikepoint_2026-10-03T17-22-05Z.json.gz",
        "execucao_2026-10-03T17-22-05Z.json",
    ]
    log = (_estado(ambiente) / "chamadas.log").read_text(encoding="utf-8")
    assert log.count("release create") == 1  # criada uma vez, mesmo com dois arquivos
    assert "--prerelease" in log  # release de dados nunca vira a "Latest" do projeto


def test_publica_em_release_existente_sem_recriar(tmp_path: Path, ambiente: dict[str, str]) -> None:
    (_estado(ambiente) / "bruto-bikepoint-2026-10-03").mkdir()
    _saida_da_coleta(tmp_path / "saida")
    r = _rodar("publicar_release.sh", _posix(tmp_path / "saida"), env=ambiente)
    assert r.returncode == 0, r.stderr
    assert "release create" not in (_estado(ambiente) / "chamadas.log").read_text(encoding="utf-8")


def test_nao_sobrescreve_arquivo_ja_publicado(tmp_path: Path, ambiente: dict[str, str]) -> None:
    _saida_da_coleta(tmp_path / "saida")
    assert _rodar("publicar_release.sh", _posix(tmp_path / "saida"), env=ambiente).returncode == 0
    r = _rodar("publicar_release.sh", _posix(tmp_path / "saida"), env=ambiente)
    assert r.returncode != 0
    assert "já existe" in r.stderr


def test_pasta_vazia_nao_publica_nada(tmp_path: Path, ambiente: dict[str, str]) -> None:
    (tmp_path / "saida").mkdir()
    r = _rodar("publicar_release.sh", _posix(tmp_path / "saida"), env=ambiente)
    assert r.returncode == 0
    assert "Nada para publicar" in r.stdout


def test_particao_fora_do_padrao_e_recusada(tmp_path: Path, ambiente: dict[str, str]) -> None:
    arquivo = tmp_path / "saida" / "bruto" / "bikepoint" / "data=ontem" / "x.json.gz"
    arquivo.parent.mkdir(parents=True)
    arquivo.write_bytes(b"x")
    r = _rodar("publicar_release.sh", _posix(tmp_path / "saida"), env=ambiente)
    assert r.returncode != 0
    assert "fora do padrão" in r.stderr


# ---------------------------------------------------------------- empacotar_dia.sh
# Dia fixo no passado: o pacote recusa dia que ainda não terminou, e o teste não pode
# depender da data em que roda.
DIA_PASSADO = "2026-09-30"


def _release_com_coleta(ambiente: dict[str, str], dia: str = DIA_PASSADO) -> Path:
    release = _estado(ambiente) / f"bruto-bikepoint-{dia}"
    release.mkdir()
    (release / f"bikepoint_{dia}T17-22-05Z.json.gz").write_bytes(gzip.compress(AMOSTRA, mtime=0))
    (release / f"execucao_{dia}T17-22-05Z.json").write_bytes(b'{"status": "sucesso"}')
    return release


def test_empacota_e_anexa_na_release(ambiente: dict[str, str]) -> None:
    release = _release_com_coleta(ambiente)
    r = _rodar("empacotar_dia.sh", DIA_PASSADO, env=ambiente)
    assert r.returncode == 0, r.stderr + r.stdout
    assert (release / f"pacote_bikepoint_{DIA_PASSADO}.tar").exists()


def test_empacotar_de_novo_nao_faz_nada(ambiente: dict[str, str]) -> None:
    _release_com_coleta(ambiente)
    assert _rodar("empacotar_dia.sh", DIA_PASSADO, env=ambiente).returncode == 0
    r = _rodar("empacotar_dia.sh", DIA_PASSADO, env=ambiente)
    assert r.returncode == 0
    assert "Nada a fazer" in r.stdout


def test_dia_de_hoje_nao_e_empacotado(ambiente: dict[str, str]) -> None:
    hoje = datetime.now(UTC).date().isoformat()
    release = _release_com_coleta(ambiente, hoje)
    r = _rodar("empacotar_dia.sh", hoje, env=ambiente)
    assert r.returncode != 0
    assert "ainda não terminou" in r.stderr
    assert not (release / f"pacote_bikepoint_{hoje}.tar").exists()


def test_dia_sem_release_falha(ambiente: dict[str, str]) -> None:
    r = _rodar("empacotar_dia.sh", DIA_PASSADO, env=ambiente)
    assert r.returncode != 0
    assert "não existe" in r.stderr


@pytest.mark.parametrize("dia", ["ontem", "2026-10-3", "2026-10-03; rm -rf /", ""])
def test_dia_invalido_e_recusado(dia: str, ambiente: dict[str, str]) -> None:
    r = _rodar("empacotar_dia.sh", dia, env=ambiente)
    assert r.returncode != 0
    assert not (_estado(ambiente) / "chamadas.log").exists()  # nem chegou a chamar o gh
