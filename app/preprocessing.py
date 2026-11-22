"""Module de prétraitement : transformation des variables brutes en variables du modèle.

La même fonction ``compute_features`` est utilisée à l'entraînement (vectorisé)
et à l'inférence (une seule demande), afin d'éviter tout écart
entraînement / production (« training-serving skew »).
"""

from __future__ import annotations

from collections.abc import Mapping

import numpy as np

# Variables brutes attendues en entrée (contrat de l'API)
RAW_FIELDS: tuple[str, ...] = (
    "age",
    "revenu_mensuel",
    "montant_credit",
    "duree_mois",
    "anciennete_activite",
)

# Variables produites par le prétraitement, dans l'ordre attendu par le modèle
FEATURES: tuple[str, ...] = (
    "age",
    "log_revenu",
    "log_montant",
    "duree_mois",
    "anciennete_activite",
    "ratio_mensualite_revenu",
)


class PreprocessingError(Exception):
    """Erreur levée lorsque les données ne peuvent pas être transformées."""


def compute_features(age, revenu_mensuel, montant_credit, duree_mois, anciennete_activite) -> np.ndarray:
    """Calcule la matrice de variables (n, len(FEATURES)) à partir des variables brutes.

    Accepte des scalaires ou des tableaux de même longueur.
    """
    age = np.atleast_1d(np.asarray(age, dtype=float))
    revenu = np.atleast_1d(np.asarray(revenu_mensuel, dtype=float))
    montant = np.atleast_1d(np.asarray(montant_credit, dtype=float))
    duree = np.atleast_1d(np.asarray(duree_mois, dtype=float))
    anciennete = np.atleast_1d(np.asarray(anciennete_activite, dtype=float))

    if np.any(revenu <= 0) or np.any(montant <= 0) or np.any(duree <= 0):
        raise PreprocessingError("revenu_mensuel, montant_credit et duree_mois doivent être strictement positifs")

    mensualite = montant / duree
    ratio = mensualite / revenu
    matrice = np.column_stack([age, np.log(revenu), np.log(montant), duree, anciennete, ratio])
    if not np.all(np.isfinite(matrice)):
        raise PreprocessingError("Le prétraitement a produit des valeurs non finies")
    return matrice


def transform(demande: Mapping[str, float]) -> np.ndarray:
    """Transforme une demande (dictionnaire validé) en matrice (1, len(FEATURES))."""
    manquants = [champ for champ in RAW_FIELDS if demande.get(champ) is None]
    if manquants:
        raise PreprocessingError(f"Variables manquantes : {', '.join(manquants)}")
    try:
        return compute_features(*(demande[champ] for champ in RAW_FIELDS))
    except (TypeError, ValueError) as exc:
        raise PreprocessingError("Variables non numériques") from exc
