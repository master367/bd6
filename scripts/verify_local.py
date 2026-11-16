"""Read-only HTTP smoke checks; exports evidence without passwords or bearer tokens."""

import argparse
import json
import sys
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.config import ROOT  # noqa: E402
from app.queries import utcnow  # noqa: E402


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    args = parser.parse_args()
    credentials = json.loads((ROOT / ".cf-demo-credentials.json").read_text(encoding="utf-8"))
    evidence = {"generated_at": utcnow().isoformat(), "base_url": args.base_url, "accounts": [], "visual_browser_check": "not covered by these HTTP smoke checks"}
    with httpx.Client(base_url=args.base_url, timeout=30, trust_env=False) as client:
        for path in ["/health", "/", "/static/app.js", "/static/styles.css", "/docs"]:
            result = client.get(path)
            result.raise_for_status()
        assert client.get("/recommendations").status_code == 401
        schema = client.get("/openapi.json")
        schema.raise_for_status()
        (ROOT / "docs" / "openapi.json").write_text(json.dumps(schema.json(), indent=2), encoding="utf-8")
        devices = []
        recommendations = []
        for email in credentials["accounts"]:
            auth = client.post("/auth/token", data={"username": email, "password": credentials["password"]})
            auth.raise_for_status()
            headers = {"Authorization": f"Bearer {auth.json()['access_token']}"}
            response = client.get("/recommendations?limit=5", headers=headers)
            response.raise_for_status()
            data = response.json()
            devices.append(data["device"])
            for item in data["items"]:
                d = data["device"]
                assert d["signal"] in item["signals"]
                assert d["reference_device"] == item["requirements"]["reference_device"]
                assert item["requirements"]["memory_mb"] <= d["memory_budget_mb"]
                assert item["requirements"]["latency_ms"] <= d["max_latency_ms"]
            assert client.get("/recommendations/status", headers=headers).status_code == 403
            assert client.post("/recommendations/rebuild", headers=headers).status_code == 403
            history = client.get("/users/me/history?limit=3", headers=headers)
            history.raise_for_status()
            for path in ["/analytics/popular?limit=3", "/analytics/ratings"]:
                client.get(path, headers=headers).raise_for_status()
            recommendations.append([item["id"] for item in data["items"]])
            evidence["accounts"].append({"account": email, "method": data["method"], "fallback_reason": data["fallback_reason"], "collaborative_count": data["collaborative_count"], "device": data["device"], "recommendations": [{"id": item["id"], "name": item["name"], "strategy": item["recommendation"]["strategy"], "score": item["recommendation"]["score"]} for item in data["items"]]})
        assert devices[0] == devices[1] == devices[2]
        assert recommendations[0] != recommendations[1]
        assert all(row["method"] == "item_cf_v1" for row in evidence["accounts"][:2])
        assert evidence["accounts"][2]["fallback_reason"] == "no_history"
        evidence["checks"] = {"same_devices_different_recommendations": True, "cold_start": True, "device_constraints": True, "admin_operations_private": True, "static_assets_and_swagger": True}
    path = ROOT / "output" / "local-verification.json"
    path.parent.mkdir(exist_ok=True)
    path.write_text(json.dumps(evidence, ensure_ascii=False, indent=2), encoding="utf-8")
    print("Verified real local HTTP workflows; saved output/local-verification.json (no credentials).")


if __name__ == "__main__":
    main()
