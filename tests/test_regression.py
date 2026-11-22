"""Activité 5 - Tests de non-régression du logiciel et du modèle.

Le modèle testé est models/model.joblib, ou celui désigné par la variable
d'environnement CREDITRISK_CANDIDATE_MODEL (pour qualifier une nouvelle version).
La référence (métriques, cas golden, tolérances) est figée dans
models/baseline/reference.json.
"""

from __future__ import annotations

import math
import os
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
import pytest

from app.prediction import DEFAULT_MODEL_PATH, ModelService
from ml.regression import TOLERANCES, charger_reference, comparer
from ml.train import TEST_SET, features_frame

RACINE = Path(__file__).resolve().parent.parent
CANDIDATS = RACINE / "models" / "candidates"


@pytest.fixture(scope="module")
def reference() -> dict:
    return charger_reference()


@pytest.fixture(scope="module")
def candidat() -> ModelService:
    return ModelService.load(os.environ.get("CREDITRISK_CANDIDATE_MODEL", DEFAULT_MODEL_PATH))


@pytest.fixture(scope="module")
def comparaison(reference, candidat) -> dict:
    return comparer(reference, candidat)


# 1. Les tests fonctionnels réussissent après modification du code : garanti par
#    l'exécution de TOUTE la suite (tests/test_api.py, ...) dans le workflow CI.
#    Ici, on rejoue le contrat de l'API sur les 50 cas golden.
def test_nr1_contrat_api_sur_cas_golden(client, reference):
    for entree in reference["golden"]["entrees"]:
        demande = {k: (int(v) if k in ("age", "duree_mois") else float(v)) for k, v in entree.items()}
        response = client.post("/predict", json=demande)
        assert response.status_code == 200, (demande, response.text)


# 2. Les sorties du pipeline restent conformes au contrat
def test_nr2_sorties_pipeline_conformes(candidat):
    probas = candidat.predict_proba(features_frame(pd.read_csv(TEST_SET)))
    assert probas.shape == (len(pd.read_csv(TEST_SET)),)
    assert np.all(np.isfinite(probas))
    assert np.all((probas >= 0) & (probas <= 1))


def test_nr2_metadonnees_conformes(candidat):
    for cle in ("version", "features", "seuil_decision", "metriques_test", "plages_entrainement"):
        assert cle in candidat.metadata
    assert 0 < candidat.seuil_decision < 1


# 3. Les métriques du modèle sont comparées à celles de la référence
def test_nr3_metriques_comparees_a_la_reference(comparaison):
    assert comparaison["verdict"] in {"CONFORME", "A_SURVEILLER"}, comparaison["controles"]


def test_nr3_meme_version_predictions_identiques(reference, candidat):
    if candidat.version != reference["version"]:
        pytest.skip("nouvelle version : tolérance appliquée par test_nr3_metriques")
    golden = pd.DataFrame(reference["golden"]["entrees"])
    probas = candidat.predict_proba(features_frame(golden))
    np.testing.assert_allclose(
        probas, reference["golden"]["probabilites"], atol=TOLERANCES["ecart_proba_max_meme_version"]
    )
    assert candidat.sha256 == reference["sha256"], "même version mais artefact différent"


# 4. Une baisse excessive du rappel ou du F1-score est détectée
@pytest.mark.parametrize("metrique", ["rappel", "f1", "auc"])
def test_nr4_pas_de_baisse_excessive(comparaison, metrique):
    controle = next(c for c in comparaison["controles"] if c["controle"].startswith(metrique))
    assert controle["statut"] == "OK", controle


def test_nr4_le_detecteur_signale_un_modele_degrade(reference):
    """Le modèle v1.2.0 (étiquettes de défaut perdues) DOIT être bloqué."""
    degrade = ModelService.load(CANDIDATS / "model_v1.2.0.joblib")
    resultat = comparer(reference, degrade)
    assert resultat["verdict"] == "REGRESSION"
    echecs = {c["controle"].split(" ")[0] for c in resultat["controles"] if c["statut"] == "ECHEC"}
    assert {"rappel", "f1"} <= echecs


def test_nr4_le_detecteur_accepte_un_reentrainement_sain(reference):
    reentraine = ModelService.load(CANDIDATS / "model_v1.1.0.joblib")
    assert comparer(reference, reentraine)["verdict"] != "REGRESSION"


def test_nr4_baisse_juste_au_dela_de_la_tolerance(reference, candidat, monkeypatch):
    """Test aux limites du comparateur : rappel abaissé de 0,031 -> ÉCHEC."""
    import ml.regression as reg

    vrai_evaluer = reg.evaluer

    def evaluer_degrade(*args, **kwargs):
        m = vrai_evaluer(*args, **kwargs)
        m["rappel"] = reference["metriques"]["rappel"] - 0.031
        return m

    monkeypatch.setattr(reg, "evaluer", evaluer_degrade)
    resultat = comparer(reference, candidat)
    assert resultat["verdict"] == "REGRESSION"


# 5. Cohérence des prédictions après sauvegarde et rechargement du modèle
def test_nr5_sauvegarde_rechargement(candidat, tmp_path):
    X = features_frame(pd.read_csv(TEST_SET))
    avant = candidat.predict_proba(X)

    chemin = tmp_path / "model_recharge.joblib"
    joblib.dump({"pipeline": candidat.pipeline, "metadata": candidat.metadata}, chemin)
    recharge = ModelService.load(chemin)

    np.testing.assert_array_equal(recharge.predict_proba(X), avant)
    assert recharge.version == candidat.version
    assert recharge.metadata == candidat.metadata


def test_nr5_determinisme_entre_appels(candidat):
    X = features_frame(pd.read_csv(TEST_SET).head(100))
    np.testing.assert_array_equal(candidat.predict_proba(X), candidat.predict_proba(X))


def test_nr_reference_coherente():
    ref = charger_reference()
    assert ref["tolerances"] == TOLERANCES, "tolérances modifiées sans refiger la référence"
    assert len(ref["golden"]["entrees"]) == len(ref["golden"]["probabilites"]) == 50
    assert all(math.isfinite(p) for p in ref["golden"]["probabilites"])


def test_rapport_non_regression_genere(reference, tmp_path, monkeypatch):
    import ml.regression as reg

    monkeypatch.setattr(reg, "RAPPORT", tmp_path / "rapport.md")
    monkeypatch.setattr(
        "sys.argv", ["regression", str(CANDIDATS / "model_v1.1.0.joblib"), str(CANDIDATS / "model_v1.2.0.joblib")]
    )
    reg.main()
    texte = (tmp_path / "rapport.md").read_text()
    assert "candidat `1.1.0` : **A_SURVEILLER**" in texte
    assert "candidat `1.2.0` : **REGRESSION**" in texte


def test_figer_reference_reproductible(candidat, tmp_path, monkeypatch):
    import ml.regression as reg

    monkeypatch.setattr(reg, "REFERENCE", tmp_path / "baseline" / "reference.json")
    monkeypatch.setattr("sys.argv", ["regression", "--figer"])
    reg.main()
    nouvelle = reg.charger_reference()
    if candidat.version == "1.0.0":
        assert nouvelle["golden"] == charger_reference()["golden"]
        assert nouvelle["metriques"] == charger_reference()["metriques"]
