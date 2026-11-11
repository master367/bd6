"""Export real API responses, MongoDB schema/indexes and the latest test summary.

Run from the project root after seeding, starting the API and running pytest with JUnit output.
No passwords, hashes or bearer tokens are included in the generated evidence.
"""

import json
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.config import ROOT, Settings  # noqa: E402
from app.db import connect  # noqa: E402


def main():
    output = ROOT / "output"
    output.mkdir(exist_ok=True)
    docs = ROOT / "docs"
    docs.mkdir(exist_ok=True)
    with httpx.Client(base_url="http://127.0.0.1:8000", timeout=20, trust_env=False) as api:
        schema = api.get("/openapi.json")
        schema.raise_for_status()
        schema_json = json.dumps(schema.json(), indent=2)
        (docs / "openapi.json").write_text(schema_json, encoding="utf-8")
        (output / "openapi.json").write_text(schema_json, encoding="utf-8")
        credentials = json.loads((ROOT / ".demo-credentials.json").read_text(encoding="utf-8"))
        token = api.post(
            "/auth/token",
            data={"username": credentials["email"], "password": credentials["password"]},
        )
        token.raise_for_status()
        api.headers["Authorization"] = f"Bearer {token.json()['access_token']}"
        responses = {}
        for path in (
            "/health",
            "/models?signal=eeg&max_memory_mb=128&limit=1",
            "/analytics/popular?limit=3",
            "/analytics/ratings",
            "/analytics/summary",
            "/recommendations?limit=3",
        ):
            result = api.get(path)
            result.raise_for_status()
            responses[path] = result.json()
        model_id = responses["/models?signal=eeg&max_memory_mb=128&limit=1"]["items"][0]["id"]
        path = f"/models/{model_id}/stats?type=view"
        result = api.get(path)
        result.raise_for_status()
        responses[path] = result.json()
        (output / "api-responses.json").write_text(
            json.dumps(responses, indent=2), encoding="utf-8"
        )
    settings = Settings.from_env()
    with connect(settings.mongo_uri) as client:
        db = client[settings.database]
        snapshot = {
            "database": db.name,
            "server_version": client.server_info()["version"],
            "collections": {
                name: {
                    "count": db[name].count_documents({}),
                    "options": db[name].options(),
                    "indexes": list(db[name].list_indexes()),
                }
                for name in ("users", "models", "interactions")
            },
        }
        (output / "database-schema.json").write_text(
            json.dumps(snapshot, indent=2, default=str), encoding="utf-8"
        )
    test_path = output / "test-results.xml"
    if test_path.exists():
        suites = list(ET.parse(test_path).getroot().iter("testsuite"))
        summary = {
            key: sum(int(s.get(key, "0")) for s in suites)
            for key in ("tests", "failures", "errors", "skipped")
        }
        (output / "test-summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
        print(json.dumps(summary))
    print("Exported OpenAPI, real API responses, MongoDB validators/indexes and test summary.")


if __name__ == "__main__":
    main()
