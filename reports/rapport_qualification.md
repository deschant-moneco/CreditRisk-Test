# Rapport de qualification — Système IA d'estimation du risque de défaut (CreditRisk)

| | |
|---|---|
| **Objet** | Qualification du prototype CreditRisk (API v1.0.0, modèle v1.0.0) en vue d'une phase pilote |
| **Dépôt** | https://github.com/deschantkn/CreditRisk-Test |
| **Date** | 22 novembre 2026 |
| **Environnement** | Python 3.12, scikit-learn 1.9.1, FastAPI 0.165, Pytest 9.2, Ruff 0.17, GitHub Actions |
| **Décision proposée** | **Apte techniquement à une phase pilote encadrée, sous conditions — non apte à une décision de crédit automatisée** |

---

## 1. Contexte et exigences du système

Une institution de microfinance veut estimer la probabilité de défaut d'un demandeur de crédit. Le système
comprend quatre composants :

```
Client ──JSON──▶ API FastAPI ──▶ Validation ──▶ Prétraitement ──▶ Modèle ML ──▶ Interprétation ──▶ Réponse
                 (app/main.py)  (validation.py)  (preprocessing.py)  (prediction.py, model.joblib v1.0.0)
```

- **Entrées** : `age`, `revenu_mensuel` (FCFA), `montant_credit` (FCFA), `duree_mois`, `anciennete_activite`.
- **Variables du modèle** : âge, log(revenu), log(montant), durée, ancienneté, ratio mensualité/revenu.
- **Modèle** : StandardScaler + régression logistique, cible `defaut` (1 = défaut).
- **Sortie** : `probabilite_defaut`, `classe_risque` (faible / modéré / élevé), `decision_suggeree`
  (favorable / examen approfondi / défavorable, seuil 0,30), `alertes`, `version_modele`, `request_id`.
- **Données** : **synthétiques** (6 000 demandeurs, processus générateur documenté dans `ml/data.py`, graine fixe,
  taux de défaut 19,6 %). Elles servent à tester le système et **ne démontrent pas** la performance réelle d'un
  modèle de crédit.

Exigences : EX01–EX07 (énoncé) et **10 exigences ajoutées EX08–EX17** (champs interdits, valeurs non finies et
extrêmes, cohérence âge/ancienneté, alertes hors distribution, erreurs sans fuite technique, reproductibilité,
requête mal formée, performance, traçabilité des métadonnées, cohérence de la sortie métier).
→ détail : `reports/matrice_tracabilite.md`.

## 2. Stratégie de test et matrice de traçabilité

Pyramide de tests automatisés, toutes exécutées à chaque push et à chaque Pull Request :

| Niveau | Tests | Fichier |
|---|---|---|
| Unitaires | 67 | `tests/test_validation.py` |
| Fonctionnels (contrat API, S01–S10) | 37 | `tests/test_api.py` |
| Intégration (bout en bout + pannes) | 13 | `tests/test_integration.py` |
| Robustesse (limites, non finis, hors distribution, fuzzing, métamorphiques) | 75 | `tests/test_robustness.py` |
| Non-régression (logiciel + modèle) | 16 | `tests/test_regression.py` |
| Performance (hors CI) | benchmark + Locust | `scripts/` |

Chaque exigence est reliée à ses cas de test, ses préconditions, ses données, son résultat attendu, son risque et
sa priorité (P1 critique / P2 majeure / P3 mineure). Les 9 exigences P1 portent sur les défaillances
**silencieuses** (décision erronée sans erreur visible), les plus dangereuses pour un système de crédit.

## 3. Tests fonctionnels et d'intégration

**Résultat final : 208 tests réussis, 0 échec, 1 ignoré (test de démonstration d'échec désactivé) ;
couverture 100 % de `app/`, 99 % au total.** → `reports/resultats_tests.md`, `reports/evidence/pytest_complet.txt`.

- **Contrat API** : les 10 scénarios obligatoires renvoient le code attendu — 200 (valide), 422 (champ manquant,
  âge négatif, revenu texte, montant ≤ 0, durée non entière, champ en trop, valeurs extrêmes), 503 (modèle
  indisponible, sur les 3 endpoints), 400 (JSON mal formé). Les erreurs 422 indiquent le champ fautif.
- **Intégration** : le scénario principal vérifie les 6 étapes (validation, transformation exacte, probabilité
  identique à l'appel direct du modèle, structure, interprétation, cohérence des métadonnées
  `/predict`–`/health`–`/model-info`–sha256). Les 5 scénarios de panne (modèle non chargeable ou corrompu, variable
  absente, prétraitement en erreur, dimensions incompatibles, exception interne, NaN du modèle) sont gérés
  proprement : codes 503/500 explicites, **aucune trace technique exposée**, détail journalisé côté serveur, service
  rétabli à la requête suivante.

## 4. Résultats des tests de robustesse

Première campagne sur la validation initiale (v0.1) : **27 échecs**. Après correction (v0.2) : **0 échec**.
→ `reports/registre_anomalies.md`.

| Famille | v0.1 | Final |
|---|---|---|
| Valeurs manquantes / `null` | ✅ | ✅ |
| Non numériques (texte, booléen…) | ❌ 7/21 acceptées | ✅ |
| Non finies (∞, NaN, 1e309) | ❌ 6/15 → erreur 500 | ✅ 422 |
| Limites des intervalles et cohérence | ❌ 3 | ✅ |
| Hors distribution (inhabituel mais valide) | ❌ aucune alerte | ✅ 200 + alertes |
| Schéma incorrect | ❌ 2 | ✅ |
| Fuzzing (200 cas) et propriétés métamorphiques | ✅ | ✅ |

Deux anomalies **critiques** ont été trouvées puis corrigées : `revenu_mensuel: true` était converti en 1 FCFA
(probabilité 1,0, avis défavorable) et une ancienneté de 1 000 000 d'années produisait un avis **favorable**
(probabilité 0,0) — dans les deux cas **sans aucune erreur**.

## 5. Résultats de non-régression

Référence figée : modèle v1.0.0 (sha256, métriques sur 1 500 observations figées, 50 cas « golden »).
Tolérances fixées **avant** comparaison : baisse max AUC 0,02, rappel 0,03, F1 0,03 (bloquant) ; variation
précision / taux prédit ± 0,05 (avertissement) ; ≤ 10 % de décisions golden modifiées (bloquant).
→ `reports/non_regression_report.md`.

| Version | AUC | Rappel | F1 | Précision | Décisions golden modifiées | Verdict |
|---|---|---|---|---|---|---|
| 1.0.0 (référence) | 0,836 | 0,592 | 0,587 | 0,582 | 0 % | — |
| 1.0.0 (rechargée) | 0,836 | 0,592 | 0,587 | 0,582 | 0 % (écart 0) | ✅ CONFORME |
| 1.1.0 (réentraînement, nouvelles données) | 0,835 | 0,575 | 0,603 | 0,633 | 2 % | ⚠️ À SURVEILLER (précision +0,051) |
| 1.2.0 (étiquettes de défaut perdues) | 0,834 | **0,140** | **0,243** | 0,954 | 30 % | ❌ RÉGRESSION |

Enseignement : la version dégradée a **la même AUC** que la référence ; seul le suivi du **rappel et du F1 au seuil
de décision** révèle qu'elle laisserait passer 86 % des défauts. Le contrôle est automatisé en CI : la PR #1 qui
tentait de déployer v1.2.0 a été bloquée. La sauvegarde/rechargement donne des prédictions identiques bit à bit.

## 6. Mesures de performance

→ `reports/rapport_performance.md` (Apple M3 Pro, uvicorn 1 worker, client local).

| Indicateur | Objectif | Mesuré | |
|---|---|---|---|
| P95 inférence (validation + prétraitement + modèle) | ≤ 10 ms | 0,125 ms | ✅ |
| P95 API, 10 clients simultanés | ≤ 200 ms | 4,9 ms | ✅ |
| Débit, 10 clients | ≥ 50 req/s | 1 015 req/s | ✅ |
| Locust, montée 0 → 50 utilisateurs, 60 s | 0 % d'erreur | 20 311 requêtes, 0 échec, P95 3 ms | ✅ |

Saturation vers ~1 000 req/s avec un seul worker, sans erreur ; marge très large par rapport au besoin estimé
(~5 req/s en pointe). Mesures à refaire sur l'infrastructure cible et avec la latence réseau réelle.

## 7. Anomalies détectées et gravité

| ID | Anomalie | Gravité | Statut |
|---|---|---|---|
| ANO-02 | booléen accepté comme revenu → p = 1,0 | **Critique** | ✅ corrigée |
| ANO-03 | pas de bornes supérieures → avis favorable/défavorable absurdes | **Critique** | ✅ corrigée |
| ANO-01 | conversion implicite (`"250000"`, `"12"`, `12.0`) | Majeure | ✅ corrigée |
| ANO-04 | champs supplémentaires ignorés (ex. `sexe`) | Majeure | ✅ corrigée |
| ANO-05 | ∞ / 1e309 → erreur 500 au lieu de 422 | Majeure | ✅ corrigée |
| ANO-06 | incohérence âge/ancienneté non détectée | Majeure | ✅ corrigée |
| ANO-07 | entrées hors distribution non signalées | Majeure | ✅ corrigée |
| ANO-08 | faux échecs dus à l'outillage de test | Mineure | ✅ corrigée |
| ANO-09 | pas de limite de taille de requête (10 Mo lus) | Majeure | ⏳ ouverte |
| ANO-10 | pas d'authentification ni de limitation de débit | Majeure | ⏳ ouverte |
| ANO-11 | minima métier absents (revenu 1 FCFA → p = 1, avec alerte) | Mineure | ⏳ ouverte |
| ANO-12 | rappel 0,59 : 41 % des défauts non détectés (données synthétiques) | Majeure (métier) | ⏳ ouverte |
| ANO-13 | dépréciation httpx/starlette | Mineure | ⏳ ouverte |
| ANO-14 | v1.1.0 : variations à la limite des tolérances | Information | ⏳ à analyser |

## 8. Limites de l'évaluation

1. **Données synthétiques** : toutes les métriques (AUC 0,84, rappel 0,59) mesurent la capacité du modèle à
   retrouver un processus que nous avons nous-mêmes simulé. Elles ne disent rien de la performance sur de vrais
   demandeurs.
2. **Aucune évaluation d'équité** : le jeu ne contient ni sexe, ni région, ni secteur d'activité ; les écarts de
   performance entre groupes (faux négatifs, faux positifs) n'ont pas pu être mesurés. L'âge, présent dans le
   modèle, est une variable potentiellement discriminatoire.
3. **Pas de calibration ni de validation temporelle** : la probabilité n'a pas été vérifiée comme bien calibrée
   (courbe de fiabilité, score de Brier) ni testée sur une période postérieure (dérive).
4. **Conformité juridique non évaluée** (protection des données personnelles, explicabilité exigée par le
   régulateur, droit du demandeur à contester une décision).
5. **Performance** mesurée sur un poste de développement, client et serveur sur la même machine.
6. **Sécurité** : pas de test d'intrusion, pas d'authentification (ANO-10).
7. Le seuil de décision (0,30) et les classes de risque sont des **hypothèses** non validées par le métier.

## 9. Recommandations d'amélioration

| Priorité | Recommandation |
|---|---|
| Avant pilote | Ajouter authentification, limitation de débit et taille maximale de requête (ANO-09, ANO-10) |
| Avant pilote | Faire valider par le métier les bornes, minima (ANO-11), le seuil de décision et les libellés des classes |
| Avant pilote | Entraîner et évaluer sur des **données historiques réelles** de l'institution, avec validation temporelle (hors temps) et calibration |
| Avant pilote | Mesurer la performance **par segment** (âge, sexe, région, secteur, montant) : taux de faux négatifs et faux positifs, écarts tolérés fixés à l'avance ; ajouter ces contrôles à la non-régression |
| Pendant pilote | Journaliser chaque prédiction (request_id, version, entrées, sortie, décision de l'agent) et suivre la dérive des entrées (part d'alertes `hors_distribution`) et des scores |
| Pendant pilote | Comparer les recommandations du modèle aux décisions des agents et aux remboursements effectifs |
| Continu | Mesurer la performance sur l'infrastructure cible ; ajouter un test d'endurance |
| Continu | Fournir une explication par prédiction (contributions des variables de la régression logistique) |

## 10. Conclusion : aptitude à la phase pilote

**Validation technique** : le système respecte ses exigences fonctionnelles et techniques testées — contrat
d'API, gestion des entrées invalides et inhabituelles, gestion des pannes sans fuite d'information,
reproductibilité, détection automatique des régressions du modèle, performances très supérieures au besoin, chaîne
CI qui bloque effectivement les modifications défaillantes. Toutes les anomalies critiques détectées sont corrigées
et couvertes par des tests de non-régression.

**Décision métier** : ce résultat ne suffit pas à autoriser une décision de crédit automatisée. Le modèle n'a été
entraîné et évalué que sur des données synthétiques ; son rappel (0,59) laisserait passer une part importante des
défauts ; son équité et sa conformité ne sont pas établies.

> **Avis : apte à une phase pilote encadrée, sous conditions** — après correction des anomalies ANO-09/ANO-10,
> réentraînement et requalification sur données réelles (y compris analyse par segment), et validation du seuil par
> le métier. Pendant le pilote, le modèle est un **outil d'aide** : l'agent de crédit garde la décision, toutes les
> prédictions sont journalisées et revues, et des critères d'arrêt sont définis à l'avance (par ex. taux de défaut
> non détectés supérieur à la référence humaine, écart de faux négatifs entre segments au-delà de la tolérance).

---

## Réponse à la question de synthèse

> *Tous les tests fonctionnels et techniques réussissent, mais le modèle présente encore un taux élevé de faux
> négatifs pour certains profils de demandeurs. Peut-on recommander sa mise en production ?*

**Non, pas en l'état** — au mieux une utilisation encadrée en pilote, avec contrôles complémentaires.

**1. Ce que prouvent les preuves techniques.** Des tests au vert démontrent que le *logiciel* fait ce que dit son
contrat : il valide les entrées, renvoie une probabilité dans [0, 1], gère les pannes, est reproductible, rapide,
et qu'une nouvelle version ne dégrade pas les métriques *globales* suivies. Ils ne démontrent pas que les
prédictions sont *justes* pour chaque population : un modèle peut respecter parfaitement son contrat tout en se
trompant systématiquement pour un groupe. Nos propres résultats l'illustrent : la version dégradée v1.2.0 a la même
AUC que la référence et passe tous les tests de contrat, alors qu'elle manque 86 % des défauts. Une moyenne globale
satisfaisante peut masquer un segment très mal servi.

**2. Ce qu'exige le métier.** Ici un faux négatif est un demandeur à risque classé « favorable » : le crédit est
accordé puis non remboursé. Les conséquences sont doubles : perte financière pour l'institution, et
**surendettement** pour l'emprunteur, ce qui est contraire à la mission sociale de la microfinance. Si les faux
négatifs se concentrent sur « certains profils », le modèle traite inégalement des groupes de demandeurs ; selon les
variables en cause (âge, sexe, zone géographique, secteur informel…), cela peut constituer une **discrimination
indirecte** et exposer l'institution sur les plans juridique et réputationnel. L'exigence métier, c'est un niveau
de risque acceptable **pour chaque segment**, et pas seulement une bonne AUC moyenne.

**3. Risques d'une mise en production immédiate.** Pertes sur crédit concentrées sur un segment ; injustice et
non-conformité (protection des consommateurs, données personnelles, obligation d'expliquer un refus) ; biais
d'automatisation (les agents finissent par suivre le score sans le remettre en question) ; boucle de rétroaction
(les profils mal évalués génèrent des données qui renforcent le biais) ; perte de confiance des clients et du
régulateur.

**4. Contrôles complémentaires nécessaires avant la production.**
- Analyse d'erreur **par segment** : rappel, taux de faux négatifs et de faux positifs, calibration par groupe, avec
  des intervalles de confiance. Identifier pourquoi ces profils sont mal évalués : sous-représentation, variable
  manquante, données d'entraînement biaisées.
- Définir avec le métier, la conformité et le juridique un **critère d'acceptation** : coût d'un faux négatif
  comparé à celui d'un faux positif, écart maximal toléré entre segments. Ajouter ces critères aux **tests de
  non-régression** (bloquants en CI) au même titre que le rappel global.
- Corriger : données complémentaires pour ces profils, rééchantillonnage ou repondération, seuils de décision
  adaptés et validés, variables explicatives supplémentaires — puis requalifier.
- **Gouvernance** : la décision reste humaine ; examen approfondi obligatoire pour les segments concernés ;
  explication fournie à l'agent et au demandeur ; journalisation et audit ; suivi en production des taux de défaut
  par segment ; procédure de retour arrière vers la version précédente ou la décision manuelle.
- Validation indépendante du modèle (fonction risque / conformité) et pilote limité avec critères d'arrêt.

**Conclusion.** La validation technique est nécessaire mais pas suffisante. Une suite de tests réussie prouve que
le système est correctement construit, pas qu'il est équitable, légalement conforme ou adapté à une décision de
crédit réelle. Avec un taux élevé de faux négatifs sur certains profils, l'exigence métier n'est pas satisfaite. On
ne peut pas recommander la mise en production ; on peut recommander un pilote encadré **après** analyse et
correction du problème par segment, avec décision humaine et surveillance continue.
