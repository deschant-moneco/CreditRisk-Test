"""Activité 3 - Tests d'intégration de bout en bout.

Vérifient la collaboration validation -> prétraitement -> modèle -> API,
ainsi que la gestion propre des erreurs (aucune trace technique exposée).
"""

from __future__ import annotations

import logging

import numpy as np
import pytest
from fastapi.testclient import TestClient

from app import main as main_module
from app import preprocessing
from app.main import app
from app.prediction import DEFAULT_MODEL_PATH, interpreter
from app.validation import DemandeCredit

MOTS_INTERDITS = ("Traceback", 'File "', "Exception", "Error(", ".py", "line ")


def assert_sans_trace_technique(response):
    texte = response.text
    for mot in MOTS_INTERDITS:
        assert mot not in texte, f"trace technique exposée : {mot!r} dans {texte!r}"


# ---------------------------------------------------------------------------
# Scénario principal (étapes 1 à 6)
# ---------------------------------------------------------------------------


def test_scenario_principal_bout_en_bout(client, demande, service, monkeypatch):
    espion = {}
    transform_original = preprocessing.transform

    def transform_espion(d):
        espion["entree"] = dict(d)
        espion["sortie"] = transform_original(d)
        return espion["sortie"]

    monkeypatch.setattr(preprocessing, "transform", transform_espion)

    # 1. requête valide
    response = client.post("/predict", json=demande)
    assert response.status_code == 200
    resultat = response.json()

    # 2. validation : les données transmises au prétraitement sont celles validées
    assert espion["entree"] == DemandeCredit(**demande).model_dump()

    # 3. transformation des variables
    X = espion["sortie"]
    assert X.shape == (1, 6)
    assert np.all(np.isfinite(X))
    assert X[0, 5] == pytest.approx((1_000_000 / 12) / 250_000)

    # 4. prédiction : la probabilité de l'API = celle du modèle appelé directement
    attendu = service.predict_one(X)
    assert resultat["probabilite_defaut"] == pytest.approx(attendu, abs=1e-6)

    # 5. structure de la réponse et cohérence de l'interprétation
    interpretation = interpreter(attendu, service.seuil_decision)
    assert resultat["classe_risque"] == interpretation.classe_risque
    assert resultat["decision_suggeree"] == interpretation.decision
    assert resultat["seuil_decision"] == service.seuil_decision
    assert isinstance(resultat["alertes"], list)
    assert resultat["duree_inference_ms"] >= 0

    # 6. métadonnées cohérentes entre /predict, /model-info, /health et le fichier
    info = client.get("/model-info").json()
    sante = client.get("/health").json()
    assert info["version"] == resultat["version_modele"] == sante["version_modele"]
    assert info["seuil_decision"] == resultat["seuil_decision"]
    assert info["features"] == list(preprocessing.FEATURES)
    assert info["variables_entree"] == list(preprocessing.RAW_FIELDS)
    assert info["sha256"] == service.sha256
    assert 0.5 <= info["metriques_test"]["auc"] <= 1.0


def test_identifiants_de_requete_uniques(client, demande):
    ids = {client.post("/predict", json=demande).json()["request_id"] for _ in range(5)}
    assert len(ids) == 5


def test_lot_de_profils_varies(client):
    """Plusieurs profils traversent la chaîne complète sans erreur."""
    rng = np.random.default_rng(0)
    for _ in range(30):
        age = int(rng.integers(21, 66))
        demande = {
            "age": age,
            "revenu_mensuel": float(rng.integers(40, 1500) * 1000),
            "montant_credit": float(rng.integers(5, 300) * 10000),
            "duree_mois": int(rng.choice([3, 6, 12, 24, 36])),
            "anciennete_activite": float(rng.integers(0, age - 17)),
        }
        response = client.post("/predict", json=demande)
        assert response.status_code == 200, response.text
        assert 0 <= response.json()["probabilite_defaut"] <= 1


# ---------------------------------------------------------------------------
# Scénarios complémentaires
# ---------------------------------------------------------------------------


def test_modele_ne_peut_pas_etre_charge(monkeypatch, tmp_path, demande):
    """Démarrage avec un chemin de modèle invalide : service dégradé mais pas de crash."""
    monkeypatch.setitem(app.state._state, "model_service", app.state.model_service)  # restauration
    monkeypatch.setenv("CREDITRISK_MODEL_PATH", str(tmp_path / "absent.joblib"))
    with TestClient(app, raise_server_exceptions=False) as c:
        assert c.get("/health").status_code == 503
        response = c.post("/predict", json=demande)
        assert response.status_code == 503
        assert_sans_trace_technique(response)


def test_modele_corrompu_au_demarrage(monkeypatch, tmp_path, demande):
    monkeypatch.setitem(app.state._state, "model_service", app.state.model_service)
    corrompu = tmp_path / "model.joblib"
    corrompu.write_bytes(b"\x00\x01corrompu")
    monkeypatch.setenv("CREDITRISK_MODEL_PATH", str(corrompu))
    with TestClient(app, raise_server_exceptions=False) as c:
        response = c.post("/predict", json=demande)
        assert response.status_code == 503
        assert_sans_trace_technique(response)


def test_demarrage_avec_modele_valide(monkeypatch):
    monkeypatch.setitem(app.state._state, "model_service", app.state.model_service)
    monkeypatch.setenv("CREDITRISK_MODEL_PATH", str(DEFAULT_MODEL_PATH))
    with TestClient(app) as c:
        assert c.get("/health").status_code == 200


def test_variable_attendue_absente_au_pretraitement(client, demande, monkeypatch):
    """La validation est contournée (bug) : le prétraitement détecte la variable absente."""
    transform_original = preprocessing.transform

    def transform_sans_age(d):
        d = dict(d)
        d.pop("age")
        return transform_original(d)

    monkeypatch.setattr(preprocessing, "transform", transform_sans_age)
    response = client.post("/predict", json=demande)

    assert response.status_code == 500
    assert response.json()["erreur"] == "erreur_pretraitement"
    assert_sans_trace_technique(response)


def test_pretraitement_retourne_une_erreur(client, demande, monkeypatch, caplog):
    def transform_en_echec(d):
        raise preprocessing.PreprocessingError("détail interne confidentiel")

    monkeypatch.setattr(preprocessing, "transform", transform_en_echec)
    with caplog.at_level(logging.ERROR, logger="creditrisk"):
        response = client.post("/predict", json=demande)

    assert response.status_code == 500
    assert response.json() == {
        "erreur": "erreur_pretraitement",
        "message": "La demande n'a pas pu être traitée.",
    }
    assert "confidentiel" not in response.text
    assert "Erreur de prétraitement" in caplog.text  # tracé côté serveur uniquement


def test_dimensions_incompatibles_avec_le_modele(client, demande, monkeypatch):
    monkeypatch.setattr(preprocessing, "transform", lambda d: np.zeros((1, 4)))
    response = client.post("/predict", json=demande)

    assert response.status_code == 500
    assert response.json()["erreur"] == "erreur_prediction"
    assert_sans_trace_technique(response)


def test_erreur_interne_pendant_la_prediction(client, demande, monkeypatch):
    service = app.state.model_service

    def predict_proba_en_echec(X):
        raise RuntimeError("segfault simulé dans /opt/model/secret.py line 42")

    monkeypatch.setattr(service.pipeline, "predict_proba", predict_proba_en_echec)
    response = client.post("/predict", json=demande)

    assert response.status_code == 500
    assert response.json() == {
        "erreur": "erreur_interne",
        "message": "Une erreur interne est survenue.",
    }
    assert_sans_trace_technique(response)
    assert "secret" not in response.text


def test_modele_renvoie_probabilite_invalide(client, demande, monkeypatch):
    service = app.state.model_service
    monkeypatch.setattr(service.pipeline, "predict_proba", lambda X: np.array([[0.5, np.nan]]))
    response = client.post("/predict", json=demande)

    assert response.status_code == 500
    assert response.json()["erreur"] == "erreur_prediction"


def test_service_retabli_apres_erreur(client, demande, monkeypatch):
    """Une erreur ponctuelle ne laisse pas l'application dans un état dégradé."""
    with monkeypatch.context() as m:
        m.setattr(preprocessing, "transform", lambda d: np.zeros((1, 2)))
        assert client.post("/predict", json=demande).status_code == 500
    assert client.post("/predict", json=demande).status_code == 200


def test_module_main_utilise_le_module_pretraitement():
    """Garde-fou : main appelle preprocessing.transform via le module (patchable)."""
    assert main_module.preprocessing is preprocessing
