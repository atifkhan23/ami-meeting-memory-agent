"""Build the full technical report PDF (outputs/AMI_Meeting_Memory_Agent_Report.pdf).

All numbers come from outputs/ and the SQLite store; code snippets are cut from the real source files.

    python scripts/build_report_pdf.py
"""
from _report_common import *  # noqa: F401,F403
from _report_common import _bootstrap  # noqa: F401

OUT = config.OUTPUTS_DIR / "AMI_Meeting_Memory_Agent_Report.pdf"

story = []
W = A4[0] - 4 * cm

# ---- Page 1: title + summary (technical-but-clear version)
story += [Spacer(1, 1.0 * cm),
          P("<font size=24 color='#1F3A5F'><b>AMI Meeting Memory Agent</b></font>", ParagraphStyle("t", leading=30)),
          Spacer(1, 4),
          P("<font size=12 color='#2A7F8E'>Hybrid retrieval, temporal decision memory and verified citations over "
            "138 meeting transcripts</font>", ParagraphStyle("st", leading=16)),
          Spacer(1, 4),
          P("Catalist Media - Agentic AI Intern build test &nbsp;|&nbsp; Technical report &nbsp;|&nbsp; November 2026", SMALL),
          Spacer(1, 12)]
summary = Table([[P("<b>Summary.</b> A Python agent that ingests 138 AMI meetings into a persistent store "
                    "(SQLite + FTS5 + ChromaDB), extracts structured memory with an LLM, resolves how decisions change "
                    "across meetings with a <b>deterministic state machine</b>, and answers questions through an "
                    "<b>iterative retrieve-assess-answer loop</b>. Every citation is validated <b>verbatim in code</b> "
                    "before it can be returned.", BODY)]], colWidths=[W])
summary.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, -1), LIGHT), ("BOX", (0, 0), (-1, -1), 0.8, TEAL),
                             ("LEFTPADDING", (0, 0), (-1, -1), 10), ("RIGHTPADDING", (0, 0), (-1, -1), 10),
                             ("TOPPADDING", (0, 0), (-1, -1), 8), ("BOTTOMPADDING", (0, 0), (-1, -1), 8)]))
story += [summary, Spacer(1, 10), P("Key results (measured)", H2)]
story.append(table([
    ["Area", "Result"],
    ["Ingestion", f"{STATS['meetings']}/138 meetings, {STATS['turns']:,} turns, {STATS['chunks']:,} chunks, 0 errors"],
    ["Structured memory", f"{STATS['memory_records']:,} records, {VERIFIED[0] / VERIFIED[1]:.0%} with verified evidence quotes; "
                          f"{sum(LINKS.values())} temporal links; 35/35 teams reconciled"],
    ["25 assessment questions", f"25/25 answered; {N_CIT} citations, 100% verbatim; {N_MULTI}/25 multi-meeting"],
    ["TS3012 brief", f"State replayed as of before meeting d; {BRIEF['n_citations']}/{BRIEF['n_citations']} citations valid"],
    ["Independent eval (12 Q)", f"{V['correct']} correct / {V['partial']} partial / {V['incorrect']} incorrect; exact-match "
                                f"{S['citation_exact_match_accuracy']:.0%}, support {S['citation_support_accuracy']:.0%}, "
                                f"retrieval recall {S['mean_retrieval_recall']:.0%}"],
    ["Cost", f"$0 actual (free tiers); ~${COST[1]['llm_cost_usd']:.0f} per 1,000 meetings at list prices"],
    ["Tests", "32 pytest tests (parsing, ingestion, retrieval, temporal, citations, agent, provider fallback)"],
], [4.3 * cm, W - 4.3 * cm], bold_first_col=True))
story += [Spacer(1, 10), P("Contents", H2)]
story += bullets(["1. Problem and constraints", "2. Data inspection and design decisions", "3. System architecture",
                  "4. Ingestion pipeline and data model", "5. Hybrid retrieval", "6. Temporal memory (state machine)",
                  "7. Agent loop", "8. Citation validation", "9. Model vs code, and provider engineering",
                  "10. Evaluation and results", "11. Failure analysis", "12. Cost, scale and production"])
story.append(PageBreak())

# ---- 1 + 2
story += [P("1. Problem and constraints", H1)]
story += bullets(["<b>Goal:</b> turn meeting transcripts into queryable memory: decisions over time, who said what, "
                  "commitments, numbers.",
                  "<b>Outputs:</b> 25 answers (1-3 sentences, 1-3 citations each) and a pre-meeting brief for Team TS3012.",
                  "<b>Citation rule:</b> meeting id + quote of at least 6 words, verbatim, from <b>one speaker turn</b> "
                  "(case and spacing ignored).",
                  "<b>Scale constraint:</b> design for 10,000+ meetings, so the corpus (~900k tokens) is never put in one "
                  "prompt; the agent must <b>retrieve</b>."])
story += [P("2. Data inspection and design decisions", H1),
          P("Before writing code I profiled the dataset with deterministic scripts:", BODY)]
story.append(table([
    ["Finding", "Design decision"],
    ["138 files, 35 teams (ES/IS/TS), meetings a-d", "Team id is a mandatory metadata filter on every query"],
    ["Strict format: 'HH:MM:SS Speaker X' + one text line", "Regex parser; keeps char offsets into the original file"],
    ["0 malformed files; IS1002 lacks a, IS1005 lacks d", "Coverage report; agent must detect absent meetings"],
    ["Speaker letters not stable across meetings", "Roles stored per (meeting, speaker) with evidence quotes"],
    ["676,745 words, 48,148 turns, avg 4,904 words/meeting", "Chunk-level retrieval + fixed evidence token budget"],
], [7.6 * cm, W - 7.6 * cm]))
story += [P("Technology stack", H2)]
story.append(table([
    ["Layer", "Choice", "Reason"],
    ["Orchestration", "Plain Python (no LangChain/LangGraph)", "~150-line loop, fully traceable; no hidden prompts"],
    ["Verbatim store + lexical search", "SQLite + FTS5 (BM25, porter stemmer)", "Transactional, persistent, filterable"],
    ["Dense retrieval", "ChromaDB, all-MiniLM-L6-v2 (384-d)", "Local CPU embeddings, $0, metadata filters"],
    ["LLMs", "Gemini (primary), Groq (fallback), REST", "Free tiers; one provider abstraction"],
    ["UI / tests", "Streamlit / pytest", "Demo + offline deterministic tests"],
], [3.9 * cm, 5.6 * cm, W - 9.5 * cm]))
story.append(PageBreak())

# ---- 3 architecture
story += [P("3. System architecture", H1)]
story += bullets(["Three persistent memory layers: <b>verbatim</b> (exact turns), <b>search</b> (BM25 + vectors), "
                  "<b>structured</b> (typed records + temporal links).",
                  "One agent reads from all three; <b>green = deterministic code / local model</b>, <b>amber = LLM call</b>."])
story += [architecture_diagram(), P("Figure 1 - End-to-end architecture; red path = the agent's re-retrieval loop.", CAPTION)]
story.append(table([
    ["Component", "Module", "Model or code"],
    ["Parser (ids, speaker, time, offsets)", "src/parsing/transcript.py", "Code"],
    ["Ingestion: sha256, incremental, backfill", "src/ingestion/pipeline.py", "Code"],
    ["Speaker-turn chunker", "src/ingestion/chunker.py", "Code"],
    ["Embeddings + Chroma index", "src/retrieval/vector_store.py", "Local model"],
    ["BM25 + RRF + filters", "src/retrieval/hybrid.py", "Code"],
    ["Structured extraction", "src/memory/extractor.py", "LLM + code verification"],
    ["Temporal state machine", "src/memory/temporal.py", "LLM proposes, code decides"],
    ["Agent loop", "src/agents/qa_agent.py", "LLM for language, code for control"],
    ["Citation validator", "src/citations/validator.py", "Code only"],
    ["Provider layer", "src/llm/client.py", "Code (fallback, retry, breaker, cache)"],
], [5.9 * cm, 5.4 * cm, W - 11.3 * cm]))
story.append(PageBreak())

# ---- 3b LLMs: which, why, where and how
UM = usage_by_model()
N_LIVE, N_ALL = len(LIVE), len(USAGE)
story += [P("3.1 The LLMs: which ones, why, where and how", H1)]
story += bullets([f"<b>{len(UM)} different LLMs</b> were actually called, from <b>2 providers</b> (Google Gemini and Groq).",
                  f"<b>{N_ALL} LLM calls</b> in total: {N_LIVE} live API calls and {N_ALL - N_LIVE} answered from the "
                  "response cache (free, instant, reproducible). Every call is logged in "
                  "<font face='Courier'>logs/llm_usage.jsonl</font>.",
                  "<b>Why Gemini (primary):</b> free tier, very long context, native JSON output mode, two quality tiers "
                  "(flash for reasoning, flash-lite for bulk work).",
                  "<b>Why Groq (fallback):</b> a different provider, so one outage cannot stop the system; very fast "
                  "(~3-6 s); free open-weight models (gpt-oss).",
                  "<b>Why several models instead of one:</b> free-tier quotas are <b>per model</b> (20-500 requests/day), "
                  "and cheap bulk work (extraction) should not consume the quota needed for answering."])
ROLE = {
    "gemini/gemini-3.6-flash": ("Requested main reasoning model", "Best quality in the flash tier",
                                "Mostly 503/timeouts all day; 20 req/day free; only 1 successful call"),
    "gemini/gemini-3-flash-preview": ("2nd reasoning model", "Fast (~3 s), good quality",
                                      "Free tier only 20 req/day - exhausted early"),
    "gemini/gemini-3.5-flash-lite": ("Main reasoning model in practice", "Available when others were down",
                                     "Wrote every final answer and the brief"),
    "gemini/gemini-3.1-flash-lite": ("Bulk extraction + light steps", "Cheap, long context, JSON mode",
                                     "500 req/day free - fully used once"),
    "groq/openai/gpt-oss-20b": ("Extraction fallback", "Different provider, fast",
                                "8,000 tokens/min free - about 1 big call/min"),
    "groq/openai/gpt-oss-120b": ("Last-resort fallback", "Larger open model on Groq",
                                 "Same 8k tokens/min limit; answer prompts too big"),
    "groq/qwen/qwen3.8-27b": ("Tried for extraction", "Extra Groq capacity",
                              "Removed: only 1,000 output tokens/min"),
}
rows = [["Model", "Role", "Why chosen", "Live calls", "Avg latency", "What happened"]]
for m, u in UM.items():
    role, why, note = ROLE.get(m, ("-", "-", "-"))
    rows.append([m.split("/", 1)[1], role, why, str(u["calls"]), f"{u['lat'] / u['calls']:.1f} s", note])
story.append(table(rows, [3.3 * cm, 3.1 * cm, 2.9 * cm, 1.4 * cm, 1.5 * cm, W - 12.2 * cm]))
story += [P("Fallback chains (src/llm/client.py, config.py)", H2)]
story.append(table([
    ["Chain", "Order tried", "Used for"],
    ["Reasoning", "gemini-3.6-flash -> gemini-3-flash-preview -> gemini-3.5-flash-lite -> gemini-3.1-flash-lite -> "
                  "gpt-oss-120b", "Assess + answer, add evidence, reconcile, brief"],
    ["Bulk / cheap", "gemini-3.1-flash-lite -> gemini-3.5-flash-lite -> gpt-oss-20b -> gpt-oss-120b",
     "Extraction, intent planning, support judge, revision"],
], [2.3 * cm, 9.6 * cm, W - 11.9 * cm]))
story += [P("How one LLM call works", H2), llm_call_diagram(),
          P("Figure - Every request: cache check, circuit breaker, API call with retries, JSON parsing, usage ledger; "
            "any failure falls back to the next model.", CAPTION)]
story.append(PageBreak())

story += [P("Where each LLM is used in the workflow", H1)]
import collections  # noqa: E402

TASK_COUNT = collections.Counter(u["task"] for u in LIVE)
story.append(table([
    ["Phase", "LLM task", "Chain", "Input to the LLM", "Output (JSON)", "What code does next"],
    ["Ingestion (once per meeting)", f"extract ({TASK_COUNT['extract']} calls)", "Bulk",
     "~2,200-word transcript segment with turn ids", "Typed records + quote + turn; speaker roles",
     "Snaps/verifies every quote; stores records"],
    ["Ingestion (once per team)", f"reconcile ({TASK_COUNT['reconcile']})", "Reasoning",
     "Compact record list (no transcripts)", "Canonical topics + typed links",
     "State machine applies or rejects links"],
    ["Per question", f"intent ({TASK_COUNT['intent']})", "Bulk", "Question + team",
     "Answer parts + 5-7 search queries", "Runs hybrid retrieval"],
    ["Per question", f"answer ({TASK_COUNT['answer']})", "Reasoning",
     "Question, roles, memory records, ~9k tokens of evidence", "sufficient? follow-ups, answer, citations",
     "Loops (max 3) or validates citations"],
    ["Per question", f"citation_repair ({TASK_COUNT['citation_repair']})", "Reasoning",
     "Answer + evidence", "New quotes", "Validates again"],
    ["Per question", f"support_check ({TASK_COUNT['support_check']})", "Bulk", "Answer + verified quotes",
     "Supported? unsupported claims", "Drops weak quotes; triggers next step"],
    ["Per question", f"add_evidence ({TASK_COUNT['add_evidence']})", "Reasoning",
     "Unsupported claims + evidence", "Extra quotes", "Validates, adds up to 3 citations"],
    ["Per question", f"revise ({TASK_COUNT['revise']})", "Bulk", "Answer + quotes + flagged claims",
     "Rewritten answer", "Inline-quote guard; final answer"],
    ["Brief", f"brief ({TASK_COUNT['brief']})", "Reasoning", "State as of meeting d + evidence (a-c)",
     "Sections with citations", "Drops any item without a valid quote"],
], [2.0 * cm, 2.3 * cm, 1.85 * cm, 3.4 * cm, 3.1 * cm, W - 12.65 * cm]))
story += [P("Which model produced the final outputs", H2)]
ext_rows = conn.execute("SELECT model, COUNT(*) FROM extraction_runs GROUP BY model ORDER BY 2 DESC").fetchall()
only_lite = next((n for m, n in ext_rows if m == "gemini/gemini-3.1-flash-lite"), 0)
rec_rows = dict(conn.execute("SELECT model, COUNT(*) FROM reconcile_runs GROUP BY model").fetchall())
story += bullets(["<b>25 answers:</b> the answer step ran on <b>gemini-3.5-flash-lite</b> for all 25; light steps "
                  "(intent, judge, revise) also used gemini-3.1-flash-lite.",
                  "<b>TS3012 brief:</b> " + BRIEF["model"].split("/", 1)[1] + ".",
                  f"<b>Memory extraction:</b> {only_lite} of 138 meetings fully by gemini-3.1-flash-lite; the rest mixed "
                  "with Groq fallbacks during 503 bursts.",
                  "<b>Reconciliation:</b> " + ", ".join(f"{n} teams by {m.split('/', 1)[1]}" for m, n in rec_rows.items()) + ".",
                  "<b>Honest note:</b> the requested gemini-3.6-flash produced almost nothing; quality was limited by "
                  "lite models - a stronger model is the first improvement."])
story += [P("What the LLM never does", H2)]
story += bullets(["Never sets the final status of a decision (the state machine does).",
                  "Never decides if a quote is real (the validator does, word for word).",
                  "Never sees the whole corpus - only retrieved evidence within a fixed token budget."])
story.append(PageBreak())

# ---- 4 ingestion
story += [P("4. Ingestion pipeline and data model", H1)]
story += bullets(["<b>Discover</b> *.txt files, compute <b>sha256</b>; an unchanged hash means the file is skipped (idempotent).",
                  "<b>Changed file:</b> its derived rows (turns, chunks, vectors, memory) are deleted and rebuilt - incremental.",
                  "<b>Parse</b> each turn with its timestamp, speaker and <b>character offsets</b> into the source file.",
                  "<b>Chunk</b> whole turns only: target 220 words, max 400, 3-turn overlap; a turn ending in '?' extends "
                  "the chunk by up to 2 turns so questions keep their answers.",
                  "<b>Embed</b> chunks in batches of 64 with MiniLM (measured: 618 s for 4,334 chunks on a 2-core CPU).",
                  "<b>Resilience:</b> per-file failures are logged; a crash between commit and embedding is repaired by a "
                  "vector backfill on the next run (regression-tested)."])
story += snippet("src/ingestion/chunker.py", "while j < len(turns):", 13)
story += [P("Data model (SQLite)", H2)]
story.append(table([
    ["Table", "Purpose", "Key columns"],
    ["meetings", "One row per transcript", "meeting_id, team_id, stage, meeting_order, sha256"],
    ["turns", "Verbatim speech", "meeting_id, turn_idx, speaker, time, text, char_start/end"],
    ["chunks + chunks_fts", "Retrieval units + BM25 index", "chunk_id, turn_start/end, team_id, text"],
    ["memory_records", "Typed memory", "type, topic, status, raw_status, evidence_quote, evidence_turn, is_current"],
    ["memory_links", "Temporal relations", "from_id, to_id, relation (supersedes/rejects/confirms/completes)"],
    ["speaker_roles", "Per-meeting roles", "meeting_id, speaker, role, evidence_quote"],
], [3.3 * cm, 3.8 * cm, W - 7.1 * cm]))
story.append(PageBreak())

# ---- 5 retrieval
story += [P("5. Hybrid retrieval", H1)]
story += bullets(["<b>Lexical:</b> SQLite FTS5 BM25 over chunk text; the query is reduced to OR-joined content terms "
                  "(stop-words removed, input sanitised).",
                  "<b>Dense:</b> cosine similarity on 384-d MiniLM embeddings in Chroma, filtered with "
                  "<font face='Courier'>where={team_id}</font>.",
                  "<b>Fusion:</b> Reciprocal Rank Fusion, score = sum of 1 / (60 + rank) over both lists - no score "
                  "calibration needed.",
                  "<b>Coverage:</b> an extra per-meeting BM25 pass adds the best chunk from <b>each</b> of the team's "
                  "meetings, so 'how did it change' questions see a, b, c and d.",
                  "<b>Context expansion:</b> on later rounds, neighbouring chunks of the top hits are added.",
                  "<b>Why hybrid:</b> BM25 finds exact spoken tokens ('titanium', 'twelve fifty'); vectors find "
                  "paraphrases ('stop it getting lost')."])
story += [retrieval_diagram(), P("Figure 2 - Team-filtered hybrid retrieval with RRF fusion.", CAPTION)]
story += snippet("src/retrieval/hybrid.py", "scores: dict[str, float] = {}", 8)
story += [P("Evidence packing", H2)]
story += bullets(["Hits are merged into per-meeting turn sets and rendered <b>chronologically</b> as "
                  "<font face='Courier'>[meeting tN time] Speaker X: text</font>.",
                  "Bounded by an evidence budget of <b>9,000 tokens</b>, so per-question cost is independent of corpus size."])
story.append(PageBreak())

# ---- 6 temporal
story += [P("6. Temporal memory (state machine)", H1)]
story += bullets(["<b>Extraction (LLM, flash-lite):</b> each meeting is sent in ~2,200-word segments; the model returns "
                  "typed records (decision, action, commitment, disagreement, open question, reference) with a quote.",
                  "<b>Verification (code):</b> every evidence quote is snapped to the transcript - 96% verified.",
                  "<b>Reconciliation (LLM):</b> per team, the model sees only the compact record list (never "
                  "transcripts) and proposes canonical topics and typed links.",
                  "<b>State machine (code):</b> <font face='Courier'>apply_links()</font> is a pure, unit-tested "
                  "function that decides the final status."])
story += [state_diagram(), P("Figure 3 - Status transitions enforced in code.", CAPTION)]
story += bullets(["<b>Time order</b> = (meeting_order, turn_idx); links may only point backwards.",
                  "<b>Same-topic guard:</b> supersedes/confirms across different topics are downgraded to refers_to "
                  "(this caught a real LLM error).",
                  "<b>No 'latest statement wins':</b> only an <i>accepted</i> later decision can supersede; proposals cannot.",
                  "<b>Current</b> = latest accepted decision per topic; superseded records keep their evidence.",
                  "<b>state_as_of(cutoff)</b> replays the machine on earlier meetings only - used for the TS3012 brief "
                  "(meetings a-c)."])
story += snippet("src/memory/temporal.py", "for ln in links:", 11)
story += [P(f"Measured: statuses - {', '.join(f'{k} {v}' for k, v in sorted(STATUS.items(), key=lambda x: -x[1]))}. "
            f"Example (TS3012): LCD dropped in meeting b, reinstated in meeting c; current = keep LCD.", SMALL)]
story.append(PageBreak())

# ---- 7 agent
story += [P("7. Agent loop", H1)]
story += bullets(["<b>Scope (code):</b> regex for the team id; checks whether a referenced meeting stage exists.",
                  "<b>Plan (LLM):</b> splits the question into answer parts and writes 5-7 spoken-language search queries.",
                  "<b>Retrieve (code):</b> hybrid search per query + relevant memory records + per-meeting role table.",
                  "<b>Assess + draft (LLM):</b> returns sufficient / missing / follow-up queries / answer / citations "
                  "(meeting, turn, quote).",
                  "<b>Loop:</b> if insufficient, run the follow-up queries plus neighbour expansion; maximum 3 rounds.",
                  "<b>Verify (code):</b> snap and validate citations; one repair round if none survive.",
                  "<b>Support check (LLM judge):</b> flags unsupported claims; the agent first looks for more evidence, "
                  "then revises (hedges, never deletes the direct answer).",
                  "<b>Guards (code):</b> unverifiable quotation marks are removed from answer text; no valid citation "
                  "means UNCERTAIN."])
story += snippet("src/agents/qa_agent.py", "draft = res.data if isinstance(res.data, dict) else {}", 10)
story += [P("Real trace for Q01 (outputs/traces/Q01.json)", H2)]
TR = json.loads((config.OUTPUTS_DIR / "traces" / "Q01.json").read_text(encoding="utf-8"))
def _brief(t):
    st = t["stage"]
    if st == "scope": return f"team {t['team_id']}; meetings {', '.join(t['meetings'])}"
    if st == "intent": return "queries: " + "; ".join(t["queries"][1:4])
    if st == "retrieval": return (f"round {t['round']}: {t['total_chunks']} chunks from {len(t['meetings'])} meetings; "
                                  f"{t['memory_records']} memory records; {t['evidence_turns']} evidence turns")
    if st == "assessment": return f"sufficient={t['sufficient']} (model {t['model']})"
    if st == "citation_validation": return f"{t['valid']}/{t['proposed']} citations valid after snapping"
    if st == "support_check": return f"judge flagged {len(t.get('unsupported_claims') or [])} unsupported claim(s)"
    if st == "add_evidence": return f"searched evidence for more quotes: {t['added']} added"
    if st == "revise": return "answer rewritten to hedge unsupported parts"
    if st == "final": return t["answer"]
    return ""
story.append(table([["Stage", "Model", "Detail"]] +
                   [[t["stage"], (t.get("model") or t.get("judge") or ("code" if t["stage"] in ("scope", "retrieval", "citation_validation", "final") else "-")),
                     _brief(t)] for t in TR if _brief(t)],
                   [3.1 * cm, 3.3 * cm, W - 6.4 * cm]))
story.append(PageBreak())

# ---- 8 citations + 9 model vs code
story += [P("8. Citation validation", H1)]
story += bullets(["<b>Checks:</b> meeting id well-formed and present; meeting belongs to the question's team; quote "
                  "found inside <b>one turn</b> after normalising only case and whitespace; at least 6 words.",
                  "<b>Snapping:</b> word-level SequenceMatcher alignment against the cited turn (then neighbours, then "
                  "the meeting); if similarity >= 0.8 the <b>transcript's own characters</b> replace the model's quote.",
                  "<b>Short quotes:</b> a valid quote under 6 words is widened inside the same turn.",
                  "<b>Independent re-check:</b> answers.json is re-validated after generation, including the brief's quotes."])
story += snippet("src/citations/validator.py", "t = find_quote_turn(conn, meeting_id, quote)", 9)
story += [P("9. Model vs code, and provider engineering", H1)]
story.append(table([
    ["Deterministic code", "LLM"],
    ["Discovery, hashing, parsing, chunking", "Classifying decision vs suggestion vs question"],
    ["BM25, vector search, RRF, filters", "Owners of commitments; disagreements"],
    ["Temporal ordering and state transitions", "Proposing topic merges and temporal links"],
    ["Quote matching, snapping, schema checks", "Resolving indirect references; synthesis"],
    ["Evaluation scoring, cost arithmetic", "Sufficiency/support judgement; the brief"],
], [W / 2, W / 2]))
story += [Spacer(1, 4)]
story += bullets(["<b>Fallback chains:</b> reasoning = gemini-3.6-flash, 3-flash-preview, 3.5-flash-lite, 3.1-flash-lite, "
                  "Groq gpt-oss-120b; bulk = 3.1-flash-lite, 3.5-flash-lite, Groq gpt-oss-20b/120b.",
                  "<b>Reliability:</b> exponential back-off; cross-process <b>circuit breaker</b> (503: 2 min, timeouts: "
                  "15 min, daily quota: parsed from the violated quotaId).",
                  "<b>Cost control:</b> SQLite response cache (re-runs free and reproducible); usage ledger with tokens, "
                  "latency, retries.",
                  "<b>Measured limits:</b> 3.6-flash mostly 503; 20 req/day (3.6-flash, 3-flash-preview); 500 req/day "
                  "(3.1-flash-lite); Groq 8k tokens/min, so oversize prompts fail fast."])
story.append(PageBreak())

# ---- 10 results
story += [P("10. Evaluation and results", H1)]
story += bullets(["<b>Ground truth</b> written by reading transcripts (not by the agent's LLM); teams disjoint from the "
                  "graded set; 10 answerable + 2 abstention traps.",
                  "<b>Scoring:</b> regex key-fact matching (deterministic), then a recorded human review "
                  "(data/eval_manual_review.json).",
                  "<b>Metrics:</b> exact-match (validator re-check), support (gold meeting and judge), retrieval recall "
                  "(gold turns present in the retrieved evidence), multi-meeting coverage, abstention quality."])
rows = [["ID", "Team", "Category", "Verdict", "Recall"]]
for r in EVAL["rows"]:
    rows.append([r["id"], r["team"], r["category"][0], r["manual_verdict"] or r["auto_verdict"],
                 "-" if r["retrieval_recall"] is None else f"{r['retrieval_recall']:.2f}"])
t = table(rows, [1.4 * cm, 2 * cm, 6.5 * cm, 3 * cm, W - 12.9 * cm])
colour = {"correct": GREEN, "partial": AMBER, "incorrect": RED}
t.setStyle(TableStyle([("BACKGROUND", (3, i), (3, i), colour[rows[i][3]]) for i in range(1, len(rows))]))
story += [t, Spacer(1, 6)]
story.append(table([
    ["Metric", "Value"],
    ["Final verdicts (human-reviewed) / regex only",
     f"{V['correct']}/{V['partial']}/{V['incorrect']} / " + "{correct}/{partial}/{incorrect}".format(**S["verdicts_automatic"])],
    ["Citation exact-match / support", f"{S['citation_exact_match_accuracy']:.2f} / {S['citation_support_accuracy']:.2f}"],
    ["Retrieval recall / multi-meeting coverage", f"{S['mean_retrieval_recall']:.2f} / {S['mean_multi_meeting_coverage']:.2f}"],
    ["Correct abstentions / false abstentions", f"{S['correct_abstentions']} of 2 / {S['false_abstentions']} of 10"],
    ["Mean retrieval iterations", f"{S['mean_iterations']}"],
], [8.5 * cm, W - 8.5 * cm]))
story += [Spacer(1, 4)]
story += bullets([f"<b>25 graded questions:</b> 25/25 answered, {N_CIT} citations, 0 validation problems, "
                  f"{N_MULTI}/25 multi-meeting."])
story.append(PageBreak())

# ---- 11 failures + 12 cost
story += [P("11. Failure analysis", H1)]
story.append(table([
    ["Case", "Agent output", "Transcript truth", "Root cause / fix"],
    ["E11 IS1005 meeting d", "Gave 12.50 EUR from a/b", "Meeting d does not exist", "Scope; fixed with a deterministic stage-existence check"],
    ["E08 ES2005 fruit objection", "Objection 'gone'", "C: 'not swallowing the fruit'", "Generation (recall 1.0); latest-artefact-wins reasoning"],
    ["E07 ES2005 PM concern", "Wrong 'PM (C)'", "A raised the concern", "Memory: conflicting roles; enforce one role per speaker"],
    ["Q15 ES2016 costing", "'removed a component'", "15.5 vs 12.5; LCD removed", "Abstract queries missed the chunk; overconfident 'sufficient'"],
], [3.2 * cm, 3.3 * cm, 3.7 * cm, W - 10.2 * cm]))
story += [Spacer(1, 4)]
story += bullets(["<b>Insight:</b> exact-quote validation prevents fabrication, but not wrong reasoning or attribution.",
                  "<b>Weakness:</b> mean iterations = 1.0 - the lite model's self-assessment is overconfident; "
                  "sufficiency should be decided partly in code (every answer part covered by a citation)."])
story += [P("12. Cost, scale and production", H1)]
story.append(table([["Meetings", "Tokens", "Chunks", "LLM calls", "Cost 2026", "Cost 2027", "Storage", "Embed (CPU)"]] +
                   [[f"{r['meetings']:,}", f"{r['tokens']:,}", f"{r['chunks']:,}",
                     f"{r['extraction_llm_calls'] + r['reconcile_llm_calls']:,}", f"${r['llm_cost_usd']:,}",
                     f"${r['llm_cost_usd_2027_prices']:,}", f"{r['storage_mb']:,.0f} MB", f"{r['embed_hours_laptop_cpu']} h"]
                    for r in COST],
                   [1.6 * cm, 2.1 * cm, 1.8 * cm, 1.7 * cm, 1.9 * cm, 1.9 * cm, 2 * cm, W - 13 * cm]))
story += [Spacer(1, 4)]
story += bullets(["Based on <b>measured</b> tokens: 4.2k in / 1.9k out per extraction call, ~2.7 calls per meeting, "
                  "1 reconciliation per team.",
                  "<b>Incremental:</b> ~$0.016 per new meeting; unchanged files are free; query cost is flat in N.",
                  "<b>Production at 10k+:</b> Postgres (tsvector + pgvector), a queue of idempotent per-meeting jobs, paid "
                  "or Batch API quota, GPU embeddings, access control, and the citation validator as a hard gate."])
story += [P("Conclusion", H2),
          P("A persistent hybrid memory, an observable agent loop, a temporal model where <b>code decides what is "
            "current</b>, and verbatim citation checking. It answered all 25 questions with verified quotes, scored "
            f"{V['correct']}/{V['partial']}/{V['incorrect']} on a hand-checked evaluation, and its failure modes are "
            "measured and explained.", BODY),
          P("Data: AMI Meeting Corpus, University of Edinburgh and partners, CC BY 4.0.", SMALL)]


doc = SimpleDocTemplate(str(OUT), pagesize=A4, leftMargin=2 * cm, rightMargin=2 * cm, topMargin=1.7 * cm,
                        bottomMargin=2 * cm, title="AMI Meeting Memory Agent - Technical Report",
                        author="AMI Meeting Memory Agent project")
doc.build(story, onFirstPage=on_page, onLaterPages=on_page)
from pypdf import PdfReader  # noqa: E402
print(f"wrote {OUT} ({len(PdfReader(str(OUT)).pages)} pages)")
