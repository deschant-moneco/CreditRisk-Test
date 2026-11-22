# Activité 6 — Rapport de performance

Données brutes : `reports/perf/benchmark.json` (script `scripts/benchmark.py`) et `reports/perf/locust_*.csv`
(scénario `scripts/locustfile.py`). Mesures du 22/11/2026.

## 1. Configuration matérielle et logicielle

| Élément | Valeur |
|---|---|
| Machine | MacBook Pro, Apple M3 Pro, 12 cœurs logiques, 18 Go de RAM |
| Système | macOS (Darwin 25.5.0, arm64) |
| Python / libs | Python 3.12.8, scikit-learn 1.9.1, FastAPI 0.165.0, uvicorn 0.54.0, NumPy 2.5.5 |
| Serveur | `uvicorn app.main:app`, **1 worker**, logs d'accès désactivés |
| Client | httpx (connexions keep-alive) et Locust 2.47.0, **sur la même machine** que le serveur |
| Modèle | v1.0.0 — StandardScaler + régression logistique, 6 variables |

## 2. Objectif de performance et justification

| Indicateur | Objectif | Justification |
|---|---|---|
| Latence API P95 à 10 clients simultanés | **≤ 200 ms** | outil interactif utilisé par un agent de crédit pendant l'entretien : en dessous de ~200 ms, la réponse est perçue comme immédiate ; marge pour le réseau d'agence (souvent mobile/3G, 100–300 ms d'aller-retour en plus) |
| Débit soutenu à 10 clients | **≥ 50 req/s** | hypothèse dimensionnante : 200 agents × 40 dossiers/jour ≈ 8 000 requêtes/jour, soit < 1 req/s en moyenne et ~5 req/s en pointe ; 50 req/s offre une marge × 10 (rejeux, traitements par lots, croissance) |
| Latence d'inférence P95 (validation + prétraitement + modèle) | **≤ 10 ms** | l'inférence ne doit représenter qu'une petite fraction du budget de 200 ms |
| Taux d'erreur sous charge | **0 %** de 5xx | toute erreur serveur sous charge normale est une anomalie |

## 3. Résultats

### 3.1 Latence d'inférence (en mémoire, 5 000 itérations après échauffement)

| Mesure | Moyenne | P50 | **P95** | P99 | Max |
|---|---|---|---|---|---|
| Modèle seul (`predict_proba`) | 0,107 ms | 0,107 ms | **0,110 ms** | 0,117 ms | 0,171 ms |
| Validation + prétraitement + modèle | 0,122 ms | 0,122 ms | **0,125 ms** | 0,131 ms | 0,493 ms |

### 3.2 Temps de réponse de l'API (HTTP réel, 1 000 requêtes séquentielles)

| Moyenne | P50 | **P95** | P99 | Max |
|---|---|---|---|---|
| 0,63 ms | 0,60 ms | **0,67 ms** | 0,74 ms | 21,6 ms |

### 3.3 Charge progressive (benchmark, 100 requêtes par client sans temps de pause)

| Clients simultanés | Requêtes | Débit (req/s) | P50 | **P95** | P99 | Max | Erreurs |
|---|---|---|---|---|---|---|---|
| 1 | 100 | 1 501 | 0,57 ms | **0,63 ms** | 0,70 ms | 1,1 ms | 0 |
| 5 | 500 | 1 760 | 1,83 ms | **2,45 ms** | 3,18 ms | 3,3 ms | 0 |
| **10** | 1 000 | **1 015** | 3,49 ms | **4,89 ms** | 6,29 ms | 23,1 ms | 0 |
| 25 | 2 500 | 957 | 8,59 ms | **11,84 ms** | 14,63 ms | 23,8 ms | 0 |
| 50 | 5 000 | 960 | 16,55 ms | **27,31 ms** | 47,03 ms | 74,5 ms | 0 |

### 3.4 Test de charge Locust (montée progressive 0 → 50 utilisateurs à 5 utilisateurs/s, 60 s)

Profil « agent de crédit » : 10/12 prédictions (3 profils), 1/12 requête invalide (422 attendu), 1/12 `/health`,
pause de 50 à 200 ms entre actions.

| Endpoint | Requêtes | Échecs | Médiane | Moyenne | P95 | P99 | Max | Débit |
|---|---|---|---|---|---|---|---|---|
| `POST /predict` | 18 615 | 0 | 1 ms | 1,7 ms | 3 ms | 5 ms | 62 ms | 332 req/s |
| `GET /health` | 1 696 | 0 | 1 ms | 1,4 ms | 3 ms | 5 ms | 24 ms | 30 req/s |
| **Total** | **20 311** | **0 (0 %)** | 1 ms | 1,7 ms | **3 ms** | 5 ms | 62 ms | **362 req/s** |

## 4. Interprétation

| Objectif | Mesure | Verdict |
|---|---|---|
| P95 API ≤ 200 ms à 10 clients | 4,9 ms | ✅ atteint (marge × 40) |
| Débit ≥ 50 req/s à 10 clients | 1 015 req/s | ✅ atteint (marge × 20) |
| P95 inférence ≤ 10 ms | 0,125 ms | ✅ atteint |
| 0 % d'erreurs 5xx sous charge | 0 / 30 000+ requêtes | ✅ atteint |

- **Saturation** : avec 1 worker, le débit plafonne vers **~1 000 req/s** à partir de 10 clients ; au-delà, la latence
  croît linéairement avec la file d'attente (P95 × 2,3 entre 25 et 50 clients) **sans erreur**. Le goulot est le
  processus Python unique (GIL + pool de threads de FastAPI pour l'endpoint synchrone), pas le modèle
  (0,1 ms). Plusieurs workers (`--workers N`) augmenteraient le débit quasi linéairement.
- **Coût réparti** : sur ~0,6 ms par requête, l'inférence (validation + prétraitement + modèle) en représente
  ~0,12 ms ; le reste est la pile HTTP/JSON de FastAPI.
- Les maxima isolés (21–74 ms) sont des pics ponctuels (ordonnanceur de l'OS, ramasse-miettes), sans effet sur le P95.

## 5. Limites de la mesure

- Client et serveur sur la **même machine** : la latence réseau réelle (agences, réseau mobile) n'est pas mesurée
  et dominera probablement le temps perçu.
- Poste de développement récent (Apple M3 Pro) ≠ serveur de production ; à refaire sur l'infrastructure cible
  (souvent un vCPU partagé, potentiellement 3 à 5 fois plus lent).
- Le modèle est une régression logistique très légère ; un modèle plus complexe (gradient boosting, réseau de
  neurones) modifierait fortement la latence d'inférence — le benchmark devra être rejoué à chaque changement
  d'algorithme (il fait partie de la procédure de qualification d'une nouvelle version).
- Pas de test d'endurance (plusieurs heures) ni de mesure mémoire dans la durée.
- La performance mesurée ici est **technique** ; elle ne dit rien de la **qualité prédictive** du modèle.
