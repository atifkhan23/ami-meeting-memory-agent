"""Scale/cost estimate for ingesting N meetings. Pure arithmetic over MEASURED inputs:

* corpus statistics from the SQLite store (words, turns, chunks per meeting)
* LLM token usage per task from logs/llm_usage.jsonl (live, non-cached calls of this project)
* measured wall-clock timings from outputs/ingestion_stats.json
Prices are list prices recorded in config.PRICING (labelled assumptions; free tier was used = $0 actual).

    python scripts/cost_estimate.py
"""
import _bootstrap  # noqa: F401
import json
import os
import statistics

import config
from src.memory import db

conn = db.connect()
s = db.stats(conn)
n_meet = s["meetings"]
words_pm = s["words"] / n_meet
chunks_pm = s["chunks"] / n_meet
chunk_words = conn.execute("SELECT AVG(n_words) FROM chunks").fetchone()[0]
TOK_PER_WORD = 1.33  # assumption for conversational English (Gemini/GPT tokenisers ~1.3)

# ---- measured LLM usage from the ledger ----
usage = [json.loads(l) for l in open(config.LOG_DIR / "llm_usage.jsonl", encoding="utf-8")] \
    if (config.LOG_DIR / "llm_usage.jsonl").exists() else []
live = [u for u in usage if not u["cached"]]
def per_task(task):
    xs = [u for u in live if u["task"] == task]
    if not xs:
        return None
    return {"calls": len(xs), "in": statistics.mean(u["input_tokens"] for u in xs),
            "out": statistics.mean(u["output_tokens"] for u in xs),
            "latency": statistics.mean(u["latency_s"] for u in xs),
            "models": sorted({u["model"] for u in xs})}
ext, rec = per_task("extract"), per_task("reconcile")
# extraction calls per meeting = ~ceil(words / 2500) segments (deterministic from the segmenter)
seg_pm = statistics.mean(max(1, -(-r[0] // 2200)) for r in conn.execute("SELECT n_words FROM meetings"))
ext_in = ext["in"] if ext else 4200
ext_out = ext["out"] if ext else 1800
rec_in = rec["in"] if rec else 7000
rec_out = rec["out"] if rec else 3000

timings = {}
sp = config.OUTPUTS_DIR / "ingestion_stats.json"
if sp.exists():
    timings = json.loads(sp.read_text()).get("timings", {})
EMBED_S_PER_CHUNK = 618.3 / 4334   # measured: 4,334 chunks embedded in 618 s on an i5-7300U (2C/4T) CPU

P_EXT = config.PRICING["gemini-3.1-flash-lite"]
P_REC = config.PRICING["gemini-3.6-flash"]
P_REC_2027 = {"in": 1.50, "out": 7.50}


def row(n):
    teams = n / 4
    ext_calls = n * seg_pm
    ext_cost = ext_calls * (ext_in * P_EXT["in"] + ext_out * P_EXT["out"]) / 1e6
    rec_cost = teams * (rec_in * P_REC["in"] + rec_out * P_REC["out"]) / 1e6
    rec_cost_27 = teams * (rec_in * P_REC_2027["in"] + rec_out * P_REC_2027["out"]) / 1e6
    chunks = n * chunks_pm
    store_mb = n * (os.path.getsize(config.SQLITE_PATH) / n_meet) / 1e6 + chunks * 384 * 4 * 1.5 / 1e6
    embed_h_cpu = chunks * EMBED_S_PER_CHUNK / 3600
    llm_h_serial = (ext_calls * (ext["latency"] if ext else 8) + teams * (rec["latency"] if rec else 30)) / 3600
    return {"meetings": n, "words": round(n * words_pm), "tokens": round(n * words_pm * TOK_PER_WORD),
            "chunks": round(chunks), "embedding_calls_local": round(chunks), "extraction_llm_calls": round(ext_calls),
            "reconcile_llm_calls": round(teams), "llm_cost_usd": round(ext_cost + rec_cost, 2),
            "llm_cost_usd_2027_prices": round(ext_cost + rec_cost_27, 2),
            "storage_mb": round(store_mb, 1), "embed_hours_laptop_cpu": round(embed_h_cpu, 2),
            "llm_hours_serial": round(llm_h_serial, 2), "llm_hours_8_parallel": round(llm_h_serial / 8, 2)}


rows = [row(n) for n in (138, 1000, 10000)]
qa_in = per_task("answer")
md = f"""# Scale and cost estimate

All inputs below are either **measured** on this project or **labelled assumptions**. The actual spend for
this project was **$0** (Gemini and Groq free tiers); dollar figures are what the same token volumes would cost
at list prices.

## Measured inputs (this corpus)
| Input | Value | Source |
|---|---|---|
| Meetings / words | {n_meet} / {s['words']:,} | SQLite store |
| Avg words per meeting | {words_pm:,.0f} | measured |
| Avg tokens per meeting | {words_pm*TOK_PER_WORD:,.0f} | words x {TOK_PER_WORD} (assumption) |
| Chunks per meeting | {chunks_pm:.1f} (avg {chunk_words:.0f} words; target 220, max 400, 3-turn overlap) | measured |
| Embedding model | all-MiniLM-L6-v2, local CPU, 384-d, $0 | config |
| Embedding throughput | {1/EMBED_S_PER_CHUNK:.1f} chunks/s on a 2-core i5-7300U laptop (618 s for 4,334 chunks) | measured |
| Extraction calls per meeting | {seg_pm:.2f} (2,200-word segments) | deterministic segmenter |
| Extraction tokens per call (in / out) | {ext_in:,.0f} / {ext_out:,.0f} | {'measured over %d live calls (%s)' % (ext['calls'], ', '.join(ext['models'])) if ext else 'ASSUMED'} |
| Reconciliation tokens per team (in / out) | {rec_in:,.0f} / {rec_out:,.0f} | {'measured over %d live calls' % rec['calls'] if rec else 'ASSUMED'} |
| Extraction latency per call | {round(ext['latency'], 1) if ext else 'n/a'} s | {'measured' if ext else ''} |
| Prices (USD / 1M tokens) | extraction gemini-3.1-flash-lite {P_EXT['in']}/{P_EXT['out']}; reconciliation gemini-3.6-flash {P_REC['in']}/{P_REC['out']} (intro, to 2026-12-31; {P_REC_2027['in']}/{P_REC_2027['out']} from 2027) | public price trackers, Nov 2026 (assumption) |

## Estimated one-time ingestion
| Meetings | Tokens | Chunks (local embeddings) | Extraction calls | Reconcile calls | LLM cost (2026 prices) | LLM cost (2027 prices) | Storage | Embedding time (laptop CPU) | LLM time serial / 8 parallel |
|---|---|---|---|---|---|---|---|---|---|
""" + "\n".join(
    f"| {r['meetings']:,} | {r['tokens']:,} | {r['chunks']:,} | {r['extraction_llm_calls']:,} | {r['reconcile_llm_calls']:,} | "
    f"${r['llm_cost_usd']:,} | ${r['llm_cost_usd_2027_prices']:,} | {r['storage_mb']:,} MB | {r['embed_hours_laptop_cpu']} h | "
    f"{r['llm_hours_serial']} h / {r['llm_hours_8_parallel']} h |" for r in rows) + f"""

## Incremental (ongoing) cost
A new meeting costs the same per-meeting share as above (~{seg_pm:.1f} extraction calls, ~{chunks_pm:.0f} local embeddings)
plus re-reconciling only its own team (one call over that team's records, not the corpus). Unchanged files are
skipped by sha256, so re-running ingestion costs nothing. Per new meeting: ~${rows[1]['llm_cost_usd']/1000:.4f} at 2026 prices.

## Query-time cost (not ingestion)
Each question uses ~3-5 LLM calls (intent, 1-3 assess/answer rounds, support check);
{'measured mean answer-call input %.0f tokens' % qa_in['in'] if qa_in else 'answer-call input is bounded by EVIDENCE_TOKEN_BUDGET=9,000 tokens'} regardless of corpus size,
because retrieval sends only top-ranked turns. Cost per question is therefore flat in N.

## Caveats
* Measured free-tier daily quotas (from 429 bodies, 2026-11-19): gemini-3.1-flash-lite 500 requests/day,
  gemini-3.6-flash and gemini-3-flash-preview 20 requests/day each; Groq 1,000 requests/day per model with
  8,000 tokens/minute. One full ingestion of this corpus (~380 extraction + ~35 reconcile calls, plus retries) nearly
  exhausts a day of flash-lite quota, which is why the actual wall-clock for LLM extraction here was ~2.5 h
  (dominated by 503 back-off and quota fallbacks), not the 0.22 h the parallel estimate assumes on a paid tier.
* The answer prompt is ~16k tokens (9k-token evidence budget + memory records + role table + instructions);
  it is bounded by configuration, not by corpus size.
* Free-tier limits, not cost, were the real constraint: Groq gpt-oss-20b free tier = 8,000 tokens/minute (from its
  429 response), i.e. about one extraction call per minute; Gemini flash/lite models returned intermittent 503s.
  At 1,000+ meetings a paid tier (or Batch API at ~50% of list price) is required to hit the timings above.
* Embedding time is for a weak laptop CPU; a single modern GPU embeds MiniLM at >1,000 chunks/s
  (10,000 meetings ~= 5 min) - an assumption, not measured here.
* Storage includes SQLite (verbatim turns + chunks + FTS index + memory) and vectors (384 float32 + ~50% index overhead).
"""
(config.OUTPUTS_DIR / "cost_estimate.md").write_text(md, encoding="utf-8")
(config.OUTPUTS_DIR / "cost_estimate.json").write_text(json.dumps(rows, indent=2), encoding="utf-8")
print(md)
