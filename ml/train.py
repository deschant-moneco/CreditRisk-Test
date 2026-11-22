"""Entraînement et évaluation du modèle de risque de défaut.

Usage :
    python -m ml.train                       # (re)construit le modèle de référence v1.0.0
    python -m ml.train --variante retrain    # candidat v1.1.0 (nouvelles données)
    python -m ml.train --variante degrade    # candidat v1.2.0 volontairement dégradé

Le jeu d'évaluation (data/test_set.csv) est figé : toutes les versions sont
comparées sur les mêmes observations.
"""

from __future__ import annotations

import argparse
import json
from datetime import UTC, datetime
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
import sklearn
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import (
    accuracy_score,
    f1_score,
    precision_score,
    recall_score,
    roc_auc_score,
)
from sklearn.model_selection import train_test_split
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler

from app.preprocessing import FEATURES, RAW_FIELDS, compute_features
from ml.data import generer

RACINE = Path(__file__).resolve().parent.parent
DATA_DIR = RACINE / "data"
MODELS_DIR = RACINE / "models"
TEST_SET = DATA_DIR / "test_set.csv"
SEUIL_DECISION = 0.30  # privilégie le rappel : un défaut non détecté coûte plus cher

VARIANTES = {
    # nom: (version, graine des données, C, taux de défauts « perdus » dans les étiquettes)
    "reference": ("1.0.0", 42, 1.0, 0.0),
    "retrain": ("1.1.0", 7, 0.5, 0.0),
    "degrade": ("1.2.0", 7, 1.0, 0.6),
}


def features_frame(df: pd.DataFrame) -> np.ndarray:
    return compute_features(*(df[c].to_numpy() for c in RAW_FIELDS))


def evaluer(pipeline, df: pd.DataFrame, seuil: float = SEUIL_DECISION) -> dict:
    X = features_frame(df)
    y = df["defaut"].to_numpy()
    proba = pipeline.predict_proba(X)[:, 1]
    pred = (proba >= seuil).astype(int)
    return {
        "auc": round(float(roc_auc_score(y, proba)), 4),
        "rappel": round(float(recall_score(y, pred)), 4),
        "precision": round(float(precision_score(y, pred, zero_division=0)), 4),
        "f1": round(float(f1_score(y, pred)), 4),
        "exactitude": round(float(accuracy_score(y, pred)), 4),
        "taux_defaut_reel": round(float(y.mean()), 4),
        "taux_defaut_predit": round(float(pred.mean()), 4),
        "n": len(y),
    }


def preparer_donnees() -> tuple[pd.DataFrame, pd.DataFrame]:
    """Jeu de référence (graine 42) découpé 75/25 ; le test set est figé sur disque."""
    df = generer(n=6000, seed=42)
    train, test = train_test_split(df, test_size=0.25, random_state=0, stratify=df["defaut"])
    DATA_DIR.mkdir(exist_ok=True)
    if not TEST_SET.exists():
        test.to_csv(TEST_SET, index=False)
    return train, pd.read_csv(TEST_SET)


def entrainer(variante: str = "reference") -> tuple[Pipeline, dict]:
    version, graine, C, perte_etiquettes = VARIANTES[variante]
    train_ref, test = preparer_donnees()
    # graine != 42 : nouvelles données issues du même processus, sans recouvrement avec le test set
    train = train_ref if graine == 42 else generer(n=4500, seed=graine)
    if perte_etiquettes > 0:  # simulation d'une collecte d'étiquettes défaillante
        rng = np.random.default_rng(0)
        train = train.copy()
        masque = (train["defaut"] == 1) & (rng.uniform(size=len(train)) < perte_etiquettes)
        train.loc[masque, "defaut"] = 0

    pipeline = Pipeline([("scaler", StandardScaler()), ("clf", LogisticRegression(C=C, max_iter=1000))])
    pipeline.fit(features_frame(train), train["defaut"].to_numpy())

    plages = {
        c: {
            "min": float(train[c].min()),
            "max": float(train[c].max()),
            "p01": float(train[c].quantile(0.01)),
            "p99": float(train[c].quantile(0.99)),
        }
        for c in RAW_FIELDS
    }
    metadata = {
        "nom": "creditrisk-defaut",
        "version": version,
        "variante": variante,
        "algorithme": "LogisticRegression (StandardScaler + régression logistique)",
        "features": list(FEATURES),
        "variables_entree": list(RAW_FIELDS),
        "seuil_decision": SEUIL_DECISION,
        "date_entrainement": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "donnees": "synthétiques (ml/data.py) - ne démontrent pas la performance réelle",
        "n_entrainement": len(train),
        "metriques_test": evaluer(pipeline, test),
        "plages_entrainement": plages,
        "scikit_learn": sklearn.__version__,
    }
    return pipeline, metadata


def sauvegarder(pipeline, metadata: dict, chemin: Path) -> None:
    chemin.parent.mkdir(parents=True, exist_ok=True)
    joblib.dump({"pipeline": pipeline, "metadata": metadata}, chemin)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--variante", choices=sorted(VARIANTES), default="reference")
    parser.add_argument("--sortie", type=Path, default=None)
    args = parser.parse_args()

    pipeline, metadata = entrainer(args.variante)
    if args.sortie is None:
        args.sortie = (
            MODELS_DIR / "model.joblib"
            if args.variante == "reference"
            else MODELS_DIR / "candidates" / f"model_v{metadata['version']}.joblib"
        )
    sauvegarder(pipeline, metadata, args.sortie)
    print(json.dumps({"fichier": str(args.sortie.relative_to(RACINE)), **metadata["metriques_test"]}, indent=2))


if __name__ == "__main__":
    main()
