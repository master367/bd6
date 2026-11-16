from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from unittest.mock import patch
from uuid import uuid4

import pytest
from bson import ObjectId

from app.cf_data import seed_cf
from app.config import Settings
from app.queries import utcnow
from app.recommender import (
    Preference,
    RecommendationEngine,
    build_snapshot,
    preference,
    rank_candidates,
    snapshot_from_preferences,
)
from app.security import hash_password


def test_rating_overrides_interest_and_views_are_bounded():
    row = {"views": 1000, "saved": 1, "selected": 1, "rating": None}
    assert preference(row) == Preference(4.0, True)
    assert preference({**row, "rating": 1}) == Preference(-4.0, True)
    assert preference({**row, "rating": 3}) == Preference(0.0, True)


def test_similarity_comes_from_other_users_and_negative_interest_reduces_score():
    a, b, c = [ObjectId() for _ in range(3)]
    profiles = {ObjectId(): {a: Preference(4, True), b: Preference(4, True), c: Preference(4, True)} for _ in range(3)}
    snapshot = snapshot_from_preferences(profiles)
    candidates = [{"_id": mid, "requirements": {"memory_mb": 10, "latency_ms": 10}} for mid in [a, b, c]]
    liked, _, _ = rank_candidates(snapshot, {a: Preference(4, True)}, candidates, 10)
    disliked, _, _ = rank_candidates(snapshot, {a: Preference(4, True), c: Preference(-4, True)}, candidates, 10)
    assert {row[0]["_id"] for row in liked} == {b, c}
    assert not disliked
    empty = snapshot_from_preferences({})
    assert not rank_candidates(empty, {a: Preference(4, True)}, candidates, 10)[0]


def test_snapshot_cache_builds_once_for_concurrent_readers_and_expires():
    snapshot = snapshot_from_preferences({})
    engine = RecommendationEngine(60)
    with patch("app.recommender.build_snapshot", return_value=snapshot) as builder:
        with ThreadPoolExecutor(max_workers=8) as pool:
            results = list(pool.map(lambda _: engine.snapshot(None), range(8)))
        assert builder.call_count == 1
        assert sum(hit for _, hit in results) == 7
        engine.invalidate()
        assert not engine.status()["ready"]
        assert engine.snapshot(None)[1] is False
        with patch("app.recommender.time.monotonic", return_value=10**12):
            assert engine.snapshot(None)[1] is False
        assert builder.call_count == 3


@pytest.mark.parametrize("ttl", [-1, float("inf"), float("nan"), 3601])
def test_cache_configuration_rejects_unbounded_ttl(ttl):
    with pytest.raises(ValueError):
        Settings("mongodb://localhost", "test", "secret", ttl)


@pytest.fixture
def collaborative_catalog(environment, model_body):
    api, db, headers, ids = environment
    model_ids = []
    for i in range(6):
        result = api.post("/models", headers=headers["admin"], json={**model_body, "slug": f"cf-test-{i}", "name": f"CF Test {i}"})
        assert result.status_code == 201
        model_ids.append(ObjectId(result.json()["id"]))
    now = utcnow()
    password_hash = hash_password("neighbor-test-password")
    for cohort in range(2):
        for i in range(3):
            uid = ObjectId()
            db.users.insert_one({"_id": uid, "email": f"neighbor-{cohort}-{i}@example.com", "display_name": "Neighbor", "role": "user", "password_hash": password_hash, "device": None, "created_at": now, "updated_at": now})
            for mid in model_ids[cohort * 3 : cohort * 3 + 3]:
                model = db.models.find_one({"_id": mid})
                db.interactions.insert_one({"user_id": uid, "model_id": mid, "type": "rating", "rating": 5, "request_id": str(uuid4()), "model_snapshot": {k: model[k] for k in ("name", "slug", "version")}, "created_at": now})
    for person, mid in [("alice", model_ids[0]), ("bob", model_ids[3])]:
        result = api.put("/users/me", headers=headers[person], json={"display_name": person, "device": {"signal": "eeg", "memory_budget_mb": 64, "max_latency_ms": 20, "reference_device": "synthetic-edge-v1"}})
        assert result.status_code == 200
        result = api.post("/interactions", headers=headers[person], json={"model_id": str(mid), "type": "rating", "rating": 5})
        assert result.status_code == 201
    return api, db, headers, ids, model_ids


@pytest.mark.integration
def test_same_device_different_behaviour_gets_different_cf_results(collaborative_catalog):
    api, _, headers, _, mids = collaborative_catalog
    alice = api.get("/recommendations?limit=2", headers=headers["alice"]).json()
    bob = api.get("/recommendations?limit=2", headers=headers["bob"]).json()
    assert alice["method"] == bob["method"] == "item_cf_v1"
    assert {x["id"] for x in alice["items"]} == {str(x) for x in mids[1:3]}
    assert {x["id"] for x in bob["items"]} == {str(x) for x in mids[4:6]}
    assert all(x["recommendation"]["score"] > 0 for x in alice["items"])
    assert all(x["recommendation"]["based_on"][0]["id"] == str(mids[0]) for x in alice["items"])
    assert alice["snapshot"]["cache_hit"] is False
    assert bob["snapshot"]["cache_hit"] is True
    assert api.get("/recommendations/status", headers=headers["alice"]).status_code == 403
    assert api.post("/recommendations/rebuild", headers=headers["alice"]).status_code == 403
    assert api.post("/recommendations/rebuild", headers=headers["admin"]).json()["ready"]


@pytest.mark.integration
def test_latest_rating_and_event_idempotency_update_recommendations(collaborative_catalog):
    api, db, headers, ids, mids = collaborative_catalog
    api.get("/recommendations", headers=headers["alice"])
    body = {"model_id": str(mids[0]), "type": "rating", "rating": 1, "request_id": str(uuid4())}
    assert api.post("/interactions", headers=headers["alice"], json=body).status_code == 201
    assert api.post("/interactions", headers=headers["alice"], json=body).status_code == 200
    snapshot = build_snapshot(db)
    assert snapshot.preferences[ObjectId(ids["alice"])][mids[0]].score == -4
    result = api.get("/recommendations", headers=headers["alice"]).json()
    assert result["collaborative_count"] == 0
    assert not {str(x) for x in mids[:3]} & {x["id"] for x in result["items"]}
    # A later view never hides the latest explicit rating.
    assert api.post("/interactions", headers=headers["alice"], json={"model_id": str(mids[0]), "type": "view"}).status_code == 201
    assert build_snapshot(db).preferences[ObjectId(ids["alice"])][mids[0]].score == -4


@pytest.mark.integration
def test_live_device_filter_archival_and_cold_start(collaborative_catalog, model_body):
    api, _, headers, _, mids = collaborative_catalog
    api.get("/recommendations", headers=headers["alice"])
    assert api.delete(f"/models/{mids[1]}", headers=headers["admin"]).status_code == 204
    assert api.put(f"/models/{mids[2]}", headers=headers["admin"], json={**model_body, "slug": "updated-large", "requirements": {**model_body["requirements"], "memory_mb": 1000}}).status_code == 200
    result = api.get("/recommendations", headers=headers["alice"]).json()
    assert not {str(x) for x in mids[:3]} & {x["id"] for x in result["items"]}
    profile = {"display_name": "admin", "device": {"signal": "eeg", "memory_budget_mb": 64, "max_latency_ms": 20, "reference_device": "synthetic-edge-v1"}}
    assert api.put("/users/me", headers=headers["admin"], json=profile).status_code == 200
    result = api.get("/recommendations", headers=headers["admin"]).json()
    assert result["fallback_reason"] == "no_history"
    assert result["fallback_count"] > 0
    assert all(x["recommendation"]["strategy"] == "fallback" for x in result["items"])
    profile["device"]["signal"] = "ecg"
    api.put("/users/me", headers=headers["admin"], json=profile)
    assert api.get("/recommendations", headers=headers["admin"]).json()["items"] == []


@pytest.mark.integration
def test_temporal_snapshot_has_no_future_rating_leakage(collaborative_catalog):
    api, db, headers, ids, mids = collaborative_catalog
    cutoff = utcnow()
    api.post("/interactions", headers=headers["alice"], json={"model_id": str(mids[0]), "type": "rating", "rating": 1})
    assert build_snapshot(db, before=cutoff).preferences[ObjectId(ids["alice"])][mids[0]].score == 4
    assert build_snapshot(db, before=cutoff - timedelta(days=1)).events == 0


@pytest.mark.integration
def test_cf_seed_is_additive_repeatable_and_has_sparse_preferences(environment):
    _, db, _, _ = environment
    before = db.users.count_documents({})
    seed_cf(db, users=30, models=30, interactions=1500, save_credentials=False)
    first = {name: db[name].count_documents({}) for name in ["users", "models", "interactions"]}
    seed_cf(db, users=30, models=30, interactions=1500, save_credentials=False)
    assert {name: db[name].count_documents({}) for name in first} == first
    assert first["users"] == before + 30
    snapshot = build_snapshot(db)
    assert snapshot.events == 1500
    assert snapshot.pairs < 30 * 30 / 2
    assert db.users.find_one({"email": "cf-new@example.com"})["_id"] not in snapshot.preferences


@pytest.mark.integration
def test_other_users_behaviour_updates_cached_collaborative_relationships(collaborative_catalog):
    api, _, headers, _, mids = collaborative_catalog
    before = api.get("/recommendations", headers=headers["alice"]).json()
    before_strategies = {item["id"]: item["recommendation"]["strategy"] for item in before["items"]}
    assert before_strategies[str(mids[3])] == "fallback"
    # Two users connect the previously disjoint interest groups.
    for person, mid in [("bob", mids[0]), ("admin", mids[0]), ("admin", mids[3])]:
        assert api.post("/interactions", headers=headers[person], json={"model_id": str(mid), "type": "rating", "rating": 5}).status_code == 201
    after = api.get("/recommendations", headers=headers["alice"]).json()
    assert after["snapshot"]["cache_hit"] is False
    strategies = {item["id"]: item["recommendation"]["strategy"] for item in after["items"]}
    assert strategies[str(mids[3])] == "collaborative"


@pytest.mark.integration
@pytest.mark.parametrize("field,value", [("latency_ms", 1000), ("reference_device", "other-device")])
def test_cf_never_overrides_device_constraints(collaborative_catalog, model_body, field, value):
    api, _, headers, _, mids = collaborative_catalog
    api.get("/recommendations", headers=headers["alice"])
    for i, mid in enumerate(mids[1:3]):
        result = api.put(f"/models/{mid}", headers=headers["admin"], json={**model_body, "slug": f"unavailable-{i}", "requirements": {**model_body["requirements"], field: value}})
        assert result.status_code == 200
    result = api.get("/recommendations", headers=headers["alice"]).json()
    assert not {str(x) for x in mids[1:3]} & {item["id"] for item in result["items"]}
