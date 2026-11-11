from datetime import UTC, datetime, timedelta

import jwt
from pwdlib import PasswordHash

password_hash = PasswordHash.recommended()
ISSUER = "edge-catalog"
AUDIENCE = "edge-catalog-api"


def hash_password(password: str) -> str:
    return password_hash.hash(password)


def verify_password(password: str, hashed: str) -> bool:
    try:
        return password_hash.verify(password, hashed)
    except (ValueError, TypeError):
        return False


def create_token(user_id: str, secret: str) -> str:
    now = datetime.now(UTC)
    return jwt.encode(
        {
            "sub": user_id,
            "iat": now,
            "exp": now + timedelta(minutes=30),
            "iss": ISSUER,
            "aud": AUDIENCE,
        },
        secret,
        algorithm="HS256",
    )


def token_subject(token: str, secret: str) -> str:
    claims = jwt.decode(
        token,
        secret,
        algorithms=["HS256"],
        issuer=ISSUER,
        audience=AUDIENCE,
        options={"require": ["sub", "exp", "iat", "iss", "aud"]},
    )
    return claims["sub"]
