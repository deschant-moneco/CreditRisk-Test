# Activité 7 — Chaîne de tests automatisés (GitHub Actions)

- **Dépôt** : https://github.com/deschantkn/CreditRisk-Test
- **Workflow** : [`.github/workflows/tests.yml`](../.github/workflows/tests.yml) —
  https://github.com/deschantkn/CreditRisk-Test/actions/workflows/tests.yml

## 1. Ce que fait le workflow

| Déclencheur | Rôle |
|---|---|
| `push` sur `main` | validation continue de la branche principale |
| `pull_request` (toute PR) | **bloque** une PR qui casse un test, la qualité ou la non-régression |
| `workflow_dispatch` (option `demo_echec`) | relance manuelle ; avec `demo_echec=true`, active le test volontairement défaillant |

| Job | Étapes |
|---|---|
| **Qualité du code (Ruff)** | Python 3.12 (cache pip) → `pip install -r requirements-dev.txt` (versions figées) → `ruff check` → `ruff format --check` |
| **Tests Pytest + couverture** | Python 3.12 → dépendances figées → **contrôle d'intégrité** : sha256 de `models/model.joblib` = référence figée → `pytest --cov --cov-fail-under=90 --junitxml` → résumé dans l'onglet *Summary* → artefacts (`junit.xml`, `coverage.xml`, `htmlcov/`) |

Choix de reproductibilité : versions exactes dans `requirements*.txt`, modèle de test **versionné** (pas de
réentraînement en CI), jeu d'évaluation figé (`data/test_set.csv`), graines fixes, runner CPU standard
(`ubuntu-latest`), durée de la suite ≈ 3–4 s.

## 2. Preuves d'exécution

| Run | Déclencheur | Commit | Résultat | Détail |
|---|---|---|---|---|
| [#45080180593](https://github.com/deschantkn/CreditRisk-Test/actions/runs/45080180593) | push `main` | `203791a` | ✅ **succès** | Ruff OK ; `208 passed, 1 skipped` ; couverture 99,66 % |
| [#45080271149](https://github.com/deschantkn/CreditRisk-Test/actions/runs/45080271149) | `workflow_dispatch`, `demo_echec=true` | `203791a` | ❌ **échec attendu** | `FAILED tests/test_ci_demo_echec.py::test_volontairement_defaillant - AssertionError: échec volontaire : la CI doit être rouge` — `1 failed, 208 passed` |
| [#45080185850](https://github.com/deschantkn/CreditRisk-Test/actions/runs/45080185850) — [PR #1](https://github.com/deschantkn/CreditRisk-Test/pull/1) | `pull_request` | `f370ce0` | ❌ **échec attendu** | la PR remplace le modèle par la version dégradée v1.2.0 : contrôle d'intégrité KO (« Le modèle déployé diffère de la référence figée ») **et** 5 tests en échec, dont `test_nr4_pas_de_baisse_excessive[rappel]` (0,5918 → 0,1395) et `[f1]` (0,5868 → 0,2433) |

Historique : le dépôt a été créé sous un autre compte puis transféré, et l'auteur des commits a été réécrit
(nouveaux identifiants de commits). Les runs antérieurs à la réécriture (#45079125769, #45079231235 verts ;
#45079322752 et #45079240908 rouges attendus, avec les mêmes résultats) restent visibles dans l'onglet *Actions*.

Extrait du journal du run de la PR #1 :

```
AssertionError: Le modèle déployé diffère de la référence figée
FAILED tests/test_api.py::test_s01_requete_valide - AssertionError: assert '1.2.0' == '1.0.0'
FAILED tests/test_regression.py::test_nr3_metriques_comparees_a_la_reference
FAILED tests/test_regression.py::test_nr4_pas_de_baisse_excessive[rappel] - {'controle': 'rappel (baisse max 0.03)', 'reference': 0.5918, 'candidat': 0.1395, 'ecart': -0.4523, ...}
FAILED tests/test_regression.py::test_nr4_pas_de_baisse_excessive[f1] - {'controle': 'f1 (baisse max 0.03)', 'reference': 0.5868, 'candidat': 0.2433, 'ecart': -0.3435, ...}
FAILED tests/test_validation.py::test_info_contient_empreinte - AssertionError: assert '1.2.0' == '1.0.0'
=================== 5 failed, 202 passed, 2 skipped in 4.02s ===================
```

Preuve locale équivalente : `reports/evidence/demo_echec_local.txt` (code de sortie Pytest = 1).

## 3. Commandes d'exécution locale

```bash
python3.12 -m venv .venv && source .venv/bin/activate
pip install -r requirements-dev.txt
ruff check . && ruff format --check .
pytest --cov --cov-report=term-missing --cov-fail-under=90
CREDITRISK_DEMO_ECHEC=1 pytest tests/test_ci_demo_echec.py     # doit échouer
```
