"""Module de validation : format, bornes et cohérence des données du demandeur.

Version 0.2 - corrige les anomalies ANO-01 à ANO-08 détectées par la première
campagne de tests (voir reports/registre_anomalies.md) :
- typage strict (pas de conversion implicite "250000" -> 250000, true -> 1) ;
- rejet des valeurs non finies (Infinity, NaN, 1e309) ;
- bornes supérieures pour toutes les variables ;
- champs supplémentaires interdits ;
- cohérence entre l'âge et l'ancienneté d'activité.

Les entrées INHABITUELLES mais VALIDES ne sont pas rejetées : elles produisent
des alertes (voir ``detecter_alertes``).
"""

from __future__ import annotations

from typing import Annotated

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StrictFloat,
    StrictInt,
    ValidationInfo,
    field_validator,
)
from pydantic_core import PydanticCustomError

LIMITES = {
    "age_min": 18,  # majorité légale
    "age_max": 75,  # politique de crédit (âge en fin de prêt raisonnable)
    "revenu_max": 50_000_000,  # FCFA / mois ; au-delà : saisie erronée probable
    "montant_max": 500_000_000,  # FCFA ; plafond microfinance très large
    "duree_min": 1,
    "duree_max": 120,  # mois
    "anciennete_max": 60,  # années
    "age_debut_activite_min": 14,  # ancienneté <= âge - 14
}
SEUIL_ENDETTEMENT = 0.5  # mensualité / revenu au-delà duquel une alerte est émise

# StrictFloat accepte les entiers JSON mais refuse les chaînes et les booléens
Montant = Annotated[StrictFloat, Field(gt=0, allow_inf_nan=False)]


class DemandeCredit(BaseModel):
    """Contrat d'entrée de POST /predict."""

    model_config = ConfigDict(extra="forbid", strict=True)

    age: StrictInt = Field(ge=LIMITES["age_min"], le=LIMITES["age_max"])
    revenu_mensuel: Annotated[Montant, Field(le=LIMITES["revenu_max"])]
    montant_credit: Annotated[Montant, Field(le=LIMITES["montant_max"])]
    duree_mois: StrictInt = Field(ge=LIMITES["duree_min"], le=LIMITES["duree_max"])
    anciennete_activite: StrictFloat = Field(ge=0, le=LIMITES["anciennete_max"], allow_inf_nan=False)

    @field_validator("anciennete_activite")
    @classmethod
    def verifier_coherence(cls, anciennete: float, info: ValidationInfo) -> float:
        age = info.data.get("age")  # absent si l'âge est lui-même invalide
        if age is not None and anciennete > age - LIMITES["age_debut_activite_min"]:
            raise PydanticCustomError(
                "incoherence",
                "anciennete_activite ({anciennete}) incompatible avec l'âge ({age}) : maximum {maximum} ans",
                {
                    "anciennete": anciennete,
                    "age": age,
                    "maximum": age - LIMITES["age_debut_activite_min"],
                },
            )
        return anciennete


def detecter_alertes(demande: DemandeCredit, plages: dict | None) -> list[str]:
    """Signale les entrées valides mais inhabituelles (sans les rejeter).

    - ``hors_distribution:<champ>`` : valeur hors de la plage observée à l'entraînement ;
      la prédiction est une extrapolation et doit être revue par un agent ;
    - ``taux_endettement_eleve`` : mensualité > 50 % du revenu.
    """
    alertes: list[str] = []
    for champ, plage in (plages or {}).items():
        valeur = getattr(demande, champ, None)
        if valeur is not None and not plage["min"] <= valeur <= plage["max"]:
            alertes.append(f"hors_distribution:{champ}")
    mensualite = demande.montant_credit / demande.duree_mois
    if mensualite / demande.revenu_mensuel > SEUIL_ENDETTEMENT:
        alertes.append("taux_endettement_eleve")
    return alertes
