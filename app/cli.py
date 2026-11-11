import argparse
import getpass
import json
import os
from pathlib import Path
from uuid import uuid4

import httpx

from app.config import ROOT

SESSION = ROOT / ".cli-session.json"


def print_json(value):
    print(json.dumps(value, indent=2, ensure_ascii=False))


def login(client, email, password):
    response = client.post("/auth/token", data={"username": email, "password": password})
    response.raise_for_status()
    token = response.json()["access_token"]
    SESSION.write_text(json.dumps({"token": token}), encoding="utf-8")
    try:
        os.chmod(SESSION, 0o600)
    except OSError:
        pass
    client.headers["Authorization"] = f"Bearer {token}"


def main():
    parser = argparse.ArgumentParser(description="CLI client for the Edge Catalog REST API")
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    sub = parser.add_subparsers(dest="command", required=True)
    auth = sub.add_parser("login")
    auth.add_argument("--email", required=True)
    catalog = sub.add_parser("catalog")
    catalog.add_argument("--signal")
    catalog.add_argument("--category")
    catalog.add_argument("--q")
    for name in ("me", "history", "recommend", "demo", "logout"):
        sub.add_parser(name)
    raw = sub.add_parser("request")
    raw.add_argument("method", choices=["GET", "POST", "PUT", "DELETE"])
    raw.add_argument("path")
    raw.add_argument("--json-file")
    args = parser.parse_args()
    if args.command == "logout":
        SESSION.unlink(missing_ok=True)
        print("Local session removed.")
        return
    with httpx.Client(base_url=args.base_url, timeout=20, trust_env=False) as client:
        try:
            if SESSION.exists():
                token = json.loads(SESSION.read_text(encoding="utf-8"))["token"]
                client.headers["Authorization"] = f"Bearer {token}"
            if args.command == "login":
                login(client, args.email, getpass.getpass("Password: "))
                print("Signed in; token saved locally for 30 minutes.")
                return
            if args.command == "demo":
                credentials = json.loads(
                    (ROOT / ".demo-credentials.json").read_text(encoding="utf-8")
                )
                login(client, credentials["email"], credentials["password"])
                for path in ["/health", "/users/me", "/models?limit=3"]:
                    response = client.get(path)
                    response.raise_for_status()
                    print(path)
                    print_json(response.json())
                models = client.get("/models?limit=1")
                models.raise_for_status()
                items = models.json()["items"]
                if not items:
                    raise ValueError("Catalog is empty; run app.manage seed first")
                event = client.post(
                    "/interactions",
                    json={
                        "model_id": items[0]["id"],
                        "type": "view",
                        "request_id": str(uuid4()),
                    },
                )
                event.raise_for_status()
                print("Recorded one real demo view")
                print_json(event.json())
                for path in [
                    "/users/me/history?limit=3",
                    "/recommendations?limit=3",
                    "/analytics/popular?limit=3",
                    "/analytics/summary",
                ]:
                    response = client.get(path)
                    response.raise_for_status()
                    print(path)
                    print_json(response.json())
                return
            if args.command == "catalog":
                params = {
                    key: getattr(args, key)
                    for key in ("signal", "category", "q")
                    if getattr(args, key)
                }
                response = client.get("/models", params=params)
            elif args.command == "request":
                if not args.path.startswith("/") or args.path.startswith("//"):
                    parser.error("Use a relative API path starting with one slash")
                body = (
                    json.loads(Path(args.json_file).read_text(encoding="utf-8"))
                    if args.json_file
                    else None
                )
                response = client.request(args.method, args.path, json=body)
            else:
                path = {
                    "me": "/users/me",
                    "history": "/users/me/history",
                    "recommend": "/recommendations",
                }[args.command]
                response = client.get(path)
            response.raise_for_status()
            print_json(response.json() if response.content else {"status": response.status_code})
        except httpx.HTTPStatusError as exc:
            print(f"HTTP {exc.response.status_code}: {exc.response.text}")
            raise SystemExit(1) from None
        except (httpx.RequestError, OSError, KeyError, ValueError) as exc:
            print(f"CLI error: {exc}")
            raise SystemExit(1) from None


if __name__ == "__main__":
    main()
