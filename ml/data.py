"""Génération d'un jeu de données SYNTHÉTIQUE documenté.

AVERTISSEMENT : ces données sont simulées. Elles servent uniquement à tester
le système (contrat, robustesse, non-régression, performance). Elles ne
permettent PAS de démontrer la performance réelle d'un modèle de crédit.

Processus générateur (graine fixe => reproductible) :
- age ~ U{21..65}
- anciennete_activite ~ Gamma(2, 3) tronquée à age - 18, arrondie à 0,5 an
- revenu_mensuel ~ LogNormale(ln 200 000, 0,6), bornée à [30 000 ; 3 000 000] FCFA
- duree_mois ∈ {3, 6, 9, 12, 18, 24, 36, 48, 60}
- montant_credit = revenu x U(0,5 ; 12), arrondi à 10 000 FCFA
- logit(P(defaut)) = -2,1 + 3,2 (ratio - 0,3) - 0,09 anciennete - 0,015 (age - 40)
                     - 0,35 ln(revenu / 200 000) + 0,012 (duree - 12) + bruit N(0 ; 0,4)
  où ratio = (montant / duree) / revenu
- defaut ~ Bernoulli(sigmoid(logit)) ; 1 = défaut, 0 = remboursement sans défaut
"""

from __future__ import annotations

import numpy as np
import pandas as pd

DUREES = np.array([3, 6, 9, 12, 18, 24, 36, 48, 60])
POIDS_DUREES = np.array([0.05, 0.12, 0.08, 0.25, 0.15, 0.15, 0.10, 0.06, 0.04])


def generer(n: int = 6000, seed: int = 42) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    age = rng.integers(21, 66, size=n)
    anciennete = np.minimum(rng.gamma(2.0, 3.0, size=n), age - 18)
    anciennete = np.round(anciennete * 2) / 2
    revenu = np.exp(rng.normal(np.log(200_000), 0.6, size=n))
    revenu = np.clip(np.round(revenu, -3), 30_000, 3_000_000)
    duree = rng.choice(DUREES, size=n, p=POIDS_DUREES)
    montant = np.round(revenu * rng.uniform(0.5, 12, size=n), -4)
    montant = np.maximum(montant, 50_000)

    ratio = (montant / duree) / revenu
    logit = (
        -2.1
        + 3.2 * (ratio - 0.3)
        - 0.09 * anciennete
        - 0.015 * (age - 40)
        - 0.35 * np.log(revenu / 200_000)
        + 0.012 * (duree - 12)
        + rng.normal(0, 0.4, size=n)
    )
    proba = 1 / (1 + np.exp(-logit))
    defaut = (rng.uniform(size=n) < proba).astype(int)

    return pd.DataFrame(
        {
            "age": age.astype(int),
            "revenu_mensuel": revenu,
            "montant_credit": montant,
            "duree_mois": duree.astype(int),
            "anciennete_activite": anciennete,
            "defaut": defaut,
        }
    )
