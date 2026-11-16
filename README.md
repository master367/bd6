# Edge Drowsiness Model Catalog

A web application for the Advanced Databases final project. It helps users explore and compare drowsiness detection models and receive recommendations based on their preferences and device limits.

Built with Python, FastAPI, MongoDB, and a plain HTML/CSS/JavaScript frontend. The catalog uses synthetic model data and performance values for demonstration.

## Features

- User registration and login with JWT authentication and Argon2id password hashing.
- Searchable model catalog with signal, category, memory, and latency filters.
- Administrator tools to create, edit, and archive models.
- User profiles, saved models, ratings, and interaction history.
- Item-based collaborative filtering with device constraints, cached similarities, and a fallback for new users.
- MongoDB schema validation, indexes, aggregation analytics, and cursor pagination.

## Local setup

Requirements: Python 3.12+ and a running MongoDB 8.x instance. Run these commands from the project root in Windows PowerShell:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.lock
.\.venv\Scripts\python.exe scripts/init_env.py
.\.venv\Scripts\python.exe -m app.manage seed-cf
.\.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

The setup script creates `.env` with random local secrets and preserves an existing file. If needed, update `MONGODB_URI` in `.env` before seeding. The default database is `edge_catalog`.

`seed-cf` initializes the database and adds 120 users, 60 models, and 12,000 interactions. Repeating it with the same parameters preserves existing records. Seed before starting the API, or restart the API afterwards to refresh recommendations.

- [Web application](http://127.0.0.1:8000/)
- [Swagger API documentation](http://127.0.0.1:8000/docs)
- [Health check](http://127.0.0.1:8000/health)

FastAPI serves the frontend directly. No separate frontend server is required.

## Demo

Sign in using one of the seeded accounts. Their shared password is stored locally in `.cf-demo-credentials.json`.

| Account | Example |
| --- | --- |
| `cf-alice@example.com` | Preference for Compact models |
| `cf-boris@example.com` | Preference for Temporal models |
| `cf-new@example.com` | New user without interaction history |

The accounts share the same device settings, allowing their recommendations to be compared. For a new account, configure the device profile using `synthetic-edge-v1` as the reference device.

With the API running, compare the demo accounts from another terminal:

```powershell
.\.venv\Scripts\python.exe -m app.cli cf-demo
```

To create an administrator account:

```powershell
.\.venv\Scripts\python.exe -m app.manage create-admin --email admin@example.com
```

The command prompts for a password. Administrators can manage models through the web interface.

## Docker setup

Requires Docker Compose and a local `.env` file. If needed, create it first with `python scripts/init_env.py`.

```powershell
docker compose up -d --build --wait
docker compose exec api python -m app.manage seed-cf
docker compose restart api
```

Open the [web application](http://127.0.0.1:8001/) or [Swagger UI](http://127.0.0.1:8001/docs). MongoDB is available at `mongodb://127.0.0.1:27018/`. The demo credentials file is inside the API container; view it with `docker compose exec api cat .cf-demo-credentials.json`.

Stop the services with `docker compose stop`. Database records persist in a Docker volume.

## Tests and benchmarks

The locked dependencies include pytest and Ruff. Integration tests require MongoDB and use separate temporary databases.

```powershell
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe -m ruff check app tests scripts
.\.venv\Scripts\python.exe -m app.manage benchmark
.\.venv\Scripts\python.exe scripts/benchmark_recommendations.py
.\.venv\Scripts\python.exe scripts/evaluate_recommendations.py
```

To run tests without MongoDB, use `.\.venv\Scripts\python.exe -m pytest -q -m "not integration"`. For Docker-based tests, use `docker compose run --rm tests` after starting the stack.

Benchmarks and evaluation results are generated in `output/`. Recommendation evaluation uses synthetic data and does not measure real-world recommendation quality.

## Project structure

| Path | Contents |
| --- | --- |
| `app/` | REST API, database schema, recommendation engine, CLI, and web interface |
| `scripts/` | Environment setup, benchmarks, and evaluation tools |
| `tests/` | Unit and integration tests |
| `examples/` | Example JSON request bodies |
| `compose.yaml` | Docker services for the API, MongoDB, and tests |
