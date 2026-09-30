"""Pipeline orchestration: intake -> parse -> extract -> normalize/validate -> review -> load."""
from __future__ import annotations

import hashlib
import inspect
import mimetypes
import logging
import traceback
from datetime import datetime
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from . import db, runtime
from .config import get_settings
from .extractor import Extractor
from .loader import UndoError, load_document, preview_changes, reference_names, undo_document
from .normalize import normalize
from .parsers import CONVERT_FIRST, SUPPORTED, UnsupportedFile, parse_file, sniff
from .schema import Extraction


log = logging.getLogger(__name__)


class PipelineError(Exception):
    pass


def intake(s: Session, filename: str, data: bytes, supplier_hint: str | None = None) -> tuple[db.SourceDocument, bool]:
    """Store the file and create its record. Returns (doc, is_new). Same file twice -> same record."""
    ext = Path(filename).suffix.lower()
    if not data:
        raise PipelineError("The file is empty")
    real = sniff(data, ext)
    if real in CONVERT_FIRST:
        raise PipelineError(f"This is {CONVERT_FIRST[real]}.")
    if (real in (".docx", ".xlsx", ".xlsm") and not data.startswith(b"PK")) or (real == ".pdf" and b"%PDF" not in data[:1024]):
        raise PipelineError(f"This file is damaged or is not really a {real} file. Open it and save it again, "
                            f"or export it as PDF.")
    if real not in SUPPORTED:
        raise PipelineError(f"Unsupported file type '{ext or filename}'. Upload PDF, Excel (.xlsx/.xls), CSV, "
                            f"Word (.docx), XML, HTML, JSON, text or a photo (JPG/PNG/WEBP).")
    sha = hashlib.sha256(data).hexdigest()
    existing = s.scalar(select(db.SourceDocument).where(db.SourceDocument.sha256 == sha))
    if existing:
        return existing, False
    doc = db.SourceDocument(filename=filename, sha256=sha, media_type=mimetypes.guess_type(filename)[0],
                            size_bytes=len(data), content=data, supplier_hint=supplier_hint, status="uploaded")
    s.add(doc)
    s.commit()
    return doc, True


def process(s: Session, doc: db.SourceDocument, extractor: Extractor) -> db.SourceDocument:
    """Parse + extract + normalize. Leaves the doc in needs_review (or approved with AUTO_APPROVE)."""
    runtime.refresh(s)
    doc.status, doc.error = "processing", None
    s.commit()
    try:
        parsed = parse_file(doc.filename, doc.content)
        doc.parsed_text = parsed.text
        # names this supplier's earlier sheets used, so the AI spells repeats the same way (fewer duplicates)
        reference = reference_names(s, doc.supplier_hint, doc.filename)
        if "reference" in inspect.signature(extractor.extract).parameters:
            extraction = extractor.extract(parsed, doc.filename, doc.supplier_hint, reference=reference)
        else:                      # an extractor written before `reference` existed
            extraction = extractor.extract(parsed, doc.filename, doc.supplier_hint)
        doc.extraction = extraction
        doc.model = extractor.model_name
        doc.document_type = extraction.get("document_type")
        _renormalize(doc)
        doc.status = "needs_review"
        doc.processed_at = datetime.now()
        s.commit()
        refresh_changes(s, doc)
        if get_settings().auto_approve and not _errors(doc):
            approve(s, doc, approved_by="auto")
    except Exception as e:  # noqa: BLE001 - we want every failure recorded on the document
        s.rollback()
        doc.status = "failed"
        if isinstance(e, UnsupportedFile):
            doc.error = str(e)                    # a clear message for the user; nothing to debug
            log.info("document %s could not be read: %s", doc.id, e)
        else:
            doc.error = f"{type(e).__name__}: {e}\n{traceback.format_exc(limit=3)}"
            log.exception("document %s failed while reading", doc.id)
        s.commit()
    return doc


def ingest(s: Session, filename: str, data: bytes, extractor: Extractor, supplier_hint: str | None = None):
    doc, is_new = intake(s, filename, data, supplier_hint)
    if is_new or doc.status == "failed":
        process(s, doc, extractor)
    return doc, is_new


def _renormalize(doc: db.SourceDocument, overrides: dict | None = None):
    from sqlalchemy.orm import object_session
    if object_session(doc):
        runtime.refresh(object_session(doc))
    norm = normalize(doc.extraction, overrides)
    doc.normalized = norm
    doc.issues = norm["issues"]


def _errors(doc):
    return [i for i in (doc.issues or []) if i["level"] == "error"]


def update_extraction(s: Session, doc: db.SourceDocument, extraction: dict) -> db.SourceDocument:
    """Reviewer edited the extracted JSON: validate it against the contract and re-check."""
    if doc.status == "approved":
        raise PipelineError("Document already approved - upload a corrected sheet instead")
    doc.extraction = Extraction.model_validate(extraction).model_dump()
    doc.document_type = doc.extraction["document_type"]
    _renormalize(doc)
    doc.status = "needs_review"
    doc.error = None
    s.commit()
    refresh_changes(s, doc)
    return doc


def _with_links(norm: dict, overrides: dict | None) -> dict:
    """The reviewer's choice per package: 'auto', 'new', or the family id it is a new version of."""
    links = (overrides or {}).get("package_links")
    if links:
        norm["package_links"] = {str(k): v for k, v in links.items()}
    return norm


def preview(s: Session, doc: db.SourceDocument, overrides: dict | None = None) -> dict:
    """Checks + what approving would change in the library (nothing is written)."""
    norm = _with_links(normalize(doc.extraction, overrides), overrides)
    out = dict(norm)
    if doc.status == "needs_review" and not [i for i in norm["issues"] if i["level"] == "error"]:
        try:
            out["changes"] = preview_changes(s, doc, norm)
        except Exception as e:  # noqa: BLE001 - a preview must never block the review screen
            out["changes"] = {"error": f"{type(e).__name__}: {e}"}
    return out


def refresh_changes(s: Session, doc: db.SourceDocument, overrides: dict | None = None) -> None:
    """Store the change preview on a document waiting for review (shown on the review screen)."""
    if doc.status != "needs_review" or _errors(doc):
        if doc.status == "needs_review" and doc.changes:
            doc.changes = None                  # an old preview would be misleading while there are errors
            s.commit()
        return
    try:
        doc_id = doc.id
        changes = preview_changes(s, doc, _with_links(dict(doc.normalized), overrides))
        doc = s.get(db.SourceDocument, doc_id)
        doc.changes = changes
        s.commit()
    except Exception:  # noqa: BLE001 - the preview is a convenience; review still works without it
        log.exception("change preview failed for document %s", getattr(doc, "id", "?"))
        s.rollback()


def approve(s: Session, doc: db.SourceDocument, overrides: dict | None = None, approved_by: str | None = None) -> dict:
    if doc.status == "approved":
        raise PipelineError("Already approved")
    if not doc.extraction:
        raise PipelineError(f"Document is '{doc.status}', nothing to approve")
    _renormalize(doc, overrides)
    if errs := _errors(doc):
        s.commit()
        raise PipelineError(f"{len(errs)} error(s) must be fixed first: " + "; ".join(e["message"] for e in errs[:5]))
    try:
        stats = load_document(s, doc, _with_links(dict(doc.normalized), overrides))
        doc.status = "approved"
        doc.approved_at = datetime.now()
        doc.approved_by = approved_by
        s.commit()
        return stats
    except Exception:
        s.rollback()
        raise


def reject(s: Session, doc: db.SourceDocument):
    if doc.status == "approved":
        raise PipelineError("Already approved")
    doc.status = "rejected"
    s.commit()


def create_manual(s: Session, supplier: str | None, document_type: str = "mixed", by: str | None = None) -> db.SourceDocument:
    """A document for rates typed in by hand (a phone quote, a WhatsApp message): it goes through the same
    checks, change preview and approval as an uploaded file."""
    import uuid
    name = (supplier or "").strip()
    stamp = datetime.now().strftime("%d %b %Y %H:%M")
    doc = db.SourceDocument(filename=f"Manual entry - {name or 'no supplier'} - {stamp}", sha256=uuid.uuid4().hex,
                            media_type="application/x-manual", size_bytes=0, content=b"", supplier_hint=name or None,
                            status="needs_review", model=f"manual ({by})" if by else "manual")
    doc.extraction = Extraction(document_type=document_type if document_type in (
        "hotel_rate_sheet", "dmc_rate_sheet", "package", "mixed") else "mixed",
        supplier={"name": name or None}).model_dump()
    doc.document_type = doc.extraction["document_type"]
    s.add(doc)
    s.flush()
    _renormalize(doc)
    doc.processed_at = datetime.now()
    s.commit()
    log.info("manual entry document %s created by %s", doc.id, by)
    return doc


def discard(s: Session, doc: db.SourceDocument) -> None:
    """Cancel: remove a document that was not saved to the library (the file and what was read from it)."""
    if doc.status == "approved":
        raise PipelineError("This document is in the library. Use 'Take out of library' first.")
    s.delete(doc)
    s.commit()


def undo(s: Session, doc: db.SourceDocument) -> dict:
    try:
        out = undo_document(s, doc)
        _renormalize(doc)
        s.commit()
    except UndoError as e:
        s.rollback()
        raise PipelineError(str(e)) from e
    refresh_changes(s, doc)
    log.info("document %s taken out of the library: %s", doc.id, out)
    return out
