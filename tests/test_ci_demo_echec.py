"""Activité 7 - Test volontairement défaillant pour prouver que la CI bloque.

Désactivé par défaut. Activé par CREDITRISK_DEMO_ECHEC=1 (variable positionnée par
le job « demo-echec » du workflow, déclenché manuellement via workflow_dispatch).
"""

from __future__ import annotations

import os

import pytest


@pytest.mark.demo_echec
@pytest.mark.skipif(os.environ.get("CREDITRISK_DEMO_ECHEC") != "1", reason="démonstration CI désactivée")
def test_volontairement_defaillant(client):
    """Simule une régression : on exige un contrat que l'API ne respecte pas."""
    response = client.post("/predict", json={"age": 35})
    assert response.status_code == 200, "échec volontaire : la CI doit être rouge"
