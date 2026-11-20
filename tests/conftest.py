import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.memory import db  # noqa: E402

HEADER = """Meeting: {mid}
Team: {team}
Meeting number: {n} ({stage}) of the team's four meetings
Speakers: Speaker A, Speaker B, Speaker C, Speaker D
Times: turn start time from the start of the recording (HH:MM:SS)
Source: AMI Meeting Corpus, CC BY 4.0

"""


def make_transcript(mid: str, turns: list[tuple[str, str]]) -> str:
    team, stage = mid[:6], mid[6]
    body = "".join(f"\n00:00:{i:02d} Speaker {spk}\n{text}\n" for i, (spk, text) in enumerate(turns))
    return HEADER.format(mid=mid, team=team, n="abcd".index(stage) + 1, stage=stage) + body


class FakeVectorStore:
    """Keyword-overlap 'vector' store so tests never download a model."""
    backend = "fake"

    def __init__(self):
        self.docs = {}

    def upsert(self, ids, texts, metadatas):
        for i, t, m in zip(ids, texts, metadatas):
            self.docs[i] = (t.lower(), m)

    def delete_meeting(self, mid):
        self.docs = {k: v for k, v in self.docs.items() if v[1]["meeting_id"] != mid}

    def count(self):
        return len(self.docs)

    def query(self, text, k=10, team_id=None):
        words = set(text.lower().split())
        scored = [(i, len(words & set(t.split())) / (len(words) or 1)) for i, (t, m) in self.docs.items()
                  if not team_id or m["team_id"] == team_id]
        return sorted(scored, key=lambda x: -x[1])[:k]


@pytest.fixture
def corpus(tmp_path):
    d = tmp_path / "transcripts"
    d.mkdir()
    files = {
        "ES9001a": [("A", "Okay, welcome everyone. I'm the project manager for this project."),
                    ("B", "Hi, I'm the industrial designer."),
                    ("A", "Should we use a rechargeable battery or normal batteries?"),
                    ("C", "Um I think normal batteries are cheaper, uh, so let's go for batteries."),
                    ("A", "Okay, we agree on normal batteries for now. B, can you check the prices of the case?"),
                    ("B", "Yes, I'll look into the price of a titanium case before next meeting.")],
        "ES9001b": [("A", "Last time we said batteries, but the kinetic option came up."),
                    ("B", "The titanium case costs too much, I'd rather use rubber for the case."),
                    ("D", "I don't agree, rubber looks cheap and the market wants something fancy."),
                    ("A", "Okay, we drop the batteries and go with a kinetic energy source instead.")],
        "TS9002a": [("A", "Welcome to TS9002. Let's discuss the solar panel idea today please."),
                    ("B", "The solar panel would work only in bright light, which is a problem.")],
    }
    for mid, turns in files.items():
        (d / f"{mid}.txt").write_text(make_transcript(mid, turns), encoding="utf-8")
    return d


@pytest.fixture
def store(tmp_path, corpus):
    from src.ingestion.pipeline import ingest
    conn = db.connect(tmp_path / "test.sqlite")
    vs = FakeVectorStore()
    rep = ingest(corpus, conn, vs)
    return conn, vs, rep, corpus


def _fake_ids(self):
    return list(self.docs)


FakeVectorStore.ids = _fake_ids
