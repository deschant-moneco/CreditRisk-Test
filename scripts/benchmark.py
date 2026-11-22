"""Activité 6 - Mesure de la latence et du débit.

Usage : python scripts/benchmark.py [--rapide]

1. Latence d'inférence du modèle seul (prétraitement + predict_proba), en mémoire.
2. Latence de l'API (HTTP réel, serveur uvicorn local, 1 worker), requêtes séquentielles.
3. Charge progressive : 1, 5, 10, 25, 50 clients concurrents -> débit, P50/P95/P99, erreurs.
Résultats : reports/perf/benchmark.json
"""

from __future__ import annotations

import argparse
import json
import os
import platform
import socket
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import httpx
import numpy as np

RACINE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RACINE))

from app.prediction import ModelService  # noqa: E402
from app.preprocessing import transform  # noqa: E402
from app.validation import DemandeCredit  # noqa: E402

SORTIE = RACINE / "reports" / "perf" / "benchmark.json"
DEMANDE = {"age": 35, "revenu_mensuel": 250000, "montant_credit": 1000000, "duree_mois": 12, "anciennete_activite": 4}
OBJECTIFS = {"api_p95_ms_10_clients": 200.0, "debit_min_rps_10_clients": 50.0, "inference_p95_ms": 10.0}


def stats(durees_s: list[float]) -> dict:
    ms = np.array(durees_s) * 1000
    return {
        "n": len(ms),
        "moyenne_ms": round(float(ms.mean()), 3),
        "p50_ms": round(float(np.percentile(ms, 50)), 3),
        "p95_ms": round(float(np.percentile(ms, 95)), 3),
        "p99_ms": round(float(np.percentile(ms, 99)), 3),
        "max_ms": round(float(ms.max()), 3),
    }


def config_materielle() -> dict:
    try:
        cpu = subprocess.run(
            ["sysctl", "-n", "machdep.cpu.brand_string"], capture_output=True, text=True, check=True
        ).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        cpu = platform.processor()
    import fastapi
    import sklearn
    import uvicorn

    return {
        "os": f"{platform.system()} {platform.release()} ({platform.machine()})",
        "cpu": cpu,
        "coeurs_logiques": os.cpu_count(),
        "python": platform.python_version(),
        "scikit_learn": sklearn.__version__,
        "fastapi": fastapi.__version__,
        "uvicorn": uvicorn.__version__,
        "serveur": "uvicorn, 1 worker, boucle asyncio par défaut, logs d'accès désactivés",
        "client": "httpx (même machine, connexions keep-alive)",
    }


def mesurer_inference(n: int) -> dict:
    service = ModelService.load()
    for _ in range(100):  # échauffement
        service.predict_one(transform(DEMANDE))
    modele, chaine = [], []
    for _ in range(n):
        t0 = time.perf_counter()
        X = transform(DemandeCredit(**DEMANDE).model_dump())
        t1 = time.perf_counter()
        service.predict_one(X)
        t2 = time.perf_counter()
        modele.append(t2 - t1)
        chaine.append(t2 - t0)
    return {"modele_seul": stats(modele), "validation_pretraitement_modele": stats(chaine)}


def port_libre() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def demarrer_serveur(port: int) -> subprocess.Popen:
    proc = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "uvicorn",
            "app.main:app",
            "--port",
            str(port),
            "--no-access-log",
            "--log-level",
            "warning",
        ],
        cwd=RACINE,
    )
    url = f"http://127.0.0.1:{port}/health"
    for _ in range(100):
        try:
            if httpx.get(url, timeout=0.5).status_code == 200:
                return proc
        except httpx.HTTPError:
            time.sleep(0.1)
    proc.kill()
    raise RuntimeError("le serveur n'a pas démarré")


def mesurer_api_sequentiel(base: str, n: int) -> dict:
    durees = []
    with httpx.Client(base_url=base) as client:
        for _ in range(20):
            client.post("/predict", json=DEMANDE)
        for _ in range(n):
            t0 = time.perf_counter()
            r = client.post("/predict", json=DEMANDE)
            durees.append(time.perf_counter() - t0)
            assert r.status_code == 200
    return stats(durees)


def palier(base: str, clients: int, requetes_par_client: int) -> dict:
    def travail(_):
        durees, erreurs = [], 0
        with httpx.Client(base_url=base, timeout=10) as client:
            for _ in range(requetes_par_client):
                t0 = time.perf_counter()
                try:
                    ok = client.post("/predict", json=DEMANDE).status_code == 200
                except httpx.HTTPError:
                    ok = False
                durees.append(time.perf_counter() - t0)
                erreurs += not ok
        return durees, erreurs

    debut = time.perf_counter()
    with ThreadPoolExecutor(max_workers=clients) as pool:
        resultats = list(pool.map(travail, range(clients)))
    total = time.perf_counter() - debut
    durees = [d for r in resultats for d in r[0]]
    erreurs = sum(r[1] for r in resultats)
    return {
        "clients": clients,
        **stats(durees),
        "debit_rps": round(len(durees) / total, 1),
        "erreurs": erreurs,
        "taux_erreur": round(erreurs / len(durees), 4),
        "duree_palier_s": round(total, 2),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--rapide", action="store_true")
    args = parser.parse_args()
    n_inf, n_seq, n_par_client = (500, 100, 20) if args.rapide else (5000, 1000, 100)

    resultats = {"configuration": config_materielle(), "objectifs": OBJECTIFS}
    print("1/3 inférence…")
    resultats["inference"] = mesurer_inference(n_inf)
    port = port_libre()
    proc = demarrer_serveur(port)
    base = f"http://127.0.0.1:{port}"
    try:
        print("2/3 API séquentielle…")
        resultats["api_sequentielle"] = mesurer_api_sequentiel(base, n_seq)
        print("3/3 charge progressive…")
        resultats["charge_progressive"] = []
        for clients in (1, 5, 10, 25, 50):
            p = palier(base, clients, n_par_client)
            resultats["charge_progressive"].append(p)
            print(f"  {clients:>2} clients : {p['debit_rps']} req/s, P95 {p['p95_ms']} ms, erreurs {p['erreurs']}")
    finally:
        proc.terminate()
        proc.wait(timeout=10)

    dix = next(p for p in resultats["charge_progressive"] if p["clients"] == 10)
    resultats["verdict"] = {
        "inference_p95_ms": resultats["inference"]["validation_pretraitement_modele"]["p95_ms"]
        <= OBJECTIFS["inference_p95_ms"],
        "api_p95_ms_10_clients": dix["p95_ms"] <= OBJECTIFS["api_p95_ms_10_clients"],
        "debit_min_rps_10_clients": dix["debit_rps"] >= OBJECTIFS["debit_min_rps_10_clients"],
    }
    SORTIE.parent.mkdir(parents=True, exist_ok=True)
    SORTIE.write_text(json.dumps(resultats, indent=2, ensure_ascii=False))
    print(json.dumps(resultats["verdict"], indent=2))
    print(f"Résultats : {SORTIE}")


if __name__ == "__main__":
    main()
