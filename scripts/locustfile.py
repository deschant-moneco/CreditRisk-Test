"""Test de charge Locust (local, léger).

Démarrer l'API :  uvicorn app.main:app --port 8000 --no-access-log
Lancer la charge : locust -f scripts/locustfile.py --host http://127.0.0.1:8000 \
                   --headless -u 50 -r 5 -t 60s --csv reports/perf/locust --only-summary
(-r 5 : 5 nouveaux utilisateurs par seconde => charge progressive de 0 à 50 en 10 s)
"""

from __future__ import annotations

import random

from locust import HttpUser, between, task

PROFILS = [
    {"age": 35, "revenu_mensuel": 250000, "montant_credit": 1000000, "duree_mois": 12, "anciennete_activite": 4},
    {"age": 52, "revenu_mensuel": 600000, "montant_credit": 3000000, "duree_mois": 24, "anciennete_activite": 20},
    {"age": 23, "revenu_mensuel": 90000, "montant_credit": 800000, "duree_mois": 6, "anciennete_activite": 1},
]


class AgentDeCredit(HttpUser):
    wait_time = between(0.05, 0.2)

    @task(10)
    def predire(self):
        self.client.post("/predict", json=random.choice(PROFILS))

    @task(1)
    def requete_invalide(self):
        with self.client.post("/predict", json={"age": -1}, catch_response=True) as r:
            if r.status_code == 422:
                r.success()

    @task(1)
    def sante(self):
        self.client.get("/health")
