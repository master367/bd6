from contextlib import asynccontextmanager
from datetime import timedelta

import jwt
from bson import ObjectId
from fastapi import Depends, FastAPI, HTTPException, Query, Request, Response
from fastapi.responses import JSONResponse
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from pymongo import ReturnDocument
from pymongo.errors import DuplicateKeyError, PyMongoError

from app.config import Settings
from app.db import connect, initialize
from app.queries import object_id, page, popularity_pipeline, public, ratings_pipeline, utcnow
from app.schemas import (
    CatalogModel,
    Category,
    EventType,
    Interaction,
    ProfileUpdate,
    Register,
    Signal,
)
from app.security import create_token, hash_password, token_subject, verify_password

oauth = OAuth2PasswordBearer(tokenUrl="/auth/token")
DUMMY_HASH = hash_password("dummy-password-used-only-to-balance-login-cost")


def get_db(request: Request):
    return request.app.state.db


def current_user(request: Request, token: str = Depends(oauth), db=Depends(get_db)):
    try:
        subject = token_subject(token, request.app.state.settings.jwt_secret)
        if not ObjectId.is_valid(subject):
            raise ValueError
        user = db.users.find_one({"_id": ObjectId(subject)})
        if not user:
            raise ValueError
        return user
    except (jwt.InvalidTokenError, ValueError, TypeError):
        raise HTTPException(
            401, "Invalid or expired token", headers={"WWW-Authenticate": "Bearer"}
        ) from None


def admin(user=Depends(current_user)):
    if user["role"] != "admin":
        raise HTTPException(403, "Administrator access required")
    return user


def create_app(settings=None, database=None):
    settings = settings or Settings.from_env()

    @asynccontextmanager
    async def lifespan(app):
        settings.check_secret()
        client = None
        if database is None:
            client = connect(settings.mongo_uri)
            db = client[settings.database]
        else:
            db = database
        try:
            db.command("ping")
            initialize(db)
            app.state.db = db
            app.state.settings = settings
            yield
        finally:
            if client is not None:
                client.close()

    api = FastAPI(
        title="Edge Drowsiness Model Catalog",
        version="0.1.0",
        description=(
            "Assignment 6: NoSQL catalog, profiles, interactions and analytics. "
            "Seeded model characteristics are synthetic, not measured research results."
        ),
        lifespan=lifespan,
    )

    @api.exception_handler(PyMongoError)
    async def database_error(request, exc):
        return JSONResponse(
            status_code=503,
            content={"detail": "Database operation unavailable"},
            headers={"Retry-After": "2"},
        )

    @api.get("/health", tags=["system"])
    def health(db=Depends(get_db)):
        db.command("ping")
        return {"status": "ok", "database": "connected"}

    @api.post("/auth/register", status_code=201, tags=["authentication"])
    def register(body: Register, db=Depends(get_db)):
        now = utcnow()
        doc = {
            "email": str(body.email),
            "display_name": body.display_name,
            "password_hash": hash_password(body.password),
            "role": "user",
            "device": None,
            "created_at": now,
            "updated_at": now,
        }
        try:
            db.users.insert_one(doc)
        except DuplicateKeyError:
            raise HTTPException(409, "Email already registered") from None
        return public(doc)

    @api.post("/auth/token", tags=["authentication"])
    def login(form: OAuth2PasswordRequestForm = Depends(), db=Depends(get_db)):
        user = db.users.find_one({"email": form.username.strip().lower()})
        valid = verify_password(form.password, user["password_hash"] if user else DUMMY_HASH)
        if not user or not valid:
            raise HTTPException(
                401, "Incorrect email or password", headers={"WWW-Authenticate": "Bearer"}
            )
        return {
            "access_token": create_token(str(user["_id"]), settings.jwt_secret),
            "token_type": "bearer",
            "expires_in": 1800,
        }

    @api.get("/users/me", tags=["profile"])
    def me(user=Depends(current_user)):
        return public(user)

    @api.put("/users/me", tags=["profile"])
    def update_profile(body: ProfileUpdate, user=Depends(current_user), db=Depends(get_db)):
        result = db.users.find_one_and_update(
            {"_id": user["_id"]},
            {"$set": {**body.model_dump(), "updated_at": utcnow()}},
            return_document=ReturnDocument.AFTER,
        )
        return public(result)

    @api.get("/models", tags=["catalog"])
    def catalog(
        q: str | None = Query(None, min_length=1, max_length=100),
        category: Category | None = None,
        signal: Signal | None = None,
        max_memory_mb: float | None = Query(None, ge=0.001, le=1_000_000, allow_inf_nan=False),
        max_latency_ms: float | None = Query(None, ge=0.001, le=1_000_000, allow_inf_nan=False),
        reference_device: str | None = Query(None, min_length=1, max_length=100),
        limit: int = Query(20, ge=1, le=100),
        cursor: str | None = Query(None, max_length=256),
        db=Depends(get_db),
    ):
        query = {"active": True}
        if q:
            query["$text"] = {"$search": q}
        if category:
            query["category"] = category
        if signal:
            query["signals"] = signal
        if max_memory_mb is not None:
            query["requirements.memory_mb"] = {"$lte": max_memory_mb}
        if max_latency_ms is not None:
            query["requirements.latency_ms"] = {"$lte": max_latency_ms}
        if reference_device:
            query["requirements.reference_device"] = reference_device
        return page(db.models, query, limit, cursor)

    @api.post("/models", status_code=201, tags=["catalog"])
    def add_model(body: CatalogModel, user=Depends(admin), db=Depends(get_db)):
        now = utcnow()
        doc = {**body.model_dump(), "active": True, "created_at": now, "updated_at": now}
        try:
            db.models.insert_one(doc)
        except DuplicateKeyError:
            raise HTTPException(409, "This slug and version already exist") from None
        return public(doc)

    @api.get("/models/{model_id}", tags=["catalog"])
    def get_model(model_id: str, db=Depends(get_db)):
        doc = db.models.find_one({"_id": object_id(model_id), "active": True})
        if doc is None:
            raise HTTPException(404, "Model not found")
        return public(doc)

    @api.get("/models/{model_id}/stats", tags=["analytics"])
    def model_stats(
        model_id: str,
        days: int = Query(30, ge=1, le=3650),
        kind: EventType | None = Query(None, alias="type"),
        user=Depends(current_user),
        db=Depends(get_db),
    ):
        oid = object_id(model_id)
        if not db.models.find_one({"_id": oid, "active": True}, {"_id": 1}):
            raise HTTPException(404, "Model not found")
        query = {"model_id": oid, "created_at": {"$gte": utcnow() - timedelta(days=days)}}
        if kind:
            query["type"] = kind
        return {
            "model_id": model_id,
            "items": list(
                db.interactions.aggregate(
                    [
                        {"$match": query},
                        {"$group": {"_id": "$type", "events": {"$sum": 1}}},
                        {"$sort": {"_id": 1}},
                    ]
                )
            ),
        }

    @api.put("/models/{model_id}", tags=["catalog"])
    def update_model(model_id: str, body: CatalogModel, user=Depends(admin), db=Depends(get_db)):
        try:
            doc = db.models.find_one_and_update(
                {"_id": object_id(model_id), "active": True},
                {"$set": {**body.model_dump(), "updated_at": utcnow()}},
                return_document=ReturnDocument.AFTER,
            )
        except DuplicateKeyError:
            raise HTTPException(409, "This slug and version already exist") from None
        if doc is None:
            raise HTTPException(404, "Model not found")
        return public(doc)

    @api.delete("/models/{model_id}", status_code=204, tags=["catalog"])
    def delete_model(model_id: str, user=Depends(admin), db=Depends(get_db)):
        result = db.models.update_one(
            {"_id": object_id(model_id), "active": True},
            {"$set": {"active": False, "updated_at": utcnow()}},
        )
        if not result.matched_count:
            raise HTTPException(404, "Model not found")
        return Response(status_code=204)

    @api.post("/interactions", status_code=201, tags=["interactions"])
    def interact(
        body: Interaction, response: Response, user=Depends(current_user), db=Depends(get_db)
    ):
        key = {"user_id": user["_id"], "request_id": str(body.request_id)}

        def previous(existing):
            if (
                existing["model_id"] != ObjectId(body.model_id)
                or existing["type"] != body.type
                or existing["rating"] != body.rating
            ):
                raise HTTPException(409, "request_id was already used for a different event")
            response.status_code = 200
            return public(existing)

        existing = db.interactions.find_one(key)
        if existing:
            return previous(existing)
        model = db.models.find_one({"_id": object_id(body.model_id), "active": True})
        if model is None:
            raise HTTPException(404, "Active model not found")
        doc = {
            **key,
            "model_id": model["_id"],
            "type": body.type,
            "rating": body.rating,
            "model_snapshot": {k: model[k] for k in ("name", "slug", "version")},
            "created_at": utcnow(),
        }
        try:
            db.interactions.insert_one(doc)
        except DuplicateKeyError:
            existing = db.interactions.find_one(key)
            if existing:
                return previous(existing)
            raise
        return public(doc)

    @api.get("/users/me/history", tags=["interactions"])
    def history(
        limit: int = Query(20, ge=1, le=100),
        cursor: str | None = Query(None, max_length=256),
        user=Depends(current_user),
        db=Depends(get_db),
    ):
        return page(db.interactions, {"user_id": user["_id"]}, limit, cursor)

    @api.get("/recommendations", tags=["recommendations"])
    def recommendations(
        limit: int = Query(10, ge=1, le=100), user=Depends(current_user), db=Depends(get_db)
    ):
        device = user.get("device")
        if not device:
            raise HTTPException(400, "Set a device profile with PUT /users/me first")
        query = {
            "active": True,
            "signals": device["signal"],
            "requirements.reference_device": device["reference_device"],
            "requirements.memory_mb": {"$lte": device["memory_budget_mb"]},
            "requirements.latency_ms": {"$lte": device["max_latency_ms"]},
        }
        docs = list(
            db.models.find(query)
            .sort([("requirements.latency_ms", 1), ("requirements.memory_mb", 1), ("_id", 1)])
            .limit(limit)
        )
        return {
            "method": "constraint_filter_v1",
            "device": device,
            "note": "Baseline matching on one reference device; synthetic metrics are not measurements.",
            "items": [public(doc) for doc in docs],
        }

    @api.get("/analytics/popular", tags=["analytics"])
    def popular(
        days: int = Query(30, ge=1, le=3650),
        limit: int = Query(10, ge=1, le=100),
        user=Depends(current_user),
        db=Depends(get_db),
    ):
        since = utcnow() - timedelta(days=days)
        return {
            "since": since,
            "items": [
                public(doc) for doc in db.interactions.aggregate(popularity_pipeline(since, limit))
            ],
        }

    @api.get("/analytics/ratings", tags=["analytics"])
    def ratings(user=Depends(current_user), db=Depends(get_db)):
        return {"items": [public(doc) for doc in db.interactions.aggregate(ratings_pipeline())]}

    @api.get("/analytics/summary", tags=["analytics"])
    def summary(days: int = Query(30, ge=1, le=3650), user=Depends(admin), db=Depends(get_db)):
        result = list(
            db.interactions.aggregate(
                [
                    {"$match": {"created_at": {"$gte": utcnow() - timedelta(days=days)}}},
                    {
                        "$facet": {
                            "by_type": [
                                {"$group": {"_id": "$type", "events": {"$sum": 1}}},
                                {"$sort": {"_id": 1}},
                            ],
                            "by_day": [
                                {
                                    "$group": {
                                        "_id": {
                                            "$dateToString": {
                                                "date": "$created_at",
                                                "format": "%Y-%m-%d",
                                                "timezone": "UTC",
                                            }
                                        },
                                        "events": {"$sum": 1},
                                    }
                                },
                                {"$sort": {"_id": 1}},
                            ],
                        }
                    },
                ]
            )
        )
        return {"timezone": "UTC", **result[0]}

    return api


app = create_app()
