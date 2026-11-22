"""Activité 4 - Tests de robustesse : entrées limites et comportements inattendus.

Distinction appliquée :
- entrée INVALIDE  -> rejetée (422 / 400), aucune prédiction ;
- entrée INHABITUELLE mais VALIDE -> prédiction (200) accompagnée d'alertes.
Chaque test référence l'identifiant du registre des anomalies (reports/registre_anomalies.md).
"""

from __future__ import annotations

import json
import math

import numpy as np
import pytest

from app.validation import LIMITES


def post_brut(client, corps: str):
    return client.post("/predict", content=corps, headers={"Content-Type": "application/json"})


def test_probabilite_dans_intervalle(client, demande):
    """Test de contrat (exemple de l'énoncé)."""
    resultat = client.post("/predict", json=demande).json()
    probabilite = resultat["probabilite_defaut"]
    assert math.isfinite(probabilite)
    assert 0.0 <= probabilite <= 1.0


# --- R01 : valeurs manquantes -------------------------------------------------
@pytest.mark.parametrize("champ", ["age", "revenu_mensuel", "montant_credit", "duree_mois", "anciennete_activite"])
def test_r01_valeur_null(client, demande, champ):
    demande[champ] = None
    response = client.post("/predict", json=demande)
    assert response.status_code == 422
    assert response.json()["details"][0]["champ"] == champ


def test_r01_objet_vide(client):
    response = client.post("/predict", json={})
    assert response.status_code == 422
    assert len(response.json()["details"]) == 5


# --- R02 : valeurs non numériques ---------------------------------------------
@pytest.mark.parametrize("valeur", ["35", "trente-cinq", True, [35], {"v": 35}, "", "1e3"])
@pytest.mark.parametrize("champ", ["age", "revenu_mensuel", "montant_credit"])
def test_r02_valeur_non_numerique(client, demande, champ, valeur):
    demande[champ] = valeur
    response = client.post("/predict", json=demande)
    assert response.status_code == 422, f"{champ}={valeur!r} accepté"


# --- R03 : valeurs infinies ou non finies -------------------------------------
@pytest.mark.parametrize("litteral", ["Infinity", "-Infinity", "NaN", "1e309", "-1e309"])
@pytest.mark.parametrize("champ", ["revenu_mensuel", "montant_credit", "anciennete_activite"])
def test_r03_valeur_non_finie(client, demande, champ, litteral):
    corps = json.dumps(demande).replace(f'"{champ}": {json.dumps(demande[champ])}', f'"{champ}": {litteral}')
    assert litteral in corps
    response = post_brut(client, corps)
    assert response.status_code == 422, response.text
    assert "Traceback" not in response.text


# --- R04 : valeurs aux limites des intervalles autorisés -----------------------
LIMITES_ACCEPTEES = [
    ("age", LIMITES["age_min"]),
    ("age", LIMITES["age_max"]),
    ("duree_mois", LIMITES["duree_min"]),
    ("duree_mois", LIMITES["duree_max"]),
    ("revenu_mensuel", 1),
    ("revenu_mensuel", LIMITES["revenu_max"]),
    ("montant_credit", 1),
    ("montant_credit", LIMITES["montant_max"]),
    ("anciennete_activite", 0),
]
LIMITES_REJETEES = [
    ("age", LIMITES["age_min"] - 1),
    ("age", LIMITES["age_max"] + 1),
    ("duree_mois", LIMITES["duree_min"] - 1),
    ("duree_mois", LIMITES["duree_max"] + 1),
    ("revenu_mensuel", 0),
    ("revenu_mensuel", LIMITES["revenu_max"] + 1),
    ("montant_credit", 0),
    ("montant_credit", LIMITES["montant_max"] + 1),
    ("anciennete_activite", -0.5),
]


@pytest.mark.parametrize("champ,valeur", LIMITES_ACCEPTEES)
def test_r04_limite_acceptee(client, demande, champ, valeur):
    demande[champ] = valeur
    if champ == "age":
        demande["anciennete_activite"] = 0
    response = client.post("/predict", json=demande)
    assert response.status_code == 200, response.text
    p = response.json()["probabilite_defaut"]
    assert math.isfinite(p) and 0 <= p <= 1


@pytest.mark.parametrize("champ,valeur", LIMITES_REJETEES)
def test_r04_limite_rejetee(client, demande, champ, valeur):
    demande[champ] = valeur
    response = client.post("/predict", json=demande)
    assert response.status_code == 422
    assert champ in {d["champ"] for d in response.json()["details"]}


def test_r04_coherence_age_anciennete(client, demande):
    demande["age"] = 20
    demande["anciennete_activite"] = 10
    response = client.post("/predict", json=demande)
    assert response.status_code == 422
    assert response.json()["details"][0]["champ"] == "anciennete_activite"


# --- R05 : entrées valides mais très éloignées des données d'entraînement ------
def test_r05_hors_distribution_signale(client, demande):
    demande.update(
        age=74,
        revenu_mensuel=40_000_000,
        montant_credit=400_000_000,
        duree_mois=120,
        anciennete_activite=50,
    )
    response = client.post("/predict", json=demande)
    assert response.status_code == 200
    resultat = response.json()
    assert 0 <= resultat["probabilite_defaut"] <= 1
    for champ in ("age", "revenu_mensuel", "montant_credit", "duree_mois", "anciennete_activite"):
        assert f"hors_distribution:{champ}" in resultat["alertes"]


def test_r05_endettement_extreme_signale(client, demande):
    demande.update(revenu_mensuel=50_000, montant_credit=10_000_000, duree_mois=3)
    resultat = client.post("/predict", json=demande).json()
    assert "taux_endettement_eleve" in resultat["alertes"]
    assert resultat["classe_risque"] == "eleve"


def test_r05_profil_courant_sans_alerte(client, demande):
    assert client.post("/predict", json=demande).json()["alertes"] == []


# --- R06 : schéma incorrect ----------------------------------------------------
@pytest.mark.parametrize(
    "corps",
    [
        [{"age": 35}],
        {"demande": {"age": 35}},
        {"AGE": 35, "Revenu_Mensuel": 250000},
        {
            "age": 35,
            "revenu_mensuel": 250000,
            "montant_credit": 1000000,
            "duree_mois": 12,
            "anciennete_activite": 4,
            "score_interne": 999,
        },
    ],
    ids=["liste", "objet_imbrique", "casse_differente", "champ_en_trop"],
)
def test_r06_schema_incorrect(client, corps):
    response = client.post("/predict", json=corps)
    assert response.status_code == 422


def test_r06_content_type_incorrect(client, demande):
    response = client.post("/predict", content=json.dumps(demande), headers={"Content-Type": "text/plain"})
    assert response.status_code in (415, 422)


def test_r06_corps_volumineux(client, demande):
    demande["commentaire"] = "x" * 1_000_000
    response = client.post("/predict", json=demande)
    assert response.status_code == 422
    assert len(response.content) < 5_000  # la réponse ne renvoie pas l'entrée


# --- R07 : propriétés générales (fuzzing déterministe + test métamorphique) -----
def test_r07_fuzzing_entrees_valides(client):
    rng = np.random.default_rng(2024)
    for _ in range(200):
        age = int(rng.integers(LIMITES["age_min"], LIMITES["age_max"] + 1))
        demande = {
            "age": age,
            "revenu_mensuel": float(rng.uniform(1, LIMITES["revenu_max"])),
            "montant_credit": float(rng.uniform(1, LIMITES["montant_max"])),
            "duree_mois": int(rng.integers(1, LIMITES["duree_max"] + 1)),
            "anciennete_activite": float(rng.uniform(0, age - LIMITES["age_debut_activite_min"])),
        }
        response = client.post("/predict", json=demande)
        assert response.status_code == 200, (demande, response.text)
        p = response.json()["probabilite_defaut"]
        assert math.isfinite(p) and 0 <= p <= 1


def test_r07_metamorphique_montant(client, demande):
    """Toutes choses égales par ailleurs, augmenter le montant n'abaisse pas le risque."""
    probas = []
    for montant in (200_000, 500_000, 1_000_000, 2_000_000, 5_000_000):
        demande["montant_credit"] = montant
        probas.append(client.post("/predict", json=demande).json()["probabilite_defaut"])
    assert probas == sorted(probas)


def test_r07_metamorphique_revenu(client, demande):
    """Toutes choses égales par ailleurs, un revenu plus élevé n'augmente pas le risque."""
    probas = []
    for revenu in (80_000, 150_000, 250_000, 500_000, 1_000_000):
        demande["revenu_mensuel"] = revenu
        probas.append(client.post("/predict", json=demande).json()["probabilite_defaut"])
    assert probas == sorted(probas, reverse=True)


def test_r07_entier_et_flottant_equivalents(client, demande):
    p1 = client.post("/predict", json=demande).json()["probabilite_defaut"]
    demande["revenu_mensuel"] = 250000.0
    p2 = client.post("/predict", json=demande).json()["probabilite_defaut"]
    assert p1 == p2
