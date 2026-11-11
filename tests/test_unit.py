import base64
import json
from datetime import UTC, datetime, timedelta

import jwt
import pytest
from bson import ObjectId
from fastapi import HTTPException
from pydantic import ValidationError

from app.queries import cursor_filter, cursor_for
from app.schemas import Interaction, Register
from app.security import AUDIENCE, ISSUER, create_token, token_subject

SECRET = "test-secret-that-is-at-least-48-characters-long-123"


@pytest.mark.parametrize(
    "payload",
    [
        {"type": "rating"},
        {"type": "rating", "rating": 0},
        {"type": "rating", "rating": True},
        {"type": "view", "rating": 4},
        {"type": "view", "user_id": "another-user"},
    ],
)
def test_invalid_interactions_rejected(payload):
    with pytest.raises(ValidationError):
        Interaction(model_id=str(ObjectId()), **payload)


def test_registration_cannot_assign_role_and_normalizes_email():
    body = {"email": "ALICE@EXAMPLE.COM", "password": "valid-password-123", "display_name": "Alice"}
    assert str(Register(**body).email) == "alice@example.com"
    with pytest.raises(ValidationError):
        Register(**body, role="admin")


def test_jwt_signature_expiry_and_algorithm_are_enforced():
    uid = str(ObjectId())
    assert token_subject(create_token(uid, SECRET), SECRET) == uid
    with pytest.raises(jwt.InvalidTokenError):
        token_subject(create_token(uid, "another-secret-at-least-32-characters"), SECRET)
    payload = {
        "sub": uid,
        "iat": datetime.now(UTC) - timedelta(hours=2),
        "exp": datetime.now(UTC) - timedelta(hours=1),
        "iss": ISSUER,
        "aud": AUDIENCE,
    }
    with pytest.raises(jwt.ExpiredSignatureError):
        token_subject(jwt.encode(payload, SECRET, algorithm="HS256"), SECRET)
    payload["exp"] = datetime.now(UTC) + timedelta(hours=1)
    with pytest.raises(jwt.InvalidAlgorithmError):
        token_subject(jwt.encode(payload, SECRET, algorithm="HS384"), SECRET)


def test_cursor_preserves_timestamp_and_id_tiebreaker():
    doc = {"_id": ObjectId(), "created_at": datetime(2026, 11, 1, tzinfo=UTC)}
    result = cursor_filter(cursor_for(doc))
    assert result["$or"][1] == {"created_at": doc["created_at"], "_id": {"$lt": doc["_id"]}}


@pytest.mark.parametrize(
    "cursor",
    [
        "garbage",
        "W10",
        "A" * 257,
        base64.urlsafe_b64encode(
            json.dumps({"time": "2026-11-01T00:00:00+00:00", "id": "invalid-id"}).encode()
        ).decode(),
    ],
)
def test_bad_cursors_are_client_errors(cursor):
    with pytest.raises(HTTPException) as error:
        cursor_filter(cursor)
    assert error.value.status_code == 422
