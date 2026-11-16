"""Real localhost HTTP benchmark on isolated, automatically cleaned MongoDB databases.

Compares the same item-CF algorithm with per-request rebuild versus a reusable
snapshot. No Docker, application database writes, or production index removal.
"""

import argparse
import csv
import json
import os
import platform
import secrets
import socket
import statistics
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from pathlib import Path
from uuid import uuid4

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.cf_data import DEMO_EMAILS, seed_cf  # noqa: E402
from app.config import ROOT, Settings  # noqa: E402
from app.db import connect  # noqa: E402
from app.queries import utcnow  # noqa: E402
from app.recommender import preference_pipeline  # noqa: E402
from app.security import create_token  # noqa: E402


def percentile(values, fraction):
    values = sorted(values)
    position = (len(values) - 1) * fraction
    low = int(position)
    high = min(low + 1, len(values) - 1)
    return values[low] + (values[high] - values[low]) * (position - low)


def summary(values, elapsed):
    return {"requests": len(values), "p50_ms": round(statistics.median(values), 3), "p95_ms": round(percentile(values, 0.95), 3), "throughput_rps": round(len(values) / elapsed, 3), "samples_ms": [round(v, 3) for v in values]}


@contextmanager
def local_server(settings, database, ttl, log_path):
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    env = {**os.environ, "MONGODB_URI": settings.mongo_uri, "MONGODB_DB": database, "JWT_SECRET": settings.jwt_secret, "RECOMMENDATION_CACHE_SECONDS": str(ttl)}
    with log_path.open("w", encoding="utf-8") as log:
        process = subprocess.Popen([sys.executable, "-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", str(port), "--no-access-log", "--log-level", "warning"], cwd=ROOT, env=env, stdout=log, stderr=subprocess.STDOUT, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        try:
            with httpx.Client(base_url=f"http://127.0.0.1:{port}", timeout=180, trust_env=False) as client:
                deadline = time.monotonic() + 30
                while True:
                    if process.poll() is not None:
                        raise RuntimeError(f"Benchmark server exited; see {log_path}")
                    try:
                        if client.get("/health").status_code == 200:
                            break
                    except httpx.RequestError:
                        pass
                    if time.monotonic() > deadline:
                        raise RuntimeError(f"Benchmark server did not start; see {log_path}")
                    time.sleep(0.1)
                yield client
        finally:
            process.terminate()
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=10)


def signature(body):
    return [(item["id"], item["recommendation"]["score"], item["recommendation"]["strategy"]) for item in body["items"]]


def measure(client, token, repetitions, parallel=False):
    headers = {"Authorization": f"Bearer {token}"}

    def request(_=None):
        started = time.perf_counter()
        response = client.get("/recommendations?limit=5", headers=headers)
        response.raise_for_status()
        body = response.json()
        if body["method"] != "item_cf_v1":
            raise RuntimeError("Benchmark must exercise collaborative recommendations")
        return (time.perf_counter() - started) * 1000, signature(body), body["snapshot"]["cache_hit"]

    request()  # Explicit, excluded warm-up.
    started = time.perf_counter()
    if parallel:
        with ThreadPoolExecutor(max_workers=8) as pool:
            results = list(pool.map(request, range(repetitions)))
    else:
        results = [request() for _ in range(repetitions)]
    elapsed = time.perf_counter() - started
    if any(result[1] != results[0][1] for result in results):
        raise RuntimeError("Recommendation output changed during measurement")
    result = summary([row[0] for row in results], elapsed)
    result["cache_hits"] = sum(row[2] for row in results)
    return result, results[0][1]


def profile_query_experiment(db, uid):
    plans = {}
    outputs = []
    for label, hint in [("scan", {"$natural": 1}), ("indexed", "user_model_preferences")]:
        pipeline = preference_pipeline(uid)
        outputs.append(sorted(list(db.interactions.aggregate(pipeline, hint=hint)), key=lambda row: row["_id"]["model"]))
        plans[label] = db.command("explain", {"aggregate": "interactions", "pipeline": pipeline, "cursor": {}, "hint": hint}, verbosity="executionStats")
    if outputs[0] != outputs[1]:
        raise RuntimeError("Indexed aggregation differs from natural scan")
    return {"results_equal": True, "plans": plans}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sizes", nargs="+", type=int, default=[10000, 100000, 1000000])
    parser.add_argument("--repetitions", type=int, default=7)
    parser.add_argument("--output", type=Path, default=ROOT / "output" / "performance")
    args = parser.parse_args()
    if args.repetitions < 3 or any(size < 1000 or size > 2_000_000 for size in args.sizes):
        parser.error("Use at least 3 repetitions and sizes in 1000..2000000")
    args.output.mkdir(parents=True, exist_ok=True)
    settings = Settings.from_env()
    # The benchmark uses its own secret and demo password, never exports either.
    settings = Settings(settings.mongo_uri, settings.database, secrets.token_urlsafe(48))
    os.environ["DEMO_PASSWORD"] = secrets.token_urlsafe(24)
    report = {"generated_at": utcnow().isoformat(), "python": platform.python_version(), "os": platform.platform(), "transport": "real HTTP over localhost, one Uvicorn process", "algorithm": "item_cf_v1", "warmup_requests": 1, "repetitions": args.repetitions, "scenarios": [], "caveats": ["Synthetic sparse preference cohorts; no claims about real user satisfaction.", "Rebuild and cached modes use the same algorithm, data and recommendation query.", "Warm cache, no writes during sampling. A mutation invalidates the snapshot; the following request pays rebuild cost.", "Sequential samples use one account. The separate concurrency sample uses eight threads and that same account.", "Small samples describe this local run and are not a production capacity estimate."]}
    with connect(settings.mongo_uri) as mongo:
        report["mongodb"] = mongo.server_info()["version"]
        for size in args.sizes:
            name = f"edge_catalog_bench_{uuid4().hex}"
            db = mongo[name]
            try:
                users, models = (120, 60) if size <= 10000 else (1000, 120) if size <= 100000 else (5000, 240)
                print(f"Preparing {size:,} events, {users} users, {models} models in isolated database", flush=True)
                started = time.perf_counter()
                seed_cf(db, users, models, size, save_credentials=False)
                seed_ms = (time.perf_counter() - started) * 1000
                user = db.users.find_one({"email": DEMO_EMAILS[0]})
                token = create_token(str(user["_id"]), settings.jwt_secret)
                admin = db.users.find_one({"email": DEMO_EMAILS[2]})
                db.users.update_one({"_id": admin["_id"]}, {"$set": {"role": "admin"}})
                admin_token = create_token(str(admin["_id"]), settings.jwt_secret)
                scenario = {"events": size, "users": users, "models": models, "seed_ms": round(seed_ms, 3)}
                signatures = []
                for mode, ttl in [("rebuild_each_request", 0), ("cached_snapshot", 3600)]:
                    print(f"Measuring {mode} at {size:,} events", flush=True)
                    with local_server(settings, name, ttl, args.output / f"server-{size}-{mode}.log") as client:
                        scenario[mode], sig = measure(client, token, args.repetitions)
                        signatures.append(sig)
                        response = client.get("/recommendations/status", headers={"Authorization": f"Bearer {admin_token}"})
                        response.raise_for_status()
                        scenario[mode]["snapshot"] = response.json()
                        if ttl:
                            scenario["cached_concurrency_8"], _ = measure(client, token, 32, parallel=True)
                scenario["results_equal"] = signatures[0] == signatures[1]
                if not scenario["results_equal"]:
                    raise RuntimeError("Optimization changed the recommendation results")
                plans = profile_query_experiment(db, user["_id"])
                (args.output / f"query-plans-{size}.json").write_text(json.dumps(plans, indent=2, default=str), encoding="utf-8")
                scenario["query_results_equal"] = plans["results_equal"]
                scenario["interaction_index_bytes"] = db.command("collStats", "interactions")["indexSizes"]
                report["scenarios"].append(scenario)
                (args.output / "recommendations.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
                print(json.dumps({"events": size, "rebuild_p50_ms": scenario["rebuild_each_request"]["p50_ms"], "cached_p50_ms": scenario["cached_snapshot"]["p50_ms"], "equal": scenario["results_equal"]}), flush=True)
            finally:
                # Only this loop's newly generated database is eligible for deletion.
                if not name.startswith("edge_catalog_bench_") or len(name) != 51:
                    raise RuntimeError("Refusing to remove unexpected database")
                mongo.drop_database(name)
    with (args.output / "recommendations.csv").open("w", newline="", encoding="utf-8") as stream:
        writer = csv.writer(stream)
        writer.writerow(["events", "users", "models", "mode", "p50_ms", "p95_ms", "throughput_rps"])
        for scenario in report["scenarios"]:
            for mode in ["rebuild_each_request", "cached_snapshot", "cached_concurrency_8"]:
                result = scenario[mode]
                writer.writerow([scenario["events"], scenario["users"], scenario["models"], mode, result["p50_ms"], result["p95_ms"], result["throughput_rps"]])
    print(f"Saved performance data to {args.output}", flush=True)


if __name__ == "__main__":
    main()
