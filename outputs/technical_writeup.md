# Technical write-up: AMI Meeting Memory Agent

**Architecture.** Three memory layers over one persistent store. (1) *Verbatim*: every speaker turn of 138
meetings (48,148 turns, 676,745 words) in SQLite with meeting/team/stage, speaker, timestamp and character
offsets. (2) *Search*: 4,334 speaker-turn chunks (whole turns only, ~220 words, 3-turn overlap, a question is never
cut from its answer) indexed twice - SQLite FTS5 BM25 and MiniLM-L6 vectors in Chroma - fused with reciprocal rank
fusion after filtering to the team. (3) *Structured temporal memory*: LLM-extracted decisions, actions,
commitments, disagreements, open questions and references, each with a code-verified evidence quote, plus
per-meeting speaker roles; a reconciler links records over time and a deterministic state machine assigns
`proposed / accepted / rejected / superseded / completed / unresolved` and `is_current`.

**Why an agent, not RAG.** Per question: code scopes the team → an LLM plans the answer parts and writes
spoken-language search queries → hybrid retrieval with per-meeting coverage + memory records + role table →
the LLM judges whether the evidence is *sufficient*; if not it issues follow-up queries and the agent expands
neighbouring chunks (≤ 3 rounds) → answer with (meeting, turn, quote) citations → code snaps and verifies every
quote → an LLM judge checks support → a revision step strips unsupported claims. If no quote survives, the answer
is marked UNCERTAIN instead of shipped. Every stage is logged to `outputs/traces/Qxx.json`.

**Memory over time.** Time is `(meeting_order, turn)` computed in code. The reconciler LLM sees only the compact
record list for one team (never transcripts) and proposes topics and typed links. Code then enforces: links only
point backwards; `supersedes/confirms` must join the same topic (a real reconciler error - "speech recognition
removal" superseding "design phases" - was caught by this rule); a later *proposal* never overrides an accepted
decision; superseded records are kept with `superseded_by`. `state_as_of()` replays the machine at any cutoff,
so the TS3012 brief is written strictly from meetings a-c ("before their final meeting").

**Model vs code.** *Never an LLM:* file discovery, hashing/idempotency, parsing, meeting-id validation, chunking,
embedding batching, BM25/RRF/filters, temporal ordering and state transitions, quote matching and snapping, JSON
schema checks, evaluation scoring, cost arithmetic - all deterministic, testable, free, and wrong answers there
would be silent. *LLM:* deciding whether "let's just go with rubber then" is a decision or a musing, who owns
"I'll look into it", whether a remark disagrees with or replaces an earlier one, resolving "the aspect discussed
last time", synthesising evidence across meetings, judging sufficiency/support, and writing the brief - all
language understanding that rules cannot do on real disfluent speech.

**Frameworks, models, APIs.** Python with no orchestration framework (the loop is ~150 visible lines); SQLite/FTS5;
Chroma; sentence-transformers MiniLM-L6 (local CPU); Gemini and Groq through REST behind one provider layer with an
ordered fallback chain, retries, a cross-process circuit breaker, a response cache (re-runs are free and
reproducible) and a usage ledger. Requested models were `gemini-3.6-flash` (reasoning) and `gemini-3.1-flash-lite`
(extraction).

**Where the tools broke (measured, 2026-11-19).** `gemini-3.6-flash`, `3.7-flash`, `3.8-flash` and both Gemma 4
models returned 503 UNAVAILABLE or 60-75 s timeouts for most of the day; `gemini-3-flash-preview` worked (~3 s)
but its free tier is **20 requests/day per model** and was exhausted after one question plus some extraction;
the flash-lite models returned intermittent 503 bursts. Groq's free tier is **8,000 tokens/minute per model**
including `max_tokens` (prompts above ~7k tokens get 413, so evidence-heavy answer prompts cannot run there), a
daily token cap on `gpt-oss-20b`, and `qwen3.8-27b` allows only **1,000 output tokens/minute**. Each failure became
a code change: logged fallback chains, quota-aware routing (extraction never consumes the reasoning models'
quota), TPM-aware output caps, fail-fast on oversize, per-meeting wait-and-retry, a persisted breaker. On the local
side, CPU embedding of 4,334 chunks took 618 s on a 2-core laptop, and an interrupted run exposed a real bug
(SQLite rows committed but vectors missing) now fixed by an automatic vector backfill with a regression test.

**Evaluation.** 12 questions I wrote and answered by reading the transcripts (teams not used by the graded
set): 10 answerable across decision changes, rejected proposals, commitments/follow-up, ownership, preferences,
disagreements, a 3-meeting trail and an indirect reference, plus 2 abstention traps. Final (human-reviewed):
**8 correct, 3 partial, 1 incorrect** (regex-only: 6/5/1). Citation exact-match 100% (all quotes re-validated
independently), citation support 95.8%, retrieval recall of gold evidence turns 0.90, multi-meeting citation
coverage 0.80, 1/2 correct abstentions, 0 false abstentions. All 25 graded answers carry 1-3 valid citations
(validator: 0 problems); the TS3012 brief carries 11/11 valid citations.

**Three failures** (details in `failure_analysis.md`). *E11*: asked about IS1005's meeting d, which doesn't
exist; the agent answered from meetings a/b with real but irrelevant quotes (scope) - fixed afterwards with a
deterministic missing-meeting check, verified in a separate post-fix probe. *E08*: the decisive "I'm just not
swallowing the fruit" turn was retrieved, but the lite model concluded the objection was resolved because the final
prototype was a banana - a latest-artefact-wins reasoning error. *E07*: the ingest-time role table gave two people
the Project Manager role, so the agent attributed the wrong concern to the "PM". Also Q15: abstract search queries
missed the turn with the 15.5 total, the model still declared the evidence sufficient (mean iterations was 1.0 -
the lite model's self-assessment is overconfident), and the revision step removed a correct claim. Common thread:
exact-quote validation stops fabrication, not wrong reasoning or wrong attribution.

**Cost and time at 1,000 meetings** (`cost_estimate.md`, from measured tokens). ~31k chunks embedded locally ($0;
1.2 h on this 2-core laptop CPU, minutes on a GPU), ~2,700 extraction calls (4.2k in / 1.9k out tokens each,
measured) + 250 team reconciliations ≈ **$16** at Nov-2026 list prices ($21 at 2027 prices), ~1.6 h of LLM time
at 8-way parallelism on a paid tier, ~0.3 GB storage. New meetings cost ~$0.016 each; unchanged files are free.
The real constraint here was free-tier capacity, not money: 500 requests/day on flash-lite and 20/day on the
flash models, so ingesting 138 meetings took ~2.5 h of wall-clock.

**Production at 10,000+ meetings.** Move the verbatim store to Postgres (`tsvector` BM25 + `pgvector`/managed vector
DB, partitioned by team/org), run ingestion as a queue of idempotent per-meeting jobs (hash → parse → chunk → embed
→ extract → reconcile team) with a paid-tier or Batch API LLM quota and GPU embeddings; reconcile incrementally per
team on each new meeting; key retrieval by organisation/team/date for access control; add speaker diarisation to
person-identity mapping (letters are per meeting); monitor citation-validity and abstention rates as quality SLOs;
and keep the deterministic citation validator as a hard gate in front of every answer.
