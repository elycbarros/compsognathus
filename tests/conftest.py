"""Fixtures compartilhadas pela suíte de testes.

Cada parser é testado com HTML sintético para que os testes sejam rápidos,
determinísticos e independentes da disponibilidade dos sites externos.
"""
from pathlib import Path

import pytest


FIXTURES_DIR = Path(__file__).parent / "fixtures"


@pytest.fixture
def load_fixture():
    """Retorna uma função que lê uma fixture HTML pelo nome do arquivo."""
    def _load(name: str) -> str:
        path = FIXTURES_DIR / name
        assert path.exists(), f"Fixture não encontrada: {path}"
        return path.read_text(encoding="utf-8")

    return _load
