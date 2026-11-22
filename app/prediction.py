"""Module de prédiction : chargement du modèle versionné et interprétation métier."""

from __future__ import annotations

import hashlib
import math
from dataclasses import dataclass
from pathlib import Path

import joblib
import numpy as np

from app.preprocessing import FEATURES

DEFAULT_MODEL_PATH = Path(__file__).resolve().parent.parent / "models" / "model.joblib"


class ModelUnavailableError(Exception):
    """Le modèle n'est pas chargé ou ne peut pas l'être."""


class PredictionError(Exception):
    """Erreur interne pendant l'inférence."""


@dataclass(frozen=True)
class Interpretation:
    classe_risque: str
    decision: str


def interpreter(probabilite: float, seuil_decision: float) -> Interpretation:
    """Couche applicative : traduit une probabilité en information exploitable.

    - probabilité < 0,5 x seuil        -> risque faible, avis favorable
    - 0,5 x seuil <= probabilité < seuil -> risque modéré, examen approfondi
    - probabilité >= seuil              -> risque élevé, avis défavorable
    La décision finale reste celle de l'agent de crédit.
    """
    if probabilite >= seuil_decision:
        return Interpretation("eleve", "defavorable")
    if probabilite >= seuil_decision / 2:
        return Interpretation("modere", "examen_approfondi")
    return Interpretation("faible", "favorable")


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for bloc in iter(lambda: f.read(65536), b""):
            h.update(bloc)
    return h.hexdigest()


class ModelService:
    """Encapsule le pipeline scikit-learn et ses métadonnées."""

    def __init__(self, pipeline, metadata: dict, sha256: str | None = None):
        self.pipeline = pipeline
        self.metadata = dict(metadata)
        self.sha256 = sha256
        self._verifier_coherence()

    @classmethod
    def load(cls, path: str | Path = DEFAULT_MODEL_PATH) -> ModelService:
        path = Path(path)
        if not path.is_file():
            raise ModelUnavailableError(f"Fichier modèle introuvable : {path}")
        try:
            artefact = joblib.load(path)
            pipeline = artefact["pipeline"]
            metadata = artefact["metadata"]
        except Exception as exc:  # fichier corrompu, format inattendu...
            raise ModelUnavailableError("Artefact modèle illisible") from exc
        return cls(pipeline, metadata, sha256=_sha256(path))

    def _verifier_coherence(self) -> None:
        features_modele = tuple(self.metadata.get("features", ()))
        if features_modele != FEATURES:
            raise ModelUnavailableError("Les variables du modèle ne correspondent pas au prétraitement")
        n_attendu = getattr(self.pipeline, "n_features_in_", len(FEATURES))
        if n_attendu != len(FEATURES):
            raise ModelUnavailableError("Dimension du modèle incohérente")
        if not hasattr(self.pipeline, "predict_proba"):
            raise ModelUnavailableError("Le modèle ne fournit pas de probabilités")

    @property
    def version(self) -> str:
        return str(self.metadata.get("version", "inconnue"))

    @property
    def seuil_decision(self) -> float:
        return float(self.metadata.get("seuil_decision", 0.5))

    def predict_proba(self, X: np.ndarray) -> np.ndarray:
        """Probabilités de défaut pour une matrice (n, len(FEATURES))."""
        X = np.asarray(X, dtype=float)
        if X.ndim != 2 or X.shape[1] != len(FEATURES):
            raise PredictionError(f"Dimensions inattendues : {X.shape}, attendu (n, {len(FEATURES)})")
        probas = self.pipeline.predict_proba(X)[:, 1]
        if not np.all(np.isfinite(probas)) or np.any(probas < 0) or np.any(probas > 1):
            raise PredictionError("Probabilité hors de l'intervalle [0, 1]")
        return probas

    def predict_one(self, X: np.ndarray) -> float:
        proba = float(self.predict_proba(X)[0])
        if not math.isfinite(proba):  # pragma: no cover - garde-fou redondant
            raise PredictionError("Probabilité non finie")
        return proba

    def info(self) -> dict:
        return {**self.metadata, "sha256": self.sha256}
