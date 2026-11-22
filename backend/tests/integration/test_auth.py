from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
import importlib.util
from pathlib import Path

import pytest
import sqlalchemy as sa
from sqlalchemy import inspect, select, text
from starlette.requests import Request

from app.integrations import email as email_module
from app.models import PasswordResetToken, RefreshToken
from app.core.security import hash_password_reset_token
from app.core.timeutil import utcnow
from app.core.deps import client_ip
from tests.integration.helpers import API, PASSWORD, auth, login, register


def load_migration_0004():
    spec = importlib.util.spec_from_file_location(
        "migration_0004_password_reset",
        Path("alembic/versions/0004_password_reset_tokens.py"),
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_register_login_and_me(client):
    reg = register(client, "Lakshmi", "9000000001", language="te")
    assert reg["user"]["role"] == "PATIENT" and reg["patient_id"]
    me = client.get(f"{API}/me", headers=reg["headers"]).json()["data"]
    assert me["phone"] == "9000000001" and me["preferred_language"] == "te"
    again = login(client, "+91 90000 00001")  # same number written differently
    assert again["user"]["id"] == reg["user"]["id"]


def test_duplicate_identifier_is_rejected(client):
    register(client, "A", "a@test.demo")
    r = client.post(f"{API}/auth/register", json={"full_name": "B", "identifier": "A@test.demo", "password": PASSWORD,
                                                  "role": "PATIENT"})
    assert r.status_code == 409 and r.json()["error"]["code"] == "IDENTIFIER_TAKEN"


def test_staff_roles_cannot_self_register(client):
    for role in ("DOCTOR", "HOSPITAL_ADMIN", "SUPER_ADMIN"):
        r = client.post(f"{API}/auth/register", json={"full_name": "X", "identifier": f"{role}@test.demo",
                                                      "password": PASSWORD, "role": role})
        assert r.status_code == 400


def test_wrong_password_and_unknown_user_look_the_same(client):
    register(client, "A", "a@test.demo")
    wrong = client.post(f"{API}/auth/login", json={"identifier": "a@test.demo", "password": "Wrong@12345"})
    unknown = client.post(f"{API}/auth/login", json={"identifier": "nobody@test.demo", "password": "Wrong@12345"})
    assert wrong.status_code == unknown.status_code == 401
    assert wrong.json()["error"] == unknown.json()["error"]


def test_login_is_rate_limited(client):
    register(client, "A", "a@test.demo")
    codes = [client.post(f"{API}/auth/login", json={"identifier": "a@test.demo", "password": "Wrong@12345"}).status_code
             for _ in range(7)]
    assert codes[:5] == [401] * 5 and codes[5:] == [429, 429]
    # The limit is per identifier: another account can still sign in.
    register(client, "B", "b@test.demo")
    assert login(client, "b@test.demo")["user"]["full_name"] == "B"


def test_protected_route_needs_a_valid_token(client):
    assert client.get(f"{API}/me").status_code == 401
    assert client.get(f"{API}/me", headers=auth("not-a-token")).status_code == 401


def test_refresh_rotates_and_detects_reuse(client):
    register(client, "A", "a@test.demo")
    header = {"X-Requested-With": "carebridge"}
    old_cookie = client.cookies.get("cb_refresh")
    assert old_cookie
    assert client.post(f"{API}/auth/refresh").status_code == 403  # custom header is required
    first = client.post(f"{API}/auth/refresh", headers=header)
    assert first.status_code == 200 and first.json()["data"]["access_token"]
    new_cookie = client.cookies.get("cb_refresh")
    assert new_cookie and new_cookie != old_cookie
    # Replaying the old token ends the whole session family.
    client.cookies.clear()
    client.cookies.set("cb_refresh", old_cookie)
    assert client.post(f"{API}/auth/refresh", headers=header).status_code == 401
    client.cookies.clear()
    client.cookies.set("cb_refresh", new_cookie)
    assert client.post(f"{API}/auth/refresh", headers=header).status_code == 401


def test_logout_revokes_refresh_token(client):
    register(client, "A", "a@test.demo")
    cookie = client.cookies.get("cb_refresh")
    assert client.post(f"{API}/auth/logout").status_code == 200
    client.cookies.clear()
    client.cookies.set("cb_refresh", cookie)
    assert client.post(f"{API}/auth/refresh", headers={"X-Requested-With": "carebridge"}).status_code == 401


def test_change_password(client):
    reg = register(client, "A", "a@test.demo")
    r = client.post(f"{API}/auth/change-password", headers=reg["headers"],
                    json={"current_password": "Nope@12345", "new_password": "Newer@12345"})
    assert r.status_code == 400
    r = client.post(f"{API}/auth/change-password", headers=reg["headers"],
                    json={"current_password": PASSWORD, "new_password": "Newer@12345"})
    assert r.status_code == 200
    assert login(client, "a@test.demo", "Newer@12345")["user"]["id"] == reg["user"]["id"]


def test_forgot_password_is_account_enumeration_safe(client):
    register(client, "Known", "known@test.demo")
    known = client.post(f"{API}/auth/forgot-password", json={"email": "known@test.demo"})
    unknown = client.post(f"{API}/auth/forgot-password", json={"email": "unknown@test.demo"})
    assert known.status_code == unknown.status_code == 200
    assert known.json()["data"] == unknown.json()["data"]


def test_forgot_password_email_throttling(client):
    from app.core.ratelimit import forgot_password_limiter

    forgot_password_limiter.reset()
    email = "limited@example.test"
    responses = [
        client.post(f"{API}/auth/forgot-password", json={"email": email})
        for _ in range(6)
    ]
    assert all(response.status_code == 200 for response in responses[:5])
    assert responses[5].status_code == 429


def test_forgot_password_ip_throttling(client):
    from app.core.ratelimit import forgot_password_limiter

    forgot_password_limiter.reset()
    responses = [
        client.post(
            f"{API}/auth/forgot-password",
            json={"email": f"ip-{index}@example.test"},
        )
        for index in range(6)
    ]
    assert all(response.status_code == 200 for response in responses[:5])
    assert responses[5].status_code == 429


def test_missing_client_ip_cannot_bypass_ip_limit():
    from app.core.ratelimit import forgot_password_limiter

    forgot_password_limiter.reset()
    request = Request({
        "type": "http",
        "method": "POST",
        "path": "/",
        "headers": [],
        "client": None,
        "server": ("testserver", 80),
        "scheme": "http",
        "query_string": b"",
    })
    assert client_ip(request) == "unknown"
    results = [
        forgot_password_limiter.allow("ip:unknown")
        for _ in range(6)
    ]
    assert results[:5] == [True] * 5
    assert results[5] is False


def test_x_forwarded_for_cannot_change_ip_limit_key():
    request = Request({
        "type": "http",
        "method": "POST",
        "path": "/",
        "headers": [(b"x-forwarded-for", b"203.0.113.10")],
        "client": ("127.0.0.1", 12345),
        "server": ("testserver", 80),
        "scheme": "http",
        "query_string": b"",
    })
    assert client_ip(request) == "127.0.0.1"


def test_password_reset_migration_accepts_valid_existing_schema(db):
    load_migration_0004()._validate_existing_password_reset_table(inspect(db.bind))


def test_password_reset_migration_rejects_missing_primary_key(db):
    migration = load_migration_0004()

    db.execute(text(
        "ALTER TABLE password_reset_tokens DROP CONSTRAINT password_reset_tokens_pkey"
    ))
    db.commit()
    try:
        with pytest.raises(RuntimeError, match="primary key"):
            migration._validate_existing_password_reset_table(inspect(db.bind))
    finally:
        db.execute(text(
            "ALTER TABLE password_reset_tokens "
            "ADD CONSTRAINT password_reset_tokens_pkey PRIMARY KEY (id)"
        ))
        db.commit()


def test_password_reset_migration_rejects_wrong_nullability(db):
    migration = load_migration_0004()

    db.execute(text(
        "ALTER TABLE password_reset_tokens ALTER COLUMN used_at SET NOT NULL"
    ))
    db.commit()
    try:
        with pytest.raises(RuntimeError, match="nullability"):
            migration._validate_existing_password_reset_table(inspect(db.bind))
    finally:
        db.execute(text(
            "ALTER TABLE password_reset_tokens ALTER COLUMN used_at DROP NOT NULL"
        ))
        db.commit()


def test_valid_password_reset_works_and_consumes_token(client, db):
    reg = register(client, "Reset", "reset@test.demo")
    email_module.set_email(email_module.MockEmail())
    response = client.post(f"{API}/auth/forgot-password", json={"email": "reset@test.demo"})
    assert response.status_code == 200
    provider = email_module.get_email()
    assert len(provider.deliveries) == 1
    raw_token = provider.deliveries[0]["token"]

    reset = client.post(
        f"{API}/auth/reset-password",
        json={"token": raw_token, "new_password": "Reset@12345"},
    )
    assert reset.status_code == 200
    assert login(client, "reset@test.demo", "Reset@12345")["user"]["id"] == reg["user"]["id"]

    reuse = client.post(
        f"{API}/auth/reset-password",
        json={"token": raw_token, "new_password": "Other@12345"},
    )
    assert reuse.status_code == 400
    assert reuse.json()["error"]["code"] == "INVALID_RESET_TOKEN"


def test_expired_password_reset_token_is_rejected(client, db):
    register(client, "Expired", "expired@test.demo")
    email_module.set_email(email_module.MockEmail())
    assert client.post(f"{API}/auth/forgot-password", json={"email": "expired@test.demo"}).status_code == 200
    raw_token = email_module.get_email().deliveries[0]["token"]
    token_hash = hash_password_reset_token(raw_token)
    reset_row = db.scalar(select(PasswordResetToken).where(PasswordResetToken.token_hash == token_hash))
    reset_row.expires_at = utcnow() - timedelta(minutes=1)
    db.commit()

    response = client.post(
        f"{API}/auth/reset-password",
        json={"token": raw_token, "new_password": "Expired@12345"},
    )
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "INVALID_RESET_TOKEN"


def test_invalid_password_reset_token_is_rejected(client):
    response = client.post(
        f"{API}/auth/reset-password",
        json={"token": "x" * 32, "new_password": "Invalid@12345"},
    )
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "INVALID_RESET_TOKEN"


def test_password_reset_revokes_refresh_sessions(client):
    reg = register(client, "Sessions", "sessions@test.demo")
    old_cookie = client.cookies.get("cb_refresh")
    assert old_cookie
    email_module.set_email(email_module.MockEmail())
    assert client.post(f"{API}/auth/forgot-password", json={"email": "sessions@test.demo"}).status_code == 200
    raw_token = email_module.get_email().deliveries[0]["token"]
    assert client.post(
        f"{API}/auth/reset-password",
        json={"token": raw_token, "new_password": "Sessions@12345"},
    ).status_code == 200

    client.cookies.clear()
    client.cookies.set("cb_refresh", old_cookie)
    response = client.post(
        f"{API}/auth/refresh",
        headers={"X-Requested-With": "carebridge"},
    )
    assert response.status_code == 401


def test_concurrent_password_reset_uses_token_once(client):
    register(client, "Concurrent", "concurrent@test.demo")
    email_module.set_email(email_module.MockEmail())
    assert client.post(f"{API}/auth/forgot-password", json={"email": "concurrent@test.demo"}).status_code == 200
    raw_token = email_module.get_email().deliveries[0]["token"]

    def attempt(password):
        return client.post(
            f"{API}/auth/reset-password",
            json={"token": raw_token, "new_password": password},
        )

    with ThreadPoolExecutor(max_workers=2) as pool:
        responses = list(pool.map(attempt, ("Concurrent1@", "Concurrent2@")))
    statuses = [response.status_code for response in responses]
    assert statuses.count(200) == 1
    assert statuses.count(400) == 1


def test_health_endpoints(client):
    assert client.get(f"{API}/health").json()["data"]["status"] == "ok"
    ready = client.get(f"{API}/health/ready").json()["data"]
    assert ready["database"] == "ok" and ready["llm"]["provider"] == "none"
    assert client.get(f"{API}/health").headers.get("X-Request-ID")
