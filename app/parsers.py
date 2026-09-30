"""Stage 1: turn any uploaded file into text the AI can read -- whatever its layout.

Suppliers send the same kind of data in very different shapes (and the same supplier changes its layout),
so this stage does NOT try to understand the layout. It only makes every format readable, keeping the
structure that carries meaning: tables stay tables (cells separated by |), merged header cells are repeated
over the columns they cover, page / sheet boundaries are marked, and headers / footers (where validity is
often printed) are kept. Understanding the content is the AI's job (extractor.py); checking it is plain
code (normalize.py).

  PDF with a text layer   page text + tables (pdfplumber)
  scanned PDF, photos     sent to the AI as the file / image itself (it reads them visually)
  Excel .xlsx/.xlsm/.xls  every visible sheet as a grid; merged cells repeated; formulas as their values
  CSV / TSV               delimiter and encoding detected (Excel's ; and cp1252 exports included)
  Word .docx              paragraphs and tables in document order, plus headers and footers
  XML                     elements as indented "tag: text" lines, attributes kept (safe parser)
  HTML                    text + tables (rate sheets saved from a website or exported by a booking system)
  JSON, TXT, MD           as text

The real type is detected from the file's first bytes, so a web export named ".xls" that is really HTML,
or a ".pdf" that is really an image, is still read correctly. Long sheets are split into parts that
repeat the header rows, so every part keeps its column meaning.
"""
from __future__ import annotations

import csv
import io
import json
import logging
import zipfile
from dataclasses import dataclass, field
from datetime import date, datetime
from html.parser import HTMLParser
from pathlib import Path

log = logging.getLogger(__name__)

PDF_TYPES = {".pdf"}
EXCEL_TYPES = {".xlsx", ".xlsm"}
OLD_EXCEL_TYPES = {".xls"}
CSV_TYPES = {".csv", ".tsv"}
WORD_TYPES = {".docx"}
XML_TYPES = {".xml"}
HTML_TYPES = {".html", ".htm"}
JSON_TYPES = {".json"}
IMAGE_TYPES = {".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png", ".webp": "image/webp",
               ".gif": "image/gif"}
TEXT_TYPES = {".txt", ".md"}

SUPPORTED = (PDF_TYPES | EXCEL_TYPES | OLD_EXCEL_TYPES | CSV_TYPES | WORD_TYPES | XML_TYPES | HTML_TYPES
             | JSON_TYPES | set(IMAGE_TYPES) | TEXT_TYPES)
# formats we recognise but can't read directly -- the message tells the user what to do instead
CONVERT_FIRST = {".doc": "an old Word file (.doc): open it in Word and 'Save as' .docx or PDF",
                 ".rtf": "an RTF file: save it as .docx or PDF",
                 ".odt": "an OpenDocument text file: save it as .docx or PDF",
                 ".ods": "an OpenDocument spreadsheet: save it as .xlsx",
                 ".numbers": "a Numbers file: export it as .xlsx",
                 ".pages": "a Pages file: export it as .docx or PDF",
                 ".heic": "an iPhone HEIC photo: share it as JPG (or take a screenshot)",
                 ".zip": "a ZIP file: unzip it and upload the files inside"}

MAX_ROWS_PER_PART = 400           # a long sheet is split into parts of this many rows, header repeated
HEADER_ROWS = 6                   # rows repeated at the top of every part of a split sheet


class UnsupportedFile(ValueError):
    pass


@dataclass
class ParsedDocument:
    kind: str                      # pdf | excel | csv | word | xml | html | json | image | text
    media_type: str
    chunks: list[str] = field(default_factory=list)   # page / sheet sized pieces of text, in order
    raw_bytes: bytes | None = None                     # kept for native PDF / image extraction
    has_text_layer: bool = True
    meta: dict = field(default_factory=dict)

    @property
    def text(self) -> str:
        return "\n\n".join(self.chunks)


# ---------------------------------------------------------------- type detection
def sniff(data: bytes, ext: str) -> str:
    """The file's real type from its first bytes; the extension when the content doesn't say otherwise."""
    head = data[:2048]
    if head.startswith(b"%PDF") or b"%PDF-" in head[:1024]:
        return ".pdf"
    if head.startswith(b"\x89PNG"):
        return ".png"
    if head.startswith(b"\xff\xd8\xff"):
        return ".jpg"
    if head[:4] == b"RIFF" and head[8:12] == b"WEBP":
        return ".webp"
    if head[:6] in (b"GIF87a", b"GIF89a"):
        return ".gif"
    if head.startswith(b"PK\x03\x04"):
        try:
            names = zipfile.ZipFile(io.BytesIO(data)).namelist()
        except zipfile.BadZipFile:
            return ext
        if any(n.startswith("word/") for n in names):
            return ".docx"
        if any(n.startswith("xl/") for n in names):
            return ".xlsm" if ext == ".xlsm" else ".xlsx"
        return ext if ext in (".docx", ".xlsx", ".xlsm") else ".zip"
    if head.startswith(b"\xd0\xcf\x11\xe0"):                 # old Office (OLE): .xls or .doc
        return ".doc" if ext == ".doc" else ".xls"
    text = head.lstrip(b"\xef\xbb\xbf \t\r\n").lower()
    if text.startswith((b"<!doctype html", b"<html", b"<table", b"<meta")) or b"<html" in text[:512]:
        return ".html"
    if text.startswith(b"<?xml") or (text.startswith(b"<") and ext in XML_TYPES):
        return ".xml"
    if text.startswith((b"{", b"[")) and ext in JSON_TYPES | TEXT_TYPES:
        return ".json"
    return ext


def parse_file(path: str | Path, data: bytes | None = None) -> ParsedDocument:
    path = Path(path)
    ext = path.suffix.lower()
    data = data if data is not None else path.read_bytes()
    if not data:
        raise UnsupportedFile("The file is empty")
    real = sniff(data, ext)
    if real != ext:
        log.info("file %s looks like %s, reading it as that", path.name, real)
    if real in CONVERT_FIRST:
        raise UnsupportedFile(f"This is {CONVERT_FIRST[real]}.")
    try:
        doc = _dispatch(real, path.name, data)
    except UnsupportedFile:
        raise
    except Exception as e:  # noqa: BLE001 - a damaged file must give a clear message, not a crash
        log.warning("could not read %s as %s: %s", path.name, real, e)
        raise UnsupportedFile(f"Could not read this file as {real.lstrip('.').upper()} ({type(e).__name__}: {e}). "
                              f"If it opens on your computer, save it again as PDF or .xlsx and upload that.") from e
    doc.meta.setdefault("detected_type", real)
    return doc


def _dispatch(ext: str, name: str, data: bytes) -> ParsedDocument:
    if ext in PDF_TYPES:
        return _parse_pdf(data)
    if ext in EXCEL_TYPES:
        return _parse_xlsx(data)
    if ext in OLD_EXCEL_TYPES:
        return _parse_xls(data)
    if ext in CSV_TYPES:
        return _parse_csv(data, "\t" if ext == ".tsv" else None)
    if ext in WORD_TYPES:
        return _parse_docx(data)
    if ext in XML_TYPES:
        return _parse_xml(data)
    if ext in HTML_TYPES:
        return _parse_html(data)
    if ext in JSON_TYPES:
        return _parse_json(data)
    if ext in IMAGE_TYPES:
        return ParsedDocument(kind="image", media_type=IMAGE_TYPES[ext], raw_bytes=data, has_text_layer=False,
                              chunks=[f"[image file {name}]"])
    if ext in TEXT_TYPES:
        return ParsedDocument(kind="text", media_type="text/plain", chunks=_split_text(_decode(data)))
    raise UnsupportedFile(f"Unsupported file type '{ext or name}'. Supported: {', '.join(sorted(SUPPORTED))}")


def _decode(data: bytes) -> str:
    """UTF-8 when it is; otherwise the most likely encoding (Excel CSVs are often Windows-1252)."""
    for enc in ("utf-8-sig",):
        try:
            return data.decode(enc)
        except UnicodeDecodeError:
            pass
    from charset_normalizer import from_bytes
    best = from_bytes(data).best()
    return str(best) if best else data.decode("utf-8", "replace")


def _split_text(text: str, size: int = 20000) -> list[str]:
    parts, cur = [], []
    n = 0
    for para in text.split("\n\n"):
        if cur and n + len(para) > size:
            parts.append("\n\n".join(cur))
            cur, n = [], 0
        cur.append(para)
        n += len(para) + 2
    if cur:
        parts.append("\n\n".join(cur))
    return parts or [""]


# ---------------------------------------------------------------- PDF
def _cell(v) -> str:
    if v is None:
        return ""
    return " ".join(str(v).split())


def _table_to_text(rows: list[list]) -> str:
    rows = [[_cell(c) for c in r] for r in rows if r and any(c not in (None, "") for c in r)]
    return "\n".join("| " + " | ".join(r) + " |" for r in rows)


def _parse_pdf(data: bytes) -> ParsedDocument:
    import pdfplumber

    chunks: list[str] = []
    text_chars = 0
    try:
        pdf = pdfplumber.open(io.BytesIO(data))
    except Exception as e:  # noqa: BLE001
        if "password" in str(e).lower() or "encrypt" in str(e).lower():
            raise UnsupportedFile("This PDF is password protected. Remove the password (print to PDF) and upload again.")
        # unreadable structure: let the AI look at the file itself
        log.warning("pdfplumber could not open the PDF (%s); sending it to the AI as a file", e)
        return ParsedDocument(kind="pdf", media_type="application/pdf", chunks=["[PDF could not be read as text]"],
                              raw_bytes=data, has_text_layer=False, meta={"pages": None, "text_error": str(e)[:200]})
    with pdf:
        n_pages = len(pdf.pages)
        for i, page in enumerate(pdf.pages, 1):
            try:
                text = page.extract_text() or ""
                tables = [t for t in (page.extract_tables() or []) if t]
            except Exception as e:  # noqa: BLE001 - one bad page must not lose the rest
                log.warning("page %s of a PDF could not be read: %s", i, e)
                text, tables = "", []
            text_chars += len(text.strip())
            parts = [f"=== Page {i} of {n_pages} ===", text.strip()]
            for j, t in enumerate(tables, 1):
                parts.append(f"--- Table {j} on page {i} (cells separated by |) ---\n{_table_to_text(t)}")
            chunks.append("\n".join(p for p in parts if p))
    # < ~40 characters a page means it is almost certainly a scan / image-only PDF
    has_text = text_chars >= 40 * max(n_pages, 1)
    return ParsedDocument(kind="pdf", media_type="application/pdf", chunks=chunks, raw_bytes=data,
                          has_text_layer=has_text, meta={"pages": n_pages})


# ---------------------------------------------------------------- spreadsheets
def _fmt(v) -> str:
    if v is None:
        return ""
    if isinstance(v, datetime):
        return v.date().isoformat() if v.time() == datetime.min.time() else v.isoformat(sep=" ")
    if isinstance(v, date):
        return v.isoformat()
    if isinstance(v, float) and v.is_integer():
        return str(int(v))
    return " ".join(str(v).split())


def _grid_to_chunks(title: str, grid: list[list[str]], kind: str = "Sheet") -> list[str]:
    """A grid as text, keeping the real row numbers. Long grids become several parts, each repeating the
    first rows (titles, season headers, column names) so the AI knows what every column means."""
    numbered = [(i, r) for i, r in enumerate(grid, 1) if any(c for c in r)]
    if not numbered:
        return []
    width = max(max((i for i, c in enumerate(r) if c), default=-1) for _, r in numbered) + 1

    def line(idx, r):
        last = max(i for i, c in enumerate(r[:width]) if c) + 1
        return f"R{idx}: | " + " | ".join(r[:last]) + " |"
    lines = [line(i, r) for i, r in numbered]
    if len(lines) <= MAX_ROWS_PER_PART:
        return [f"=== {kind}: {title} ({len(lines)} rows; cells separated by |, merged cells repeated) ===\n"
                + "\n".join(lines)]
    head, body = lines[:HEADER_ROWS], lines[HEADER_ROWS:]
    step = MAX_ROWS_PER_PART - HEADER_ROWS
    parts = [body[i:i + step] for i in range(0, len(body), step)]
    return [f"=== {kind}: {title}, part {n} of {len(parts)} ({len(lines)} rows in all; the first {HEADER_ROWS} "
            f"rows are repeated as headers) ===\n" + "\n".join(head + p) for n, p in enumerate(parts, 1)]


def _parse_xlsx(data: bytes) -> ParsedDocument:
    from openpyxl import load_workbook

    wb = load_workbook(io.BytesIO(data), data_only=True)   # formulas -> last computed values
    chunks = []
    for ws in wb.worksheets:
        if ws.sheet_state != "visible":
            continue
        values = {}
        for row in ws.iter_rows():
            for c in row:
                if c.value is not None:
                    values[(c.row, c.column)] = _fmt(c.value)
        # merged header cells ("Peak Season" spanning 4 columns) are repeated into every cell, so each
        # rate column carries its season. A merged title that is alone on its row is left as one cell.
        for rng in ws.merged_cells.ranges:
            top = values.get((rng.min_row, rng.min_col), "")
            alone = all(c in range(rng.min_col, rng.max_col + 1) for (r, c) in values if r == rng.min_row)
            if alone and rng.min_row == rng.max_row:
                continue
            for r in range(rng.min_row, rng.max_row + 1):
                for c in range(rng.min_col, rng.max_col + 1):
                    values[(r, c)] = top
        if not values:
            continue
        max_r = max(r for r, _ in values)
        max_c = max(c for _, c in values)
        grid = [[values.get((r, c), "") for c in range(1, max_c + 1)] for r in range(1, max_r + 1)]
        chunks += _grid_to_chunks(ws.title, grid)
    if not chunks:
        raise UnsupportedFile("The spreadsheet has no visible data")
    return ParsedDocument(kind="excel", media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                          chunks=chunks, meta={"sheets": len(wb.worksheets)})


def _parse_xls(data: bytes) -> ParsedDocument:
    import xlrd

    book = xlrd.open_workbook(file_contents=data, formatting_info=False)
    chunks = []
    for sh in book.sheets():
        if sh.visibility != 0:
            continue
        grid = []
        for r in range(sh.nrows):
            row = []
            for c in range(sh.ncols):
                cell = sh.cell(r, c)
                if cell.ctype == xlrd.XL_CELL_DATE:
                    try:
                        v = xlrd.xldate.xldate_as_datetime(cell.value, book.datemode)
                    except Exception:  # noqa: BLE001
                        v = cell.value
                else:
                    v = cell.value
                row.append(_fmt(v))
            grid.append(row)
        # merged cells (xlrd reports them only with formatting_info on .xls; best effort without)
        chunks += _grid_to_chunks(sh.name, grid)
    if not chunks:
        raise UnsupportedFile("The spreadsheet has no visible data")
    return ParsedDocument(kind="excel", media_type="application/vnd.ms-excel", chunks=chunks)


def _parse_csv(data: bytes, delimiter: str | None) -> ParsedDocument:
    text = _decode(data)
    if delimiter is None:
        try:
            delimiter = csv.Sniffer().sniff(text[:20000], delimiters=",;\t|").delimiter
        except csv.Error:
            delimiter = ","
    grid = [[_fmt(c) for c in row] for row in csv.reader(io.StringIO(text), delimiter=delimiter)]
    chunks = _grid_to_chunks("csv", grid, "Table")
    if not chunks:
        raise UnsupportedFile("The CSV file has no data")
    return ParsedDocument(kind="csv", media_type="text/csv", chunks=chunks, meta={"delimiter": delimiter})


# ---------------------------------------------------------------- Word
def _parse_docx(data: bytes) -> ParsedDocument:
    import docx
    from docx.table import Table
    from docx.text.paragraph import Paragraph

    d = docx.Document(io.BytesIO(data))
    out: list[str] = []
    seen_headers = set()
    for section in d.sections:          # validity / supplier details often sit in the header or footer
        for part, label in ((section.header, "Header"), (section.footer, "Footer")):
            try:
                txt = "\n".join(p.text.strip() for p in part.paragraphs if p.text.strip())
            except Exception:  # noqa: BLE001
                txt = ""
            if txt and txt not in seen_headers:
                seen_headers.add(txt)
                out.append(f"--- {label} ---\n{txt}")
    n_tables = 0
    for block in d.element.body.iterchildren():
        tag = block.tag.rsplit("}", 1)[-1]
        if tag == "p":
            t = Paragraph(block, d).text.strip()
            if t:
                out.append(t)
        elif tag == "tbl":
            n_tables += 1
            rows = []
            for r in Table(block, d).rows:
                cells, last = [], None
                for c in r.cells:              # a merged cell is returned once per column it spans
                    txt = " ".join(c.text.split())
                    cells.append(txt)
                    last = c
                rows.append(cells)
            out.append(f"--- Table {n_tables} (cells separated by |, merged cells repeated) ---\n" + _table_to_text(rows))
    text = "\n".join(out)
    if len(text.strip()) < 40:
        # a Word file that only wraps a scanned rate card: send the biggest picture to the AI instead
        imgs = sorted(((len(p.blob), p) for p in d.part.package.parts
                       if p.content_type.startswith("image/")), key=lambda x: -x[0])
        if imgs:
            part = imgs[0][1]
            return ParsedDocument(kind="image", media_type=part.content_type, raw_bytes=part.blob,
                                  has_text_layer=False, chunks=["[picture inside a Word file]"], meta={"from": "docx"})
        raise UnsupportedFile("The Word file has no text or pictures")
    return ParsedDocument(kind="word", media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                          chunks=_split_text(text), meta={"tables": n_tables})


# ---------------------------------------------------------------- XML / HTML / JSON
def _parse_xml(data: bytes) -> ParsedDocument:
    from defusedxml import ElementTree as ET        # refuses entity expansion attacks and external entities

    root = ET.fromstring(data)
    lines: list[str] = []

    def walk(el, depth):
        tag = el.tag.rsplit("}", 1)[-1]
        attrs = " ".join(f'{k.rsplit("}", 1)[-1]}="{v}"' for k, v in el.attrib.items())
        text = " ".join((el.text or "").split())
        lines.append("  " * depth + tag + (f" [{attrs}]" if attrs else "") + (f": {text}" if text else ""))
        for ch in el:
            walk(ch, depth + 1)
    walk(root, 0)
    return ParsedDocument(kind="xml", media_type="application/xml", chunks=_split_text("\n".join(lines), 20000),
                          meta={"elements": len(lines)})


class _HTMLText(HTMLParser):
    """Visible text with tables kept as | rows; scripts and styles dropped."""
    BLOCK = {"p", "div", "br", "li", "h1", "h2", "h3", "h4", "h5", "h6", "section", "article", "header", "footer"}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.out: list[str] = []
        self.skip = 0
        self.row: list[str] | None = None
        self.cell: list[str] | None = None
        self.span = 1

    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style", "noscript", "head"):
            self.skip += 1
        elif tag == "tr":
            self.row = []
        elif tag in ("td", "th"):
            self.cell = []
            try:
                self.span = max(1, min(50, int(dict(attrs).get("colspan") or 1)))
            except ValueError:
                self.span = 1
        elif tag == "table":
            self.out.append("\n--- Table (cells separated by |, merged cells repeated) ---")
        elif tag in self.BLOCK:
            self.out.append("\n")

    def handle_endtag(self, tag):
        if tag in ("script", "style", "noscript", "head"):
            self.skip = max(0, self.skip - 1)
        elif tag in ("td", "th") and self.cell is not None and self.row is not None:
            self.row += [" ".join("".join(self.cell).split())] * self.span
            self.cell = None
        elif tag == "tr" and self.row is not None:
            if any(self.row):
                self.out.append("\n| " + " | ".join(self.row) + " |")
            self.row = None
        elif tag == "table":
            self.out.append("\n")

    def handle_data(self, data):
        if self.skip:
            return
        if self.cell is not None:
            self.cell.append(data)
        elif data.strip():
            self.out.append(" ".join(data.split()) + " ")


def _parse_html(data: bytes) -> ParsedDocument:
    p = _HTMLText()
    p.feed(_decode(data))
    text = "\n".join(line.strip() for line in "".join(p.out).splitlines() if line.strip())
    if not text:
        raise UnsupportedFile("The web page has no readable text")
    return ParsedDocument(kind="html", media_type="text/html", chunks=_split_text(text))


def _parse_json(data: bytes) -> ParsedDocument:
    obj = json.loads(_decode(data))
    return ParsedDocument(kind="json", media_type="application/json",
                          chunks=_split_text(json.dumps(obj, indent=1, ensure_ascii=False, default=str)))
