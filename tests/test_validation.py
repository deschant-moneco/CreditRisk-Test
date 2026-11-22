"""Tests unitaires : validation, prétraitement, interprétation et service modèle."""

from __future__ import annotations

import math

import joblib
import numpy as np
import pytest
from pydantic import ValidationError

from app.prediction import ModelService, ModelUnavailableError, PredictionError, interpreter
from app.preprocessing import FEATURES, PreprocessingError, compute_features, transform
from app.validation import LIMITES, DemandeCredit, detecter_alertes

# ---------------------------------------------------------------------------
# Validation (EX01, EX02, EX03, EX06, EX08, EX09, EX10)
# ---------------------------------------------------------------------------


def test_demande_valide(demande):
    d = DemandeCredit(**demande)
    assert d.age == 35 and d.duree_mois == 12


@pytest.mark.parametrize("age", [18, 19, 74, 75])
def test_ex01_age_bornes_acceptees(demande, age):
    demande["age"] = age
    demande["anciennete_activite"] = 0
    assert DemandeCredit(**demande).age == age


@pytest.mark.parametrize("age", [-1, 0, 17, 76, 150])
def test_ex01_age_hors_bornes_rejete(demande, age):
    demande["age"] = age
    with pytest.raises(ValidationError):
        DemandeCredit(**demande)


@pytest.mark.parametrize("valeur", ["250000", None, True, [250000], {"v": 1}, -1, 0])
def test_ex02_revenu_invalide(demande, valeur):
    demande["revenu_mensuel"] = valeur
    with pytest.raises(ValidationError):
        DemandeCredit(**demande)


@pytest.mark.parametrize("valeur", [float("inf"), float("-inf"), float("nan")])
@pytest.mark.parametrize("champ", ["revenu_mensuel", "montant_credit", "anciennete_activite"])
def test_ex09_valeurs_non_finies_rejetees(demande, champ, valeur):
    demande[champ] = valeur
    with pytest.raises(ValidationError):
        DemandeCredit(**demande)


@pytest.mark.parametrize("duree", [1, 12, 120])
def test_ex03_duree_valide(demande, duree):
    demande["duree_mois"] = duree
    assert DemandeCredit(**demande).duree_mois == duree


@pytest.mark.parametrize("duree", [0, -12, 121, 12.5, 12.0, "12", True])
def test_ex03_duree_invalide(demande, duree):
    demande["duree_mois"] = duree
    with pytest.raises(ValidationError):
        DemandeCredit(**demande)


def test_ex08_champ_supplementaire_interdit(demande):
    demande["nationalite"] = "SN"
    with pytest.raises(ValidationError) as exc:
        DemandeCredit(**demande)
    assert exc.value.errors()[0]["type"] == "extra_forbidden"


def test_ex10_anciennete_incoherente_avec_age(demande):
    demande["age"] = 25
    demande["anciennete_activite"] = 20  # aurait commencé à 5 ans
    with pytest.raises(ValidationError) as exc:
        DemandeCredit(**demande)
    assert "anciennete_activite" in str(exc.value)


def test_ex10_anciennete_limite_coherente(demande):
    demande["age"] = 25
    demande["anciennete_activite"] = 25 - LIMITES["age_debut_activite_min"]
    assert DemandeCredit(**demande).anciennete_activite == 11


# ---------------------------------------------------------------------------
# Alertes pour entrées inhabituelles mais valides (EX11)
# ---------------------------------------------------------------------------

PLAGES = {
    "age": {"min": 21, "max": 65},
    "revenu_mensuel": {"min": 30000, "max": 2000000},
    "montant_credit": {"min": 50000, "max": 20000000},
    "duree_mois": {"min": 3, "max": 60},
    "anciennete_activite": {"min": 0, "max": 30},
}


def test_ex11_pas_d_alerte_pour_profil_courant(demande):
    assert detecter_alertes(DemandeCredit(**demande), PLAGES) == []


def test_ex11_alerte_hors_distribution(demande):
    demande["age"] = 72
    demande["duree_mois"] = 120
    alertes = detecter_alertes(DemandeCredit(**demande), PLAGES)
    assert "hors_distribution:age" in alertes
    assert "hors_distribution:duree_mois" in alertes


def test_ex11_alerte_taux_endettement(demande):
    demande["montant_credit"] = 3_000_000  # 250 000 / mois pour 250 000 de revenu
    alertes = detecter_alertes(DemandeCredit(**demande), PLAGES)
    assert "taux_endettement_eleve" in alertes


def test_ex11_alertes_sans_plages(demande):
    assert detecter_alertes(DemandeCredit(**demande), None) == []


# ---------------------------------------------------------------------------
# Prétraitement
# ---------------------------------------------------------------------------


def test_pretraitement_dimensions_et_valeurs(demande):
    X = transform(demande)
    assert X.shape == (1, len(FEATURES))
    ratio = (1_000_000 / 12) / 250_000
    assert X[0, FEATURES.index("ratio_mensualite_revenu")] == pytest.approx(ratio)
    assert X[0, FEATURES.index("log_revenu")] == pytest.approx(math.log(250_000))


def test_pretraitement_vectorise_identique_au_scalaire(demande):
    """Même code à l'entraînement et à l'inférence (pas de training-serving skew)."""
    scalaire = transform(demande)
    vecteur = compute_features(*([v, v] for v in demande.values()))
    np.testing.assert_array_equal(vecteur[0], scalaire[0])


def test_pretraitement_variable_manquante(demande):
    del demande["duree_mois"]
    with pytest.raises(PreprocessingError, match="duree_mois"):
        transform(demande)


def test_pretraitement_valeur_non_numerique(demande):
    demande["revenu_mensuel"] = "abc"
    with pytest.raises(PreprocessingError):
        transform(demande)


@pytest.mark.parametrize("champ", ["revenu_mensuel", "montant_credit", "duree_mois"])
def test_pretraitement_refuse_valeurs_non_positives(demande, champ):
    demande[champ] = 0
    with pytest.raises(PreprocessingError):
        transform(demande)


def test_pretraitement_refuse_non_fini(demande):
    demande["age"] = float("nan")
    with pytest.raises(PreprocessingError):
        transform(demande)


# ---------------------------------------------------------------------------
# Interprétation métier
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "proba,classe,decision",
    [
        (0.0, "faible", "favorable"),
        (0.149, "faible", "favorable"),
        (0.15, "modere", "examen_approfondi"),
        (0.2999, "modere", "examen_approfondi"),
        (0.30, "eleve", "defavorable"),
        (1.0, "eleve", "defavorable"),
    ],
)
def test_interpretation_seuils(proba, classe, decision):
    resultat = interpreter(proba, 0.30)
    assert (resultat.classe_risque, resultat.decision) == (classe, decision)


# ---------------------------------------------------------------------------
# Service modèle (EX04, EX05, EX12)
# ---------------------------------------------------------------------------


def test_ex05_fichier_modele_absent(tmp_path):
    with pytest.raises(ModelUnavailableError):
        ModelService.load(tmp_path / "absent.joblib")


def test_ex05_fichier_modele_corrompu(tmp_path):
    chemin = tmp_path / "corrompu.joblib"
    chemin.write_bytes(b"pas un modele")
    with pytest.raises(ModelUnavailableError):
        ModelService.load(chemin)


def test_ex12_modele_incompatible_avec_pretraitement(service):
    metadata = {**service.metadata, "features": ["age", "revenu_mensuel"]}
    with pytest.raises(ModelUnavailableError):
        ModelService(service.pipeline, metadata)


def test_ex12_modele_mauvaise_dimension(service, tmp_path):
    from sklearn.dummy import DummyClassifier

    clf = DummyClassifier().fit(np.zeros((4, 3)), [0, 1, 0, 1])
    chemin = tmp_path / "dim.joblib"
    joblib.dump({"pipeline": clf, "metadata": service.metadata}, chemin)
    with pytest.raises(ModelUnavailableError, match="Dimension"):
        ModelService.load(chemin)


def test_ex12_modele_sans_probabilites(service):
    class SansProba:
        n_features_in_ = len(FEATURES)

    with pytest.raises(ModelUnavailableError):
        ModelService(SansProba(), service.metadata)


def test_ex12_matrice_mal_dimensionnee(service):
    with pytest.raises(PredictionError):
        service.predict_proba(np.zeros((1, 5)))


def test_ex04_probabilite_hors_intervalle_detectee(service):
    class ModeleDefaillant:
        n_features_in_ = len(FEATURES)

        def predict_proba(self, X):
            return np.array([[-0.2, 1.2]])

    defaillant = ModelService(ModeleDefaillant(), service.metadata)
    with pytest.raises(PredictionError):
        defaillant.predict_one(np.zeros((1, len(FEATURES))))


def test_ex04_probabilite_valide(service, demande):
    proba = service.predict_one(transform(demande))
    assert math.isfinite(proba) and 0.0 <= proba <= 1.0


def test_ex13_reproductibilite(service, demande):
    X = transform(demande)
    assert len({service.predict_one(X) for _ in range(20)}) == 1


def test_info_contient_empreinte(service):
    info = service.info()
    assert info["version"] == service.version == "1.0.0"
    assert info["sha256"] and len(info["sha256"]) == 64
