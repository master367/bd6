import argparse
import getpass
import hashlib
import json
import os
import random
import secrets
import statistics
from datetime import timedelta
from pathlib import Path
from uuid import NAMESPACE_URL, uuid5

from bson import ObjectId
from pymongo import UpdateOne

from app.config import ROOT, Settings
from app.db import CATEGORIES, SIGNALS, connect, initialize
from app.queries import public, utcnow
from app.schemas import Register
from app.security import hash_password, verify_password


def demo_id(value):
    return ObjectId(hashlib.sha256(value.encode()).hexdigest()[:24])


def seed(db, users=100, models=60, interactions=10000, seed_value=7, save_credentials=True):
    if not (2 <= users <= 10000 and 1 <= models <= 10000 and 0 <= interactions <= 2_000_000):
        raise ValueError("Use 2..10000 users, 1..10000 models, 0..2000000 interactions")
    initialize(db)
    rng = random.Random(seed_value)
    now = utcnow()
    password = os.getenv("DEMO_PASSWORD") or secrets.token_urlsafe(24)
    hashed = hash_password(password)
    user_ids = [demo_id(f"bd6-user-{i}") for i in range(users)]
    for i, uid in enumerate(user_ids):
        doc = {
            "email": "demo-admin@example.com" if i == 0 else f"demo{i:03d}@example.com",
            "display_name": "Demo Administrator" if i == 0 else f"Demo User {i:03d}",
            "password_hash": hashed,
            "role": "admin" if i == 0 else "user",
            "device": {
                "signal": SIGNALS[i % len(SIGNALS)],
                "memory_budget_mb": 128.0,
                "max_latency_ms": 100.0,
                "reference_device": "synthetic-edge-v1",
            },
            "created_at": now,
            "updated_at": now,
        }
        db.users.update_one({"_id": uid}, {"$setOnInsert": doc}, upsert=True)
    model_docs = []
    for i in range(models):
        signal = SIGNALS[i % len(SIGNALS)]
        doc = {
            "_id": demo_id(f"bd6-model-{i}"),
            "name": f"Demo {signal.upper()} Model {i:03d}",
            "slug": f"demo-{signal.replace('_', '-')}-{i:03d}",
            "version": "1.0",
            "description": (
                "Synthetic catalog entry for database demonstrations. No model has "
                "been trained; resource and quality values are simulated."
            ),
            "category": CATEGORIES[i % len(CATEGORIES)],
            "signals": [signal],
            "tags": ["synthetic", "edge", signal],
            "requirements": {
                "memory_mb": round(rng.uniform(8, 256), 2),
                "latency_ms": round(rng.uniform(5, 200), 2),
                "reference_device": "synthetic-edge-v1",
            },
            "evaluation": {
                "f1": round(rng.uniform(0.65, 0.96), 4),
                "dataset": "synthetic-drowsiness-v1",
                "protocol": "Simulated values; not an experimental evaluation",
            },
            "synthetic": True,
            "active": True,
            "created_at": now,
            "updated_at": now,
        }
        db.models.update_one({"_id": doc["_id"]}, {"$setOnInsert": doc}, upsert=True)
        # Use stored metadata for snapshots when a demo model has been edited.
        model_docs.append(db.models.find_one({"_id": doc["_id"]}))
    start = now - timedelta(days=29)
    batch = []
    for i in range(interactions):
        model = rng.choice(model_docs)
        event = rng.choices(["view", "save", "select", "rating"], weights=[65, 15, 10, 10])[0]
        doc = {
            "user_id": rng.choice(user_ids[1:]),
            "model_id": model["_id"],
            "type": event,
            "rating": rng.randint(1, 5) if event == "rating" else None,
            "request_id": str(uuid5(NAMESPACE_URL, f"bd6-demo/{seed_value}/{i}")),
            "model_snapshot": {k: model[k] for k in ("name", "slug", "version")},
            "created_at": start + timedelta(seconds=i * 29 * 86400 / max(interactions, 1)),
        }
        batch.append(
            UpdateOne(
                {"_id": demo_id(f"bd6-event-{seed_value}-{i}")}, {"$setOnInsert": doc}, upsert=True
            )
        )
        if len(batch) == 1000:
            db.interactions.bulk_write(batch, ordered=False)
            batch = []
    if batch:
        db.interactions.bulk_write(batch, ordered=False)
    admin = db.users.find_one({"_id": user_ids[0]})
    if save_credentials and verify_password(password, admin["password_hash"]):
        (ROOT / ".demo-credentials.json").write_text(
            json.dumps({"email": admin["email"], "password": password}), encoding="utf-8"
        )
        print("Demo credentials saved locally to .demo-credentials.json (gitignored).")
    counts = {name: db[name].count_documents({}) for name in ("users", "models", "interactions")}
    print(json.dumps(counts))
    return counts


def stages(value):
    result = set()
    if isinstance(value, dict):
        if isinstance(value.get("stage"), str):
            result.add(value["stage"])
        for child in value.values():
            result.update(stages(child))
    elif isinstance(value, list):
        for child in value:
            result.update(stages(child))
    return sorted(result)


def benchmark(db, output, repetitions=5):
    # Force both access paths on the same collection; never drop working indexes.
    user = db.users.find_one({"_id": demo_id("bd6-user-1")})
    if not user:
        raise ValueError("Run seed first")
    query = {"user_id": user["_id"]}
    runs = {}
    for label, hint in [("natural_scan", {"$natural": 1}), ("indexed", "user_recent")]:
        results = []
        for _ in range(repetitions):
            explain = db.command(
                "explain",
                {
                    "find": "interactions",
                    "filter": query,
                    "sort": {"created_at": -1, "_id": -1},
                    "limit": 20,
                    "hint": hint,
                },
                verbosity="executionStats",
            )
            stats = explain["executionStats"]
            results.append(
                {
                    "stages": stages(explain["queryPlanner"]["winningPlan"]),
                    "returned": stats["nReturned"],
                    "documents_examined": stats["totalDocsExamined"],
                    "keys_examined": stats["totalKeysExamined"],
                    "execution_ms": stats["executionTimeMillis"],
                }
            )
        runs[label] = {
            "runs": results,
            "median_execution_ms": statistics.median(r["execution_ms"] for r in results),
            "median_documents_examined": statistics.median(
                r["documents_examined"] for r in results
            ),
        }
    sort = [("created_at", -1), ("_id", -1)]
    baseline = list(db.interactions.find(query).sort(sort).limit(20).hint({"$natural": 1}))
    indexed = list(db.interactions.find(query).sort(sort).limit(20).hint("user_recent"))
    if [x["_id"] for x in baseline] != [x["_id"] for x in indexed]:
        raise RuntimeError("Indexed and baseline query results differ")
    result = {
        "generated_at": utcnow().isoformat(),
        "database": db.name,
        "server_version": db.client.server_info()["version"],
        "interaction_count": db.interactions.count_documents({}),
        "query": {"user_id": str(user["_id"]), "sort": sort, "limit": 20},
        "results_equal": True,
        "repetitions": repetitions,
        "results": runs,
        "index_sizes_bytes": db.command("collStats", "interactions")["indexSizes"],
        "caveats": [
            "Hints isolate access paths; this is not a cold-cache benchmark.",
            "Millisecond timings may be zero. Compare plans and examined documents.",
            "Indexes require storage and add write overhead.",
        ],
    }
    path = Path(output)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(json.dumps(result, indent=2))
    return result


def main():
    parser = argparse.ArgumentParser(description="Database setup, test data and query measurements")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("init-db")
    create = sub.add_parser("create-admin")
    create.add_argument("--email", required=True)
    seed_parser = sub.add_parser("seed")
    seed_parser.add_argument("--users", type=int, default=100)
    seed_parser.add_argument("--models", type=int, default=60)
    seed_parser.add_argument("--interactions", type=int, default=10000)
    seed_parser.add_argument("--seed", type=int, default=7)
    bench = sub.add_parser("benchmark")
    bench.add_argument("--output", default="output/benchmark.json")
    bench.add_argument("--repetitions", type=int, default=5, choices=range(1, 21))
    args = parser.parse_args()
    settings = Settings.from_env()
    with connect(settings.mongo_uri) as client:
        db = client[settings.database]
        db.command("ping")
        if args.command == "init-db":
            initialize(db)
            print("Collections, validators and indexes initialized.")
        elif args.command == "seed":
            seed(db, args.users, args.models, args.interactions, args.seed)
        elif args.command == "benchmark":
            benchmark(db, args.output, args.repetitions)
        elif args.command == "create-admin":
            body = Register(
                email=args.email,
                password=getpass.getpass("New admin password: "),
                display_name="Administrator",
            )
            initialize(db)
            now = utcnow()
            doc = {
                **body.model_dump(exclude={"password"}),
                "password_hash": hash_password(body.password),
                "role": "admin",
                "device": None,
                "created_at": now,
                "updated_at": now,
            }
            # Never silently promote or overwrite an existing account.
            db.users.insert_one(doc)
            print(json.dumps(public(doc)))


if __name__ == "__main__":
    main()
