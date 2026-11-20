"""Generate the TS3012 pre-meeting brief -> outputs/ts3012_brief.md and the 'brief' field of answers.json."""
import _bootstrap  # noqa: F401
import argparse
import json

import config
from src.briefing.brief import build_brief, render_markdown, render_plain

ap = argparse.ArgumentParser()
ap.add_argument("--team", default="TS3012")
a = ap.parse_args()
b = build_brief(a.team)
md = render_markdown(b)
config.OUTPUTS_DIR.mkdir(exist_ok=True)
(config.OUTPUTS_DIR / f"{a.team.lower()}_brief.md").write_text(md, encoding="utf-8")
(config.OUTPUTS_DIR / f"{a.team.lower()}_brief.json").write_text(json.dumps(b, indent=2, ensure_ascii=False), encoding="utf-8")
p = config.OUTPUTS_DIR / "answers.json"
sub = json.load(open(p, encoding="utf-8")) if p.exists() else {"answers": [], "brief": ""}
sub["brief"] = render_plain(b)
p.write_text(json.dumps(sub, indent=2, ensure_ascii=False), encoding="utf-8")
# Independent re-check of every quote that appears in the rendered brief
from src.citations.validator import validate_citation  # noqa: E402
from src.evaluation.schema import brief_quotes  # noqa: E402
from src.memory import db  # noqa: E402
conn = db.connect()
qs = brief_quotes(sub["brief"])
bad = [(m, q) for m, q in qs if not validate_citation(conn, m, q, a.team).valid]
print(md)
print(f"brief quotes re-validated: {len(qs) - len(bad)}/{len(qs)} valid", bad[:3])
print(f"citations: {b['n_citations']}, dropped uncited items: {len(b['dropped_uncited'])}, model: {b['model']}")
