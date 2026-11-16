"""Sparse synthetic preference cohorts, additive to the Assignment 6 dataset."""

import json
import os
import random
import secrets
from datetime import timedelta
from uuid import NAMESPACE_URL, uuid5

from pymongo import UpdateOne

from app.config import ROOT
from app.db import CATEGORIES, initialize
from app.manage import demo_id
from app.queries import utcnow
from app.security import hash_password, verify_password

DEMO_EMAILS = ("cf-alice@example.com", "cf-boris@example.com", "cf-new@example.com")


def seed_cf(db, users=120, models=60, interactions=12000, seed_value=42, save_credentials=True):
    if not (12 <= users <= 10000 and 12 <= models <= 600 and models % 3 == 0 and 4 <= interactions <= 2_000_000):
        raise ValueError("CF data requires 12..10000 users, 12..600 models (multiple of 3), 4..2000000 events")
    initialize(db)
    rng = random.Random(seed_value)
    now = utcnow()
    password = os.getenv("DEMO_PASSWORD") or secrets.token_urlsafe(24)
    password_hash = hash_password(password)
    user_ids = [demo_id(f"cf-user-{seed_value}-{i}") for i in range(users)]
    model_ids = [demo_id(f"cf-model-{seed_value}-{i}") for i in range(models)]
    emails = DEMO_EMAILS if seed_value == 42 else tuple(f"cf-{seed_value}-{name}@example.com" for name in ("alice", "boris", "new"))
    width = models // 3
    user_writes = []
    for i, uid in enumerate(user_ids):
        email = emails[i] if i < 3 else f"cf-{seed_value}-{i:05d}@example.com"
        name = ("CF Alice", "CF Boris", "CF New User")[i] if i < 3 else f"CF Researcher {i:05d}"
        user_writes.append(UpdateOne({"_id": uid}, {"$setOnInsert": {
            "email": email, "display_name": name, "password_hash": password_hash, "role": "user",
            "device": {"signal": "eeg", "memory_budget_mb": 128.0, "max_latency_ms": 100.0, "reference_device": "synthetic-edge-v1"},
            "created_at": now, "updated_at": now,
        }}, upsert=True))
    db.users.bulk_write(user_writes, ordered=False)
    model_writes = []
    for i, mid in enumerate(model_ids):
        cohort = i // width
        model_writes.append(UpdateOne({"_id": mid}, {"$setOnInsert": {
            "name": f"CF EEG {('Compact', 'Temporal', 'Hybrid')[cohort]} {i % width + 1:02d}",
            "slug": f"cf-{seed_value}-eeg-{i:03d}", "version": "1.0",
            "description": "Synthetic candidate for collaborative filtering demonstrations. Resource and quality values are simulated; no detector was trained.",
            "category": CATEGORIES[cohort], "signals": ["eeg"], "tags": ["synthetic", "cf-demo", "edge"],
            "requirements": {"memory_mb": round(16 + rng.random() * 80, 2), "latency_ms": round(8 + rng.random() * 70, 2), "reference_device": "synthetic-edge-v1"},
            "evaluation": {"f1": round(0.7 + rng.random() * 0.2, 4), "dataset": "synthetic-cf-v1", "protocol": "Simulation; not real detector measurements"},
            "synthetic": True, "active": True, "created_at": now, "updated_at": now,
        }}, upsert=True))
    db.models.bulk_write(model_writes, ordered=False)
    stored = {doc["_id"]: doc for doc in db.models.find({"_id": {"$in": model_ids}})}
    choices = {}
    for i in range(3, users):
        cohort = i % 3
        own = list(range(cohort * width, (cohort + 1) * width))
        other = list(range(((cohort + 1) % 3) * width, (((cohort + 1) % 3) + 1) * width))
        choices[i] = (rng.sample(own, min(6, width)), rng.sample(other, min(2, width)))
    batch = []
    start = now - timedelta(days=30)
    for i in range(interactions):
        if i < 4:
            user_index = i // 2
            model_index = user_index * width + i % 2
            kind, rating = "rating", 5
        else:
            user_index = rng.randrange(3, users)
            positive = rng.random() < 0.92
            strong, weak = choices[user_index]
            model_index = rng.choice(strong if positive else weak)
            kind = rng.choices(["view", "save", "select", "rating"], [60, 18, 10, 12])[0]
            rating = rng.choice([4, 5] if positive else [1, 2]) if kind == "rating" else None
        model = stored[model_ids[model_index]]
        event = {
            "user_id": user_ids[user_index], "model_id": model["_id"], "type": kind, "rating": rating,
            "request_id": str(uuid5(NAMESPACE_URL, f"cf-demo/{seed_value}/{i}")),
            "model_snapshot": {key: model[key] for key in ("name", "slug", "version")},
            "created_at": start + timedelta(seconds=(i + 1) * 30 * 86400 / (interactions + 1)),
        }
        batch.append(UpdateOne({"_id": demo_id(f"cf-event-{seed_value}-{i}")}, {"$setOnInsert": event}, upsert=True))
        if len(batch) == 1000:
            db.interactions.bulk_write(batch, ordered=False)
            batch = []
    if batch:
        db.interactions.bulk_write(batch, ordered=False)
    if save_credentials:
        accounts = list(db.users.find({"_id": {"$in": user_ids[:3]}}))
        if all(verify_password(password, account["password_hash"]) for account in accounts):
            (ROOT / ".cf-demo-credentials.json").write_text(json.dumps({"password": password, "accounts": list(emails)}, indent=2), encoding="utf-8")
            print("CF demo access saved locally to .cf-demo-credentials.json; no credentials are printed.")
    return {"users": users, "models": models, "interactions": interactions, "seed": seed_value}
