# CreditRisk-Test

[![tests](https://github.com/deschantkn/CreditRisk-Test/actions/workflows/tests.yml/badge.svg)](https://github.com/deschantkn/CreditRisk-Test/actions/workflows/tests.yml)

Stratégie de test complète d'un système IA qui estime le **risque de défaut de remboursement**
d'un demandeur de crédit (microfinance) : validation → prétraitement → modèle scikit-learn → API FastAPI.

> ⚠️ **Données synthétiques.** Le modèle est entraîné sur un jeu simulé et documenté
> (`ml/data.py`). Il sert à **tester le système**, pas à démontrer la performance réelle
> d'un modèle de crédit. Aucune décision réelle ne doit en dépendre.

## Structure

```
CreditRisk-Test/
├── app/
│   ├── main.py            # API FastAPI : /health, /predict, /model-info + gestion des erreurs
│   ├── validation.py      # contrat d'entrée (Pydantic strict), bornes, cohérence, alertes
│   ├── preprocessing.py   # variables du modèle (même code à l'entraînement et à l'inférence)
│   └── prediction.py      # chargement du modèle versionné, contrôles, interprétation métier
├── ml/
│   ├── data.py            # générateur de données synthétiques (graine fixe)
│   ├── train.py           # entraînement des versions 1.0.0 / 1.1.0 / 1.2.0
│   └── regression.py      # référence figée, tolérances, comparateur, rapport de non-régression
├── models/
│   ├── model.joblib                 # modèle de test versionné (v1.0.0) utilisé par l'API et la CI
│   ├── baseline/reference.json      # métriques, 50 cas « golden », tolérances, sha256
│   └── candidates/                  # v1.1.0 (réentraînement sain), v1.2.0 (volontairement dégradé)
├── data/test_set.csv      # jeu d'évaluation figé (1 500 observations)
├── tests/
│   ├── test_validation.py # tests unitaires (validation, prétraitement, interprétation, service modèle)
│   ├── test_api.py        # tests fonctionnels du contrat (scénarios S01–S10)
│   ├── test_integration.py# tests de bout en bout + pannes (modèle absent, prétraitement, dimensions…)
│   ├── test_robustness.py # entrées limites, non finies, hors distribution, fuzzing, métamorphiques
│   ├── test_regression.py # non-régression logiciel + modèle
│   └── test_ci_demo_echec.py # test volontairement défaillant (désactivé par défaut)
├── scripts/
│   ├── benchmark.py       # latence d'inférence, latence API, charge progressive
│   └── locustfile.py      # test de charge Locust
├── reports/               # matrice, résultats, anomalies, non-régression, performance, rapport final
├── .github/workflows/tests.yml
├── requirements*.txt  pyproject.toml  .gitignore
```

## Exécution locale

```bash
python3.12 -m venv .venv && source .venv/bin/activate
pip install -r requirements-dev.txt          # + requirements-perf.txt pour Locust

ruff check . && ruff format --check .        # qualité du code
pytest                                       # toute la suite (~3 s)
pytest --cov --cov-report=term-missing --cov-report=html   # couverture (htmlcov/index.html)
pytest tests/test_api.py -v                  # une suite particulière

uvicorn app.main:app --reload                # API sur http://127.0.0.1:8000 (docs : /docs)
```

Exemple :

```bash
curl -s -X POST http://127.0.0.1:8000/predict -H 'Content-Type: application/json' \
  -d '{"age":35,"revenu_mensuel":250000,"montant_credit":1000000,"duree_mois":12,"anciennete_activite":4}'
```

### Non-régression d'une nouvelle version du modèle

```bash
python -m ml.train --variante retrain                       # produit models/candidates/model_v1.1.0.joblib
CREDITRISK_CANDIDATE_MODEL=models/candidates/model_v1.1.0.joblib pytest tests/test_regression.py
python -m ml.regression models/candidates/model_v1.1.0.joblib models/candidates/model_v1.2.0.joblib
#  -> reports/non_regression_report.md
python -m ml.regression --figer                              # (uniquement après validation) nouvelle référence
```

### Performance

```bash
python scripts/benchmark.py                                  # -> reports/perf/benchmark.json
uvicorn app.main:app --port 8765 --no-access-log &
locust -f scripts/locustfile.py --host http://127.0.0.1:8765 --headless -u 50 -r 5 -t 60s \
       --csv reports/perf/locust --only-summary
```

### Démonstration d'échec de la CI

```bash
CREDITRISK_DEMO_ECHEC=1 pytest tests/test_ci_demo_echec.py   # échoue volontairement (code 1)
```
Sur GitHub : *Actions → tests → Run workflow → cocher « demo_echec »*.

## Contrat de l'API

| Endpoint | Succès | Erreurs |
|---|---|---|
| `GET /health` | `200 {"status":"ok","modele_charge":true,"version_modele","version_api"}` | `503 {"status":"indisponible","modele_charge":false}` |
| `GET /model-info` | `200` version, algorithme, features, seuil, métriques, plages d'entraînement, sha256 | `503 modele_indisponible` |
| `POST /predict` | `200` (voir ci-dessous) | `400`, `422`, `503`, `500` |

**Entrée** (`application/json`, aucun champ supplémentaire autorisé, typage strict) :

| Champ | Type | Règle |
|---|---|---|
| `age` | entier | 18 ≤ age ≤ 75 |
| `revenu_mensuel` | nombre (FCFA) | 0 < revenu ≤ 50 000 000, fini |
| `montant_credit` | nombre (FCFA) | 0 < montant ≤ 500 000 000, fini |
| `duree_mois` | entier | 1 ≤ durée ≤ 120 (`12.0` et `"12"` refusés) |
| `anciennete_activite` | nombre (années) | 0 ≤ ancienneté ≤ min(60, age − 14) |

Les chaînes (`"250000"`), booléens, `null`, `Infinity`, `NaN`, `1e309` sont refusés.

**Réponse 200** :

```json
{
  "request_id": "uuid",
  "probabilite_defaut": 0.099218,
  "classe_risque": "faible | modere | eleve",
  "decision_suggeree": "favorable | examen_approfondi | defavorable",
  "seuil_decision": 0.3,
  "alertes": ["hors_distribution:<champ>", "taux_endettement_eleve"],
  "version_modele": "1.0.0",
  "duree_inference_ms": 0.4
}
```

Interprétation : `p ≥ 0,30` → élevé / défavorable ; `0,15 ≤ p < 0,30` → modéré / examen approfondi ;
`p < 0,15` → faible / favorable. La décision finale reste celle de l'agent de crédit.

**Erreurs** (aucune trace technique n'est renvoyée au client ; le détail est journalisé côté serveur) :

| Code | `erreur` | Cas |
|---|---|---|
| 400 | `requete_mal_formee` | corps JSON syntaxiquement invalide |
| 422 | `donnees_invalides` + `details[{champ,type,message}]` | champ manquant, mauvais type, hors bornes, incohérence, champ en trop, JSON non objet |
| 503 | `modele_indisponible` | modèle absent, corrompu ou incompatible |
| 500 | `erreur_pretraitement` / `erreur_prediction` / `erreur_interne` | panne interne |

## Livrables

| Livrable | Emplacement |
|---|---|
| Matrice de traçabilité | `reports/matrice_tracabilite.md` |
| Résultats des tests fonctionnels / intégration | `reports/resultats_tests.md` |
| Registre des anomalies (robustesse) | `reports/registre_anomalies.md` |
| Rapport de non-régression | `reports/non_regression_report.md` |
| Rapport de performance | `reports/rapport_performance.md` |
| Preuves CI | `reports/preuves_ci.md` |
| Rapport final de qualification | `reports/rapport_qualification.md` |
