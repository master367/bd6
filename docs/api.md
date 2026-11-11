# API reference

Base URL: `http://127.0.0.1:8000`. Interactive documentation: `/docs`.
Machine-readable OpenAPI schema: `/openapi.json`.

## Authentication

Register using JSON:

```http
POST /auth/register
Content-Type: application/json

{"email":"researcher@example.com","password":"choose-a-long-password","display_name":"Researcher"}
```

The response is a user document with `id`, `email`, `display_name`, `role`, `device`,
`created_at`, and `updated_at`; it contains no password or password hash.
The server assigns `role=user`. Emails are normalized to lowercase.

Log in with `application/x-www-form-urlencoded`, not JSON:

```http
POST /auth/token
Content-Type: application/x-www-form-urlencoded

username=researcher%40example.com&password=choose-a-long-password
```

Response: `access_token`, `token_type=bearer`, `expires_in=1800`.
Use `Authorization: Bearer <access_token>` for authenticated endpoints.
Role is read from the database per request, not trusted from a client-supplied token role.

## Endpoints

| Method | Path | Access | Purpose |
|---|---|---|---|
| GET | `/health` | Public | Verify MongoDB connectivity |
| POST | `/auth/register` | Public | Create a user; 201 |
| POST | `/auth/token` | Public | Obtain a 30-minute bearer token |
| GET | `/users/me` | User | Own profile |
| PUT | `/users/me` | User | Replace display name and device profile |
| GET | `/models` | Public | Search and paginate the active catalog |
| POST | `/models` | Admin | Create a model version; 201 |
| GET | `/models/{id}` | Public | Active model details |
| PUT | `/models/{id}` | Admin | Replace editable catalog fields |
| DELETE | `/models/{id}` | Admin | Archive the model; 204, empty body |
| GET | `/models/{id}/stats` | User | Count events by type for this model |
| POST | `/interactions` | User | Record event; 201, or 200 for a matching retry |
| GET | `/users/me/history` | User | Own event history |
| GET | `/recommendations` | User | Constraint-based baseline selection |
| GET | `/analytics/popular` | User | Rank active models by event count |
| GET | `/analytics/ratings` | User | Average latest rating per user/model pair |
| GET | `/analytics/summary` | Admin | Event counts by type and UTC date |

## Catalog

`POST` and `PUT /models` accept the complete structure in `../examples/model.json`.
`active`, timestamps and identifiers are server-managed; sending unknown fields returns 422.
PUT is a full replacement of editable fields, not a partial PATCH. Existing history snapshots
are intentionally unchanged when the item is edited.

`GET /models` supports:

| Parameter | Meaning |
|---|---|
| `q` | Up to 100 characters; MongoDB word-based text search across name, description, tags |
| `category` | `classical_ml`, `deep_learning`, or `hybrid` |
| `signal` | `eeg`, `ecg`, `eog`, `imu`, or `video_features` |
| `max_memory_mb` | Positive upper bound on stored memory requirement |
| `max_latency_ms` | Positive upper bound on stored latency |
| `reference_device` | Exact reference-device identifier |
| `limit` | Page size 1..100; default 20 |
| `cursor` | Opaque cursor from the previous page, up to 256 characters |

Example: `/models?signal=eeg&max_memory_mb=128&category=deep_learning&limit=10`.
Text search is word-based, not a substring or fuzzy search; stemming uses English.
Results are ordered by `created_at DESC, _id DESC`, including searches with `q`.

Paginated catalog and history responses:

```json
{"items": [], "next_cursor": null}
```

When `next_cursor` is non-null, send it as `cursor` with the same filters to continue.
Identifiers are hexadecimal strings in JSON; timestamps use ISO 8601 UTC.

## Interaction contract

```json
{
  "model_id": "0123456789abcdef01234567",
  "type": "rating",
  "rating": 4,
  "request_id": "3f917f9d-5ac6-4a43-81bd-2f5e37b56d6b"
}
```

Types: `view`, `save`, `select`, `rating`. The integer `rating` is required only for `rating`;
omit it or pass `null` for other types. `request_id` can be omitted for a new event, in which
case the server generates a UUID. To retry safely, the client must reuse the same request_id.

The server determines `user_id` and `created_at` and stores a model snapshot. A duplicate
request_id for the same user and identical payload returns the original event with status 200.
A changed payload with the same key returns 409. New events for archived models return 404;
retries of existing events remain valid. Events are append-only. A `save` is a historical action,
not a toggle; favorites management is outside this version's API.

History supports `limit` and `cursor`. It always uses the authenticated user's identifier;
the caller cannot specify another user. Archiving a catalog item preserves its history.

## Profiles, recommendations and analytics

Profile replacement: see `../examples/profile.json`. `device=null` clears the device profile.
Without a profile, `/recommendations` returns 400. With one, it matches signal and exact
reference device, filters memory and latency, and orders by latency, memory, then `_id`.
The response has `method`, `device`, `note`, and `items`; this is a transparent baseline.

`/analytics/popular`: `days=1..3650` (default 30), `limit=1..100` (default 10).
The response has `since` and `items`. An item has `model_id`, `name`, `events`, `views`,
and `selections`. Re-ratings are distinct events for popularity, but only the latest rating
per user/model contributes to `/analytics/ratings`. Ratings return `average_rating` and
`voters`, up to 100 active models. No individual user histories are exposed by analytics.

`/models/{id}/stats`: `days=1..3650` and optional `type`; returns counts by event type.
`/analytics/summary`: `days=1..3650`; returns `timezone=UTC`, `by_type`, and `by_day`.
Each row in these count groups uses `_id` as the group key and `events` as the count.

## Errors

| Status | Meaning |
|---|---|
| 400 | Device profile needed for baseline selection |
| 401 | Missing, invalid or expired token, or incorrect credentials |
| 403 | Administrator permission required |
| 404 | No active model with the given identifier |
| 409 | Duplicate email/model version, or conflicting idempotency key |
| 422 | Invalid request body, identifier, cursor, filter or query bound |
| 503 | Database operation unavailable |

Application errors return `{"detail": "message"}`. Validation errors use FastAPI's detail
array with field locations and messages. Database responses do not expose connection strings.
