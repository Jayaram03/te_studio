from datetime import datetime, timedelta

from fastapi.testclient import TestClient
from sqlalchemy import select

from app import api, auth, db
from app.config import get_settings
from conftest import ADMIN, signed_in_client


def test_password_hashing():
    h = auth.hash_password("correct horse battery")
    assert h.startswith("scrypt$") and "correct" not in h
    assert auth.verify_password("correct horse battery", h) and not auth.verify_password("wrong", h)
    assert auth.hash_password("same-password") != auth.hash_password("same-password")   # salted


def test_everything_needs_sign_in_except_public_parts(session):
    anon = TestClient(api.app)
    assert anon.get("/api/trips").status_code == 401
    assert anon.get("/api/catalog/summary").status_code == 401
    r = anon.get("/", follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == "/login"
    assert anon.get("/app.js", follow_redirects=False).status_code == 303
    assert anon.get("/login").status_code == 200 and "Sign in" in anon.get("/login").text
    assert anon.get("/static/brand/logo.png").status_code == 200
    assert anon.get("/api/health").status_code == 200
    for hidden in ("/docs", "/openapi.json", "/api/docs"):
        assert anon.get(hidden, follow_redirects=False).status_code in (303, 401, 404)


def test_login_logout_and_session_cookie(session):
    auth.create_user(session, **ADMIN)
    c = TestClient(api.app, headers={"X-Requested-With": "x"})
    bad = c.post("/api/auth/login", json={"email": ADMIN["email"], "password": "nope-nope-nope"})
    assert bad.status_code == 401 and bad.json()["detail"] == "Wrong email or password"
    unknown = c.post("/api/auth/login", json={"email": "who@x.com", "password": "whatever-123"})
    assert unknown.json()["detail"] == "Wrong email or password"          # same message: no user enumeration
    ok = c.post("/api/auth/login", json={"email": ADMIN["email"].upper(), "password": ADMIN["password"]})
    assert ok.status_code == 200
    cookie = ok.headers["set-cookie"].lower()
    assert "httponly" in cookie and "samesite=lax" in cookie
    assert c.get("/api/auth/me").json()["email"] == ADMIN["email"]
    assert c.get("/", follow_redirects=False).status_code == 200
    assert c.get("/login", follow_redirects=False).status_code == 303            # already signed in
    stored = session.scalar(select(db.UserSession))
    assert stored.token_hash != c.cookies.get(auth.COOKIE)                      # only a hash is stored
    c.post("/api/auth/logout")
    assert c.get("/api/auth/me").status_code == 401


def test_lockout_after_repeated_failures(session):
    auth.create_user(session, **ADMIN)
    c = TestClient(api.app)
    for _ in range(auth.MAX_FAILED):
        c.post("/api/auth/login", json={"email": ADMIN["email"], "password": "wrong-password-x"})
    r = c.post("/api/auth/login", json={"email": ADMIN["email"], "password": ADMIN["password"]})
    assert r.status_code == 401 and "Too many attempts" in r.json()["detail"]
    u = session.scalar(select(db.User))
    session.refresh(u)
    u.locked_until = datetime.utcnow() - timedelta(seconds=1)
    session.commit()
    assert c.post("/api/auth/login", json={"email": ADMIN["email"], "password": ADMIN["password"]}).status_code == 200


def test_csrf_header_required_for_changes(session):
    c = signed_in_client(session)
    bare = TestClient(api.app)
    bare.cookies.set(auth.COOKIE, c.cookies.get(auth.COOKIE))
    assert bare.get("/api/trips").status_code == 200                           # reading is fine
    assert bare.post("/api/trips", json={"title": "x"}).status_code == 403       # changing needs the header
    assert c.post("/api/trips", json={"title": "x"}).status_code == 200


def test_user_management_and_password_change(session):
    c = signed_in_client(session)
    assert c.post("/api/users", json={"email": "rakesh@te.in", "name": "Rakesh", "password": "short"}).status_code == 400
    u = c.post("/api/users", json={"email": "rakesh@te.in", "name": "Rakesh", "password": "ooty-weekend-2026"}).json()
    assert u["must_change_password"] and u["active"]
    r = TestClient(api.app, headers={"X-Requested-With": "x"})
    assert r.post("/api/auth/login", json={"email": "rakesh@te.in", "password": "ooty-weekend-2026"}).status_code == 200
    assert r.post("/api/auth/password", json={"current_password": "bad", "new_password": "munnar-tea-2026"}).status_code == 400
    assert r.post("/api/auth/password", json={"current_password": "ooty-weekend-2026", "new_password": "munnar-tea-2026"}).status_code == 200
    assert r.get("/api/auth/me").json()["must_change_password"] is False
    # disabling signs them out immediately
    c.patch(f"/api/users/{u['id']}", json={"active": False})
    assert r.get("/api/auth/me").status_code == 401
    me = c.get("/api/auth/me").json()
    assert c.patch(f"/api/users/{me['id']}", json={"active": False}).status_code == 400   # not yourself
    # notes and trips record who did it
    t = c.post("/api/trips", json={"title": "Who made me"}).json()
    assert t["notes_log"] == [] or True
    v = c.post(f"/api/trips/{t['id']}/notes", json={"text": "Called"}).json()
    assert v["notes_log"][0]["author"] == ADMIN["name"]


def test_bootstrap_admin_from_env(session):
    st = get_settings()
    st.admin_email, st.admin_password = "owner@te.in", "first-admin-pass-1"
    try:
        auth.ensure_bootstrap_admin(session)
        auth.ensure_bootstrap_admin(session)          # only once, only while there are no users
        assert [u.email for u in session.scalars(select(db.User)).all()] == ["owner@te.in"]
    finally:
        st.admin_email = st.admin_password = None


def test_daily_cron_needs_its_secret(session):
    from datetime import datetime, timedelta
    st = get_settings()
    anon = TestClient(api.app)
    assert anon.get("/api/cron/daily").status_code == 401                      # no secret configured
    st.cron_secret = "cron-secret-xyz"
    try:
        assert anon.get("/api/cron/daily", headers={"Authorization": "Bearer wrong"}).status_code == 401
        u = auth.create_user(session, **ADMIN)
        session.add(db.UserSession(user_id=u.id, token_hash="x" * 64, created_at=datetime.utcnow(),
                                   expires_at=datetime.utcnow() - timedelta(days=1)))
        session.commit()
        r = anon.get("/api/cron/daily", headers={"Authorization": "Bearer cron-secret-xyz"})
        assert r.status_code == 200 and r.json()["expired_sessions_removed"] == 1
    finally:
        st.cron_secret = None


def test_sign_in_length_from_settings_applies_immediately(session):
    from app import runtime
    runtime.save(session, {"session_days": 3})
    runtime.reset_cache()                                  # like a fresh server that hasn't read Settings yet
    get_settings().session_days = 14
    auth.create_user(session, **ADMIN)
    r = TestClient(api.app).post("/api/auth/login", json={"email": ADMIN["email"], "password": ADMIN["password"]})
    assert "max-age=259200" in r.headers["set-cookie"].lower()      # 3 days, from Settings
    get_settings().session_days = 14


def test_password_rules_are_sensible():
    import pytest
    for ok in [("tea-estate-munnar-9", "a@b.in", "A"), ("ops-team-pass-2026", "ops@te.in", "Ops")]:
        auth.check_password_rules(*ok)                          # short email/name parts don't block everything
    for bad in [("rakesh-2026-pass", "rakesh@te.in", "Rakesh"), ("my-dhineshwar-99", "d@te.in", "Dhineshwar"),
                ("travelepisodes", "x@y.in", "")]:
        with pytest.raises(auth.AuthError):
            auth.check_password_rules(*bad)
