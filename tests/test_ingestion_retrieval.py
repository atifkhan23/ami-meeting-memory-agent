from src.ingestion.pipeline import ingest
from src.memory import db
from src.retrieval.hybrid import HybridRetriever, fts_query
from tests.conftest import make_transcript


def test_ingest_counts_and_metadata(store):
    conn, vs, rep, _ = store
    assert len(rep.added) == 3 and not rep.errors
    s = db.stats(conn)
    assert s["meetings"] == 3 and s["teams"] == 2 and s["turns"] == 12
    row = conn.execute("SELECT * FROM chunks WHERE meeting_id='ES9001b'").fetchone()
    assert row["team_id"] == "ES9001" and row["stage"] == "b" and row["meeting_order"] == 2
    assert vs.count() == s["chunks"]
    assert rep.missing_meetings["ES9001"] == ["c", "d"]


def test_duplicate_ingestion_is_skipped(store):
    conn, vs, _, corpus = store
    rep2 = ingest(corpus, conn, vs)
    assert rep2.added == [] and rep2.updated == [] and len(rep2.skipped) == 3
    assert db.stats(conn)["chunks"] == vs.count()


def test_incremental_new_and_changed_files(store):
    conn, vs, _, corpus = store
    (corpus / "ES9001c.txt").write_text(make_transcript("ES9001c", [("A", "New meeting about the yellow colour scheme.")]), encoding="utf-8")
    (corpus / "TS9002a.txt").write_text(make_transcript("TS9002a", [("A", "Edited transcript about wind power now.")]), encoding="utf-8")
    rep = ingest(corpus, conn, vs)
    assert rep.added == ["ES9001c"] and rep.updated == ["TS9002a"] and len(rep.skipped) == 2
    texts = " ".join(r["text"] for r in conn.execute("SELECT text FROM turns WHERE meeting_id='TS9002a'"))
    assert "wind power" in texts and "solar" not in texts
    assert db.stats(conn)["chunks"] == vs.count()


def test_malformed_file_logged_not_fatal(store):
    conn, vs, _, corpus = store
    (corpus / "notes.txt").write_text("random file", encoding="utf-8")
    (corpus / "ES9003a.txt").write_text("Meeting: ES9003a\nTeam: ES9003\n\nno turns here\n", encoding="utf-8")
    rep = ingest(corpus, conn, vs)
    names = [e[0] for e in rep.errors]
    assert "notes.txt" in names and "ES9003a.txt" in names
    assert conn.execute("SELECT COUNT(*) FROM ingest_log WHERE status='error'").fetchone()[0] == 2


def test_retrieval_filters_by_team(store):
    conn, vs, _, _ = store
    r = HybridRetriever(conn, vs)
    hits = r.search("solar panel battery", team_id="ES9001", k=10)
    assert hits and all(h.team_id == "ES9001" for h in hits)
    hits2 = r.search("solar panel", team_id="TS9002", k=10)
    assert hits2 and all(h.team_id == "TS9002" for h in hits2)


def test_fts_query_sanitises_input():
    q = fts_query('What did "they" decide about the titanium case? (and AND OR)')
    assert '"titanium"' in q and '"case"' in q and "(" not in q


def test_vectors_backfilled_after_crash(store):
    """Simulate a crash after the SQLite commit but before embedding: rerun must repair the index."""
    conn, vs, _, corpus = store
    vs.docs.clear()
    rep = ingest(corpus, conn, vs)
    assert len(rep.skipped) == 3 and rep.backfilled == db.stats(conn)["chunks"] == vs.count()
