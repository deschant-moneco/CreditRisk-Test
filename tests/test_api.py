"""Activité 2 - Tests fonctionnels du contrat de l'API (scénarios S01 à S10 + endpoints).

Contrat documenté (README, section « Contrat de l'API ») :
- 200 : prédiction ; champs probabilite_defaut, classe_risque, decision_suggeree, ...
- 400 : corps de requête mal formé (JSON invalide)
- 422 : données invalides ; {"erreur": "donnees_invalides", "details": [{"champ", ...}]}
- 503 : modèle indisponible ; {"erreur": "modele_indisponible"}
"""

from __future__ import annotations

import math

import pytest

CHAMPS_REPONSE = {
    "request_id",
    "probabilite_defaut",
    "classe_risque",
    "decision_suggeree",
    "seuil_decision",
    "alertes",
    "version_modele",
    "duree_inference_ms",
}


def champs_en_erreur(response) -> set[str]:
    return {d["champ"] for d in response.json().get("details", [])}


# --- S01 : requête valide ----------------------------------------------------
def test_s01_requete_valide(client, demande):
    response = client.post("/predict", json=demande)

    assert response.status_code == 200
    resultat = response.json()
    assert set(resultat) == CHAMPS_REPONSE
    assert math.isfinite(resultat["probabilite_defaut"])
    assert 0 <= resultat["probabilite_defaut"] <= 1
    assert resultat["classe_risque"] in {"faible", "modere", "eleve"}
    assert resultat["decision_suggeree"] in {"favorable", "examen_approfondi", "defavorable"}
    assert resultat["alertes"] == []
    assert resultat["version_modele"] == "1.0.0"


# --- S02 : champ obligatoire manquant ---------------------------------------
@pytest.mark.parametrize("champ", ["age", "revenu_mensuel", "montant_credit", "duree_mois", "anciennete_activite"])
def test_s02_champ_obligatoire_manquant(client, demande, champ):
    del demande[champ]
    response = client.post("/predict", json=demande)

    assert response.status_code == 422
    assert response.json()["erreur"] == "donnees_invalides"
    assert champ in champs_en_erreur(response)


# --- S03 : âge négatif --------------------------------------------------------
def test_s03_age_negatif(client, demande):
    demande["age"] = -5
    response = client.post("/predict", json=demande)

    assert response.status_code == 422
    assert "age" in champs_en_erreur(response)


# --- S04 : revenu sous forme de texte ----------------------------------------
@pytest.mark.parametrize("valeur", ["250000", "deux cent mille", ""])
def test_s04_revenu_texte(client, demande, valeur):
    demande["revenu_mensuel"] = valeur
    response = client.post("/predict", json=demande)

    assert response.status_code == 422
    assert "revenu_mensuel" in champs_en_erreur(response)


# --- S05 : montant nul ou négatif --------------------------------------------
@pytest.mark.parametrize("valeur", [0, -1, -1000000])
def test_s05_montant_nul_ou_negatif(client, demande, valeur):
    demande["montant_credit"] = valeur
    response = client.post("/predict", json=demande)

    assert response.status_code == 422
    assert "montant_credit" in champs_en_erreur(response)


# --- S06 : durée non entière --------------------------------------------------
@pytest.mark.parametrize("valeur", [12.5, "12", 12.0])
def test_s06_duree_non_entiere(client, demande, valeur):
    demande["duree_mois"] = valeur
    response = client.post("/predict", json=demande)

    assert response.status_code == 422
    assert "duree_mois" in champs_en_erreur(response)


# --- S07 : champs supplémentaires non autorisés -----------------------------
def test_s07_champ_supplementaire(client, demande):
    demande["sexe"] = "F"
    response = client.post("/predict", json=demande)

    assert response.status_code == 422
    assert "sexe" in champs_en_erreur(response)


# --- S08 : valeurs extrêmement élevées ---------------------------------------
@pytest.mark.parametrize(
    "champ,valeur",
    [
        ("age", 10**6),
        ("revenu_mensuel", 1e15),
        ("montant_credit", 1e18),
        ("duree_mois", 10**9),
        ("anciennete_activite", 1e6),
    ],
)
def test_s08_valeurs_extremement_elevees(client, demande, champ, valeur):
    demande[champ] = valeur
    response = client.post("/predict", json=demande)

    assert response.status_code == 422
    assert champ in champs_en_erreur(response)


# --- S09 : modèle indisponible ou non chargé ---------------------------------
def test_s09_modele_indisponible_predict(sans_modele, demande):
    response = sans_modele.post("/predict", json=demande)

    assert response.status_code == 503
    assert response.json() == {
        "erreur": "modele_indisponible",
        "message": "Le modèle de prédiction n'est pas disponible.",
    }


def test_s09_modele_indisponible_health(sans_modele):
    response = sans_modele.get("/health")

    assert response.status_code == 503
    assert response.json()["modele_charge"] is False


def test_s09_modele_indisponible_model_info(sans_modele):
    response = sans_modele.get("/model-info")

    assert response.status_code == 503
    assert response.json()["erreur"] == "modele_indisponible"


# --- S10 : requête mal formée -------------------------------------------------
@pytest.mark.parametrize(
    "corps",
    ['{"age": 35, "revenu_mensuel": 250000', "ceci n'est pas du JSON", "{'age': 35}"],
)
def test_s10_json_mal_forme(client, corps):
    response = client.post("/predict", content=corps, headers={"Content-Type": "application/json"})

    assert response.status_code == 400
    assert response.json()["erreur"] == "requete_mal_formee"


@pytest.mark.parametrize("corps", ["[]", "42", '"texte"', "null"])
def test_s10_json_valide_mais_pas_un_objet(client, corps):
    response = client.post("/predict", content=corps, headers={"Content-Type": "application/json"})

    assert response.status_code == 422


def test_s10_corps_vide(client):
    response = client.post("/predict")

    assert response.status_code == 422


# --- Endpoints de service -----------------------------------------------------
def test_health_ok(client):
    response = client.get("/health")

    assert response.status_code == 200
    assert response.json()["status"] == "ok"
    assert response.json()["modele_charge"] is True


def test_model_info(client):
    response = client.get("/model-info")

    assert response.status_code == 200
    info = response.json()
    for cle in ("version", "algorithme", "features", "seuil_decision", "metriques_test", "sha256"):
        assert cle in info
    assert len(info["sha256"]) == 64


def test_methode_non_autorisee(client):
    assert client.get("/predict").status_code == 405


def test_route_inconnue(client):
    assert client.get("/inexistant").status_code == 404
