"""HTTP API + the web app (served at /).

Security: every page and /api call needs a signed-in admin (session cookie), except the login page, brand
assets and client share links (/share/<token>). Server-to-server calls can use `X-API-Key: <API_KEY>` instead.
Processing: PROCESS_MODE=inline (default, works on Vercel) reads the document inside the upload request;
PROCESS_MODE=background returns immediately and reads it afterwards (normal servers only).
"""
from __future__ import annotations

import hmac
import logging
from contextlib import asynccontextmanager
from datetime import date
from pathlib import Path

from fastapi import BackgroundTasks, Body, Depends, FastAPI, File, Form, HTTPException, Query, Request, UploadFile
from fastapi.concurrency import run_in_threadpool
from fastapi.openapi.docs import get_swagger_ui_html
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, PlainTextResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from . import (ai, auth, catalog, company, db, exports, google_auth, history, logs, pdfgen, pipeline, quotes, rates,
               runtime, sharepage, trips)
from .config import get_settings

log = logging.getLogger("app.api")


@asynccontextmanager
async def lifespan(_app):
    logs.setup()
    db.init_db()
    s = db.SessionLocal()
    try:
        auth.ensure_bootstrap_admin(s)
    finally:
        s.close()
    yield


app = FastAPI(title="Travel Episodes Studio API", version="0.3.0", lifespan=lifespan,
              docs_url=None, redoc_url=None, openapi_url=None)
STATIC = Path(__file__).parent / "static"
app.mount("/static", StaticFiles(directory=STATIC), name="static")

# Allow your main website (another domain / subdomain) to call this API from the browser
_origins = [o.strip() for o in (get_settings().cors_origins or "").split(",") if o.strip()]
if _origins:
    app.add_middleware(CORSMiddleware, allow_origins=_origins, allow_methods=["*"], allow_headers=["*"])


PUBLIC_PREFIXES = ("/static/", "/share/", "/q/")
PUBLIC_PATHS = {"/login", "/favicon.ico", "/api/health", "/api/auth/login", "/api/auth/logout", "/api/cron/daily",
                "/api/auth/providers", "/auth/google/start", "/auth/google/callback"}


def _session_lookup(token: str | None):
    s = db.SessionLocal()
    try:
        found = auth.session_user(s, token)
        return (found[0].id, found[0].name, found[1].id) if found else None
    finally:
        s.close()


@app.middleware("http")
async def require_sign_in(request: Request, call_next):
    path = request.url.path
    request.state.user_id = request.state.user_name = request.state.session_id = None
    if request.method == "OPTIONS" or path in PUBLIC_PATHS or path.startswith(PUBLIC_PREFIXES):
        return await call_next(request)
    key = get_settings().api_key
    sent_key = request.headers.get("x-api-key")
    if key and sent_key and hmac.compare_digest(sent_key, key):          # server-to-server integrations
        request.state.user_name = "api"
        return await call_next(request)
    found = await run_in_threadpool(_session_lookup, request.cookies.get(auth.COOKIE))
    if not found:
        if path.startswith("/api/"):
            return JSONResponse({"detail": "Please sign in"}, status_code=401)
        nxt = path if path != "/" else ""
        return RedirectResponse("/login" + (f"?next={nxt}" if nxt else ""), status_code=303)
    request.state.user_id, request.state.user_name, request.state.session_id = found
    # CSRF: state-changing calls must come from our own page (custom header => same-origin or CORS-approved)
    if path.startswith("/api/") and request.method not in ("GET", "HEAD") and not request.headers.get("x-requested-with"):
        return JSONResponse({"detail": "Missing X-Requested-With header"}, status_code=403)
    return await call_next(request)


SECURITY_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "strict-origin-when-cross-origin",       # share tokens never leak to linked sites
    "Permissions-Policy": "camera=(), microphone=(), geolocation=(), payment=()",
    "Content-Security-Policy": ("default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; "
                                "img-src 'self' data: blob:; font-src 'self'; connect-src 'self'; "
                                "frame-ancestors 'none'; base-uri 'self'; form-action 'self' https://accounts.google.com; "
                                "object-src 'none'"),
}


@app.middleware("http")
async def observe(request: Request, call_next):
    """Outermost layer: request id, one log line per request, security headers, and a clean JSON error
    (with a reference) instead of a crash page when something unexpected goes wrong."""
    import time
    import uuid
    rid = (request.headers.get("x-request-id") or uuid.uuid4().hex)[:12]
    logs.request_id.set(rid)
    logs.user_name.set("-")
    t0 = time.perf_counter()
    try:
        resp = await call_next(request)
    except Exception:  # noqa: BLE001 - the last safety net: log it, answer politely, keep the server up
        log.exception("unhandled error on %s %s", request.method, request.url.path)
        resp = JSONResponse({"detail": f"Something went wrong on our side. Reference: {rid}"}, status_code=500)
    ms = int((time.perf_counter() - t0) * 1000)
    user = getattr(request.state, "user_name", None) or "-"
    logs.user_name.set(user)
    path = request.url.path
    if not path.startswith(("/static/", "/favicon")):
        level = logging.WARNING if resp.status_code >= 500 else logging.INFO
        log.log(level, "%s %s %s %sms", request.method, path, resp.status_code, ms)
    resp.headers["X-Request-ID"] = rid
    for k, v in SECURITY_HEADERS.items():
        if k == "Content-Security-Policy" and path == "/api/docs":
            continue                            # Swagger UI loads its scripts from a CDN
        resp.headers.setdefault(k, v)
    if request.url.scheme == "https" or request.headers.get("x-forwarded-proto") == "https":
        resp.headers.setdefault("Strict-Transport-Security", "max-age=31536000; includeSubDomains")
    if path.startswith("/api/"):
        resp.headers.setdefault("Cache-Control", "no-store")
    return resp


def get_session():
    s = db.SessionLocal()
    try:
        yield s
    finally:
        s.close()


_extractor_override = None


def set_extractor(e):   # used by tests
    global _extractor_override
    _extractor_override = e


def _process(s: Session, doc: db.SourceDocument):
    """Read a document with the AI configured in Settings → AI connector (usage is logged per call)."""
    try:
        ex = _extractor_override or ai.build_extractor(s, "extraction", doc.id)
    except Exception as e:  # noqa: BLE001 - e.g. no API key, budget used up: shown on the document
        log.warning("document %s not read: %s", doc.id, e)
        doc.status, doc.error = "failed", str(e)
        s.commit()
        return
    pipeline.process(s, doc, ex)


def _run_background(doc_id: int):
    s = db.SessionLocal()
    try:
        doc = s.get(db.SourceDocument, doc_id)
        if doc:
            _process(s, doc)
    except Exception:  # noqa: BLE001 - background work must never take the server down
        log.exception("background processing of document %s failed", doc_id)
        s.rollback()
        doc = s.get(db.SourceDocument, doc_id)
        if doc and doc.status == "processing":
            doc.status, doc.error = "failed", "Unexpected error while reading - press Try again"
            s.commit()
    finally:
        s.close()


def _doc_summary(d: db.SourceDocument) -> dict:
    stats = (d.normalized or {}).get("stats", {})
    return {"id": d.id, "filename": d.filename, "status": d.status, "document_type": d.document_type,
            "media_type": d.media_type,
            "supplier": ((d.normalized or {}).get("supplier") or {}).get("name") or d.supplier_hint,
            "created_at": d.created_at and d.created_at.isoformat(), "stats": stats,
            "errors": stats.get("errors", 0), "warnings": stats.get("warnings", 0),
            "error": (d.error or "").split("\n")[0] or None}


# ------------------------------------------------------------------ pages
@app.get("/", include_in_schema=False)
def index():
    return FileResponse(STATIC / "index.html", headers={"Cache-Control": "no-store"})


@app.get("/login", include_in_schema=False)
def login_page(request: Request):
    s = db.SessionLocal()
    try:
        if auth.session_user(s, request.cookies.get(auth.COOKIE)):
            return RedirectResponse("/", status_code=303)
    finally:
        s.close()
    return FileResponse(STATIC / "login.html", headers={"Cache-Control": "no-store"})


@app.get("/app.js", include_in_schema=False)
def app_js():
    return FileResponse(STATIC / "app.js", media_type="text/javascript")


@app.get("/favicon.ico", include_in_schema=False)
def favicon():
    return FileResponse(STATIC / "brand" / "favicon.png", media_type="image/png")


def _download(data: bytes, filename: str, media: str, inline: bool = False) -> Response:
    disp = "inline" if inline else "attachment"
    return Response(data, media_type=media, headers={"Content-Disposition": f'{disp}; filename="{filename}"'})


def _slug(s: str) -> str:
    import re
    return re.sub(r"[^A-Za-z0-9]+", "-", s or "trip").strip("-")[:60] or "trip"


@app.get("/api/health")
def health():
    return {"ok": True}


# ------------------------------------------------------------------ documents
@app.post("/api/documents", status_code=202)
async def upload(bg: BackgroundTasks, file: UploadFile = File(...), supplier: str | None = Form(None),
                 s: Session = Depends(get_session)):
    data = await file.read()
    if not data:
        raise HTTPException(400, "Empty file")
    runtime.refresh(s)
    limit = get_settings().max_upload_mb
    if len(data) > limit * 1024 * 1024:
        raise HTTPException(413, f"File is larger than {limit} MB - compress the PDF or split it")
    try:
        doc, is_new = pipeline.intake(s, file.filename or "upload", data, supplier or None)
    except pipeline.PipelineError as e:
        raise HTTPException(400, str(e))
    if is_new or doc.status == "failed":
        if get_settings().process_mode == "background":
            doc.status = "processing"
            s.commit()
            bg.add_task(_run_background, doc.id)
        else:
            _process(s, doc)
    return {**_doc_summary(doc), "duplicate": not is_new}


@app.get("/api/documents")
def list_documents(status: str | None = None, s: Session = Depends(get_session)):
    q = select(db.SourceDocument).order_by(db.SourceDocument.id.desc())
    if status:
        q = q.where(db.SourceDocument.status == status)
    return [_doc_summary(d) for d in s.scalars(q).all()]


def _get(s, doc_id) -> db.SourceDocument:
    d = s.get(db.SourceDocument, doc_id)
    if not d:
        raise HTTPException(404, "Document not found")
    return d


@app.get("/api/documents/{doc_id}")
def get_document(doc_id: int, include_text: bool = False, s: Session = Depends(get_session)):
    d = _get(s, doc_id)
    out = {**_doc_summary(d), "error": d.error, "extraction": d.extraction, "normalized": d.normalized,
           "issues": d.issues or [], "model": d.model, "changes": d.changes,
           "approved_at": d.approved_at and d.approved_at.isoformat(), "approved_by": d.approved_by}
    if include_text:
        out["parsed_text"] = d.parsed_text
    return out


@app.get("/api/documents/{doc_id}/file")
def get_file(doc_id: int, s: Session = Depends(get_session)):
    d = _get(s, doc_id)
    return Response(d.content, media_type=d.media_type or "application/octet-stream",
                    headers={"Content-Disposition": f'inline; filename="{d.filename}"'})


class Overrides(BaseModel):
    valid_from: str | None = None
    valid_to: str | None = None
    currency: str | None = None
    rate_type: str | None = None   # net | rack
    taxes: str | None = None       # included | excluded
    approved_by: str | None = None
    # per package (by its position in the document): "auto", "new", or the family id it is a new version of
    package_links: dict[str, int | str] | None = None

    def as_dict(self):
        return {k: v for k, v in self.model_dump().items() if v and k != "approved_by"}


@app.post("/api/documents/{doc_id}/preview")
def preview(doc_id: int, ov: Overrides = Body(default_factory=Overrides), s: Session = Depends(get_session)):
    d = _get(s, doc_id)
    if not d.extraction:
        raise HTTPException(409, f"Document is {d.status}")
    return pipeline.preview(s, d, ov.as_dict())


@app.put("/api/documents/{doc_id}/extraction")
def edit_extraction(doc_id: int, extraction: dict = Body(...), s: Session = Depends(get_session)):
    d = _get(s, doc_id)
    try:
        pipeline.update_extraction(s, d, extraction)
    except Exception as e:  # noqa: BLE001 - validation errors go back to the reviewer
        raise HTTPException(422, str(e))
    return get_document(doc_id, s=s)


@app.post("/api/documents/{doc_id}/approve")
def approve(doc_id: int, request: Request, ov: Overrides = Body(default_factory=Overrides), s: Session = Depends(get_session)):
    d = _get(s, doc_id)
    try:
        stats = pipeline.approve(s, d, ov.as_dict(), approved_by=ov.approved_by or getattr(request.state, "user_name", None))
    except pipeline.PipelineError as e:
        raise HTTPException(409, str(e))
    return {"status": "approved", "loaded": stats}


@app.post("/api/documents/manual")
def manual_document(request: Request, data: dict = Body(default={}), s: Session = Depends(get_session)):
    """Start a manual entry: an empty document to type rates, packages or add-ons into."""
    doc = pipeline.create_manual(s, data.get("supplier"), data.get("document_type") or "mixed",
                                 getattr(request.state, "user_name", None))
    return get_document(doc.id, s=s)


@app.delete("/api/documents/{doc_id}")
def discard_document(doc_id: int, s: Session = Depends(get_session)):
    try:
        pipeline.discard(s, _get(s, doc_id))
    except pipeline.PipelineError as e:
        raise HTTPException(409, str(e))
    return {"deleted": doc_id}


@app.post("/api/documents/{doc_id}/undo")
def undo_document(doc_id: int, s: Session = Depends(get_session)):
    """Take an approved document out of the library, restoring the earlier rates."""
    try:
        return pipeline.undo(s, _get(s, doc_id))
    except pipeline.PipelineError as e:
        raise HTTPException(409, str(e))


@app.post("/api/documents/{doc_id}/reject")
def reject(doc_id: int, s: Session = Depends(get_session)):
    try:
        pipeline.reject(s, _get(s, doc_id))
    except pipeline.PipelineError as e:
        raise HTTPException(409, str(e))
    return {"status": "rejected"}


@app.post("/api/documents/{doc_id}/reprocess", status_code=202)
def reprocess(doc_id: int, bg: BackgroundTasks, s: Session = Depends(get_session)):
    d = _get(s, doc_id)
    if d.status == "approved":
        raise HTTPException(409, "Already approved")
    if d.media_type == "application/x-manual":
        raise HTTPException(409, "A manual entry has no file to read again")
    if get_settings().process_mode == "background":
        d.status = "processing"
        s.commit()
        bg.add_task(_run_background, d.id)
    else:
        _process(s, d)
    return {"status": d.status}


# ------------------------------------------------------------------ rates (search + pricing)
@app.get("/api/rates/hotels")
def hotel_rates(destination: str | None = None, hotel: str | None = None, on_date: date | None = None,
                meal_plan: str | None = None, occupancy: str = "double", max_amount: float | None = None,
                net_only: bool = False, s: Session = Depends(get_session)):
    return rates.search_hotel_rates(s, destination, hotel, on_date, meal_plan, occupancy, max_amount, net_only)


@app.get("/api/rates/services")
def service_rates(destination: str | None = None, kind: str | None = None, q: str | None = None,
                  on_date: date | None = None, s: Session = Depends(get_session)):
    return rates.search_services(s, destination, kind, q, on_date)


@app.get("/api/packages")
def packages_valid(destination: str | None = None, on_date: date | None = None, s: Session = Depends(get_session)):
    return rates.search_packages(s, destination, on_date)


@app.get("/api/hotels")
def hotels_with_rooms(q: str | None = None, s: Session = Depends(get_session)):
    return [h for h in catalog.hotels(s, q=q) if h["rates"]]


class StayRequest(BaseModel):
    hotel_id: int
    room_type: str
    meal_plan: str
    check_in: date
    check_out: date
    rooms: list[dict] = [{"adults": 2}]
    prefer_net: bool = True
    markup_pct: float = 0


@app.post("/api/quote/hotel-stay")
def quote_stay(req: StayRequest, s: Session = Depends(get_session)):
    try:
        return rates.price_hotel_stay(s, **req.model_dump())
    except ValueError as e:
        raise HTTPException(400, str(e))


@app.get("/api/alerts/expiring")
def expiring(days: int = Query(30, ge=1, le=365), s: Session = Depends(get_session)):
    return rates.expiring_soon(s, days)


# ------------------------------------------------------------------ catalog
@app.get("/api/catalog/summary")
def cat_summary(s: Session = Depends(get_session)):
    return catalog.summary(s)


@app.get("/api/catalog/hotels")
def cat_hotels(q: str | None = None, city: str | None = None, category: str | None = None,
               has_rates: bool | None = None, s: Session = Depends(get_session)):
    return catalog.hotels(s, q, city, category, has_rates)


@app.get("/api/catalog/hotels/{hotel_id}")
def cat_hotel(hotel_id: int, s: Session = Depends(get_session)):
    return catalog.hotel_detail(s, hotel_id) or _404()


@app.get("/api/catalog/packages")
def cat_packages(q: str | None = None, destination: str | None = None, on_date: date | None = None,
                 s: Session = Depends(get_session)):
    return catalog.packages(s, q, destination, on_date)


@app.get("/api/catalog/packages/{package_id}")
def cat_package(package_id: int, s: Session = Depends(get_session)):
    return catalog.package_full(s, package_id) or _404()


@app.get("/api/catalog/packages/{package_id}/price")
def cat_package_price(package_id: int, category: str | None = None, adults: int = 2, extra_beds: int = 0,
                      children_with_bed: int = 0, children_without_bed: int = 0, single_rooms: int = 0,
                      travel_date: date | None = None, pax_tier: int | None = None, s: Session = Depends(get_session)):
    pkg = s.get(db.Package, package_id) or _404()
    try:
        return trips.price_package(pkg, category, adults, extra_beds, children_with_bed, children_without_bed,
                                   single_rooms, travel_date, pax_tier)
    except trips.TripError as e:
        raise HTTPException(400, str(e))


@app.get("/api/catalog/services")
def cat_services(q: str | None = None, destination: str | None = None, kind: str | None = None,
                 on_date: date | None = None, s: Session = Depends(get_session)):
    return catalog.services(s, q, destination, kind, on_date)


@app.get("/api/catalog/places")
def cat_places(q: str | None = None, destination: str | None = None, s: Session = Depends(get_session)):
    return catalog.places(s, q, destination)


@app.get("/api/catalog/suppliers")
def cat_suppliers(s: Session = Depends(get_session)):
    return catalog.suppliers(s)


def _cguard(fn, *a, **k):
    try:
        return fn(*a, **k)
    except (catalog.EditError, ValueError) as e:
        raise HTTPException(400, str(e))


@app.patch("/api/catalog/hotel-rates/{rate_id}")
def edit_hotel_rate(rate_id: int, request: Request, data: dict = Body(...), s: Session = Depends(get_session)):
    """Correct a live hotel rate (amount, dates, notes), or {"status": "retired"} to take it out of use."""
    return _cguard(catalog.edit_rate, s, db.HotelRate, rate_id, data, request.state.user_name)


@app.patch("/api/catalog/services/{rate_id}")
def edit_service_rate(rate_id: int, request: Request, data: dict = Body(...), s: Session = Depends(get_session)):
    return _cguard(catalog.edit_rate, s, db.ServiceRate, rate_id, data, request.state.user_name)


@app.get("/api/catalog/suppliers/{supplier_id}")
def cat_supplier(supplier_id: int, s: Session = Depends(get_session)):
    return catalog.supplier_detail(s, supplier_id) or _404()


@app.patch("/api/catalog/suppliers/{supplier_id}")
def edit_supplier(supplier_id: int, data: dict = Body(...), s: Session = Depends(get_session)):
    return _cguard(catalog.update_supplier, s, supplier_id, data)


@app.post("/api/catalog/suppliers/{supplier_id}/merge")
def merge_supplier(supplier_id: int, data: dict = Body(...), s: Session = Depends(get_session)):
    """Move everything of supplier `merge_id` into this one and remove it."""
    return _cguard(catalog.merge_suppliers, s, supplier_id, int(data["merge_id"]))


@app.get("/api/library/days")
def library(q: str | None = None, destination: str | None = None, s: Session = Depends(get_session)):
    return trips.library_days(s, q, destination)


def _404():
    raise HTTPException(404, "Not found")


# ------------------------------------------------------------------ trips
def _trip(s, trip_id) -> db.Trip:
    return s.get(db.Trip, trip_id) or _404()


def _guard(fn, *a, **k):
    try:
        return fn(*a, **k)
    except (trips.TripError, ValueError) as e:
        raise HTTPException(400, str(e))


@app.get("/api/trips")
def list_trips(templates: bool = False, s: Session = Depends(get_session)):
    out = []
    quotes = dict(s.execute(select(db.Quotation.trip_id, func.count(db.Quotation.id)).group_by(db.Quotation.trip_id)).all())
    for t in s.scalars(select(db.Trip).where(db.Trip.is_template.is_(templates)).order_by(db.Trip.id.desc())).all():
        tt = trips.totals(t)
        out.append({"id": t.id, "title": t.title, "customer_name": t.customer_name, "customer_phone": t.customer_phone,
                    "destination": t.destination, "start_date": t.start_date and t.start_date.isoformat(),
                    "status": t.status, "assigned_to": t.assigned_to, "lead_source": t.lead_source,
                    "follow_up_date": t.follow_up_date and t.follow_up_date.isoformat(),
                    "travellers": tt["travellers"], "sell": tt["sell"], "balance": tt["balance"],
                    "currency": tt["currency"], "updated_at": t.updated_at and t.updated_at.isoformat(),
                    "is_from_price": tt["is_from_price"], "options": len(tt["options"]), "quotations": quotes.get(t.id, 0),
                    "days": len(t.days)})
    return out


@app.post("/api/trips")
def new_trip(request: Request, data: dict = Body(...), s: Session = Depends(get_session)):
    data.setdefault("created_by", request.state.user_name)
    q = company.get_all(s)["quote"]
    data.setdefault("markup_pct", q.get("default_markup_pct", 0))
    data.setdefault("gst_pct", q.get("default_gst_pct", 0))
    t = _guard(trips.create_trip, s, data)
    if data.get("package_id"):
        _guard(trips.apply_package, s, t, int(data["package_id"]), data.get("category"),
               all_categories=bool(data.get("all_categories")))
    return trips.trip_view(s, t)


@app.get("/api/trips/{trip_id}")
def get_trip(trip_id: int, s: Session = Depends(get_session)):
    return trips.trip_view(s, _trip(s, trip_id))


@app.patch("/api/trips/{trip_id}")
def patch_trip(trip_id: int, request: Request, data: dict = Body(...), s: Session = Depends(get_session)):
    t = _trip(s, trip_id)
    data.setdefault("by", request.state.user_name)
    _guard(trips.update_trip, s, t, data)
    return trips.trip_view(s, t)


@app.delete("/api/trips/{trip_id}")
def delete_trip(trip_id: int, s: Session = Depends(get_session)):
    t = _trip(s, trip_id)
    # quotations are the sales history: they stay, detached from the deleted trip
    for q in s.scalars(select(db.Quotation).where(db.Quotation.trip_id == t.id)).all():
        q.trip_id = None
    s.delete(t)
    s.commit()
    return {"deleted": trip_id}


@app.post("/api/trips/{trip_id}/apply-package")
def trip_apply_package(trip_id: int, data: dict = Body(...), s: Session = Depends(get_session)):
    t = _trip(s, trip_id)
    _guard(trips.apply_package, s, t, int(data["package_id"]), data.get("category"),
           data.get("replace_days", True), data.get("include_price", True), bool(data.get("all_categories")))
    return trips.trip_view(s, t)


@app.post("/api/trips/{trip_id}/upgrade-package")
def trip_upgrade_package(trip_id: int, data: dict = Body(...), s: Session = Depends(get_session)):
    t = _trip(s, trip_id)
    _guard(trips.upgrade_package, s, t, int(data["from_id"]), int(data["to_id"]))
    return trips.trip_view(s, t)


@app.post("/api/trips/{trip_id}/save-template")
def trip_save_template(trip_id: int, data: dict = Body(default={}), s: Session = Depends(get_session)):
    """Keep a copy of this trip's itinerary and costing as a reusable template (no customer, no payments)."""
    t = _trip(s, trip_id)
    tpl = trips.duplicate(s, t, data.get("title") or t.title)
    tpl.is_template, tpl.customer_name, tpl.customer_phone, tpl.customer_email = True, None, None, None
    tpl.start_date = tpl.follow_up_date = None
    tpl.notes_log[-1].text = f"Template made from trip #{t.id} ({t.title})"
    s.commit()
    return trips.trip_view(s, tpl)


@app.put("/api/trips/{trip_id}/days")
def trip_days(trip_id: int, days: list[dict] = Body(...), s: Session = Depends(get_session)):
    t = _trip(s, trip_id)
    trips.set_days(s, t, days)
    return trips.trip_view(s, t)


@app.post("/api/trips/{trip_id}/days/from-library")
def trip_add_library(trip_id: int, data: dict = Body(...), s: Session = Depends(get_session)):
    t = _trip(s, trip_id)
    _guard(trips.add_library_days, s, t, [int(i) for i in data["day_ids"]], data.get("after_position"))
    return trips.trip_view(s, t)


@app.post("/api/trips/{trip_id}/items")
def trip_add_item(trip_id: int, data: dict = Body(...), s: Session = Depends(get_session)):
    t = _trip(s, trip_id)
    kind = data.get("kind")
    if kind == "hotel":
        _guard(trips.add_hotel, s, t, int(data["hotel_id"]), data["room_type"], data["meal_plan"],
               int(data.get("nights") or 1), int(data.get("day_position") or 1),
               date.fromisoformat(data["check_in"]) if data.get("check_in") else None, data.get("rooms"),
               data.get("option_label"))
    elif kind == "service":
        _guard(trips.add_service, s, t, int(data["service_id"]), data.get("day_position"), data.get("quantity"),
               data.get("optional"), data.get("option_label"))
    elif kind == "package":
        if data.get("all_categories"):          # one priced line per hotel category, each its own option
            pkg = s.get(db.Package, int(data["package_id"])) or _404()
            for cat in trips.package_categories(pkg):
                _guard(trips.add_package_price, s, t, pkg.id, cat, cat)
        else:
            _guard(trips.add_package_price, s, t, int(data["package_id"]), data.get("category"),
                   data.get("option_label"), data.get("day_position"))
    elif kind == "custom":
        _guard(trips.add_custom, s, t, data.get("description") or "", float(data.get("unit_amount") or 0),
               float(data.get("quantity") or 1), data.get("day_position"), bool(data.get("optional")),
               data.get("currency"), data.get("option_label"))
    else:
        raise HTTPException(400, "kind must be hotel, service, package or custom")
    return trips.trip_view(s, t)


@app.patch("/api/trips/{trip_id}/items/{item_id}")
def trip_edit_item(trip_id: int, item_id: int, data: dict = Body(...), s: Session = Depends(get_session)):
    t = _trip(s, trip_id)
    _guard(trips.update_item, s, t, item_id, data)
    return trips.trip_view(s, t)


@app.delete("/api/trips/{trip_id}/items/{item_id}")
def trip_delete_item(trip_id: int, item_id: int, s: Session = Depends(get_session)):
    t = _trip(s, trip_id)
    _guard(trips.delete_item, s, t, item_id)
    return trips.trip_view(s, t)


@app.post("/api/trips/{trip_id}/reprice")
def trip_reprice(trip_id: int, s: Session = Depends(get_session)):
    t = _trip(s, trip_id)
    _guard(trips.reprice_trip, s, t)
    return trips.trip_view(s, t)


@app.get("/api/trips/{trip_id}/text", response_class=PlainTextResponse)
def trip_text(trip_id: int, prices: bool = True, s: Session = Depends(get_session)):
    return trips.itinerary_text(s, _trip(s, trip_id), prices)


@app.post("/api/trips/{trip_id}/duplicate")
def trip_duplicate(trip_id: int, data: dict = Body(default={}), s: Session = Depends(get_session)):
    return trips.trip_view(s, trips.duplicate(s, _trip(s, trip_id), data.get("title")))


@app.post("/api/trips/{trip_id}/notes")
def trip_note(trip_id: int, request: Request, data: dict = Body(...), s: Session = Depends(get_session)):
    t = _trip(s, trip_id)
    _guard(trips.add_note, s, t, data.get("text", ""), data.get("author") or request.state.user_name,
           data.get("follow_up_date"))
    return trips.trip_view(s, t)


@app.post("/api/trips/{trip_id}/payments")
def trip_payment(trip_id: int, data: dict = Body(...), s: Session = Depends(get_session)):
    t = _trip(s, trip_id)
    _guard(trips.add_payment, s, t, float(data.get("amount") or 0), data.get("paid_on"), data.get("mode"),
           data.get("reference"), data.get("note"))
    return trips.trip_view(s, t)


@app.delete("/api/trips/{trip_id}/payments/{payment_id}")
def trip_payment_delete(trip_id: int, payment_id: int, s: Session = Depends(get_session)):
    t = _trip(s, trip_id)
    _guard(trips.delete_payment, s, t, payment_id)
    return trips.trip_view(s, t)


@app.post("/api/trips/{trip_id}/share")
def trip_share(trip_id: int, data: dict = Body(default={}), s: Session = Depends(get_session)):
    t = _trip(s, trip_id)
    trips.share(s, t, data.get("enable", True), data.get("prices"))
    return trips.trip_view(s, t)


def _trip_pdf(s: Session, t: db.Trip, prices: bool) -> bytes:
    settings = company.get_all(s)
    return pdfgen.trip_pdf(trips.trip_view(s, t), settings, company.team_member(s, t.assigned_to), prices)


@app.get("/api/trips/{trip_id}/pdf")
def trip_pdf(trip_id: int, prices: bool = True, s: Session = Depends(get_session)):
    t = _trip(s, trip_id)
    kind = "Quote" if prices else "Itinerary"
    return _download(_trip_pdf(s, t, prices), f"{kind}-{t.id}-{_slug(t.title)}.pdf", "application/pdf")


@app.get("/api/trips/{trip_id}/csv")
def trip_csv(trip_id: int, part: str = "costing", s: Session = Depends(get_session)):
    t = _trip(s, trip_id)
    rows = exports.rows_trip_itinerary(s, t) if part == "itinerary" else exports.rows_trip_costing(s, t)
    return _download(exports.to_csv(rows), f"Trip-{t.id}-{part}.csv", "text/csv")


@app.get("/api/trips/{trip_id}/xlsx")
def trip_xlsx(trip_id: int, s: Session = Depends(get_session)):
    t = _trip(s, trip_id)
    data = exports.to_xlsx({"Itinerary": exports.rows_trip_itinerary(s, t), "Costing": exports.rows_trip_costing(s, t)})
    return _download(data, f"Trip-{t.id}-{_slug(t.title)}.xlsx",
                     "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")


@app.get("/api/catalog/packages/{package_id}/pdf")
def package_pdf(package_id: int, s: Session = Depends(get_session)):
    p = catalog.package_full(s, package_id) or _404()
    return _download(pdfgen.package_pdf(p, company.get_all(s)), f"Rate-card-{_slug(p['title'])}.pdf", "application/pdf")


@app.get("/api/catalog/packages/{package_id}/csv")
def package_csv(package_id: int, part: str = "prices", s: Session = Depends(get_session)):
    s.get(db.Package, package_id) or _404()
    rows = exports.rows_package_itinerary(s, package_id) if part == "itinerary" else exports.rows_packages(s, package_id)
    return _download(exports.to_csv(rows), f"Package-{package_id}-{part}.csv", "text/csv")


@app.get("/api/export/library.xlsx")
def export_library(s: Session = Depends(get_session)):
    return _download(exports.library_xlsx(s), f"Travel-Episodes-library-{date.today()}.xlsx",
                     "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")


@app.get("/api/export/{what}.csv")
def export_csv(what: str, s: Session = Depends(get_session)):
    fn = exports.EXPORTS.get(what) or _404()
    return _download(exports.to_csv(fn(s)), f"{what}-{date.today()}.csv", "text/csv")


@app.get("/api/dashboard")
def dashboard(s: Session = Depends(get_session)):
    out = trips.dashboard(s)
    out["library"] = catalog.summary(s)
    out["expiring"] = rates.expiring_soon(s, 30)[:8]
    return out


@app.get("/api/settings")
def get_settings_api(s: Session = Depends(get_session)):
    return company.get_all(s)


@app.put("/api/settings")
def put_settings(data: dict = Body(...), s: Session = Depends(get_session)):
    return company.save(s, data)


# ------------------------------------------------------------------ rate history
@app.get("/api/catalog/hotels/{hotel_id}/history")
def cat_hotel_history(hotel_id: int, s: Session = Depends(get_session)):
    return history.hotel_history(s, hotel_id) or _404()


@app.get("/api/catalog/packages/{package_id}/versions")
def cat_package_versions(package_id: int, s: Session = Depends(get_session)):
    return history.package_versions(s, package_id) or _404()


@app.get("/api/changes")
def rate_changes(days: int = Query(90, ge=1, le=730), s: Session = Depends(get_session)):
    """Price increases and decreases from the supplier sheets approved in the last `days` days."""
    return history.recent_changes(s, days)


# ------------------------------------------------------------------ quotations
def _quote(s, qid) -> db.Quotation:
    return s.get(db.Quotation, qid) or _404()


def _qguard(fn, *a, **k):
    try:
        return fn(*a, **k)
    except (quotes.QuoteError, trips.TripError, ValueError) as e:
        raise HTTPException(400, str(e))


@app.get("/api/quotations")
def list_quotations(q: str | None = None, status: str | None = None, trip_id: int | None = None,
                    s: Session = Depends(get_session)):
    return quotes.listing(s, q, status, trip_id)


@app.post("/api/trips/{trip_id}/quotations")
def save_quotation(trip_id: int, request: Request, data: dict = Body(default={}), s: Session = Depends(get_session)):
    t = _trip(s, trip_id)
    q = _qguard(quotes.save, s, t, request.state.user_name, data.get("note"), data.get("valid_days"))
    return quotes.view(q)


@app.get("/api/quotations/{qid}")
def get_quotation(qid: int, s: Session = Depends(get_session)):
    return quotes.view(_quote(s, qid), full=True)


@app.patch("/api/quotations/{qid}")
def patch_quotation(qid: int, data: dict = Body(...), s: Session = Depends(get_session)):
    return quotes.view(_qguard(quotes.patch, s, _quote(s, qid), data))


@app.post("/api/quotations/{qid}/update")
def update_quotation(qid: int, request: Request, s: Session = Depends(get_session)):
    """Save the trip's current itinerary and costing into this quotation (same number)."""
    return quotes.view(_qguard(quotes.update, s, _quote(s, qid), request.state.user_name))


@app.post("/api/quotations/{qid}/restore")
def restore_quotation(qid: int, request: Request, s: Session = Depends(get_session)):
    """Load this quotation back into its trip to edit it. Returns the trip."""
    t = _qguard(quotes.restore, s, _quote(s, qid), request.state.user_name)
    return trips.trip_view(s, t)


@app.post("/api/quotations/{qid}/new-trip")
def quotation_new_trip(qid: int, request: Request, data: dict = Body(default={}), s: Session = Depends(get_session)):
    """A new trip with this quotation's plan, e.g. for another customer."""
    q = _quote(s, qid)
    t = quotes.new_trip_from(s, q, request.state.user_name, data.get("title") or f"Copy of {q.title}")
    return trips.trip_view(s, t)


@app.delete("/api/quotations/{qid}")
def delete_quotation(qid: int, s: Session = Depends(get_session)):
    s.delete(_quote(s, qid))
    s.commit()
    return {"deleted": qid}


@app.post("/api/quotations/{qid}/share")
def share_quotation(qid: int, data: dict = Body(default={}), s: Session = Depends(get_session)):
    return quotes.view(quotes.share(s, _quote(s, qid), data.get("enable", True), data.get("prices")))


def _quote_view(q: db.Quotation, share_prices: bool | None = None) -> dict:
    v = dict(q.snapshot)
    v["quote"] = {"number": q.number, "valid_until": q.valid_until and q.valid_until.isoformat(), "version": q.version}
    v["share_prices"] = q.share_prices if share_prices is None else share_prices
    return v


def _quote_pdf(s: Session, q: db.Quotation, prices: bool) -> bytes:
    v = _quote_view(q)
    return pdfgen.trip_pdf(v, company.get_all(s), company.team_member(s, v.get("assigned_to")), prices)


@app.get("/api/quotations/{qid}/pdf")
def quotation_pdf(qid: int, prices: bool = True, s: Session = Depends(get_session)):
    q = _quote(s, qid)
    return _download(_quote_pdf(s, q, prices), f"{q.number}-{_slug(q.title)}.pdf", "application/pdf")


@app.get("/api/quotations/{qid}/text", response_class=PlainTextResponse)
def quotation_text(qid: int, s: Session = Depends(get_session)):
    q = _quote(s, qid)
    return f"{q.number}\n" + trips.itinerary_text_from_view(_quote_view(q), q.share_prices)


def _shared_quote(s: Session, token: str) -> db.Quotation:
    q = s.scalar(select(db.Quotation).where(db.Quotation.share_token == token)) if token else None
    if not q:
        raise HTTPException(404, "This link is no longer active")
    return q


@app.get("/q/{token}", response_class=HTMLResponse, include_in_schema=False)
def quote_page(token: str, s: Session = Depends(get_session)):
    q = _shared_quote(s, token)
    v = _quote_view(q)
    return sharepage.render(v, company.get_all(s), company.team_member(s, v.get("assigned_to")), token, base="/q")


@app.get("/q/{token}/pdf", include_in_schema=False)
def quote_page_pdf(token: str, s: Session = Depends(get_session)):
    q = _shared_quote(s, token)
    return _download(_quote_pdf(s, q, q.share_prices), f"{q.number}.pdf", "application/pdf", inline=True)


@app.get("/api/templates")
def list_templates(s: Session = Depends(get_session)):
    return list_trips(templates=True, s=s)


# ------------------------------------------------------------------ public share links (no API key)
def _shared(s: Session, token: str) -> db.Trip:
    t = s.scalar(select(db.Trip).where(db.Trip.share_token == token)) if token else None
    if not t:
        raise HTTPException(404, "This link is no longer active")
    return t


@app.get("/share/{token}", response_class=HTMLResponse, include_in_schema=False)
def share_page(token: str, s: Session = Depends(get_session)):
    t = _shared(s, token)
    return sharepage.render(trips.trip_view(s, t), company.get_all(s), company.team_member(s, t.assigned_to), token)


@app.get("/share/{token}/pdf", include_in_schema=False)
def share_pdf(token: str, s: Session = Depends(get_session)):
    t = _shared(s, token)
    return _download(_trip_pdf(s, t, t.share_prices), f"{_slug(t.title)}.pdf", "application/pdf", inline=True)


# ------------------------------------------------------------------ sign-in & users
def _secure(request: Request) -> bool:
    return request.url.scheme == "https" or request.headers.get("x-forwarded-proto") == "https"


@app.post("/api/auth/login")
def api_login(request: Request, data: dict = Body(...), s: Session = Depends(get_session)):
    runtime.refresh(s)                     # sign-in length saved in Settings → Processing applies on every server
    try:
        token, u = auth.login(s, data.get("email", ""), data.get("password", ""),
                              request.client.host if request.client else None, request.headers.get("user-agent"))
    except auth.AuthError as e:
        raise HTTPException(401, str(e))
    resp = JSONResponse({"user": auth.user_json(u)})
    resp.set_cookie(auth.COOKIE, token, max_age=get_settings().session_days * 86400, httponly=True,
                    samesite="lax", secure=_secure(request), path="/")
    return resp


@app.get("/api/auth/providers")
def api_auth_providers():
    """What the sign-in page offers (public)."""
    return {"password": True, "google": google_auth.enabled()}


def _client(request: Request):
    return (request.client.host if request.client else None), request.headers.get("user-agent")


@app.get("/auth/google/start", include_in_schema=False)
def google_start(request: Request, next: str | None = None):
    try:
        url, cookie = google_auth.start(str(request.base_url), next)
    except google_auth.GoogleAuthError as e:
        return RedirectResponse(f"/login?error={e.code}", status_code=303)
    resp = RedirectResponse(url, status_code=303)
    resp.set_cookie(google_auth.COOKIE, cookie, max_age=google_auth.MAX_AGE, httponly=True, samesite="lax",
                    secure=_secure(request), path="/auth/google")
    return resp


@app.get("/auth/google/callback", include_in_schema=False)
def google_callback(request: Request, code: str | None = None, state: str | None = None, error: str | None = None,
                    s: Session = Depends(get_session)):
    def fail(code_: str, why: str):
        log.warning("Google sign-in refused (%s): %s", code_, why)
        r = RedirectResponse(f"/login?error={code_}", status_code=303)
        r.delete_cookie(google_auth.COOKIE, path="/auth/google")
        return r
    if error:                                   # the person pressed Cancel at Google
        return fail("cancelled", error)
    try:
        claims, nxt = google_auth.finish(str(request.base_url), code, state, request.cookies.get(google_auth.COOKIE))
        u = auth.google_user(s, claims["email"])
    except google_auth.GoogleAuthError as e:
        return fail(e.code, str(e))
    except auth.AuthError as e:
        return fail(str(e), f"{claims.get('email')} is not an active admin")
    runtime.refresh(s)
    if not u.name or u.name == u.email.split("@")[0].title():
        u.name = claims.get("name") or u.name
    token = auth.start_session(s, u, *_client(request))
    log.info("admin %s signed in with Google", u.email)
    resp = RedirectResponse(nxt, status_code=303)
    resp.delete_cookie(google_auth.COOKIE, path="/auth/google")
    resp.set_cookie(auth.COOKIE, token, max_age=get_settings().session_days * 86400, httponly=True,
                    samesite="lax", secure=_secure(request), path="/")
    return resp


@app.post("/api/auth/logout")
def api_logout(request: Request, s: Session = Depends(get_session)):
    auth.logout(s, request.cookies.get(auth.COOKIE))
    resp = JSONResponse({"ok": True})
    resp.delete_cookie(auth.COOKIE, path="/")
    return resp


def _me(request: Request, s: Session) -> db.User:
    u = s.get(db.User, request.state.user_id) if request.state.user_id else None
    if not u:
        raise HTTPException(403, "Sign in as a user for this")
    return u


@app.get("/api/auth/me")
def api_me(request: Request, s: Session = Depends(get_session)):
    return auth.user_json(_me(request, s))


@app.post("/api/auth/password")
def api_change_password(request: Request, data: dict = Body(...), s: Session = Depends(get_session)):
    u = _me(request, s)
    # a Google-only account (signed in with Google) may add a password without a current one
    if auth.has_password(u) and not auth.verify_password(data.get("current_password", ""), u.password_hash):
        raise HTTPException(400, "Current password is wrong")
    try:
        auth.set_password(s, u, data.get("new_password", ""), keep_session_id=request.state.session_id)
    except auth.AuthError as e:
        raise HTTPException(400, str(e))
    return {"ok": True}


@app.get("/api/users")
def api_users(s: Session = Depends(get_session)):
    return [auth.user_json(u) for u in s.scalars(select(db.User).order_by(db.User.name)).all()]


@app.post("/api/users")
def api_add_user(data: dict = Body(...), s: Session = Depends(get_session)):
    try:
        google_only = bool(data.get("google_only")) and not data.get("password")
        u = auth.create_user(s, data.get("email", ""), data.get("name", ""),
                             None if google_only else data.get("password", ""), must_change_password=not google_only)
    except auth.AuthError as e:
        raise HTTPException(400, str(e))
    return auth.user_json(u)


@app.patch("/api/users/{user_id}")
def api_edit_user(user_id: int, request: Request, data: dict = Body(...), s: Session = Depends(get_session)):
    u = s.get(db.User, user_id) or _404()
    try:
        if "name" in data and data["name"]:
            u.name = data["name"].strip()
        if "active" in data:
            if user_id == request.state.user_id and not data["active"]:
                raise auth.AuthError("You can't disable your own account")
            auth.set_active(s, u, bool(data["active"]))
        if data.get("password"):
            auth.set_password(s, u, data["password"])
            u.must_change_password = True
        s.commit()
    except auth.AuthError as e:
        raise HTTPException(400, str(e))
    return auth.user_json(u)


if get_settings().enable_api_docs:
    @app.get("/api/openapi.json", include_in_schema=False)
    def openapi_json():
        return app.openapi()

    @app.get("/api/docs", include_in_schema=False)
    def swagger():
        return get_swagger_ui_html(openapi_url="/api/openapi.json", title="Travel Episodes Studio API")


# ------------------------------------------------------------------ AI connector & processing options
@app.get("/api/ai/settings")
def ai_settings(s: Session = Depends(get_session)):
    return ai.public_view(s)


@app.put("/api/ai/settings")
def ai_settings_save(data: dict = Body(...), s: Session = Depends(get_session)):
    try:
        return ai.save(s, data)
    except (ai.AIError, ValueError) as e:
        raise HTTPException(400, str(e))


@app.post("/api/ai/test")
def ai_test(s: Session = Depends(get_session)):
    return ai.test_connection(s)


@app.get("/api/ai/usage")
def ai_usage(days: int = Query(30, ge=1, le=365), s: Session = Depends(get_session)):
    return ai.usage_summary(s, days)


@app.get("/api/settings/processing")
def processing_get(s: Session = Depends(get_session)):
    return runtime.view(s)


@app.put("/api/settings/processing")
def processing_put(data: dict = Body(...), s: Session = Depends(get_session)):
    try:
        return runtime.save(s, data)
    except ValueError as e:
        raise HTTPException(400, str(e))


# ------------------------------------------------------------------ system status (read-only)
APP_VERSION = app.version


@app.get("/api/system")
def system_status(s: Session = Depends(get_session)):
    """Server-level configuration that can't live in the database (it's needed to reach the database).
    Shows only whether each secret is set, never its value."""
    import os
    import platform
    from sqlalchemy import func as sfunc

    from . import secretbox
    st = get_settings()
    try:
        dbi = db.database_info()
    except Exception as e:  # noqa: BLE001
        dbi = {"kind": "unreachable", "error": str(e)[:300]}
    env_items = [
        ("DATABASE_URL", bool(st.database_url),
         "Where all data is stored", True),
        ("SECRET_KEY", bool(st.secret_key), "Encrypts AI keys saved in Settings", True),
        ("ADMIN_EMAIL / ADMIN_PASSWORD", bool(st.admin_email and st.admin_password),
         "First admin, created only while there are no users (can be removed after)", False),
        ("API_KEY", bool(st.api_key), "Lets your other systems call this API without signing in", False),
        ("ANTHROPIC_API_KEY", bool(st.anthropic_api_key), "Claude key (or save one in AI connector)", False),
        ("CORS_ORIGINS", bool(st.cors_origins), "Other websites allowed to call the API from a browser", False),
        ("PROCESS_MODE", True, f"Currently '{st.process_mode}' — inline is required on Vercel", False),
        ("CRON_SECRET", bool(st.cron_secret), "Daily job: keeps Supabase Free awake, tidies sign-ins", False),
        ("FIXTURES_DIR", bool(st.fixtures_dir), "Demo mode — must be empty in real use", False),
    ]
    counts = {"users": s.scalar(select(sfunc.count(db.User.id))), "documents": s.scalar(select(sfunc.count(db.SourceDocument.id))),
              "trips": s.scalar(select(sfunc.count(db.Trip.id))), "ai_calls": s.scalar(select(sfunc.count(db.AIUsage.id)))}
    warnings = []
    if st.fixtures_dir:
        warnings.append("Demo mode is on (FIXTURES_DIR is set): uploads use saved examples, not AI.")
    if not st.secret_key:
        warnings.append("SECRET_KEY is not set: AI keys can't be saved from Settings.")
    if dbi.get("supabase_roles") and not dbi.get("data_api_locked"):
        warnings.append("Some tables are readable through Supabase's Data API. Restart the app to lock them.")
    if st.admin_password and counts["users"] > 1:
        warnings.append("ADMIN_PASSWORD is still set on the server. It's only needed once — remove it.")
    return {"version": APP_VERSION, "python": platform.python_version(), "on_vercel": bool(os.environ.get("VERCEL")),
            "database": dbi, "env": [{"name": n, "set": v, "about": a, "required": r} for n, v, a, r in env_items],
            "can_save_keys": secretbox.available(), "counts": counts, "warnings": warnings}


# ------------------------------------------------------------------ daily job (Vercel Cron)
@app.get("/api/cron/daily", include_in_schema=False)
def cron_daily(request: Request, s: Session = Depends(get_session)):
    """Runs once a day (vercel.json → crons). Keeps a Supabase Free project from pausing after a quiet week
    and removes expired sign-in sessions. Vercel sends `Authorization: Bearer <CRON_SECRET>`."""
    from datetime import datetime as _dt

    from sqlalchemy import delete as _delete
    secret = get_settings().cron_secret
    sent = (request.headers.get("authorization") or "").removeprefix("Bearer ").strip()
    if not secret or not hmac.compare_digest(sent, secret):
        raise HTTPException(401, "Not allowed")
    removed = s.execute(_delete(db.UserSession).where(db.UserSession.expires_at < _dt.utcnow())).rowcount
    s.commit()
    expired = quotes.expire_old(s)
    return {"ok": True, "expired_sessions_removed": removed, "quotations_expired": expired,
            "trips": s.scalar(select(func_count(db.Trip.id)))}


def func_count(col):
    from sqlalchemy import func as _f
    return _f.count(col)
