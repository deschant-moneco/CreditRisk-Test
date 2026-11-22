# Activité 1 — Stratégie de test et matrice de traçabilité

## 1. Stratégie de test

| Niveau | Objet | Fichier | Outils | Déclenchement |
|---|---|---|---|---|
| Unitaire | validation, prétraitement, interprétation, service modèle | `tests/test_validation.py` | Pytest, Pydantic | chaque push / PR |
| Fonctionnel (contrat API) | `/health`, `/predict`, `/model-info` ; scénarios S01–S10 | `tests/test_api.py` | Pytest, `TestClient` FastAPI | chaque push / PR |
| Intégration | chaîne validation → prétraitement → modèle → API ; pannes | `tests/test_integration.py` | Pytest, `monkeypatch`, `caplog` | chaque push / PR |
| Robustesse | valeurs manquantes, non numériques, non finies, limites, hors distribution, schéma ; fuzzing ; tests métamorphiques | `tests/test_robustness.py` | Pytest (paramétrage), NumPy | chaque push / PR |
| Non-régression | contrat sur cas golden, métriques vs référence, sauvegarde/rechargement | `tests/test_regression.py`, `ml/regression.py` | Pytest, scikit-learn | chaque push / PR + avant tout changement de modèle |
| Performance | latence d'inférence, latence API, P95, débit, charge progressive | `scripts/benchmark.py`, `scripts/locustfile.py` | httpx, uvicorn, Locust | manuel, avant mise en pilote |
| Qualité | style, erreurs statiques, couverture ≥ 90 % | `pyproject.toml`, workflow | Ruff, pytest-cov | chaque push / PR |

**Principes retenus**

- **Contrat d'abord** : le contrat d'entrée/sortie est documenté (README) et chaque règle est testée aux bornes.
- **Distinguer invalide et inhabituel** : une entrée invalide est rejetée (400/422) ; une entrée valide mais
  inhabituelle produit une prédiction **et** une alerte (`hors_distribution:*`, `taux_endettement_eleve`).
- **Modèle de test versionné et maîtrisé** : `models/model.joblib` (v1.0.0, empreinte sha256 contrôlée en CI) ;
  aucun réentraînement en CI.
- **Tolérances fixées avant comparaison** (`ml/regression.py`, `models/baseline/reference.json`).
- **Pas de fuite d'information** : aucune trace technique n'est renvoyée au client ; le détail est journalisé.

## 2. Échelle de gravité / priorité

| Priorité | Gravité de la défaillance | Exemple |
|---|---|---|
| **P1 – Critique** | Décision de crédit erronée silencieuse, ou service inutilisable | probabilité hors [0,1], entrée absurde acceptée et notée « favorable » |
| **P2 – Majeure** | Erreur visible mais mal gérée, fuite d'information, régression de performance du modèle | trace Python renvoyée, 500 au lieu de 422 |
| **P3 – Mineure** | Écart de contrat sans impact sur la décision | mauvais code HTTP pour un JSON mal formé |

## 3. Matrice de traçabilité

EX01–EX07 : exigences imposées. **EX08–EX15 : exigences ajoutées** (≥ 5 demandées).

| ID | Exigence | Résultat attendu | Préconditions | Données d'entrée (exemples) | Cas de test | Risque associé | Priorité |
|---|---|---|---|---|---|---|---|
| EX01 | L'âge est compris dans l'intervalle autorisé [18 ; 75] | Les valeurs hors limites sont rejetées (422, champ `age`) | API démarrée, modèle chargé | 17, 18, 75, 76, −5, 10⁶ | `test_ex01_age_bornes_acceptees`, `test_ex01_age_hors_bornes_rejete`, `test_s03_age_negatif`, `test_r04_limite_*[age-*]`, `test_s08[age]` | Prêt à un mineur ; extrapolation du modèle | P1 |
| EX02 | Le revenu est numérique et positif | Une entrée invalide provoque une erreur contrôlée (422) | idem | `"250000"`, `"deux cent mille"`, `true`, `null`, 0, −1, `Infinity` | `test_ex02_revenu_invalide`, `test_s04_revenu_texte`, `test_r02_*[revenu_mensuel-*]`, `test_r03_*[revenu_mensuel-*]` | Conversion implicite (`true` → 1 FCFA) faussant le ratio d'endettement | P1 |
| EX03 | La durée est un entier valide [1 ; 120] | Les durées invalides sont rejetées (422) | idem | 0, 121, 12.5, 12.0, `"12"`, `true` | `test_ex03_duree_valide`, `test_ex03_duree_invalide`, `test_s06_duree_non_entiere`, `test_r04_*[duree_mois-*]` | Mensualité mal calculée | P2 |
| EX04 | La prédiction retourne une probabilité valide | Probabilité finie, comprise entre 0 et 1 | modèle chargé | demande valide ; 200 profils aléatoires ; modèle factice renvoyant −0,2 / NaN | `test_s01_requete_valide`, `test_probabilite_dans_intervalle`, `test_r07_fuzzing_entrees_valides`, `test_ex04_probabilite_hors_intervalle_detectee`, `test_modele_renvoie_probabilite_invalide` | Score incohérent présenté à l'agent | P1 |
| EX05 | Le modèle est disponible | Une indisponibilité est signalée correctement (503 sur `/predict`, `/health`, `/model-info`) | modèle retiré / absent / corrompu | `model_service = None` ; chemin inexistant ; fichier corrompu | `test_s09_*`, `test_ex05_fichier_modele_absent`, `test_ex05_fichier_modele_corrompu`, `test_modele_ne_peut_pas_etre_charge`, `test_modele_corrompu_au_demarrage` | Crash au démarrage ; prédiction par défaut silencieuse | P1 |
| EX06 | Une entrée incomplète est soumise à validation | Réponse 422 `donnees_invalides` listant les champs manquants | idem | chaque champ supprimé ; champs à `null` ; `{}` | `test_s02_champ_obligatoire_manquant`, `test_r01_valeur_null`, `test_r01_objet_vide`, `test_pretraitement_variable_manquante` | Imputation implicite non maîtrisée | P1 |
| EX07 | Une nouvelle version ne dégrade pas les critères critiques | Le contrôle de non-régression s'exécute (CI) et bloque une dégradation | référence figée v1.0.0 | candidats v1.1.0 (sain) et v1.2.0 (dégradé) | `tests/test_regression.py` (NR1–NR5), `test_nr4_le_detecteur_signale_un_modele_degrade` | Baisse du rappel = défauts non détectés | P1 |
| **EX08** | Les champs non prévus sont refusés | 422 avec le champ en trop (`extra_forbidden`) | idem | `sexe`, `nationalite`, `score_interne` | `test_s07_champ_supplementaire`, `test_ex08_champ_supplementaire_interdit`, `test_r06_schema_incorrect[champ_en_trop]` | Variables sensibles transmises (discrimination), injection de champs | P2 |
| **EX09** | Les valeurs non finies et extrêmes sont refusées (revenu ≤ 50 M, montant ≤ 500 M, ancienneté ≤ 60) | 422, jamais 500 ni 200 | idem | `Infinity`, `NaN`, `1e309`, 10¹⁵, 10¹⁸ | `test_ex09_valeurs_non_finies_rejetees`, `test_r03_valeur_non_finie`, `test_s08_valeurs_extremement_elevees` | Score saturé à 0 ou 1 → décision absurde | P1 |
| **EX10** | Les données du demandeur sont cohérentes entre elles (ancienneté ≤ âge − 14) | 422 sur `anciennete_activite` | idem | âge 20 / ancienneté 10 ; âge 25 / ancienneté 11 (limite) | `test_ex10_*`, `test_r04_coherence_age_anciennete` | Saisie erronée non détectée | P2 |
| **EX11** | Une entrée valide mais inhabituelle est signalée sans être rejetée | 200 + `alertes` (`hors_distribution:<champ>`, `taux_endettement_eleve`) | plages d'entraînement dans les métadonnées | âge 74, revenu 40 M, durée 120 ; mensualité > 50 % du revenu | `test_ex11_*`, `test_r05_*` | Extrapolation du modèle prise pour une certitude | P2 |
| **EX12** | Les erreurs internes sont gérées sans exposer de trace technique | 500 avec code métier (`erreur_pretraitement`, `erreur_prediction`, `erreur_interne`), détail uniquement dans les journaux | pannes simulées | exception du modèle, dimensions (1,4), prétraitement en échec | `test_pretraitement_retourne_une_erreur`, `test_dimensions_incompatibles_avec_le_modele`, `test_erreur_interne_pendant_la_prediction`, `test_ex12_*` | Fuite d'informations (chemins, versions) ; instabilité | P2 |
| **EX13** | Les prédictions sont reproductibles (même entrée, même version → même sortie, y compris après sauvegarde/rechargement) | Écart nul | modèle v1.0.0 | demande de référence ; 1 500 cas du jeu de test | `test_ex13_reproductibilite`, `test_nr5_sauvegarde_rechargement`, `test_nr3_meme_version_predictions_identiques` | Décisions différentes pour un même dossier ; non-auditabilité | P1 |
| **EX14** | Une requête mal formée renvoie une erreur explicite | 400 `requete_mal_formee` (JSON invalide) ; 422 (JSON non objet, corps vide) | idem | JSON tronqué, quotes simples, `[]`, `42`, corps vide | `test_s10_*`, `test_r06_*` | 500 ou trace renvoyée au client | P3 |
| **EX15** | Le service respecte l'objectif de performance : P95 API ≤ 200 ms et débit ≥ 50 req/s à 10 clients ; P95 inférence ≤ 10 ms | Objectifs atteints | serveur uvicorn local 1 worker | charge 1 → 50 clients ; Locust 50 utilisateurs | `scripts/benchmark.py`, `scripts/locustfile.py` | Attente de l'agent, timeouts en agence | P2 |
| **EX16** | Les métadonnées du modèle sont cohérentes et traçables | `/model-info` = version de `/predict` et `/health`, features = prétraitement, sha256 = artefact | modèle chargé | — | `test_model_info`, `test_scenario_principal_bout_en_bout` (étape 6), `test_ex12_modele_incompatible_avec_pretraitement`, contrôle sha256 en CI | Mauvais modèle déployé sans le savoir | P2 |
| **EX17** | La sortie métier est cohérente avec la probabilité et le seuil (0,30) | classe/décision conformes aux seuils 0,15 / 0,30 ; monotonie vis-à-vis du montant et du revenu | — | probabilités 0,149 / 0,15 / 0,2999 / 0,30 ; montants croissants | `test_interpretation_seuils`, `test_r07_metamorphique_montant`, `test_r07_metamorphique_revenu` | Avis « favorable » pour un risque élevé | P1 |

## 4. Priorisation de l'exécution

1. **P1** (EX01, EX02, EX04, EX05, EX06, EX07, EX09, EX13, EX17) : bloquants, exécutés à chaque push/PR ; un échec empêche la fusion.
2. **P2** (EX03, EX08, EX10, EX11, EX12, EX15, EX16) : exécutés à chaque push/PR (sauf EX15, mesuré avant chaque mise en pilote).
3. **P3** (EX14) : exécuté à chaque push/PR ; un échec n'impacte pas la décision mais doit être corrigé avant livraison.
