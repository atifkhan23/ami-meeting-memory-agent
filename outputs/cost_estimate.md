# Scale and cost estimate

All inputs below are either **measured** on this project or **labelled assumptions**. The actual spend for
this project was **$0** (Gemini and Groq free tiers); dollar figures are what the same token volumes would cost
at list prices.

## Measured inputs (this corpus)
| Input | Value | Source |
|---|---|---|
| Meetings / words | 138 / 676,745 | SQLite store |
| Avg words per meeting | 4,904 | measured |
| Avg tokens per meeting | 6,522 | words x 1.33 (assumption) |
| Chunks per meeting | 31.4 (avg 242 words; target 220, max 400, 3-turn overlap) | measured |
| Embedding model | all-MiniLM-L6-v2, local CPU, 384-d, $0 | config |
| Embedding throughput | 7.0 chunks/s on a 2-core i5-7300U laptop (618 s for 4,334 chunks) | measured |
| Extraction calls per meeting | 2.73 (2,200-word segments) | deterministic segmenter |
| Extraction tokens per call (in / out) | 4,203 / 1,929 | measured over 379 live calls (gemini-3-flash-preview, gemini-3.1-flash-lite, gemini-3.5-flash-lite, openai/gpt-oss-120b, openai/gpt-oss-20b, qwen/qwen3.8-27b) |
| Reconciliation tokens per team (in / out) | 4,580 / 4,620 | measured over 36 live calls |
| Extraction latency per call | 15.0 s | measured |
| Prices (USD / 1M tokens) | extraction gemini-3.1-flash-lite 0.25/1.5; reconciliation gemini-3.6-flash 0.75/3.75 (intro, to 2026-12-31; 1.5/7.5 from 2027) | public price trackers, Nov 2026 (assumption) |

## Estimated one-time ingestion
| Meetings | Tokens | Chunks (local embeddings) | Extraction calls | Reconcile calls | LLM cost (2026 prices) | LLM cost (2027 prices) | Storage | Embedding time (laptop CPU) | LLM time serial / 8 parallel |
|---|---|---|---|---|---|---|---|---|---|
| 138 | 900,071 | 4,334 | 377 | 34 | $2.2 | $2.92 | 38.9 MB | 0.17 h | 1.73 h / 0.22 h |
| 1,000 | 6,522,253 | 31,406 | 2,732 | 250 | $15.97 | $21.16 | 282.1 MB | 1.24 h | 12.57 h / 1.57 h |
| 10,000 | 65,222,525 | 314,058 | 27,319 | 2,500 | $159.67 | $211.58 | 2,821.5 MB | 12.45 h | 125.68 h / 15.71 h |

## Incremental (ongoing) cost
A new meeting costs the same per-meeting share as above (~2.7 extraction calls, ~31 local embeddings)
plus re-reconciling only its own team (one call over that team's records, not the corpus). Unchanged files are
skipped by sha256, so re-running ingestion costs nothing. Per new meeting: ~$0.0160 at 2026 prices.

## Query-time cost (not ingestion)
Each question uses ~3-5 LLM calls (intent, 1-3 assess/answer rounds, support check);
measured mean answer-call input 16438 tokens regardless of corpus size,
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
