# Activité 4 — Tests de robustesse et registre des anomalies

## 1. Démarche

1. La suite de robustesse (`tests/test_robustness.py`, 75 cas) a d'abord été exécutée contre la **première version
   du module de validation (v0.1)**, écrite avec les réglages par défaut de Pydantic (conversion implicite des types,
   champs supplémentaires ignorés, aucune borne supérieure).
   Résultat : **27 échecs sur 125 tests** (API + robustesse + intégration) — sortie brute :
   `reports/evidence/run1_validation_v0.1.txt`.
2. Chaque échec a été analysé, enregistré ci-dessous, puis corrigé dans la **validation v0.2** (`app/validation.py`).
3. Seconde campagne : **208 tests réussis, 0 échec** (`reports/evidence/pytest_complet.txt`), confirmée en CI.

Distinction appliquée :

| Catégorie | Traitement | Exemples |
|---|---|---|
| **Entrée invalide** | rejet **422** (ou **400** si JSON illisible), aucune prédiction | texte, booléen, `null`, ∞, NaN, hors bornes, champ en trop, incohérence âge/ancienneté |
| **Entrée inhabituelle mais valide** | prédiction **200** + `alertes` pour revue humaine | âge 74, revenu 40 M FCFA, durée 120 mois (hors plage d'entraînement) ; mensualité > 50 % du revenu |

## 2. Analyse par famille de tests

| Famille (test) | Risque visé | Comportement attendu | Résultat observé v0.1 | Résultat observé final | Gravité | Correction recommandée / appliquée |
|---|---|---|---|---|---|---|
| R01 Valeurs manquantes (`null` ×5, `{}`) — `test_r01_*` | imputation implicite, crash du prétraitement | 422, champ identifié | ✅ 422 | ✅ 422 | — | — |
| R02 Valeurs non numériques (`"35"`, `"trente-cinq"`, `true`, `[35]`, `{}`, `""`, `"1e3"` × 3 champs) — `test_r02_*` | conversion silencieuse faussant la décision | 422 | ❌ 7/21 acceptées : `"35"`, `"1e3"`, `true` sur revenu/montant ; `"35"` sur âge | ✅ 21/21 rejetées | **Critique** | typage strict (ANO-01, ANO-02) |
| R03 Valeurs non finies (`Infinity`, `-Infinity`, `NaN`, `1e309`, `-1e309` × 3 champs) — `test_r03_*` | NaN/∞ propagés au modèle | 422 sans trace | ❌ 6/15 : `Infinity` et `1e309` passent la validation → **500** `erreur_pretraitement` | ✅ 15/15 → 422 | Majeure | `allow_inf_nan=False` (ANO-05) |
| R04 Limites des intervalles (9 acceptées, 9 rejetées, cohérence) — `test_r04_*` | erreur de borne (off-by-one), score extrapolé | bornes incluses acceptées, bornes ±1 rejetées | ❌ revenu 50 000 001 et montant 500 000 001 acceptés ; âge 20 / ancienneté 10 accepté | ✅ 19/19 | Critique | bornes supérieures (ANO-03), cohérence (ANO-06) |
| R05 Hors distribution — `test_r05_*` | extrapolation présentée comme fiable | 200 + alertes | ❌ aucune alerte émise | ✅ alertes `hors_distribution:*` et `taux_endettement_eleve` | Majeure | `detecter_alertes` (ANO-07) |
| R06 Schéma incorrect (liste, objet imbriqué, casse, champ en trop, `text/plain`, corps de 1 Mo) — `test_r06_*` | injection de variables, contournement du contrat | 422 | ❌ champ en trop et corps de 1 Mo acceptés (200) | ✅ 422 | Majeure | `extra="forbid"` (ANO-04) |
| R07 Fuzzing (200 entrées valides aléatoires) — `test_r07_fuzzing_entrees_valides` | probabilité non finie ou hors [0,1] sur une combinaison rare | 200, p ∈ [0,1] | ✅ 200/200 | ✅ 200/200 | — | — |
| R07 Métamorphiques montant ↑ / revenu ↑ — `test_r07_metamorphique_*` | modèle incohérent avec le bon sens métier | p croissante avec le montant, décroissante avec le revenu | ✅ | ✅ | — | — |
| R07 Entier vs flottant (`250000` vs `250000.0`) | traitement différent selon le format JSON | probabilités identiques | ✅ | ✅ | — | — |
| Contrat de sortie — `test_probabilite_dans_intervalle` | probabilité invalide | `math.isfinite(p)` et 0 ≤ p ≤ 1 | ✅ | ✅ | — | — |

## 3. Registre des anomalies

| ID | Titre | Détection (test) | Observé | Attendu | Gravité | Statut | Correction |
|---|---|---|---|---|---|---|---|
| ANO-01 | Conversion implicite des types | `test_s04_revenu_texte[250000]`, `test_s06_duree_non_entiere[12, 12.0]`, `test_r02_*[35, 1e3]` | `"revenu_mensuel": "250000"` → 200 ; `"duree_mois": "12"` ou `12.0` → 200 | 422 | Majeure | ✅ Corrigée v0.2 | `ConfigDict(strict=True)`, `StrictInt`, `StrictFloat` |
| ANO-02 | **Booléen interprété comme un nombre** | `test_r02_*[revenu_mensuel-True]` | `"revenu_mensuel": true` → revenu = 1 FCFA → **p = 1,0, « défavorable »** | 422 | **Critique** | ✅ Corrigée v0.2 | `StrictFloat` refuse les booléens |
| ANO-03 | **Absence de bornes supérieures** | `test_s08_*`, `test_r04_limite_rejetee[*_max+1]` | ancienneté 10⁶ ans → **p = 0,0, « favorable »** ; montant 10¹⁸ → p = 1,0 ; revenu 10¹⁵ → p = 0,000002 | 422 | **Critique** | ✅ Corrigée v0.2 | `le=` : revenu ≤ 50 M, montant ≤ 500 M, ancienneté ≤ 60 |
| ANO-04 | Champs supplémentaires ignorés silencieusement | `test_s07_champ_supplementaire`, `test_r06_*[champ_en_trop]`, `test_r06_corps_volumineux` | `"sexe": "F"` → 200 | 422 | Majeure (risque de collecte de données sensibles, faux sentiment que la variable est prise en compte) | ✅ Corrigée v0.2 | `extra="forbid"` |
| ANO-05 | Valeurs non finies classées en erreur serveur | `test_r03_valeur_non_finie[*-Infinity / 1e309]` | 500 `erreur_pretraitement` | 422 (erreur client) | Majeure (fausse alerte d'exploitation, client non informé) | ✅ Corrigée v0.2 | `allow_inf_nan=False` ; le contrôle `isfinite` du prétraitement reste en défense en profondeur |
| ANO-06 | Incohérence âge / ancienneté non détectée | `test_r04_coherence_age_anciennete` | âge 20, ancienneté 10 → 200 | 422 | Majeure | ✅ Corrigée v0.2 | `field_validator` : ancienneté ≤ âge − 14 |
| ANO-07 | Entrées hors distribution non signalées | `test_r05_*` | aucune alerte | 200 + alertes | Majeure | ✅ Corrigée v0.2 | `detecter_alertes` à partir des plages d'entraînement stockées dans les métadonnées |
| ANO-08 | Faux échecs dus à l'outillage de test (pytest 9 `monkeypatch.setattr` sur `app.state` Starlette supprime l'attribut à la restauration) | `test_s09_*` (erreurs de fixture) | `AttributeError` en cascade sur les tests suivants | isolation des tests | Mineure (outil) | ✅ Corrigée | `monkeypatch.setitem(app.state._state, …)` |
| ANO-09 | Pas de limite de taille de corps | sonde manuelle | un corps de **10 Mo** est entièrement lu et analysé avant le rejet 422 | rejet 413 au-delà de ~10 Ko | Majeure (déni de service) | ⏳ Ouverte | limite de taille au reverse-proxy (nginx `client_max_body_size 16k`) ou middleware |
| ANO-10 | Pas d'authentification ni de limitation de débit | revue | tout client réseau peut interroger l'API | accès réservé aux agents authentifiés, quotas | Majeure (sécurité, confidentialité) | ⏳ Ouverte | OAuth2 / clé d'API + rate limiting à la passerelle |
| ANO-11 | Scores saturés sur des valeurs valides mais absurdes | sonde manuelle | revenu = 1 FCFA → p = 1,0 ; montant = 1 FCFA → « favorable » (avec alerte `hors_distribution`) | minima métier (revenu, montant) définis | Mineure (alerte émise) | ⏳ Ouverte | faire valider par le métier des minima (ex. revenu ≥ 10 000, montant ≥ 25 000 FCFA) |
| ANO-12 | Rappel du modèle limité | `ml/regression.py` | rappel = 0,59 au seuil 0,30 : **41 % des défauts du jeu de test ne sont pas détectés** | à fixer par le métier | Majeure (métier) | ⏳ Ouverte | revoir le seuil (coût FN/FP), variables supplémentaires, données réelles |
| ANO-13 | Dépréciation `httpx` dans `starlette.testclient` | avertissement Pytest | avertissement (filtré dans `pyproject.toml`) | — | Mineure (dette technique) | ⏳ Ouverte | migrer vers `httpx2` quand FastAPI le recommandera |
| ANO-14 | Candidat v1.1.0 : précision +0,051 et écart de probabilité 0,051 sur un cas golden | rapport de non-régression | verdict `A_SURVEILLER` | variations ≤ 0,05 | Information | ⏳ À analyser | analyse des cas golden concernés avant toute promotion |

**Bilan** : 8 anomalies corrigées (dont 2 critiques), 6 ouvertes (aucune critique). Les deux anomalies critiques
(ANO-02, ANO-03) auraient produit des **avis de crédit erronés sans aucun message d'erreur** — exactement le type
de défaillance silencieuse que les tests de robustesse doivent révéler.
