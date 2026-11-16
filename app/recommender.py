"""Item collaborative filtering over the existing MongoDB interaction documents.

Only aggregated behaviour defines similarity. Device metadata is an eligibility rule,
never a substitute for collaborative similarity. The bounded process-local snapshot
is invalidated by API writes; its TTL also covers writes from other processes.
"""

import math
import time
from collections import defaultdict
from dataclasses import dataclass
from datetime import UTC, datetime
from threading import RLock

from app.queries import public

VERSION = "item_cf_v1"
NEIGHBORS = 50
SHRINKAGE = 2.0


def preference_pipeline(user_id=None, before=None):
    pipeline = []
    match = {}
    if user_id is not None:
        match["user_id"] = user_id
    if before is not None:
        match["created_at"] = {"$lt": before}
    if match:
        pipeline.append({"$match": match})
    pipeline.extend(
        [
            {"$set": {"rating_priority": {"$cond": [{"$eq": ["$type", "rating"]}, 1, 0]}}},
            {
                "$group": {
                    "_id": {"user": "$user_id", "model": "$model_id"},
                    "events": {"$sum": 1},
                    "views": {"$sum": {"$cond": [{"$eq": ["$type", "view"]}, 1, 0]}},
                    "saved": {"$max": {"$cond": [{"$eq": ["$type", "save"]}, 1, 0]}},
                    "selected": {"$max": {"$cond": [{"$eq": ["$type", "select"]}, 1, 0]}},
                    "rating": {
                        "$top": {
                            "sortBy": {"rating_priority": -1, "created_at": -1, "_id": -1},
                            "output": "$rating",
                        }
                    },
                }
            },
        ]
    )
    return pipeline


@dataclass(frozen=True)
class Preference:
    score: float
    exclude: bool


def preference(row):
    # Explicit ratings override implicit interest, including a neutral rating.
    rating = row["rating"]
    score = (
        2.0 * (rating - 3)
        if rating is not None
        else 0.2 * min(row["views"], 5) + row["saved"] + 2.0 * row["selected"]
    )
    return Preference(score, bool(row["selected"] or rating is not None))


@dataclass(frozen=True)
class Snapshot:
    preferences: dict
    similarities: dict
    built_at: datetime
    build_ms: float
    events: int
    pairs: int


def build_snapshot(db, before=None):
    started = time.perf_counter()
    preferences = defaultdict(dict)
    events = 0
    for row in db.interactions.aggregate(preference_pipeline(before=before), allowDiskUse=True):
        preferences[row["_id"]["user"]][row["_id"]["model"]] = preference(row)
        events += row["events"]
    return snapshot_from_preferences(dict(preferences), events, started)


def snapshot_from_preferences(preferences, events=0, started=None):
    started = time.perf_counter() if started is None else started
    norms = defaultdict(float)
    dots = defaultdict(float)
    supports = defaultdict(int)
    for profile in preferences.values():
        # Joint dislikes do not establish a positive collaborative relationship.
        positive = sorted((mid, p.score) for mid, p in profile.items() if p.score > 0)
        for mid, score in positive:
            norms[mid] += score * score
        for i, (left, left_score) in enumerate(positive):
            for right, right_score in positive[i + 1 :]:
                key = (left, right)
                dots[key] += left_score * right_score
                supports[key] += 1
    similarities = defaultdict(list)
    for (left, right), dot in dots.items():
        support = supports[(left, right)]
        # Require two co-interested users, then shrink low-support similarities.
        if support < 2:
            continue
        cosine = dot / math.sqrt(norms[left] * norms[right])
        similarity = cosine * support / (support + SHRINKAGE)
        similarities[left].append((right, similarity))
        similarities[right].append((left, similarity))
    neighbors = {
        mid: tuple(sorted(values, key=lambda pair: (-pair[1], pair[0]))[:NEIGHBORS])
        for mid, values in similarities.items()
    }
    return Snapshot(
        preferences,
        neighbors,
        datetime.now(UTC),
        (time.perf_counter() - started) * 1000,
        events,
        sum(len(p) for p in preferences.values()),
    )


class RecommendationEngine:
    def __init__(self, ttl_seconds=60):
        self.ttl_seconds = ttl_seconds
        self._lock = RLock()
        self._snapshot = None
        self._expires = 0.0

    def invalidate(self):
        with self._lock:
            self._snapshot = None
            self._expires = 0.0

    def snapshot(self, db, force=False):
        # One builder per process; concurrent readers reuse the completed snapshot.
        with self._lock:
            hit = not force and self._snapshot is not None and time.monotonic() < self._expires
            if not hit:
                self._snapshot = build_snapshot(db)
                self._expires = time.monotonic() + self.ttl_seconds
            return self._snapshot, bool(hit)

    def status(self):
        with self._lock:
            snapshot = self._snapshot
            return {
                "algorithm": VERSION,
                "cache_ttl_seconds": self.ttl_seconds,
                "ready": snapshot is not None and time.monotonic() < self._expires,
                "built_at": snapshot.built_at if snapshot else None,
                "build_ms": round(snapshot.build_ms, 3) if snapshot else None,
                "source_events": snapshot.events if snapshot else None,
                "user_item_pairs": snapshot.pairs if snapshot else None,
            }


def eligible_query(device):
    return {
        "active": True,
        "signals": device["signal"],
        "requirements.reference_device": device["reference_device"],
        "requirements.memory_mb": {"$lte": device["memory_budget_mb"]},
        "requirements.latency_ms": {"$lte": device["max_latency_ms"]},
    }


def rank_candidates(snapshot, profile, candidates, limit):
    allowed = {doc["_id"]: doc for doc in candidates if not profile.get(doc["_id"], Preference(0, False)).exclude}
    totals = defaultdict(float)
    weights = defaultdict(float)
    evidence = defaultdict(list)
    for anchor, pref in profile.items():
        if not pref.score:
            continue
        for candidate, similarity in snapshot.similarities.get(anchor, ()):
            if candidate not in allowed or candidate == anchor:
                continue
            totals[candidate] += similarity * pref.score
            weights[candidate] += similarity
            if pref.score > 0:
                evidence[candidate].append((anchor, similarity))
    scores = {mid: total / (1.0 + weights[mid]) for mid, total in totals.items() if total > 0}
    order = sorted(scores, key=lambda mid: (-scores[mid], mid))[:limit]
    selected = [(allowed[mid], scores[mid], sorted(evidence[mid], key=lambda p: (-p[1], p[0]))[:3]) for mid in order]
    if not allowed:
        reason = "no_eligible_candidates"
    elif not profile:
        reason = "no_history"
    elif not any(p.score > 0 for p in profile.values()):
        reason = "no_positive_preferences"
    else:
        reason = "no_collaborative_neighbors" if not selected else "insufficient_collaborative_candidates"
    # Never fill with a model having a non-positive collaborative score: it may
    # be related to explicit dislikes. Truly unscored candidates may use baseline.
    fallback = sorted(
        (doc for mid, doc in allowed.items() if mid not in totals),
        key=lambda doc: (doc["requirements"]["latency_ms"], doc["requirements"]["memory_mb"], doc["_id"]),
    )[: max(0, limit - len(selected))]
    return selected, fallback, reason


def recommend(db, user, engine, limit=10):
    snapshot, cache_hit = engine.snapshot(db)
    # Read this user's preferences live, also when another worker wrote events.
    profile = {
        row["_id"]["model"]: preference(row)
        for row in db.interactions.aggregate(preference_pipeline(user["_id"]))
    }
    candidates = list(db.models.find(eligible_query(user["device"])))
    selected, fallback, reason = rank_candidates(snapshot, profile, candidates, limit)
    anchor_ids = {anchor for _, _, sources in selected for anchor, _ in sources}
    names = {doc["_id"]: doc["name"] for doc in db.models.find({"_id": {"$in": list(anchor_ids)}}, {"name": 1})}
    items = []
    for doc, score, sources in selected:
        item = public(doc)
        item["recommendation"] = {
            "strategy": "collaborative",
            "score": round(score, 6),
            "reason": "Пользователи с похожими предпочтениями интересовались этой моделью.",
            "based_on": [{"id": str(mid), "name": names.get(mid, "Модель из вашей истории"), "similarity": round(similarity, 6)} for mid, similarity in sources],
        }
        items.append(item)
    for doc in fallback:
        item = public(doc)
        item["recommendation"] = {
            "strategy": "fallback",
            "score": None,
            "reason": "Совместима с устройством; пока недостаточно совместных предпочтений.",
            "based_on": [],
        }
        items.append(item)
    return {
        "method": VERSION if selected else "constraint_fallback_v1",
        "device": user["device"],
        "fallback_reason": reason if fallback or not selected else None,
        "collaborative_count": len(selected),
        "fallback_count": len(fallback),
        "note": "Collaborative ranking uses synthetic behaviour; detector metrics are not measurements.",
        "snapshot": {"built_at": snapshot.built_at, "cache_hit": cache_hit, "max_age_seconds": engine.ttl_seconds},
        "items": items,
    }
