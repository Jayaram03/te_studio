"""Security checks: who can reach what, CSRF, XSS, injection, uploads, sessions, headers, error leaks."""
import re

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app import api, auth, db, trips
from conftest import ADMIN, signed_in_client

PUBLIC = {"/login", "/favicon.ico", "/api/health", "/api/auth/login", "/api/auth/logout", "/api/cron/daily",
          "/api/auth/providers", "/auth/google/start", "/auth/google/callback"}


def _routes():
    for r in api.app.routes:
        path = getattr(r, "path", "")
        for m in sorted(getattr(r, "methods", None) or []):
            if m in ("HEAD", "OPTIONS") or path.startswith("/static"):
                continue
            yield m, path


def test_every_private_route_needs_sign_in(session):
    c = TestClient(api.app)
    checked = 0
    for method, path in _routes():
        if path in PUBLIC or path.startswith(("/share/", "/q/")):
            continue
        url = re.sub(r"\{[^}]+\}", "1", path)
        r = c.request(method, url, headers={"X-Requested-With": "x"}, follow_redirects=False)
        assert r.status_code in (401, 303), f"{method} {path} answered {r.status_code} without sign-in"
        if r.status_code == 303:
            assert r.headers["location"].startswith("/login")
        checked += 1
    assert checked > 80                        # the sweep really covered the API


def test_a_forged_or_expired_session_is_refused(session):
    c = TestClient(api.app, cookies={auth.COOKIE: "made-up-token"})
    assert c.get("/api/trips").status_code == 401


def test_csrf_header_is_required_for_changes(session):
    c = signed_in_client(session)
    bare = TestClient(api.app, cookies=dict(c.cookies))
    assert bare.post("/api/trips", json={"title": "x"}).status_code == 403
    assert bare.delete("/api/quotations/1").status_code == 403
    assert bare.get("/api/trips").status_code == 200                    # reading is fine


def test_session_cookie_flags_and_lockout(session):
    auth.create_user(session, **ADMIN)
    c = TestClient(api.app, base_url="https://studio.example")
    r = c.post("/api/auth/login", json={"email": ADMIN["email"], "password": ADMIN["password"]}, headers={"X-Requested-With": "x"})
    ck = r.headers["set-cookie"].lower()
    assert "httponly" in ck and "samesite=lax" in ck and "secure" in ck
    for _ in range(5):
        c.post("/api/auth/login", json={"email": ADMIN["email"], "password": "wrong-password-0"})
    r = c.post("/api/auth/login", json={"email": ADMIN["email"], "password": ADMIN["password"]})
    assert r.status_code == 401 and "Too many attempts" in r.json()["detail"]
    # unknown email and wrong password give the same answer
    a = c.post("/api/auth/login", json={"email": "nobody@x.in", "password": "whatever-123"}).json()["detail"]
    assert a == "Wrong email or password"


def test_password_hashes_and_secrets_never_leave_the_server(session):
    c = signed_in_client(session)
    body = c.get("/api/users").text + c.get("/api/system").text + c.get("/api/ai/settings").text
    assert "scrypt$" not in body and "test-secret-key-for-encryption" not in body
    u = session.scalar(select(db.User))
    assert u.password_hash.startswith("scrypt$") and ADMIN["password"] not in u.password_hash
    s = session.scalar(select(db.UserSession))
    assert len(s.token_hash) == 64                                        # only a hash of the cookie is stored


def test_client_pages_escape_what_admins_type(session):
    c = signed_in_client(session)
    evil = '<script>alert("x")</script><img src=x onerror=alert(1)>'
    t = c.post("/api/trips", json={"title": evil, "customer_name": evil, "adults": 2}).json()
    c.put(f"/api/trips/{t['id']}/days", json=[{"title": evil, "description": evil}])
    c.post(f"/api/trips/{t['id']}/items", json={"kind": "custom", "description": evil, "unit_amount": 10})
    tok = c.post(f"/api/trips/{t['id']}/share", json={}).json()["share_token"]
    q = c.post(f"/api/trips/{t['id']}/quotations", json={}).json()
    qtok = c.post(f"/api/quotations/{q['id']}/share", json={}).json()["share_token"]
    for url in (f"/share/{tok}", f"/q/{qtok}"):
        html = TestClient(api.app).get(url).text
        assert "<script>alert" not in html and "<img src=x" not in html and "&lt;script&gt;" in html
    assert c.get(f"/api/quotations/{q['id']}/pdf").status_code == 200    # PDFs build fine with odd text too


def test_share_links_are_unguessable_and_can_be_turned_off(session):
    c = signed_in_client(session)
    t = c.post("/api/trips", json={"title": "x", "adults": 2}).json()
    tok = c.post(f"/api/trips/{t['id']}/share", json={}).json()["share_token"]
    assert len(tok) >= 24
    anon = TestClient(api.app)
    assert anon.get(f"/share/{tok}").status_code == 200
    assert anon.get(f"/share/{tok[:-1]}x").status_code == 404
    c.post(f"/api/trips/{t['id']}/share", json={"enable": False})
    assert anon.get(f"/share/{tok}").status_code == 404
    assert anon.get(f"/api/trips/{t['id']}").status_code == 401


@pytest.mark.parametrize("q", ["' or 1=1 --", "%", "_", "'); drop table trips; --", "\\", "Robert'); DROP TABLE users;--"])
def test_search_input_is_never_sql(session, q):
    c = signed_in_client(session)
    for url in ("/api/catalog/hotels", "/api/catalog/services", "/api/quotations", "/api/catalog/places"):
        assert c.get(url, params={"q": q}).status_code == 200
    assert session.scalar(select(db.User))                               # tables still there


def test_uploads_are_limited(session):
    from app.config import get_settings
    c = signed_in_client(session)
    get_settings().max_upload_mb = 0.001
    try:
        r = c.post("/api/documents", files={"file": ("big.pdf", b"%PDF-" + b"0" * 5000, "application/pdf")})
        assert r.status_code == 413
    finally:
        get_settings().max_upload_mb = 4.4
    assert c.post("/api/documents", files={"file": ("x.exe", b"MZ\x90\x00", "application/octet-stream")}).status_code == 400
    # a path in the file name is only a label: files are stored in the database, never written to disk
    assert c.post("/api/documents", files={"file": ("../../etc/passwd.txt", b"root:x:0:0", "text/plain")}).status_code == 202


def test_security_headers_and_no_error_details_leak(session, monkeypatch):
    c = signed_in_client(session)
    r = c.get("/api/trips")
    for h in ("x-content-type-options", "x-frame-options", "content-security-policy", "referrer-policy", "x-request-id"):
        assert h in r.headers
    assert "script-src 'self'" in r.headers["content-security-policy"] and "unsafe-inline" not in r.headers["content-security-policy"].split("script-src")[1].split(";")[0]
    assert r.headers.get("cache-control") == "no-store"

    def boom(*a, **k):
        raise RuntimeError("secret internal detail: password=hunter2")
    monkeypatch.setattr(trips, "dashboard", boom)
    r = c.get("/api/dashboard")
    assert r.status_code == 500 and "hunter2" not in r.text and "Reference:" in r.json()["detail"]


def test_no_open_redirect_after_google_sign_in(session):
    from app import google_auth
    from app.config import get_settings
    st = get_settings()
    st.google_client_id, st.google_client_secret = "id", "secret"
    try:
        url, cookie = google_auth.start("https://studio.example/", "//evil.example/steal")
        assert google_auth._unsign(cookie)["next"] == "/"
        url, cookie = google_auth.start("https://studio.example/", "https://evil.example")
        assert google_auth._unsign(cookie)["next"] == "/"
        # a tampered cookie is refused
        body, mac = cookie.split(".")
        with pytest.raises(google_auth.GoogleAuthError):
            google_auth._unsign(body + "x." + mac)
    finally:
        st.google_client_id = st.google_client_secret = None


def test_cron_needs_its_secret(session):
    from app.config import get_settings
    get_settings().cron_secret = "cron-secret-abc"
    try:
        c = TestClient(api.app)
        assert c.get("/api/cron/daily").status_code == 401
        assert c.get("/api/cron/daily", headers={"Authorization": "Bearer wrong"}).status_code == 401
        assert c.get("/api/cron/daily", headers={"Authorization": "Bearer cron-secret-abc"}).status_code == 200
    finally:
        get_settings().cron_secret = None
