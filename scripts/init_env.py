"""Create local development secrets without overwriting an existing environment file."""

import secrets
from pathlib import Path

path = Path(__file__).resolve().parents[1] / ".env"
if path.exists():
    print("Existing .env preserved.")
else:
    with path.open("x", encoding="utf-8") as output:
        output.write("MONGODB_URI=mongodb://127.0.0.1:27017/\nMONGODB_DB=edge_catalog\n")
        output.write(f"JWT_SECRET={secrets.token_hex(32)}\n")
        output.write(f"DEMO_PASSWORD={secrets.token_urlsafe(24)}\n")
    print("Created local .env with random development secrets.")
