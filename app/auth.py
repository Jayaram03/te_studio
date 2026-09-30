"""Sign-in for admin users.

- Passwords: scrypt (Python standard library), salted, never stored in plain text.
- Sessions: a random token in an HttpOnly, SameSite=Lax cookie (Secure over HTTPS). Only its SHA-256 hash is
  stored, so a leaked database can't be used to sign in. Sessions expire (SESSION_DAYS) and are deleted on
  sign-out, password change or when the user is disabled.
- Brute force: 5 wrong passwords lock the account for 15 minutes.
- CSRF: every state-changing /api request must carry the header X-Requested-With (browsers can't add it from
  another site without CORS permission), on top of SameSite cookies.
- Google: "Sign in with Google" works for accounts that already exist here (google_auth.py). An account can
  be Google-only (no password): its password hash is the unusable marker "!".
- First admin: created on startup while there are no users, from ADMIN_EMAIL (default
  travelepisodeschennai@gmail.com). With ADMIN_PASSWORD it can sign in with that password; without, it is
  Google-only. Or run `python -m app.cli create-admin`.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import re
import secrets
from datetime import datetime, timedelta

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from . import db
from .config import get_settings

COOKIE = "te_session"
MAX_FAILED = 5
LOCK_MINUTES = 15
MIN_PASSWORD = 10
NO_PASSWORD = "!"                       # Google-only account: no password can ever match this
DEFAULT_ADMIN = "travelepisodeschennai@gmail.com"


class AuthError(Exception):
    pass


# ------------------------------------------------------------------ passwords
def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    n, r, p = 2 ** 14, 8, 1
    dk = hashlib.scrypt(password.encode(), salt=salt, n=n, r=r, p=p, dklen=32)
    return f"scrypt${n}${r}${p}${base64.b64encode(salt).decode()}${base64.b64encode(dk).decode()}"


def verify_password(password: str, stored: str) -> bool:
    try:
        algo, n, r, p, salt, dk = stored.split("$")
        if algo != "scrypt":
            return False
        test = hashlib.scrypt(password.encode(), salt=base64.b64decode(salt), n=int(n), r=int(r), p=int(p),
                              dklen=len(base64.b64decode(dk)))
        return hmac.compare_digest(test, base64.b64decode(dk))
    except (ValueError, TypeError):
        return False


def check_password_rules(password: str, email: str = "", name: str = ""):
    if len(password or "") < MIN_PASSWORD:
        raise AuthError(f"Use at least {MIN_PASSWORD} characters")
    low = password.lower()
    local = (email or "").split("@")[0].lower()
    # a person's own name or email is easy to guess -- but only check parts long enough to mean something,
    # otherwise an address like a@b.in would reject every password containing the letter "a"
    personal = [x for x in (local, (name or "").lower()) if len(x) >= 4]
    if low in {"password123", "travelepisodes", "1234567890", "qwertyuiop"} or any(x in low for x in personal):
        raise AuthError("That password is too easy to guess")


# ------------------------------------------------------------------ users
def _norm_email(email: str) -> str:
    email = (email or "").strip().lower()
    if not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", email):
        raise AuthError("Enter a valid email address")
    return email


def create_user(s: Session, email: str, name: str, password: str | None, role: str = "admin",
                must_change_password: bool = False) -> db.User:
    """password=None makes a Google-only account (signs in with 'Sign in with Google')."""
    email = _norm_email(email)
    if s.scalar(select(db.User).where(db.User.email == email)):
        raise AuthError("A user with that email already exists")
    if password is not None:
        check_password_rules(password, email, name)
    u = db.User(email=email, name=(name or email.split("@")[0]).strip(),
                password_hash=hash_password(password) if password is not None else NO_PASSWORD,
                role=role, active=True, must_change_password=must_change_password and password is not None)
    s.add(u)
    s.commit()
    return u


def has_password(u: db.User) -> bool:
    return bool(u.password_hash) and u.password_hash != NO_PASSWORD


def ensure_bootstrap_admin(s: Session) -> db.User | None:
    """First admin, created while the users table is empty: ADMIN_EMAIL (default travelepisodeschennai@gmail.com),
    with ADMIN_PASSWORD if given, else Google-only. If that admin exists without a password and ADMIN_PASSWORD is
    set, the password is added (so a Google-only start can still get a password)."""
    import logging
    st = get_settings()
    email = (st.admin_email or DEFAULT_ADMIN).strip().lower()
    u = s.scalar(select(db.User).where(db.User.email == email))
    if u is None and not s.scalar(select(func.count(db.User.id))):
        default_name = "Travel Episodes" if email == DEFAULT_ADMIN else email.split("@")[0].replace(".", " ").title()
        u = create_user(s, email, st.admin_name or default_name, st.admin_password or None)
        logging.getLogger(__name__).info("first admin %s created (%s)", email,
                                         "password" if st.admin_password else "Google sign-in only")
        return u
    if u is not None and st.admin_password and not has_password(u):
        check_password_rules(st.admin_password, u.email, u.name)
        u.password_hash = hash_password(st.admin_password)
        s.commit()
    return u


def set_password(s: Session, user: db.User, new_password: str, keep_session_id: int | None = None):
    check_password_rules(new_password, user.email, user.name)
    user.password_hash = hash_password(new_password)
    user.must_change_password = False
    user.failed_logins, user.locked_until = 0, None
    q = delete(db.UserSession).where(db.UserSession.user_id == user.id)
    if keep_session_id:
        q = q.where(db.UserSession.id != keep_session_id)
    s.execute(q)
    s.commit()


def set_active(s: Session, user: db.User, active: bool):
    if not active:
        others = s.scalar(select(func.count(db.User.id)).where(db.User.active.is_(True), db.User.id != user.id))
        if not others:
            raise AuthError("You can't disable the last active admin")
        s.execute(delete(db.UserSession).where(db.UserSession.user_id == user.id))
    user.active = active
    s.commit()


# ------------------------------------------------------------------ sessions
def _hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def login(s: Session, email: str, password: str, ip: str | None = None, user_agent: str | None = None) -> tuple[str, db.User]:
    """Returns (cookie token, user). Same error for unknown email and wrong password."""
    generic = AuthError("Wrong email or password")
    try:
        email = _norm_email(email)
    except AuthError:
        raise generic
    u = s.scalar(select(db.User).where(db.User.email == email))
    now = datetime.utcnow()
    if not u:
        verify_password(password or "", hash_password("timing-equaliser"))   # similar time as a real check
        raise generic
    if u.locked_until and u.locked_until > now:
        mins = int((u.locked_until - now).total_seconds() // 60) + 1
        raise AuthError(f"Too many attempts. Try again in {mins} minute{'s' if mins > 1 else ''}.")
    if not verify_password(password or "", u.password_hash):
        u.failed_logins = (u.failed_logins or 0) + 1
        if u.failed_logins >= MAX_FAILED:
            u.locked_until, u.failed_logins = now + timedelta(minutes=LOCK_MINUTES), 0
        s.commit()
        raise generic
    if not u.active:
        raise AuthError("This account is disabled. Ask another admin to turn it back on.")
    if u.role != "admin":
        raise AuthError("Only admin users can sign in")
    return start_session(s, u, ip, user_agent), u


def start_session(s: Session, u: db.User, ip: str | None = None, user_agent: str | None = None) -> str:
    """Record a sign-in and return the cookie token (only its hash is stored)."""
    now = datetime.utcnow()
    u.failed_logins, u.locked_until, u.last_login_at = 0, None, now
    from . import runtime
    runtime.refresh(s)
    token = secrets.token_urlsafe(32)
    s.add(db.UserSession(user_id=u.id, token_hash=_hash_token(token), created_at=now,
                         expires_at=now + timedelta(days=get_settings().session_days), last_seen_at=now,
                         ip=(ip or "")[:64], user_agent=(user_agent or "")[:300]))
    s.execute(delete(db.UserSession).where(db.UserSession.expires_at < now))   # tidy up old sessions
    s.commit()
    return token


def google_user(s: Session, email: str) -> db.User:
    """The admin account for a verified Google email, or AuthError."""
    u = s.scalar(select(db.User).where(db.User.email == (email or "").strip().lower()))
    if not u or u.role != "admin":
        raise AuthError("not_admin")
    if not u.active:
        raise AuthError("disabled")
    return u


def session_user(s: Session, token: str | None) -> tuple[db.User, db.UserSession] | None:
    if not token:
        return None
    sess = s.scalar(select(db.UserSession).where(db.UserSession.token_hash == _hash_token(token)))
    now = datetime.utcnow()
    if not sess or sess.expires_at < now:
        return None
    u = s.get(db.User, sess.user_id)
    if not u or not u.active or u.role != "admin":
        return None
    if not sess.last_seen_at or (now - sess.last_seen_at).total_seconds() > 300:
        sess.last_seen_at = now
        s.commit()
    return u, sess


def logout(s: Session, token: str | None):
    if token:
        s.execute(delete(db.UserSession).where(db.UserSession.token_hash == _hash_token(token)))
        s.commit()


def user_json(u: db.User) -> dict:
    return {"id": u.id, "email": u.email, "name": u.name, "role": u.role, "active": u.active,
            "must_change_password": u.must_change_password, "has_password": has_password(u),
            "last_login_at": u.last_login_at and u.last_login_at.isoformat() + "Z",
            "created_at": u.created_at and u.created_at.isoformat()}
