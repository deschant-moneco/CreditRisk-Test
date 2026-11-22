"""API de prédiction du risque de défaut de remboursement (FastAPI).

Endpoints :
- GET  /health      : disponibilité du service et du modèle
- POST /predict     : estimation du risque pour une demande
- GET  /model-info  : métadonnées de la version du modèle
"""

from __future__ import annotations

import logging
import os
import time
import uuid
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from app import preprocessing
from app.prediction import (
    DEFAULT_MODEL_PATH,
    ModelService,
    ModelUnavailableError,
    PredictionError,
    interpreter,
)
from app.validation import DemandeCredit, detecter_alertes

logger = logging.getLogger("creditrisk")

API_VERSION = "1.0.0"


def charger_modele(app: FastAPI) -> None:
    chemin = os.environ.get("CREDITRISK_MODEL_PATH", str(DEFAULT_MODEL_PATH))
    try:
        app.state.model_service = ModelService.load(chemin)
        logger.info("Modèle %s chargé", app.state.model_service.version)
    except ModelUnavailableError:
        logger.exception("Échec du chargement du modèle (%s)", chemin)
        app.state.model_service = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    charger_modele(app)
    yield


app = FastAPI(title="CreditRisk API", version=API_VERSION, lifespan=lifespan)
app.state.model_service = None


def erreur(status: int, code: str, message: str, details: list | None = None) -> JSONResponse:
    contenu = {"erreur": code, "message": message}
    if details is not None:
        contenu["details"] = details
    return JSONResponse(status_code=status, content=contenu)


@app.exception_handler(RequestValidationError)
async def gestion_validation(request: Request, exc: RequestValidationError) -> JSONResponse:
    erreurs = exc.errors()
    if any(e.get("type") == "json_invalid" for e in erreurs):
        return erreur(400, "requete_mal_formee", "Le corps de la requête n'est pas un JSON valide.")
    details = [
        {
            "champ": ".".join(str(p) for p in e.get("loc", ()) if p != "body") or "body",
            "type": e.get("type"),
            "message": e.get("msg"),
        }
        for e in erreurs
    ]
    return erreur(422, "donnees_invalides", "Les données de la demande sont invalides.", details)


@app.exception_handler(Exception)
async def gestion_erreur_inattendue(request: Request, exc: Exception) -> JSONResponse:
    logger.exception("Erreur interne non gérée")
    return erreur(500, "erreur_interne", "Une erreur interne est survenue.")


def service_modele(request: Request) -> ModelService:
    service = getattr(request.app.state, "model_service", None)
    if service is None:
        raise ModelUnavailableError("Modèle non chargé")
    return service


@app.get("/health")
def health(request: Request):
    service = getattr(request.app.state, "model_service", None)
    if service is None:
        return JSONResponse(
            status_code=503,
            content={"status": "indisponible", "modele_charge": False, "version_api": API_VERSION},
        )
    return {
        "status": "ok",
        "modele_charge": True,
        "version_modele": service.version,
        "version_api": API_VERSION,
    }


@app.get("/model-info")
def model_info(request: Request):
    try:
        service = service_modele(request)
    except ModelUnavailableError:
        return erreur(503, "modele_indisponible", "Le modèle de prédiction n'est pas disponible.")
    return service.info()


@app.post("/predict")
def predict(demande: DemandeCredit, request: Request):
    request_id = str(uuid.uuid4())
    try:
        service = service_modele(request)
    except ModelUnavailableError:
        return erreur(503, "modele_indisponible", "Le modèle de prédiction n'est pas disponible.")

    debut = time.perf_counter()
    try:
        X = preprocessing.transform(demande.model_dump())
        probabilite = service.predict_one(X)
    except preprocessing.PreprocessingError:
        logger.exception("Erreur de prétraitement [%s]", request_id)
        return erreur(500, "erreur_pretraitement", "La demande n'a pas pu être traitée.")
    except PredictionError:
        logger.exception("Erreur de prédiction [%s]", request_id)
        return erreur(500, "erreur_prediction", "La prédiction n'a pas pu être calculée.")

    interpretation = interpreter(probabilite, service.seuil_decision)
    return {
        "request_id": request_id,
        "probabilite_defaut": round(probabilite, 6),
        "classe_risque": interpretation.classe_risque,
        "decision_suggeree": interpretation.decision,
        "seuil_decision": service.seuil_decision,
        "alertes": detecter_alertes(demande, service.metadata.get("plages_entrainement")),
        "version_modele": service.version,
        "duree_inference_ms": round((time.perf_counter() - debut) * 1000, 3),
    }
