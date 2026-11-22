"""Non-régression : version de référence figée, tolérances et comparaison.

Usage :
    python -m ml.regression --figer                 # fige la référence à partir de models/model.joblib
    python -m ml.regression models/candidates/model_v1.1.0.joblib [...]   # rapport de comparaison

Les tolérances sont définies AVANT toute comparaison et versionnées dans
models/baseline/reference.json.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd

from app.prediction import DEFAULT_MODEL_PATH, ModelService, interpreter
from ml.train import TEST_SET, evaluer, features_frame

RACINE = Path(__file__).resolve().parent.parent
REFERENCE = RACINE / "models" / "baseline" / "reference.json"
RAPPORT = RACINE / "reports" / "non_regression_report.md"
N_GOLDEN = 50

TOLERANCES = {
    # baisse maximale admise (référence - candidat) avant blocage
    "baisse_max": {"auc": 0.02, "rappel": 0.03, "f1": 0.03},
    # variations surveillées (avertissement, non bloquant)
    "avertissement": {"precision": 0.05, "taux_defaut_predit": 0.05},
    # écart absolu de probabilité toléré par cas sur le jeu « golden »
    "ecart_proba_max_meme_version": 1e-9,
    "ecart_proba_max_nouvelle_version": 0.05,
    # part maximale des cas « golden » dont la décision suggérée change
    "part_decisions_modifiees_max": 0.10,
}


def golden_set() -> pd.DataFrame:
    """Échantillon stratifié et figé du jeu de test (50 cas)."""
    test = pd.read_csv(TEST_SET)
    return test.sample(n=N_GOLDEN, random_state=123).reset_index(drop=True)


def figer_reference(service: ModelService) -> dict:
    golden = golden_set()
    probas = service.predict_proba(features_frame(golden))
    reference = {
        "version": service.version,
        "sha256": service.sha256,
        "metriques": evaluer(service.pipeline, pd.read_csv(TEST_SET), service.seuil_decision),
        "tolerances": TOLERANCES,
        "golden": {
            "entrees": golden.drop(columns="defaut").to_dict(orient="records"),
            "probabilites": [round(float(p), 12) for p in probas],
            "decisions": [interpreter(p, service.seuil_decision).decision for p in probas],
        },
    }
    REFERENCE.parent.mkdir(parents=True, exist_ok=True)
    REFERENCE.write_text(json.dumps(reference, indent=2, ensure_ascii=False))
    return reference


def charger_reference() -> dict:
    return json.loads(REFERENCE.read_text())


def comparer(reference: dict, candidat: ModelService) -> dict:
    """Compare un modèle candidat à la référence ; renvoie un verdict détaillé."""
    tol = reference["tolerances"]
    metriques = evaluer(candidat.pipeline, pd.read_csv(TEST_SET), candidat.seuil_decision)
    controles = []

    for nom, baisse_max in tol["baisse_max"].items():
        ref, cand = reference["metriques"][nom], metriques[nom]
        controles.append(
            {
                "controle": f"{nom} (baisse max {baisse_max})",
                "reference": ref,
                "candidat": cand,
                "ecart": round(cand - ref, 4),
                "statut": "OK" if ref - cand <= baisse_max + 1e-12 else "ECHEC",
            }
        )
    for nom, ecart_max in tol["avertissement"].items():
        ref, cand = reference["metriques"][nom], metriques[nom]
        controles.append(
            {
                "controle": f"{nom} (variation max ±{ecart_max})",
                "reference": ref,
                "candidat": cand,
                "ecart": round(cand - ref, 4),
                "statut": "OK" if abs(cand - ref) <= ecart_max else "AVERTISSEMENT",
            }
        )

    golden = pd.DataFrame(reference["golden"]["entrees"])
    probas = candidat.predict_proba(features_frame(golden))
    ecarts = np.abs(probas - np.array(reference["golden"]["probabilites"]))
    meme_version = candidat.version == reference["version"]
    ecart_max = tol["ecart_proba_max_meme_version" if meme_version else "ecart_proba_max_nouvelle_version"]
    controles.append(
        {
            "controle": f"écart de probabilité max sur {len(golden)} cas golden (≤ {ecart_max})",
            "reference": 0.0,
            "candidat": round(float(ecarts.max()), 6),
            "ecart": round(float(ecarts.max()), 6),
            "statut": "OK" if ecarts.max() <= ecart_max else ("ECHEC" if meme_version else "AVERTISSEMENT"),
        }
    )
    decisions = [interpreter(p, candidat.seuil_decision).decision for p in probas]
    part_modifiee = float(np.mean([a != b for a, b in zip(decisions, reference["golden"]["decisions"], strict=True)]))
    controles.append(
        {
            "controle": f"part des décisions golden modifiées (≤ {tol['part_decisions_modifiees_max']})",
            "reference": 0.0,
            "candidat": round(part_modifiee, 4),
            "ecart": round(part_modifiee, 4),
            "statut": "OK" if part_modifiee <= tol["part_decisions_modifiees_max"] else "ECHEC",
        }
    )
    contrat_ok = bool(np.all(np.isfinite(probas)) and np.all((probas >= 0) & (probas <= 1)))
    controles.append(
        {
            "controle": "sorties conformes au contrat (probabilités finies dans [0, 1])",
            "reference": True,
            "candidat": contrat_ok,
            "ecart": "-",
            "statut": "OK" if contrat_ok else "ECHEC",
        }
    )

    statuts = {c["statut"] for c in controles}
    verdict = "REGRESSION" if "ECHEC" in statuts else ("A_SURVEILLER" if "AVERTISSEMENT" in statuts else "CONFORME")
    return {
        "version_reference": reference["version"],
        "version_candidat": candidat.version,
        "sha256_candidat": candidat.sha256,
        "metriques_candidat": metriques,
        "controles": controles,
        "verdict": verdict,
    }


def rapport_markdown(reference: dict, resultats: list[dict]) -> str:
    lignes = [
        "# Rapport de non-régression",
        "",
        "> Généré automatiquement par `python -m ml.regression` — ne pas modifier à la main.",
        "",
        f"- **Version de référence** : `{reference['version']}` (sha256 `{reference['sha256'][:12]}…`)",
        f"- **Jeu d'évaluation figé** : `data/test_set.csv` ({reference['metriques']['n']} observations synthétiques)",
        f"- **Jeu golden** : {N_GOLDEN} cas figés dans `models/baseline/reference.json`",
        "",
        "## Tolérances (définies avant comparaison)",
        "",
        "| Contrôle | Tolérance | Effet si dépassée |",
        "|---|---|---|",
    ]
    tol = reference["tolerances"]
    for nom, v in tol["baisse_max"].items():
        lignes.append(f"| Baisse de {nom} | ≤ {v} | **Bloquant** (régression) |")
    for nom, v in tol["avertissement"].items():
        lignes.append(f"| Variation de {nom} | ± {v} | Avertissement, investigation |")
    lignes += [
        f"| Écart de probabilité par cas, même version | ≤ {tol['ecart_proba_max_meme_version']} | Bloquant |",
        f"| Écart de probabilité par cas, nouvelle version | ≤ {tol['ecart_proba_max_nouvelle_version']} "
        "| Avertissement |",
        f"| Part de décisions golden modifiées | ≤ {tol['part_decisions_modifiees_max']:.0%} | Bloquant |",
        "| Sorties conformes au contrat | 100 % | Bloquant |",
        "",
    ]
    for r in resultats:
        lignes += [
            f"## Référence `{r['version_reference']}` → candidat `{r['version_candidat']}` : **{r['verdict']}**",
            "",
            "| Contrôle | Référence | Candidat | Écart | Statut |",
            "|---|---|---|---|---|",
        ]
        for c in r["controles"]:
            icone = {"OK": "✅ OK", "ECHEC": "❌ ÉCHEC", "AVERTISSEMENT": "⚠️ AVERT."}[c["statut"]]
            lignes.append(f"| {c['controle']} | {c['reference']} | {c['candidat']} | {c['ecart']} | {icone} |")
        lignes.append("")
    return "\n".join(lignes)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--figer", action="store_true", help="fige la référence depuis models/model.joblib")
    parser.add_argument("candidats", nargs="*", type=Path)
    args = parser.parse_args()

    if args.figer:
        ref = figer_reference(ModelService.load(DEFAULT_MODEL_PATH))
        print(f"Référence {ref['version']} figée dans {REFERENCE}")
        return
    reference = charger_reference()
    resultats = [comparer(reference, ModelService.load(c)) for c in args.candidats]
    RAPPORT.write_text(rapport_markdown(reference, resultats))
    for r in resultats:
        print(f"{r['version_reference']} -> {r['version_candidat']} : {r['verdict']}")
    print(f"Rapport : {RAPPORT}")


if __name__ == "__main__":
    main()
