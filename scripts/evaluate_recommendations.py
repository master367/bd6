"""Deterministic leave-one-item-out evaluation, with all held-out pair data removed.

This is a synthetic-data diagnostic, not evidence of real recommendation quality.
It intentionally uses a static hold-out rather than claiming a temporal experiment.
"""

import argparse
import json
import math
import random
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.config import ROOT, Settings  # noqa: E402
from app.db import connect  # noqa: E402
from app.queries import utcnow  # noqa: E402
from app.recommender import (  # noqa: E402
    build_snapshot,
    eligible_query,
    rank_candidates,
    snapshot_from_preferences,
)


def metrics(rankings, targets, k, catalog_count):
    hits = 0
    ndcg = 0.0
    coverage = set()
    for ranking, target in zip(rankings, targets, strict=True):
        coverage.update(ranking)
        if target in ranking:
            hits += 1
            ndcg += 1.0 / math.log2(ranking.index(target) + 2)
    total = len(targets)
    return {"precision_at_k": round(hits / (total * k), 6), "hit_rate_at_k": round(hits / total, 6), "ndcg_at_k": round(ndcg / total, 6), "catalog_coverage": round(len(coverage) / catalog_count, 6), "recommended_unique_items": len(coverage)}


def evaluate(db, k=5, max_users=200, seed=7):
    snapshot = build_snapshot(db)
    profiles = {uid: dict(profile) for uid, profile in snapshot.preferences.items()}
    users = list(db.users.find({"device": {"$ne": None}}, {"device": 1}))
    users.sort(key=lambda user: user["_id"])
    rng = random.Random(seed)
    rng.shuffle(users)
    cases = []
    for user in users:
        profile = profiles.get(user["_id"], {})
        if len([p for p in profile.values() if p.score > 0]) < 2:
            continue
        candidates = list(db.models.find(eligible_query(user["device"])))
        eligible = {doc["_id"] for doc in candidates}
        positive = sorted(mid for mid, pref in profile.items() if pref.score >= 2 and mid in eligible)
        if not positive:
            continue
        target = rng.choice(positive)
        del profile[target]  # Remove the entire pair, including views/saves and ratings.
        cases.append((user["_id"], candidates, target))
        if len(cases) == max_users:
            break
    if not cases:
        raise ValueError("No evaluable users; run seed-cf first")
    training = snapshot_from_preferences(profiles)
    rankings = []
    baseline_rankings = []
    targets = []
    collaborative_slots = 0
    for uid, candidates, target in cases:
        profile = profiles[uid]
        selected, fallback, _ = rank_candidates(training, profile, candidates, k)
        ranking = [doc["_id"] for doc, _, _ in selected] + [doc["_id"] for doc in fallback]
        collaborative_slots += len(selected)
        allowed = [doc for doc in candidates if doc["_id"] not in profile or not profile[doc["_id"]].exclude]
        baseline = sorted(allowed, key=lambda doc: (doc["requirements"]["latency_ms"], doc["requirements"]["memory_mb"], doc["_id"]))[:k]
        assert target not in profile
        assert set(ranking) <= {doc["_id"] for doc in candidates}
        rankings.append(ranking)
        baseline_rankings.append([doc["_id"] for doc in baseline])
        targets.append(target)
    active_count = db.models.count_documents({"active": True})
    return {"generated_at": utcnow().isoformat(), "dataset": db.name, "protocol": "static leave-one-item-out; remove each held-out user's entire item pair before rebuilding all similarities", "seed": seed, "k": k, "evaluated_users": len(cases), "training_user_item_pairs": training.pairs, "held_out_pairs": len(cases), "constraint_violations": 0, "collaborative_slots": collaborative_slots, "item_cf_with_fallback": metrics(rankings, targets, k, active_count), "constraint_baseline": metrics(baseline_rankings, targets, k, active_count), "limitations": ["Synthetic behaviour and synthetic item characteristics.", "Static hold-out, not a temporal or prospective evaluation.", "Observed positive events define relevance; missing events do not establish dislike.", "Precision divides by K even when fewer than K recommendations are available.", "These results test the mechanism and do not measure real user satisfaction."]}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--k", type=int, default=5)
    parser.add_argument("--max-users", type=int, default=200)
    parser.add_argument("--output", type=Path, default=ROOT / "output" / "evaluation.json")
    args = parser.parse_args()
    if not 1 <= args.k <= 100 or args.max_users < 1:
        parser.error("Use K in 1..100 and a positive max-users")
    settings = Settings.from_env()
    with connect(settings.mongo_uri) as mongo:
        result = evaluate(mongo[settings.database], args.k, args.max_users)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
