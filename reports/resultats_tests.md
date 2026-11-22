# Résultats des tests fonctionnels, unitaires et d'intégration

Exécution de référence : `pytest -v --cov` sur la version finale (validation v0.2), le 22/11/2026,
macOS / Python 3.12.8 — sortie complète : `reports/evidence/pytest_complet.txt`.
La même suite est rejouée par GitHub Actions sur Ubuntu / Python 3.12 (voir `reports/preuves_ci.md`).

## Synthèse

| Suite | Fichier | Tests | Réussis | Échecs | Ignorés |
|---|---|---|---|---|---|
| Unitaires | `tests/test_validation.py` | 67 | 67 | 0 | 0 |
| Fonctionnels API | `tests/test_api.py` | 37 | 37 | 0 | 0 |
| Intégration | `tests/test_integration.py` | 13 | 13 | 0 | 0 |
| Robustesse | `tests/test_robustness.py` | 75 | 75 | 0 | 0 |
| Non-régression | `tests/test_regression.py` | 16 | 16 | 0 | 0 ⁽¹⁾ |
| Démo échec CI | `tests/test_ci_demo_echec.py` | 1 | 0 | 0 | 1 ⁽²⁾ |
| **Total** | | **209** | **208** | **0** | **1** |

⁽¹⁾ `test_nr3_meme_version_predictions_identiques` est ignoré automatiquement lorsqu'on qualifie une
version *différente* de la référence (`CREDITRISK_CANDIDATE_MODEL`) ; il s'exécute pour v1.0.0.
⁽²⁾ activé uniquement par `CREDITRISK_DEMO_ECHEC=1`.

**Couverture** (pytest-cov) : **99 %** des lignes de `app/` et `ml/regression.py` (`app/` : 100 %).
Seuil bloquant en CI : 90 %.

> Les chiffres de la première campagne (validation v0.1) sont différents : **27 échecs sur 125 tests**
> exécutés sur `test_api.py`, `test_robustness.py`, `test_integration.py` — voir `reports/evidence/run1_validation_v0.1.txt`
> et le registre des anomalies.

## Activité 2 — Tableau des scénarios obligatoires (`tests/test_api.py`)

Demande de référence : `{"age": 35, "revenu_mensuel": 250000, "montant_credit": 1000000, "duree_mois": 12, "anciennete_activite": 4}`.

| # | Scénario | Données | Code HTTP attendu | Contenu de réponse attendu | Comportement de l'application | Résultat v0.1 | Résultat final |
|---|---|---|---|---|---|---|---|
| S01 | Requête valide | demande de référence | **200** | `probabilite_defaut` ∈ [0,1] finie (0,099218), `classe_risque`, `decision_suggeree`, `seuil_decision`, `alertes: []`, `version_modele: "1.0.0"`, `request_id`, `duree_inference_ms` | validation → prétraitement → modèle → interprétation | ✅ | ✅ |
| S02 | Champ obligatoire absent (×5 champs) | suppression de chaque champ | **422** | `erreur: "donnees_invalides"`, `details[].champ` = champ manquant, `type: "missing"` | aucune prédiction, aucun appel au modèle | ✅ | ✅ |
| S03 | Âge négatif | `age: -5` | **422** | `details[].champ = "age"`, `type: "greater_than_equal"` | rejet | ✅ | ✅ |
| S04 | Revenu sous forme de texte | `"250000"`, `"deux cent mille"`, `""` | **422** | `details[].champ = "revenu_mensuel"`, `type: "float_type"` | rejet, **aucune conversion implicite** | ❌ `"250000"` accepté (200) → ANO-01 | ✅ |
| S05 | Montant nul ou négatif | 0, −1, −1 000 000 | **422** | `champ = "montant_credit"`, `type: "greater_than"` | rejet | ✅ | ✅ |
| S06 | Durée non entière | 12.5, `"12"`, 12.0 | **422** | `champ = "duree_mois"`, `type: "int_type"` | rejet (contrat : entier JSON) | ❌ `"12"` et `12.0` acceptés → ANO-01 | ✅ |
| S07 | Champ supplémentaire | `"sexe": "F"` | **422** | `champ = "sexe"`, `type: "extra_forbidden"` | rejet (aucune variable sensible admise) | ❌ ignoré silencieusement (200) → ANO-04 | ✅ |
| S08 | Valeurs extrêmement élevées | age 10⁶, revenu 10¹⁵, montant 10¹⁸, durée 10⁹, ancienneté 10⁶ | **422** | `champ` = variable concernée, `type: "less_than_equal"` | rejet (bornes du contrat) | ❌ revenu, montant, ancienneté acceptés ; p = 0,000002 / 1,0 / 0,0 → ANO-03 | ✅ |
| S09 | Modèle indisponible | `model_service = None` | **503** sur `/predict`, `/health`, `/model-info` | `{"erreur": "modele_indisponible", "message": "Le modèle de prédiction n'est pas disponible."}` ; `/health` : `modele_charge: false` | service dégradé explicite, pas de crash ni de valeur par défaut | ✅ | ✅ |
| S10 | Requête mal formée | JSON tronqué, texte, quotes simples | **400** | `erreur: "requete_mal_formee"` | rejet sans trace technique | ✅ | ✅ |
| S10b | JSON valide mais pas un objet | `[]`, `42`, `"texte"`, `null`, corps vide | **422** | `donnees_invalides` | rejet | ✅ | ✅ |
| — | `GET /health` | — | **200** | `status: ok`, `modele_charge: true`, `version_modele` | — | ✅ | ✅ |
| — | `GET /model-info` | — | **200** | version, algorithme, features, seuil, métriques, sha256 (64 car.) | — | ✅ | ✅ |
| — | Méthode / route inconnues | `GET /predict`, `GET /inexistant` | **405 / 404** | — | — | ✅ | ✅ |

## Activité 3 — Tests d'intégration (`tests/test_integration.py`)

| Test | Scénario | Vérification | Résultat |
|---|---|---|---|
| `test_scenario_principal_bout_en_bout` | 1. requête valide → 2. validation → 3. transformation → 4. prédiction → 5. structure → 6. métadonnées | un espion sur `preprocessing.transform` vérifie que les données validées sont transmises, que la matrice est (1, 6) et finie avec un ratio mensualité/revenu exact (0,3333) ; la probabilité API = probabilité du modèle appelé directement (±1e-6) ; classe/décision = `interpreter(p, 0.30)` ; version identique dans `/predict`, `/health`, `/model-info` ; features et sha256 cohérents | ✅ |
| `test_identifiants_de_requete_uniques` | 5 requêtes | `request_id` distincts (traçabilité) | ✅ |
| `test_lot_de_profils_varies` | 30 profils aléatoires (graine fixe) | 200 et p ∈ [0,1] pour tous | ✅ |
| `test_modele_ne_peut_pas_etre_charge` | démarrage avec chemin de modèle inexistant | l'application démarre ; `/health` 503 ; `/predict` 503 sans trace | ✅ |
| `test_modele_corrompu_au_demarrage` | fichier modèle corrompu | 503 sans trace | ✅ |
| `test_demarrage_avec_modele_valide` | démarrage nominal via `CREDITRISK_MODEL_PATH` | `/health` 200 | ✅ |
| `test_variable_attendue_absente_au_pretraitement` | la validation est contournée et `age` n'arrive pas au prétraitement | 500 `erreur_pretraitement`, sans trace | ✅ |
| `test_pretraitement_retourne_une_erreur` | le prétraitement lève une erreur contenant un « détail interne confidentiel » | 500 `erreur_pretraitement` ; le détail n'est **pas** dans la réponse mais **est** dans les journaux serveur | ✅ |
| `test_dimensions_incompatibles_avec_le_modele` | le prétraitement renvoie une matrice (1, 4) au lieu de (1, 6) | 500 `erreur_prediction`, sans trace | ✅ |
| `test_erreur_interne_pendant_la_prediction` | `predict_proba` lève `RuntimeError("… /opt/model/secret.py line 42")` | 500 `erreur_interne` ; ni chemin ni « secret » dans la réponse | ✅ |
| `test_modele_renvoie_probabilite_invalide` | le modèle renvoie NaN | 500 `erreur_prediction` (le NaN n'atteint jamais le client) | ✅ |
| `test_service_retabli_apres_erreur` | une panne ponctuelle puis une requête normale | la requête suivante renvoie 200 (pas d'état dégradé persistant) | ✅ |

Contrôle « pas de trace technique » appliqué à chaque cas d'erreur : absence de `Traceback`, `File "`,
`Exception`, `Error(`, `.py`, `line ` dans le corps de réponse.

## Tests unitaires (`tests/test_validation.py`) — 67 tests

| Composant | Tests | Points vérifiés |
|---|---|---|
| Validation | 39 | bornes âge 17/18/75/76, revenu invalide (texte, `null`, booléen, liste, objet, 0, −1), ±∞/NaN sur 3 champs, durée (0, 121, 12.5, 12.0, `"12"`, `true`), champ en trop, cohérence âge/ancienneté (limite incluse) |
| Alertes | 4 | aucune alerte pour un profil courant, `hors_distribution:*`, `taux_endettement_eleve`, absence de plages |
| Prétraitement | 8 | dimensions, valeurs exactes (log, ratio), égalité vectorisé = scalaire (pas de training-serving skew), variable manquante, non numérique, non positive, non finie |
| Interprétation | 6 | seuils 0,149 / 0,15 / 0,2999 / 0,30 / 0 / 1 |
| Service modèle | 10 | fichier absent / corrompu, features incompatibles, mauvaise dimension, absence de `predict_proba`, matrice (1,5), probabilité hors [0,1], probabilité valide, reproductibilité (20 appels), empreinte sha256 |
