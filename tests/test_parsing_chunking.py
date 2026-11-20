import pytest

from src.ingestion.chunker import chunk_meeting
from src.parsing.transcript import TranscriptParseError, parse_file, parse_meeting_id, parse_text
from tests.conftest import make_transcript


def test_meeting_id_extraction():
    assert parse_meeting_id("ES2008b") == ("ES2008", "b", 2)
    assert parse_meeting_id("TS3012d") == ("TS3012", "d", 4)
    for bad in ["ES2008", "XX2008a", "ES2008e", "es2008a", "ES20081a"]:
        with pytest.raises(TranscriptParseError):
            parse_meeting_id(bad)


def test_parse_preserves_text_speakers_and_offsets(corpus):
    m = parse_file(corpus / "ES9001a.txt")
    assert m.team_id == "ES9001" and m.stage == "a" and m.order == 1
    assert [t.speaker for t in m.turns] == ["A", "B", "A", "C", "A", "B"]
    raw = open(corpus / "ES9001a.txt", encoding="utf-8", newline="").read()
    for t in m.turns:  # every turn maps back to the exact characters of the file
        assert raw[t.char_start:t.char_end] == t.text
    assert m.turns[3].text == "Um I think normal batteries are cheaper, uh, so let's go for batteries."


def test_header_mismatch_is_rejected():
    raw = make_transcript("ES9001a", [("A", "hello there")])
    with pytest.raises(TranscriptParseError):
        parse_text(raw, "ES9001b")


def test_empty_transcript_is_rejected():
    raw = make_transcript("ES9001a", [])
    with pytest.raises(TranscriptParseError):
        parse_text(raw, "ES9001a")


def test_chunks_cover_all_turns_never_split_and_overlap():
    turns = [("ABCD"[i % 4], " ".join(["word"] * 40) + f" turn{i}") for i in range(30)]
    m = parse_text(make_transcript("ES9001a", turns), "ES9001a")
    chunks = chunk_meeting(m, target=120, max_words=200, overlap=1)
    covered = set()
    for c in chunks:
        covered.update(range(c.turn_start, c.turn_end + 1))
        for i in range(c.turn_start, c.turn_end + 1):  # whole turns only
            assert m.turns[i].text in c.text
        assert c.meeting_id == "ES9001a" and c.team_id == "ES9001" and c.stage == "a"
    assert covered == set(range(30))
    for a, b in zip(chunks, chunks[1:]):
        assert b.turn_start <= a.turn_end  # overlap
    assert len({c.chunk_id for c in chunks}) == len(chunks)


def test_question_kept_with_answer():
    turns = [("A", " ".join(["x"] * 100)), ("B", "So which battery should we use?"), ("C", "Kinetic, definitely.")]
    m = parse_text(make_transcript("ES9001a", turns), "ES9001a")
    chunks = chunk_meeting(m, target=100, max_words=400, overlap=0)
    first_with_q = next(c for c in chunks if "which battery" in c.text)
    assert "Kinetic, definitely." in first_with_q.text
