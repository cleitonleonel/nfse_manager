"""Proteção contra drift entre `pynfse` local editável e `poetry.lock`."""

from __future__ import annotations

import os
from pathlib import Path
import re
import subprocess
import tomllib

import pynfse

PROJECT_ROOT = Path(__file__).resolve().parents[1]
POETRY_LOCK_PATH = PROJECT_ROOT / "poetry.lock"


def _get_locked_pynfse_ref() -> str:
    data = tomllib.loads(POETRY_LOCK_PATH.read_text(encoding="utf-8"))
    for pkg in data.get("package", []):
        if pkg.get("name") == "pynfse":
            source = pkg.get("source") or {}
            return str(source.get("resolved_reference") or "").strip()
    return ""


def test_poetry_lock_has_valid_pynfse_resolved_reference():
    """Garante que `poetry.lock` fixa explicitamente um commit SHA válido de `pynfse`."""
    locked_ref = _get_locked_pynfse_ref()
    assert re.fullmatch(r"[0-9a-f]{40}", locked_ref), (
        f"Esperado SHA-1 de 40 caracteres em poetry.lock para pynfse, obtido: {locked_ref!r}"
    )


def test_editable_pynfse_matches_poetry_lock():
    """Impede que testes locais passem usando `pynfse` editável à frente de `poetry.lock`."""
    if os.getenv("NFSE_ALLOW_PYNFSE_LOCK_DRIFT") == "1":
        return

    pynfse_repo = Path(pynfse.__file__).resolve().parents[1]
    if not (pynfse_repo / ".git").exists():
        # Ambiente CI / Docker / instalação por wheel: já usa exatamente o commit do poetry.lock
        return

    proc = subprocess.run(
        ["git", "-C", str(pynfse_repo), "rev-parse", "HEAD"],
        capture_output=True,
        text=True,
        check=True,
    )
    local_head = proc.stdout.strip()
    locked_ref = _get_locked_pynfse_ref()

    assert local_head == locked_ref, (
        "Drift detectado entre o pynfse editável local e o poetry.lock!\n"
        f"  HEAD local ({pynfse_repo}): {local_head}\n"
        f"  poetry.lock (resolved_reference): {locked_ref}\n"
        "Faça push do emissor_nfse e execute `poetry update pynfse --lock` antes de commitar/deployar "
        "(ou defina NFSE_ALLOW_PYNFSE_LOCK_DRIFT=1 apenas para testes locais temporários)."
    )
