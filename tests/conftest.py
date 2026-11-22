"""Fixtures partagées par les suites de tests."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.prediction import DEFAULT_MODEL_PATH, ModelService

DEMANDE_VALIDE = {
    "age": 35,
    "revenu_mensuel": 250000,
    "montant_credit": 1000000,
    "duree_mois": 12,
    "anciennete_activite": 4,
}


@pytest.fixture(scope="session")
def client():
    """Client HTTP en mémoire ; le contexte déclenche le chargement du modèle (lifespan)."""
    with TestClient(app, raise_server_exceptions=False) as c:
        yield c


@pytest.fixture
def demande():
    """Copie fraîche d'une demande valide (modifiable par chaque test)."""
    return dict(DEMANDE_VALIDE)


@pytest.fixture(scope="session")
def service() -> ModelService:
    return ModelService.load(DEFAULT_MODEL_PATH)


@pytest.fixture
def sans_modele(client, monkeypatch):
    """Simule un modèle indisponible / non chargé pendant un test."""
    monkeypatch.setitem(app.state._state, "model_service", None)
    return client
