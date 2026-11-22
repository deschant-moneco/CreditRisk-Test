# Rapport de non-régression

> Généré automatiquement par `python -m ml.regression` — ne pas modifier à la main.

- **Version de référence** : `1.0.0` (sha256 `0258910e424d…`)
- **Jeu d'évaluation figé** : `data/test_set.csv` (1500 observations synthétiques)
- **Jeu golden** : 50 cas figés dans `models/baseline/reference.json`

## Tolérances (définies avant comparaison)

| Contrôle | Tolérance | Effet si dépassée |
|---|---|---|
| Baisse de auc | ≤ 0.02 | **Bloquant** (régression) |
| Baisse de rappel | ≤ 0.03 | **Bloquant** (régression) |
| Baisse de f1 | ≤ 0.03 | **Bloquant** (régression) |
| Variation de precision | ± 0.05 | Avertissement, investigation |
| Variation de taux_defaut_predit | ± 0.05 | Avertissement, investigation |
| Écart de probabilité par cas, même version | ≤ 1e-09 | Bloquant |
| Écart de probabilité par cas, nouvelle version | ≤ 0.05 | Avertissement |
| Part de décisions golden modifiées | ≤ 10% | Bloquant |
| Sorties conformes au contrat | 100 % | Bloquant |

## Référence `1.0.0` → candidat `1.0.0` : **CONFORME**

| Contrôle | Référence | Candidat | Écart | Statut |
|---|---|---|---|---|
| auc (baisse max 0.02) | 0.8363 | 0.8363 | 0.0 | ✅ OK |
| rappel (baisse max 0.03) | 0.5918 | 0.5918 | 0.0 | ✅ OK |
| f1 (baisse max 0.03) | 0.5868 | 0.5868 | 0.0 | ✅ OK |
| precision (variation max ±0.05) | 0.5819 | 0.5819 | 0.0 | ✅ OK |
| taux_defaut_predit (variation max ±0.05) | 0.1993 | 0.1993 | 0.0 | ✅ OK |
| écart de probabilité max sur 50 cas golden (≤ 1e-09) | 0.0 | 0.0 | 0.0 | ✅ OK |
| part des décisions golden modifiées (≤ 0.1) | 0.0 | 0.0 | 0.0 | ✅ OK |
| sorties conformes au contrat (probabilités finies dans [0, 1]) | True | True | - | ✅ OK |

## Référence `1.0.0` → candidat `1.1.0` : **A_SURVEILLER**

| Contrôle | Référence | Candidat | Écart | Statut |
|---|---|---|---|---|
| auc (baisse max 0.02) | 0.8363 | 0.8347 | -0.0016 | ✅ OK |
| rappel (baisse max 0.03) | 0.5918 | 0.5748 | -0.017 | ✅ OK |
| f1 (baisse max 0.03) | 0.5868 | 0.6025 | 0.0157 | ✅ OK |
| precision (variation max ±0.05) | 0.5819 | 0.633 | 0.0511 | ⚠️ AVERT. |
| taux_defaut_predit (variation max ±0.05) | 0.1993 | 0.178 | -0.0213 | ✅ OK |
| écart de probabilité max sur 50 cas golden (≤ 0.05) | 0.0 | 0.051015 | 0.051015 | ⚠️ AVERT. |
| part des décisions golden modifiées (≤ 0.1) | 0.0 | 0.02 | 0.02 | ✅ OK |
| sorties conformes au contrat (probabilités finies dans [0, 1]) | True | True | - | ✅ OK |

## Référence `1.0.0` → candidat `1.2.0` : **REGRESSION**

| Contrôle | Référence | Candidat | Écart | Statut |
|---|---|---|---|---|
| auc (baisse max 0.02) | 0.8363 | 0.834 | -0.0023 | ✅ OK |
| rappel (baisse max 0.03) | 0.5918 | 0.1395 | -0.4523 | ❌ ÉCHEC |
| f1 (baisse max 0.03) | 0.5868 | 0.2433 | -0.3435 | ❌ ÉCHEC |
| precision (variation max ±0.05) | 0.5819 | 0.9535 | 0.3716 | ⚠️ AVERT. |
| taux_defaut_predit (variation max ±0.05) | 0.1993 | 0.0287 | -0.1706 | ⚠️ AVERT. |
| écart de probabilité max sur 50 cas golden (≤ 0.05) | 0.0 | 0.665664 | 0.665664 | ⚠️ AVERT. |
| part des décisions golden modifiées (≤ 0.1) | 0.0 | 0.3 | 0.3 | ❌ ÉCHEC |
| sorties conformes au contrat (probabilités finies dans [0, 1]) | True | True | - | ✅ OK |
