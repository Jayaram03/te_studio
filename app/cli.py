"""Command line.

  python -m app.cli ingest samples/*.pdf --supplier "Green Valley DMC"
  python -m app.cli ingest ~/Downloads/rate-sheets/          # a whole folder
  python -m app.cli list
  python -m app.cli show 3
  python -m app.cli approve 3 --valid-from 2026-10-01 --valid-to 2027-03-31 --net
  python -m app.cli rates --destination Munnar --date 2026-12-24 --meal CP
  python -m app.cli quote --hotel-id 1 --room "Deluxe" --meal CP --in 2026-12-18 --out 2026-12-22 --adults 2
  python -m app.cli create-admin --email you@example.com --name "Dhineshwar"     # asks for the password
  python -m app.cli reset-password --email you@example.com                        # asks for the new password
  python -m app.cli users
"""
from __future__ import annotations

import argparse
import getpass
import json
from datetime import date
from pathlib import Path

from sqlalchemy import select

from . import auth, db, pipeline, rates
from .config import get_settings
from .extractor import ClaudeExtractor, FixtureExtractor
from .parsers import SUPPORTED


def _extractor(args):
    if args.fixtures or get_settings().fixtures_dir:
        return FixtureExtractor(args.fixtures or get_settings().fixtures_dir)
    return ClaudeExtractor()


def cmd_ingest(args):
    ex = _extractor(args)
    s = db.SessionLocal()
    files = []
    for p in map(Path, args.paths):
        files += sorted(f for f in p.rglob("*") if f.suffix.lower() in SUPPORTED) if p.is_dir() else [p]
    for f in files:
        doc, is_new = pipeline.ingest(s, f.name, f.read_bytes(), ex, args.supplier)
        st = (doc.normalized or {}).get("stats", {})
        print(f"#{doc.id:<4} {doc.status:<13} {f.name}" + ("  (already uploaded)" if not is_new else "") +
              (f"  rates={st.get('hotel_rates', 0)} packages={st.get('packages', 0)} services={st.get('services', 0)}"
               f" errors={st.get('errors', 0)} warnings={st.get('warnings', 0)}" if st else "") +
              (f"\n      {doc.error.splitlines()[0]}" if doc.error else ""))


def cmd_list(args):
    s = db.SessionLocal()
    for d in s.scalars(select(db.SourceDocument).order_by(db.SourceDocument.id)).all():
        st = (d.normalized or {}).get("stats", {})
        print(f"#{d.id:<4} {d.status:<13} {d.document_type or '':<17} {d.filename}  errors={st.get('errors', '-')} "
              f"warnings={st.get('warnings', '-')}")


def cmd_show(args):
    s = db.SessionLocal()
    d = s.get(db.SourceDocument, args.id)
    for i in d.issues or []:
        print(f"[{i['level'].upper():7}] {i['message']}   <{i['where']}>")
    print(json.dumps(d.normalized.get("stats") if d.normalized else {}, indent=2))


def cmd_approve(args):
    s = db.SessionLocal()
    d = s.get(db.SourceDocument, args.id)
    ov = {k: v for k, v in {"valid_from": args.valid_from, "valid_to": args.valid_to, "currency": args.currency,
                            "rate_type": "net" if args.net else ("rack" if args.rack else None),
                            "taxes": args.taxes}.items() if v}
    try:
        print(pipeline.approve(s, d, ov, approved_by=args.by))
    except pipeline.PipelineError as e:
        print("Cannot approve:", e)


def cmd_rates(args):
    s = db.SessionLocal()
    for r in rates.search_hotel_rates(s, args.destination, args.hotel, date.fromisoformat(args.date) if args.date else None,
                                      args.meal, args.occupancy):
        print(f"{r['hotel']:<30} {r['room_type']:<24} {r['meal_plan']:<4} {r['amount']:>10,.2f} {r['currency']} "
              f"{r['season'] or '':<10} {r['valid_from']}..{r['valid_to']}")


def cmd_quote(args):
    s = db.SessionLocal()
    q = rates.price_hotel_stay(s, args.hotel_id, args.room, args.meal, date.fromisoformat(args.check_in),
                               date.fromisoformat(args.check_out),
                               [{"adults": args.adults, "children_with_bed": args.cwb, "children_without_bed": args.cnb}],
                               markup_pct=args.markup)
    print(json.dumps(q, indent=2))


def _ask_password(args) -> str:
    if getattr(args, "password", None):
        return args.password
    p1 = getpass.getpass("New password (10+ characters): ")
    if p1 != getpass.getpass("Repeat it: "):
        raise SystemExit("Passwords don't match")
    return p1


def cmd_create_admin(args):
    s = db.SessionLocal()
    try:
        u = auth.create_user(s, args.email, args.name or "", None if args.google_only else _ask_password(args))
        print(f"Admin created: {u.name} <{u.email}>" + (" (Google sign-in only)" if args.google_only else ""))
    except auth.AuthError as e:
        raise SystemExit(f"Could not create admin: {e}")


def cmd_reset_password(args):
    s = db.SessionLocal()
    u = s.scalar(select(db.User).where(db.User.email == args.email.strip().lower()))
    if not u:
        raise SystemExit("No user with that email")
    try:
        auth.set_password(s, u, _ask_password(args))
        u.active, u.locked_until, u.failed_logins = True, None, 0
        s.commit()
        print(f"Password reset for {u.email}; all their sessions were signed out.")
    except auth.AuthError as e:
        raise SystemExit(str(e))


def cmd_users(args):
    s = db.SessionLocal()
    for u in s.scalars(select(db.User).order_by(db.User.id)).all():
        print(f"#{u.id:<3} {'active' if u.active else 'disabled':<9} {u.role:<6} {u.email:<35} {u.name}  "
              f"last login: {u.last_login_at or '-'}")


def main():
    p = argparse.ArgumentParser(prog="rate-ingest")
    p.add_argument("--fixtures", help="use saved extraction JSON from this folder instead of the Claude API")
    sub = p.add_subparsers(required=True)
    a = sub.add_parser("ingest"); a.add_argument("paths", nargs="+"); a.add_argument("--supplier"); a.set_defaults(f=cmd_ingest)
    sub.add_parser("list").set_defaults(f=cmd_list)
    a = sub.add_parser("show"); a.add_argument("id", type=int); a.set_defaults(f=cmd_show)
    a = sub.add_parser("approve"); a.add_argument("id", type=int)
    a.add_argument("--valid-from"); a.add_argument("--valid-to"); a.add_argument("--currency")
    a.add_argument("--net", action="store_true"); a.add_argument("--rack", action="store_true")
    a.add_argument("--taxes", choices=["included", "excluded"]); a.add_argument("--by"); a.set_defaults(f=cmd_approve)
    a = sub.add_parser("rates"); a.add_argument("--destination"); a.add_argument("--hotel"); a.add_argument("--date")
    a.add_argument("--meal"); a.add_argument("--occupancy", default="double"); a.set_defaults(f=cmd_rates)
    a = sub.add_parser("quote"); a.add_argument("--hotel-id", type=int, required=True); a.add_argument("--room", required=True)
    a.add_argument("--meal", required=True); a.add_argument("--in", dest="check_in", required=True)
    a.add_argument("--out", dest="check_out", required=True); a.add_argument("--adults", type=int, default=2)
    a.add_argument("--cwb", type=int, default=0); a.add_argument("--cnb", type=int, default=0)
    a.add_argument("--markup", type=float, default=0); a.set_defaults(f=cmd_quote)
    a = sub.add_parser("create-admin"); a.add_argument("--email", required=True); a.add_argument("--name")
    a.add_argument("--password", help="omit to be asked safely")
    a.add_argument("--google-only", action="store_true", help="no password: signs in with Google only")
    a.set_defaults(f=cmd_create_admin)
    a = sub.add_parser("reset-password"); a.add_argument("--email", required=True)
    a.add_argument("--password", help="omit to be asked safely"); a.set_defaults(f=cmd_reset_password)
    sub.add_parser("users").set_defaults(f=cmd_users)
    args = p.parse_args()
    from . import logs
    logs.setup()
    db.init_db()
    args.f(args)


if __name__ == "__main__":
    main()
