import requests

from src.citations.validator import snap_quote, validate_citation
from src.evaluation.schema import validate_submission
from src.memory.temporal import apply_links


# ---------------- citations ----------------
def test_exact_quote_validates_case_and_space_insensitive(store):
    conn = store[0]
    c = validate_citation(conn, "ES9001a", "um i think NORMAL batteries   are cheaper", "ES9001")
    assert c.valid and c.turn_idx == 3 and c.speaker == "C"


def test_paraphrase_and_corrected_grammar_fail(store):
    conn = store[0]
    assert not validate_citation(conn, "ES9001a", "normal batteries are cheaper, so let's go for batteries", "ES9001").valid  # filler 'uh,' removed
    assert not validate_citation(conn, "ES9001a", "normal batteries are less expensive so go", "ES9001").valid


def test_meeting_id_and_team_checks(store):
    conn = store[0]
    assert validate_citation(conn, "ES9001z", "whatever text here is long enough").error == "malformed meeting id"
    assert validate_citation(conn, "ES9001d", "whatever text here is long enough").error == "meeting id not in corpus"
    c = validate_citation(conn, "TS9002a", "The solar panel would work only in bright light", "ES9001")
    assert c.exact_match and not c.team_ok and not c.valid


def test_quote_must_be_within_one_turn_and_six_words(store):
    conn = store[0]
    c = validate_citation(conn, "ES9001a", "for batteries. Okay, we agree on normal", "ES9001")
    assert c.exact_match and not c.single_turn and not c.valid
    assert not validate_citation(conn, "ES9001a", "normal batteries are cheaper", "ES9001").valid


def test_snap_quote_returns_verbatim_transcript_text(store):
    conn = store[0]
    q, turn, ratio = snap_quote(conn, "ES9001a", "I think normal batteries are cheaper so let's go for batteries", 3)
    assert q == "Um I think normal batteries are cheaper, uh, so let's go for batteries." or \
        q in "Um I think normal batteries are cheaper, uh, so let's go for batteries."
    assert validate_citation(conn, "ES9001a", q, "ES9001").valid and turn == 3
    q2, _, _ = snap_quote(conn, "ES9001a", "the team chose a purple bamboo remote shaped like a fish", None)
    assert q2 is None  # unrelated paraphrase is not 'repaired'


# ---------------- temporal ----------------
def _rec(rid, order, turn, typ="decision", status="accepted", topic="energy source"):
    return {"record_id": rid, "meeting_order": order, "evidence_turn": turn, "type": typ, "status": status,
            "raw_status": status, "topic": topic, "related": []}


def test_supersede_keeps_history_and_marks_current():
    recs = [_rec("a1", 1, 5), _rec("b1", 2, 3)]
    out = {r["record_id"]: r for r in apply_links(recs, {}, [{"from": "b1", "to": "a1", "relation": "supersedes"}])}
    assert out["a1"]["status"] == "superseded" and out["a1"]["superseded_by"] == "b1"
    assert out["b1"]["supersedes"] == "a1"
    assert out["b1"]["is_current"] == 1 and out["a1"]["is_current"] == 0
    assert len(out) == 2  # history preserved


def test_later_proposal_does_not_override_accepted_decision():
    recs = [_rec("a1", 1, 5), _rec("c1", 3, 1, status="proposed")]
    out = {r["record_id"]: r for r in apply_links(recs, {}, [{"from": "c1", "to": "a1", "relation": "supersedes"}])}
    assert out["a1"]["status"] == "accepted" and out["a1"]["is_current"] == 1


def test_links_cannot_go_backwards_in_time():
    recs = [_rec("a1", 1, 5), _rec("b1", 2, 3)]
    out = {r["record_id"]: r for r in apply_links(recs, {}, [{"from": "a1", "to": "b1", "relation": "supersedes"}])}
    assert out["b1"]["status"] == "accepted"


def test_reject_confirm_complete_transitions():
    recs = [_rec("a1", 1, 1, status="proposed"), _rec("a2", 1, 2, status="proposed", topic="case"),
            _rec("a3", 1, 3, typ="action", status="unresolved", topic="prices"),
            _rec("b1", 2, 1), _rec("b2", 2, 2, status="rejected", topic="case"), _rec("b3", 2, 3, typ="reference")]
    links = [{"from": "b1", "to": "a1", "relation": "confirms"}, {"from": "b2", "to": "a2", "relation": "rejects"},
             {"from": "b3", "to": "a3", "relation": "completes"}, {"from": "b3", "to": "zz", "relation": "rejects"}]
    out = {r["record_id"]: r for r in apply_links(recs, {"a2": "Case Material"}, links)}
    assert out["a1"]["status"] == "accepted"
    assert out["a2"]["status"] == "rejected" and out["a2"]["topic"] == "case material"
    assert out["a3"]["status"] == "completed"


def test_state_as_of_excludes_later_meetings(store):
    from src.memory.temporal import state_as_of
    conn = store[0]
    for rid, mid, order, status in [("r1", "ES9001a", 1, "accepted"), ("r2", "ES9001b", 2, "accepted")]:
        conn.execute("INSERT INTO memory_records (record_id, team_id, meeting_id, meeting_order, type, topic, "
                     "description, status, raw_status, evidence_turn, related) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                     (rid, "ES9001", mid, order, "decision", "energy", "x", status, status, 1, "[]"))
    conn.execute("INSERT INTO memory_links VALUES ('ES9001','r2','r1','supersedes','')")
    full = {r["record_id"]: r for r in state_as_of(conn, "ES9001", 5)}
    before_b = {r["record_id"]: r for r in state_as_of(conn, "ES9001", 2)}
    assert full["r1"]["status"] == "superseded"
    assert set(before_b) == {"r1"} and before_b["r1"]["status"] == "accepted"


# ---------------- schema / missing evidence / API failure ----------------
def test_submission_schema(store):
    conn = store[0]
    good = {"answers": [{"question_id": "Q01", "answer": "Normal batteries.",
                         "citations": [{"meeting_id": "ES9001a", "quote": "Okay, we agree on normal batteries for now."}]}],
            "brief": "text"}
    assert validate_submission(good, ["Q01"], conn) == []
    bad = {"answers": [{"question_id": "Q01", "answer": "", "citations": []}]}
    probs = validate_submission(bad, ["Q01", "Q02"], conn)
    assert any("missing question ids" in p for p in probs) and any("empty answer" in p for p in probs)
    fake = {"answers": [{"question_id": "Q01", "answer": "x",
                         "citations": [{"meeting_id": "ES9001a", "quote": "we all agreed on solar power at once"}]}]}
    assert any("not found verbatim" in p for p in validate_submission(fake, None, conn))


class _StubLLM:
    """Returns canned JSON per task; used to test the agent's control flow offline."""
    def __init__(self, answer):
        self._answer = answer

    def complete(self, prompt, system="", chain=None, task="", **kw):
        from src.llm.client import LLMResult
        data = {"intent": {"answer_parts": ["x"], "search_queries": ["batteries"], "temporal": True, "topics": []},
                "answer": self._answer,
                "support_check": {"citations": [{"index": 1, "supports": True}], "unsupported_claims": []},
                "citation_repair": {"citations": []}}[task]
        return LLMResult(text="", data=data, provider="stub", model="stub")


def test_agent_abstains_when_no_verifiable_evidence(store):
    from src.agents.qa_agent import MeetingMemoryAgent
    from src.retrieval.hybrid import HybridRetriever
    conn, vs = store[0], store[1]
    ans = {"sufficient": True, "answer": "They chose solar.", "confidence": "low",
           "citations": [{"meeting_id": "ES9001a", "turn": 1, "quote": "we chose solar power for the remote control"}]}
    agent = MeetingMemoryAgent(conn, HybridRetriever(conn, vs), _StubLLM(ans))
    r = agent.answer("What energy source did team ES9001 pick?")
    assert r.abstained and r.citations == [] and r.answer.startswith("UNCERTAIN")
    r2 = agent.answer("What did the team pick?")  # no team id at all
    assert r2.abstained and r2.team_id is None


def test_agent_happy_path_snaps_and_validates(store):
    from src.agents.qa_agent import MeetingMemoryAgent
    from src.retrieval.hybrid import HybridRetriever
    conn, vs = store[0], store[1]
    ans = {"sufficient": True, "answer": "Batteries first, then kinetic.", "confidence": "high",
           "citations": [{"meeting_id": "ES9001b", "turn": 3, "quote": "we drop the batteries and go with a kinetic energy source"}]}
    r = MeetingMemoryAgent(conn, HybridRetriever(conn, vs), _StubLLM(ans)).answer("ES9001 energy source?")
    assert not r.abstained and r.citations[0]["meeting_id"] == "ES9001b"
    assert validate_citation(conn, "ES9001b", r.citations[0]["quote"], "ES9001").valid
    stages = [t["stage"] for t in r.trace]
    assert stages[:3] == ["scope", "intent", "retrieval"] and "citation_validation" in stages


def test_llm_client_falls_back_on_503(tmp_path, monkeypatch):
    from src.llm.client import LLMClient

    class R:
        status_code, text, headers = 503, "overloaded", {}
    c = LLMClient(cache_path=tmp_path / "c.sqlite", usage_path=tmp_path / "u.jsonl")
    monkeypatch.setenv("GEMINI_API_KEY", "x")
    monkeypatch.setenv("GROQ_API_KEY", "y")
    monkeypatch.setattr("time.sleep", lambda s: None)

    def boom(*a, **k):
        raise requests.HTTPError(response=R())
    monkeypatch.setattr(c, "_gemini", boom)
    monkeypatch.setattr(c, "_groq", lambda *a, **k: ('{"ok": true}', 5, 3))
    res = c.complete("hi", chain=[("gemini", "g-model"), ("groq", "q-model")])
    assert res.provider == "groq" and res.data == {"ok": True}
    assert c.complete("hi", chain=[("gemini", "g-model"), ("groq", "q-model")]).cached  # cache hit


def test_supersede_requires_same_topic():
    recs = [_rec("a1", 1, 5, topic="design phases"), _rec("d1", 4, 3, topic="speech recognition")]
    out = {r["record_id"]: r for r in apply_links(recs, {}, [{"from": "d1", "to": "a1", "relation": "supersedes"}])}
    assert out["a1"]["status"] == "accepted" and out["a1"]["superseded_by"] is None
    assert "d1" in out["a1"]["related"]  # association kept for context


def test_only_latest_accepted_per_topic_is_current():
    recs = [_rec("c1", 3, 4), _rec("d1", 4, 2), _rec("d2", 4, 9, topic="case")]
    out = {r["record_id"]: r for r in apply_links(recs, {}, [])}
    assert out["d1"]["is_current"] == 1 and out["c1"]["is_current"] == 0
    assert out["c1"]["status"] == "accepted"  # not marked superseded without an explicit link
    assert out["d2"]["is_current"] == 1


def test_extend_short_quote_stays_verbatim(store):
    from src.citations.validator import extend_quote
    conn = store[0]
    q = extend_quote(conn, "ES9001b", "drop the batteries")
    assert q and len(q.split()) >= 6 and validate_citation(conn, "ES9001b", q, "ES9001").valid
    assert "drop the batteries" in q


def test_inline_fake_quotes_are_unquoted(store):
    from src.agents.qa_agent import MeetingMemoryAgent
    from src.retrieval.hybrid import HybridRetriever
    conn, vs = store[0], store[1]
    agent = MeetingMemoryAgent(conn, HybridRetriever(conn, vs), _StubLLM({}))
    trace = []
    out = agent._guard_inline_quotes(
        'B said "The team decides to remove the sensor" and A said "we drop the batteries and go with a kinetic energy source".',
        "ES9001", trace)
    assert '"The team decides' not in out and "The team decides to remove the sensor" in out
    assert '"we drop the batteries and go with a kinetic energy source"' in out  # verbatim quote kept
    assert any(t["stage"] == "inline_quote_unverified" for t in trace)


def test_scope_note_flags_missing_meeting(store):
    from src.agents.qa_agent import MeetingMemoryAgent
    from src.retrieval.hybrid import HybridRetriever
    conn, vs = store[0], store[1]
    agent = MeetingMemoryAgent(conn, HybridRetriever(conn, vs), _StubLLM({}))
    assert "no meeting d" in agent._scope_note("What did ES9001 report in their meeting d?", "ES9001")
    assert "no meeting c" in agent._scope_note("What happened in the third meeting?", "ES9001")
    assert agent._scope_note("What happened in meeting b?", "ES9001") == ""
