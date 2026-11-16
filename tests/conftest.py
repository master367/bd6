import os
from uuid import uuid4

import pytest
from bson import ObjectId
from fastapi.testclient import TestClient

from app.config import Settings
from app.db import connect
from app.main import create_app

PASSWORD = "integration-password-123"


@pytest.fixture
def environment():
    # The only database dropped by this suite is the random database it creates here.
    settings = Settings.from_env()
    name = f"edge_catalog_test_{uuid4().hex}"
    mongo = connect(os.getenv("MONGODB_TEST_URI", settings.mongo_uri))
    mongo.admin.command("ping")
    db = mongo[name]
    app = create_app(Settings(settings.mongo_uri, name, "integration-secret-" * 4), db)
    try:
        with TestClient(app) as api:
            headers = {}
            ids = {}
            for person in ("admin", "alice", "bob"):
                response = api.post(
                    "/auth/register",
                    json={
                        "email": f"{person}@example.com",
                        "password": PASSWORD,
                        "display_name": person,
                    },
                )
                assert response.status_code == 201, response.text
                ids[person] = response.json()["id"]
                if person == "admin":
                    db.users.update_one({"_id": ObjectId(ids[person])}, {"$set": {"role": "admin"}})
                login = api.post(
                    "/auth/token", data={"username": f"{person}@example.com", "password": PASSWORD}
                )
                assert login.status_code == 200
                headers[person] = {"Authorization": f"Bearer {login.json()['access_token']}"}
            yield api, db, headers, ids
    finally:
        assert name.startswith("edge_catalog_test_") and len(name) == 50
        mongo.drop_database(name)
        mongo.close()


@pytest.fixture
def model_body():
    return {
        "name": "EEG Tiny Demo",
        "slug": "eeg-tiny",
        "version": "1.0",
        "description": "Synthetic EEG classifier for database tests.",
        "category": "classical_ml",
        "signals": ["eeg"],
        "tags": ["edge", "tiny"],
        "requirements": {
            "memory_mb": 32,
            "latency_ms": 15,
            "reference_device": "synthetic-edge-v1",
        },
        "evaluation": {"f1": 0.8, "dataset": "synthetic-v1", "protocol": "simulation"},
        "synthetic": True,
    }

