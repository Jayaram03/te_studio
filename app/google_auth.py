"""'Sign in with Google' for admins (OpenID Connect, authorization-code flow with PKCE).

Who can get in: only people who already have an *active admin* account in Settings -> Team & sign-in, matched
by their verified Google email. Anyone else gets "not an admin" and no session. Google only proves who the
person is; the app decides whether they are allowed.

Flow
  /auth/google/start     makes a random state, nonce and PKCE verifier, keeps them in a short-lived signed
                         cookie (HMAC with SECRET_KEY), and sends the browser to Google.
  /auth/google/callback  checks the state against the cookie, exchanges the code (with the PKCE verifier and
                         the client secret) at Google's token endpoint, checks the ID token (issuer, audience,
                         expiry, nonce, verified email) and signs the admin in with the normal session cookie.

The ID token comes straight from Google's token endpoint over TLS in exchange for our client secret, so, as
OpenID Connect Core 3.1.3.7 allows, the TLS connection authenticates it and its signature isn't re-checked.

Setup: Google Cloud Console -> APIs & Services -> Credentials -> OAuth client ID (Web application), with the
authorized redirect URI  https://<your domain>/auth/google/callback . Put the ID and secret in
GOOGLE_CLIENT_ID / GOOGLE_CLIENT_SECRET (and PUBLIC_URL). SECRET_KEY must be set.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import logging
import secrets
import time
from urllib.parse import urlencode

import httpx

from .config import get_settings

log = logging.getLogger(__name__)

AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_URL = "https://oauth2.googleapis.com/token"
ISSUERS = {"https://accounts.google.com", "accounts.google.com"}
COOKIE = "te_oauth"
MAX_AGE = 600                               # the sign-in must finish within 10 minutes
_transport = None                           # tests replace Google with a fake transport


class GoogleAuthError(Exception):
    """`code` is shown to the user on the sign-in page (not_admin, expired, failed ...)."""

    def __init__(self, code: str, detail: str = ""):
        super().__init__(detail or code)
        self.code = code


def enabled() -> bool:
    st = get_settings()
    return bool(st.google_client_id and st.google_client_secret and st.secret_key)


def _b64(b: bytes) -> str:
    return base64.urlsafe_b64encode(b).rstrip(b"=").decode()


def _unb64(s: str) -> bytes:
    return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))


def _sign(payload: dict) -> str:
    body = _b64(json.dumps(payload, separators=(",", ":")).encode())
    mac = hmac.new(get_settings().secret_key.encode(), body.encode(), hashlib.sha256).digest()
    return f"{body}.{_b64(mac)}"


def _unsign(value: str | None) -> dict:
    try:
        body, mac = (value or "").split(".")
        good = hmac.new(get_settings().secret_key.encode(), body.encode(), hashlib.sha256).digest()
        if not hmac.compare_digest(_unb64(mac), good):
            raise ValueError("bad signature")
        data = json.loads(_unb64(body))
    except Exception as e:  # noqa: BLE001
        raise GoogleAuthError("expired", "sign-in cookie missing or changed") from e
    if time.time() - data.get("t", 0) > MAX_AGE:
        raise GoogleAuthError("expired", "sign-in took too long")
    return data


def redirect_uri(base_url: str) -> str:
    base = (get_settings().public_url or base_url).rstrip("/")
    return f"{base}/auth/google/callback"


def start(base_url: str, next_path: str | None = None) -> tuple[str, str]:
    """Returns (Google URL to send the browser to, value for the COOKIE cookie)."""
    if not enabled():
        raise GoogleAuthError("google_off", "Google sign-in is not set up")
    state, nonce, verifier = secrets.token_urlsafe(24), secrets.token_urlsafe(24), secrets.token_urlsafe(48)
    challenge = _b64(hashlib.sha256(verifier.encode()).digest())
    nxt = next_path if next_path and next_path.startswith("/") and not next_path.startswith("//") else "/"
    cookie = _sign({"s": state, "n": nonce, "v": verifier, "t": int(time.time()), "next": nxt})
    q = {"client_id": get_settings().google_client_id, "redirect_uri": redirect_uri(base_url), "response_type": "code",
         "scope": "openid email profile", "state": state, "nonce": nonce, "code_challenge": challenge,
         "code_challenge_method": "S256", "prompt": "select_account"}
    return f"{AUTH_URL}?{urlencode(q)}", cookie


def finish(base_url: str, code: str | None, state: str | None, cookie: str | None) -> tuple[dict, str]:
    """Checks everything and returns (verified claims, where to go next)."""
    saved = _unsign(cookie)
    if not code or not state or not hmac.compare_digest(state, saved["s"]):
        raise GoogleAuthError("failed", "state does not match")
    st = get_settings()
    try:
        with httpx.Client(timeout=15, transport=_transport) as c:
            r = c.post(TOKEN_URL, data={"code": code, "client_id": st.google_client_id,
                                        "client_secret": st.google_client_secret, "redirect_uri": redirect_uri(base_url),
                                        "grant_type": "authorization_code", "code_verifier": saved["v"]})
    except httpx.HTTPError as e:
        raise GoogleAuthError("failed", f"could not reach Google: {e}") from e
    if r.status_code != 200:
        raise GoogleAuthError("failed", f"Google refused the code ({r.status_code}): {r.text[:200]}")
    id_token = (r.json() or {}).get("id_token") or ""
    try:
        claims = json.loads(_unb64(id_token.split(".")[1]))
    except Exception as e:  # noqa: BLE001
        raise GoogleAuthError("failed", "no ID token from Google") from e
    now = time.time()
    if claims.get("iss") not in ISSUERS or claims.get("aud") != st.google_client_id:
        raise GoogleAuthError("failed", "ID token is not for this app")
    if claims.get("exp", 0) < now - 60:
        raise GoogleAuthError("expired", "ID token expired")
    if not hmac.compare_digest(str(claims.get("nonce", "")), saved["n"]):
        raise GoogleAuthError("failed", "nonce does not match")
    if not claims.get("email") or claims.get("email_verified") not in (True, "true"):
        raise GoogleAuthError("unverified", "Google account email is not verified")
    return claims, saved.get("next") or "/"
