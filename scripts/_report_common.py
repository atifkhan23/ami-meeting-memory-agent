"""Shared data, styles, table/snippet helpers and diagrams for the report PDFs.

Numbers are read from outputs/ and the SQLite store; code snippets are cut from the real source files.
"""
import _bootstrap  # noqa: F401
import json
from pathlib import Path
from xml.sax.saxutils import escape

from reportlab.graphics.shapes import Drawing, Line, Polygon, Rect, String
from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import cm
from reportlab.platypus import (KeepTogether, PageBreak, Paragraph, Preformatted, SimpleDocTemplate,
                                Spacer, Table, TableStyle)

import config
from src.memory import db

ROOT = config.ROOT

# ----------------------------------------------------------------- data
conn = db.connect()
STATS = db.stats(conn)
EVAL = json.loads((config.OUTPUTS_DIR / "evaluation_report.json").read_text(encoding="utf-8"))
ANS = json.loads((config.OUTPUTS_DIR / "answers.json").read_text(encoding="utf-8"))
COST = json.loads((config.OUTPUTS_DIR / "cost_estimate.json").read_text(encoding="utf-8"))
BRIEF = json.loads((config.OUTPUTS_DIR / "ts3012_brief.json").read_text(encoding="utf-8"))
N_CIT = sum(len(a["citations"]) for a in ANS["answers"])
N_MULTI = sum(1 for a in ANS["answers"] if len({c["meeting_id"] for c in a["citations"]}) > 1)
S = EVAL["summary"]
V = S["verdicts_final"]
LINKS = dict(conn.execute("SELECT relation, COUNT(*) FROM memory_links GROUP BY relation").fetchall())
VERIFIED = conn.execute("SELECT SUM(quote_verified), COUNT(*) FROM memory_records").fetchone()
STATUS = dict(conn.execute("SELECT status, COUNT(*) FROM memory_records GROUP BY status").fetchall())

# ----------------------------------------------------------------- styles
NAVY = colors.HexColor("#1F3A5F")
TEAL = colors.HexColor("#2A7F8E")
LIGHT = colors.HexColor("#EEF3F8")
GREEN = colors.HexColor("#E3F2E5")
AMBER = colors.HexColor("#FFF3D6")
RED = colors.HexColor("#FBE3E3")
GREY = colors.HexColor("#5F6B7A")

ss = getSampleStyleSheet()
H1 = ParagraphStyle("H1", parent=ss["Heading1"], fontSize=16, textColor=NAVY, spaceBefore=4, spaceAfter=8)
H2 = ParagraphStyle("H2", parent=ss["Heading2"], fontSize=12, textColor=TEAL, spaceBefore=8, spaceAfter=4)
BODY = ParagraphStyle("B", parent=ss["BodyText"], fontSize=9.4, leading=12.6, spaceAfter=5)
SMALL = ParagraphStyle("S", parent=BODY, fontSize=8, leading=10, textColor=GREY)
CELL = ParagraphStyle("C", parent=BODY, fontSize=8.2, leading=10, spaceAfter=0)
CELLB = ParagraphStyle("CB", parent=CELL, fontName="Helvetica-Bold")
BUL = ParagraphStyle("BUL", parent=BODY, leftIndent=12, bulletIndent=2, spaceAfter=2)
CODE = ParagraphStyle("CODE", fontName="Courier", fontSize=7.1, leading=8.6, backColor=colors.HexColor("#F6F8FA"),
                      borderColor=colors.HexColor("#D0D7DE"), borderWidth=0.5, borderPadding=5,
                      leftIndent=4, rightIndent=4, spaceBefore=4, spaceAfter=8)
CAPTION = ParagraphStyle("CAP", parent=SMALL, alignment=TA_CENTER, spaceAfter=8)


def P(t, st=BODY):
    return Paragraph(t, st)


def bullets(items):
    return [Paragraph(t, BUL, bulletText="•") for t in items]


def table(rows, widths, header=True, zebra=True, bold_first_col=False):
    HDR = ParagraphStyle("hdr", parent=CELLB, textColor=colors.white)
    data = [[P(escape(str(c)) if not str(c).startswith("<") else str(c),
               HDR if (header and i == 0) else CELLB if (bold_first_col and j == 0) else CELL)
             for j, c in enumerate(r)] for i, r in enumerate(rows)]
    t = Table(data, colWidths=widths, repeatRows=1 if header else 0)
    st = [("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#C9D3DE")),
          ("VALIGN", (0, 0), (-1, -1), "TOP"),
          ("LEFTPADDING", (0, 0), (-1, -1), 4), ("RIGHTPADDING", (0, 0), (-1, -1), 4),
          ("TOPPADDING", (0, 0), (-1, -1), 2.5), ("BOTTOMPADDING", (0, 0), (-1, -1), 2.5)]
    if header:
        st += [("BACKGROUND", (0, 0), (-1, 0), NAVY), ("TEXTCOLOR", (0, 0), (-1, 0), colors.white)]
    if zebra:
        for i in range(1 if header else 0, len(rows)):
            if i % 2 == 0:
                st.append(("BACKGROUND", (0, i), (-1, i), LIGHT))
    t.setStyle(TableStyle(st))
    return t


def snippet(path, start_marker, n_lines, skip_doc=False):
    """Cut n_lines of real source starting at the line containing start_marker."""
    lines = (ROOT / path).read_text(encoding="utf-8").splitlines()
    i = next(k for k, l in enumerate(lines) if start_marker in l)
    chunk = lines[i:i + n_lines]
    if skip_doc:
        chunk = [l for l in chunk if not l.strip().startswith(('"""', "#"))]
    indent = min((len(l) - len(l.lstrip()) for l in chunk if l.strip()), default=0)
    text = "\n".join(l[indent:] for l in chunk)
    return [Preformatted(text, CODE), P(f"Source: <font face='Courier'>{path}</font> (line {i + 1})", SMALL)]


# ----------------------------------------------------------------- diagram helpers
def box(d, x, y, w, h, title, sub="", fill=LIGHT, stroke=NAVY, fs=7.6):
    d.add(Rect(x, y, w, h, rx=5, ry=5, fillColor=fill, strokeColor=stroke, strokeWidth=0.9))
    d.add(String(x + w / 2, y + h - 11, title, fontName="Helvetica-Bold", fontSize=fs, fillColor=NAVY,
                 textAnchor="middle"))
    for k, line in enumerate(sub.split("\n") if sub else []):
        d.add(String(x + w / 2, y + h - 22 - k * 9, line, fontName="Helvetica", fontSize=6.6,
                     fillColor=colors.HexColor("#33414F"), textAnchor="middle"))


def arrow(d, x1, y1, x2, y2, color=GREY, label=""):
    d.add(Line(x1, y1, x2, y2, strokeColor=color, strokeWidth=1.1))
    import math
    a = math.atan2(y2 - y1, x2 - x1)
    s = 5
    d.add(Polygon([x2, y2, x2 - s * math.cos(a - 0.4), y2 - s * math.sin(a - 0.4),
                   x2 - s * math.cos(a + 0.4), y2 - s * math.sin(a + 0.4)], fillColor=color, strokeColor=color))
    if label:
        d.add(String((x1 + x2) / 2 + 3, (y1 + y2) / 2 + 3, label, fontName="Helvetica-Oblique", fontSize=6.2,
                     fillColor=GREY))


def architecture_diagram():
    d = Drawing(480, 330)
    # ingestion row
    box(d, 0, 268, 92, 50, "Transcripts", "138 .txt files\n(AMI corpus)", fill=colors.white)
    box(d, 118, 268, 160, 50, "1. Ingestion (code)", "discover - sha256 - parse turns\nspeaker-turn chunking (overlap 3)",
        fill=GREEN)
    box(d, 304, 268, 176, 50, "2. Embedding (local model)", "all-MiniLM-L6-v2 on CPU\nbatched, $0", fill=GREEN)
    arrow(d, 92, 293, 118, 293)
    arrow(d, 278, 293, 304, 293)
    # store
    d.add(Rect(0, 150, 480, 100, rx=6, ry=6, fillColor=colors.HexColor("#F7FAFD"), strokeColor=TEAL,
               strokeWidth=1.2, strokeDashArray=[3, 2]))
    d.add(String(472, 239, "PERSISTENT MEMORY STORE (store/)", fontName="Helvetica-Bold", fontSize=7.5, fillColor=TEAL,
                 textAnchor="end"))
    box(d, 10, 160, 145, 70, "A. Verbatim layer", "SQLite: meetings, turns,\nchunks + char offsets\n48,148 turns", fill=colors.white)
    box(d, 167, 160, 145, 70, "B. Search layer", "FTS5 BM25 keyword index\n+ Chroma vectors\n4,334 chunks", fill=colors.white)
    box(d, 324, 160, 146, 70, "C. Structured memory", f"{STATS['memory_records']:,} records + links\nstatus via state machine\nper-meeting speaker roles",
        fill=colors.white)
    arrow(d, 198, 268, 82, 230)
    arrow(d, 392, 268, 240, 230)
    # LLM extraction
    box(d, 330, 112, 140, 30, "3. LLM extraction + reconcile", "", fill=AMBER, fs=7)
    arrow(d, 400, 142, 400, 160, label="")
    # agent
    d.add(Rect(0, 0, 480, 100, rx=6, ry=6, fillColor=colors.HexColor("#FDFBF4"), strokeColor=NAVY, strokeWidth=1.2))
    d.add(String(8, 88, "4. THE AGENT (one agent, observable loop, max 3 retrieval rounds)", fontName="Helvetica-Bold",
                 fontSize=7.5, fillColor=NAVY))
    steps = [("Scope", "team id\n(code)"), ("Plan", "queries\n(LLM)"), ("Retrieve", "hybrid+memory\n(code)"),
             ("Assess", "enough?\n(LLM)"), ("Cite check", "verbatim\n(code)"), ("Support", "judge+revise\n(LLM)")]
    for k, (t, s) in enumerate(steps):
        x = 10 + k * 78
        box(d, x, 22, 68, 54, t, s, fill=AMBER if "LLM" in s else GREEN, fs=7.2)
        if k:
            arrow(d, x - 10, 49, x, 49)
    d.add(Line(282, 22, 282, 12, strokeColor=colors.red, strokeWidth=0.9))
    d.add(Line(282, 12, 204, 12, strokeColor=colors.red, strokeWidth=0.9))
    arrow(d, 204, 12, 204, 22, color=colors.red)
    d.add(String(210, 3, "not enough evidence: follow-up queries", fontName="Helvetica-Oblique", fontSize=6.2,
                 fillColor=colors.red))
    arrow(d, 240, 150, 240, 100, label="read")
    return d


def retrieval_diagram():
    d = Drawing(480, 120)
    box(d, 0, 40, 80, 40, "Query", "from planner", fill=colors.white)
    box(d, 110, 75, 120, 38, "BM25 (SQLite FTS5)", "exact spoken words", fill=GREEN)
    box(d, 110, 5, 120, 38, "Vectors (Chroma)", "paraphrase / meaning", fill=GREEN)
    box(d, 260, 40, 90, 40, "RRF fusion", "1/(60+rank)", fill=LIGHT)
    box(d, 380, 40, 100, 40, "Top chunks", "+ 1 per meeting\n+ neighbours", fill=AMBER)
    arrow(d, 80, 60, 110, 94)
    d.add(String(40, 30, "filtered to team first", fontName="Helvetica-Oblique", fontSize=6.2, fillColor=GREY,
                 textAnchor="middle"))
    arrow(d, 80, 60, 110, 24)
    arrow(d, 230, 94, 260, 62)
    arrow(d, 230, 24, 260, 58)
    arrow(d, 350, 60, 380, 60)
    return d


def state_diagram():
    d = Drawing(480, 165)
    box(d, 10, 105, 90, 34, "proposed", "", fill=colors.white)
    box(d, 190, 105, 90, 34, "accepted", "(latest = current)", fill=GREEN)
    box(d, 380, 105, 90, 34, "superseded", "keeps evidence", fill=AMBER)
    box(d, 190, 28, 90, 34, "rejected", "", fill=RED)
    box(d, 380, 28, 90, 34, "completed", "actions only", fill=GREEN)
    box(d, 10, 28, 90, 34, "unresolved", "actions/disputes", fill=colors.white)
    arrow(d, 100, 122, 190, 122, label="confirms")
    arrow(d, 280, 122, 380, 122, label="supersedes")
    arrow(d, 70, 105, 200, 62, label="rejects")
    arrow(d, 235, 105, 235, 62, label="rejects")
    d.add(Line(55, 28, 55, 12, strokeColor=GREY, strokeWidth=1.1))
    d.add(Line(55, 12, 425, 12, strokeColor=GREY, strokeWidth=1.1))
    arrow(d, 425, 12, 425, 28)
    d.add(String(240, 15, "completes", fontName="Helvetica-Oblique", fontSize=6.2, fillColor=GREY, textAnchor="middle"))
    d.add(String(240, 156, "LLM proposes the link type; code applies it only if it points back in time,",
                 fontName="Helvetica-Oblique", fontSize=6.6, fillColor=GREY, textAnchor="middle"))
    d.add(String(240, 147, "joins the same topic, and comes from an ACCEPTED decision (a later proposal never wins).",
                 fontName="Helvetica-Oblique", fontSize=6.6, fillColor=GREY, textAnchor="middle"))
    return d


# ----------------------------------------------------------------- page decoration
FOOTER = "AMI Meeting Memory Agent - Technical Report"


def on_page(canvas, doc):
    canvas.saveState()
    canvas.setFont("Helvetica", 7.5)
    canvas.setFillColor(GREY)
    canvas.drawString(2 * cm, 1.2 * cm, FOOTER)
    canvas.drawRightString(A4[0] - 2 * cm, 1.2 * cm, f"Page {doc.page}")
    canvas.setStrokeColor(colors.HexColor("#C9D3DE"))
    canvas.line(2 * cm, 1.5 * cm, A4[0] - 2 * cm, 1.5 * cm)
    canvas.restoreState()


# ----------------------------------------------------------------- content


# ----------------------------------------------------------------- measured LLM usage (logs/llm_usage.jsonl)
import collections as _collections  # noqa: E402

USAGE = ([json.loads(l) for l in open(config.LOG_DIR / "llm_usage.jsonl", encoding="utf-8")]
         if (config.LOG_DIR / "llm_usage.jsonl").exists() else [])
LIVE = [u for u in USAGE if not u["cached"]]


def usage_by_model() -> dict:
    out = {}
    for u in LIVE:
        m = out.setdefault(f"{u['provider']}/{u['model']}", {"calls": 0, "in": 0, "out": 0, "lat": 0.0,
                                                               "tasks": _collections.Counter()})
        m["calls"] += 1
        m["in"] += u["input_tokens"]
        m["out"] += u["output_tokens"]
        m["lat"] += u["latency_s"]
        m["tasks"][u["task"]] += 1
    return dict(sorted(out.items(), key=lambda kv: -kv[1]["calls"]))


def llm_call_diagram():
    """How one LLM request is executed by src/llm/client.py."""
    d = Drawing(480, 118)
    steps = [("Request", "task + prompt\n+ chain", colors.white), ("Cache?", "SQLite hit\n= free, instant", GREEN),
             ("Breaker?", "skip model if\ndown / quota", GREEN), ("Call API", "REST, timeout\nretry + backoff", AMBER),
             ("Parse JSON", "invalid = next\nmodel", GREEN), ("Ledger", "tokens, latency\nmodel, retries", GREEN)]
    for k, (t, s, f) in enumerate(steps):
        x = 4 + k * 79
        box(d, x, 52, 70, 50, t, s, fill=f, fs=7.2)
        if k:
            arrow(d, x - 9, 77, x, 77)
    d.add(Line(281, 52, 281, 26, strokeColor=colors.red, strokeWidth=0.9))
    d.add(Line(281, 26, 165, 26, strokeColor=colors.red, strokeWidth=0.9))
    arrow(d, 165, 26, 165, 52, color=colors.red)
    d.add(String(170, 13, "on 503 / timeout / quota / bad JSON: fall back to the NEXT model in the chain",
                 fontName="Helvetica-Oblique", fontSize=6.4, fillColor=colors.red))
    d.add(String(240, 110, "Every call goes through one provider layer - code, not a framework",
                 fontName="Helvetica-Oblique", fontSize=6.6, fillColor=GREY, textAnchor="middle"))
    return d
