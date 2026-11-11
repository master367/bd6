import os
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from uuid import uuid4

import pytest
from bson import ObjectId
from fastapi.testclient import TestClient
from pymongo.errors import DuplicateKeyError, WriteError

from app.config import Settings
from app.db import connect
from app.main import create_app
from app.manage import benchmark, seed

pytestmark = pytest.mark.integration
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


def add_model(api, headers, body):
    result = api.post("/models", json=body, headers=headers["admin"])
    assert result.status_code == 201, result.text
    return result.json()["id"]


def event(api, headers, uid, model_id, kind="view", **extra):
    return api.post(
        "/interactions",
        headers=headers[uid],
        json={
            "model_id": model_id,
            "type": kind,
            "request_id": str(uuid4()),
            **extra,
        },
    )


def test_auth_permissions_and_conflicts(environment, model_body):
    api, db, headers, ids = environment
    assert api.get("/users/me").status_code == 401
    assert api.get("/users/me", headers={"Authorization": "Bearer invalid"}).status_code == 401
    assert api.post("/models", json=model_body, headers=headers["alice"]).status_code == 403
    assert api.get("/analytics/summary", headers=headers["alice"]).status_code == 403
    assert (
        api.post(
            "/auth/token", data={"username": "alice@example.com", "password": "wrong"}
        ).status_code
        == 401
    )
    duplicate = api.post(
        "/auth/register",
        json={"email": "ALICE@EXAMPLE.COM", "display_name": "Other", "password": PASSWORD},
    )
    assert duplicate.status_code == 409
    assert "password_hash" not in api.get("/users/me", headers=headers["alice"]).json()
    assert db.users.find_one({"_id": ObjectId(ids["alice"])})["password_hash"].startswith(
        "$argon2id$"
    )
    model_id = add_model(api, headers, model_body)
    assert api.post("/models", json=model_body, headers=headers["admin"]).status_code == 409
    updated = {**model_body, "name": "Updated Demo"}
    assert api.put(f"/models/{model_id}", json=updated, headers=headers["admin"]).status_code == 200
    assert api.get(f"/models/{model_id}").json()["name"] == "Updated Demo"
    assert api.get("/models/not-an-id").status_code == 422


def test_mongodb_rejects_invalid_direct_writes(environment, model_body):
    api, db, headers, _ = environment
    model_id = add_model(api, headers, model_body)
    doc = db.models.find_one({"_id": ObjectId(model_id)})
    doc.pop("_id")
    with pytest.raises(DuplicateKeyError):
        db.models.insert_one(doc.copy())
    doc["version"] = "2.0"
    doc["evaluation"]["f1"] = 1.5
    with pytest.raises(WriteError) as error:
        db.models.insert_one(doc)
    assert error.value.code == 121
    result = event(api, headers, "alice", model_id)
    bad = db.interactions.find_one({"_id": ObjectId(result.json()["id"])})
    bad.pop("_id")
    bad.update(request_id=str(uuid4()), type="rating", rating=None)
    with pytest.raises(WriteError) as error:
        db.interactions.insert_one(bad)
    assert error.value.code == 121


def test_concurrent_idempotency_and_archived_history(environment, model_body):
    api, db, headers, _ = environment
    model_id = add_model(api, headers, model_body)
    body = {"model_id": model_id, "type": "view", "request_id": str(uuid4())}

    def send(_):
        return api.post("/interactions", headers=headers["alice"], json=body)

    with ThreadPoolExecutor(max_workers=4) as pool:
        responses = list(pool.map(send, range(8)))
    assert sorted(r.status_code for r in responses) == [200] * 7 + [201]
    assert len({r.json()["id"] for r in responses}) == 1
    assert db.interactions.count_documents({}) == 1
    assert (
        api.post(
            "/interactions", headers=headers["alice"], json={**body, "type": "select"}
        ).status_code
        == 409
    )
    assert api.delete(f"/models/{model_id}", headers=headers["admin"]).status_code == 204
    assert api.get(f"/models/{model_id}").status_code == 404
    assert api.get("/models").json()["items"] == []
    assert send(0).status_code == 200  # Retries remain safe even after archival.
    assert event(api, headers, "alice", model_id).status_code == 404
    history = api.get("/users/me/history", headers=headers["alice"]).json()["items"]
    assert history[0]["model_snapshot"]["name"] == model_body["name"]


def test_history_pagination_is_stable_and_private(environment, model_body):
    api, db, headers, ids = environment
    model_id = add_model(api, headers, model_body)
    for _ in range(5):
        assert event(api, headers, "alice", model_id).status_code == 201
    assert event(api, headers, "bob", model_id).status_code == 201
    # Force equal timestamps to exercise the ObjectId tie-breaker.
    db.interactions.update_many({}, {"$set": {"created_at": datetime(2026, 11, 1, tzinfo=UTC)}})
    seen, cursor = [], None
    for _ in range(4):
        params = {"limit": 2}
        if cursor:
            params["cursor"] = cursor
        response = api.get("/users/me/history", params=params, headers=headers["alice"])
        assert response.status_code == 200
        data = response.json()
        assert all(x["user_id"] == ids["alice"] for x in data["items"])
        seen.extend(x["id"] for x in data["items"])
        cursor = data["next_cursor"]
        if not cursor:
            break
    assert len(seen) == len(set(seen)) == 5
    assert api.get("/users/me/history?cursor=broken", headers=headers["alice"]).status_code == 422


def test_search_recommendations_and_latest_ratings(environment, model_body):
    api, _, headers, _ = environment
    model_id = add_model(api, headers, model_body)
    other = {**model_body, "slug": "ecg-large", "name": "ECG Large", "signals": ["ecg"]}
    other_id = add_model(api, headers, other)
    search = api.get("/models", params={"q": "EEG", "signal": "eeg", "max_memory_mb": 40})
    assert [x["id"] for x in search.json()["items"]] == [model_id]
    assert api.get("/recommendations", headers=headers["alice"]).status_code == 400
    profile = {
        "display_name": "Alice",
        "device": {
            "signal": "eeg",
            "memory_budget_mb": 64,
            "max_latency_ms": 20,
            "reference_device": "synthetic-edge-v1",
        },
    }
    assert api.put("/users/me", json=profile, headers=headers["alice"]).status_code == 200
    recommended = api.get("/recommendations", headers=headers["alice"]).json()["items"]
    assert [x["id"] for x in recommended] == [model_id]
    for uid, rating in [("alice", 1), ("alice", 5), ("bob", 3)]:
        assert event(api, headers, uid, model_id, "rating", rating=rating).status_code == 201
    event(api, headers, "bob", other_id)
    ratings = api.get("/analytics/ratings", headers=headers["alice"]).json()["items"]
    assert ratings[0]["average_rating"] == 4
    assert ratings[0]["voters"] == 2
    popular = api.get("/analytics/popular", headers=headers["alice"]).json()["items"]
    assert popular[0]["model_id"] == model_id and popular[0]["events"] == 3
    stats = api.get(f"/models/{model_id}/stats?type=rating", headers=headers["alice"]).json()
    assert stats["items"] == [{"_id": "rating", "events": 3}]
    summary = api.get("/analytics/summary", headers=headers["admin"]).json()
    assert sum(row["events"] for row in summary["by_type"]) == 4


def test_seed_is_repeatable_and_index_reduces_scanned_documents(environment, tmp_path):
    _, db, _, _ = environment
    first = seed(db, users=10, models=10, interactions=1000, save_credentials=False)
    second = seed(db, users=10, models=10, interactions=1000, save_credentials=False)
    assert first == second
    result = benchmark(db, tmp_path / "benchmark.json", repetitions=2)
    assert result["results_equal"]
    baseline = result["results"]["natural_scan"]["median_documents_examined"]
    indexed = result["results"]["indexed"]["median_documents_examined"]
    assert baseline == 1000
    assert indexed <= 20 < baseline
