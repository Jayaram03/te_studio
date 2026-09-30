"""Google sign-in: only existing, active admins get in; every check of the OpenID flow is enforced."""
import base64
import json
import time
from urllib.parse import parse_qs, urlparse

import httpx
import pytest
from fastapi.testclient import TestClient

from app import api, auth, db, google_auth
from app.config import get_settings

CLIENT = "123-abc.apps.googleusercontent.com"


def _jwt(claims):
    enc = lambda d: base64.urlsafe_b64encode(json.dumps(d).encode()).rstrip(b"=").decode()
    return f"{enc({'alg': 'RS256'})}.{enc(claims)}.sig"


@pytest.fixture
def google(session):
    st = get_settings()
    st.google_client_id, st.google_client_secret = CLIENT, "secret-xyz"
    seen = {}

    def handler(req: httpx.Request):
        form = parse_qs(req.content.decode())
        seen["form"] = form
        claims = {"iss": "https://accounts.google.com", "aud": CLIENT, "exp": time.time() + 600,
                  "nonce": seen["nonce"], "email": seen.get("email", "travelepisodeschennai@gmail.com"),
                  "email_verified": seen.get("verified", True), "name": "Dhineshwar", **seen.get("override", {})}
        if form.get("code") != ["good-code"]:
            return httpx.Response(400, json={"error": "invalid_grant"})
        return httpx.Response(200, json={"id_token": _jwt(claims), "access_token": "x"})
    google_auth._transport = httpx.MockTransport(handler)
    yield seen
    google_auth._transport = None
    st.google_client_id = st.google_client_secret = None


def _begin(c, seen):
    r = c.get("/auth/google/start?next=/%23trips", follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"].startswith(google_auth.AUTH_URL)
    q = parse_qs(urlparse(r.headers["location"]).query)
    assert q["code_challenge_method"] == ["S256"] and q["client_id"] == [CLIENT] and q["scope"] == ["openid email profile"]
    seen["nonce"] = q["nonce"][0]
    return q["state"][0]


def test_default_first_admin_is_the_agency_gmail_google_only(session):
    u = auth.ensure_bootstrap_admin(session)
    assert u.email == "travelepisodeschennai@gmail.com" and not auth.has_password(u)
    with pytest.raises(auth.AuthError):
        auth.login(session, u.email, "!")                                      # no password can match
    assert auth.ensure_bootstrap_admin(session).id == u.id                     # never a second one


def test_admin_signs_in_with_google(session, google):
    auth.ensure_bootstrap_admin(session)
    c = TestClient(api.app)
    assert c.get("/api/auth/providers").json()["google"] is True
    state = _begin(c, google)
    r = c.get(f"/auth/google/callback?code=good-code&state={state}", follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == "/#trips"
    assert google["form"]["code_verifier"] and google["form"]["client_secret"] == ["secret-xyz"]
    me = c.get("/api/auth/me", headers={"X-Requested-With": "t"}).json()
    assert me["email"] == "travelepisodeschennai@gmail.com" and me["name"] == "Travel Episodes"


@pytest.mark.parametrize("case,expect", [
    ({"email": "stranger@gmail.com"}, "not_admin"),
    ({"verified": False}, "unverified"),
    ({"override": {"aud": "someone-else"}}, "failed"),
    ({"override": {"iss": "https://evil.example"}}, "failed"),
    ({"override": {"nonce": "replayed"}}, "failed"),
    ({"override": {"exp": time.time() - 3600}}, "expired"),
])
def test_google_sign_in_refusals(session, google, case, expect):
    auth.ensure_bootstrap_admin(session)
    google.update(case)
    c = TestClient(api.app)
    state = _begin(c, google)
    r = c.get(f"/auth/google/callback?code=good-code&state={state}", follow_redirects=False)
    assert r.headers["location"] == f"/login?error={expect}"
    assert c.get("/api/auth/me").status_code == 401


def test_state_and_cookie_are_required(session, google):
    auth.ensure_bootstrap_admin(session)
    c = TestClient(api.app)
    _begin(c, google)
    assert c.get("/auth/google/callback?code=good-code&state=forged", follow_redirects=False).headers["location"] \
        == "/login?error=failed"
    fresh = TestClient(api.app)                    # no cookie from /start: e.g. a link someone else made
    assert fresh.get("/auth/google/callback?code=good-code&state=x", follow_redirects=False).headers["location"] \
        == "/login?error=expired"


def test_disabled_admin_is_refused(session, google):
    u = auth.ensure_bootstrap_admin(session)
    auth.create_user(session, "rakesh@gmail.com", "Rakesh", None)
    auth.set_active(session, u, False)
    c = TestClient(api.app)
    state = _begin(c, google)
    assert c.get(f"/auth/google/callback?code=good-code&state={state}", follow_redirects=False).headers["location"] \
        == "/login?error=disabled"


def test_google_is_off_without_settings(session):
    c = TestClient(api.app)
    assert c.get("/api/auth/providers").json()["google"] is False
    assert c.get("/auth/google/start", follow_redirects=False).headers["location"] == "/login?error=google_off"


def test_google_only_admin_can_add_a_password(session, google):
    auth.ensure_bootstrap_admin(session)
    c = TestClient(api.app)
    state = _begin(c, google)
    c.get(f"/auth/google/callback?code=good-code&state={state}", follow_redirects=False)
    r = c.post("/api/auth/password", json={"new_password": "a-long-new-password-9"}, headers={"X-Requested-With": "t"})
    assert r.status_code == 200
    assert auth.login(session, "travelepisodeschennai@gmail.com", "a-long-new-password-9")
