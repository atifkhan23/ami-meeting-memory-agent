# Failure analysis

Three questions from the independent evaluation (`outputs/evaluation_report.md`) that the agent got wrong or only
partly right, plus one graded question whose correct answer I verified in the transcript. Every claim about
"what the transcript supports" below was checked against the original files; every claim about "what the agent did"
comes from its saved trace or evaluation record.

---

## 1. E11 - abstention failure on a meeting that does not exist (scope)

**Question.** "What final production cost did Team IS1005 report in their meeting d?"

**Agent answered.** "Team IS1005 reported a maximum production cost of 12.50 Euros per unit, initially proposed in
meeting a and apparently reiterated by Speaker D in meeting b." Both citations were verbatim and valid
(IS1005a: *"We expect a production cost of maximum uh twelve point fifty Euro."*).

**What the evidence supports.** Nothing: the corpus has IS1005a, b, c only (`missing_meetings` in
`outputs/ingestion_stats.json`). The correct output is "meeting d is not in the corpus". The 12.50 figure is the
*budget target* from the brief, not a reported final cost.

**Why it failed.** Retrieval behaved correctly (only IS1005a-c were searched). But nothing told the model that the
question presupposed a meeting the store doesn't have, so it answered a nearby question with true but irrelevant
evidence. The citation validator can't catch this: the quotes are real and from the right team.

**Stage.** Scope/temporal grounding. The model was left to notice a structural fact that code already knew.

**Fix (implemented after the scored run).** `MeetingMemoryAgent._scope_note()` compares any meeting stage named in
the question ("meeting d", "fourth meeting") with the stages in the store and injects a scope note into the prompt.
Post-fix probe (`outputs/postfix_probe_E11_report.md`): *"Team IS1005 apparently has no meeting d in the corpus, so
their final production cost for that meeting cannot be reported."* The scored evaluation still counts E11 as
**incorrect**; the probe is reported separately.

---

## 2. E08 - wrong temporal conclusion although the evidence was retrieved (generation / temporal reasoning)

**Question.** "Who in Team ES2005 proposed a banana-shaped remote, who was sceptical of the fruit idea, and was
that scepticism still present at the final evaluation?"

**Agent answered.** A proposed it and D was sceptical (correct), "but this scepticism was no longer present by
meeting d when they presented a banana-based prototype."

**What the evidence supports.** At the final evaluation Speaker C says (ES2005d, turn 263): *"Just the fruit does
me in, I mean uh it might it might be trendy to some, but I'm just not swallowing the fruit"*, and that they
"would have liked to have seen the L_C_D_ screen". The objection survived to the end; the prototype being a
banana shows the team went ahead *despite* it.

**Why it failed.** Retrieval recall for this item was 1.0: turn 263 was in the evidence. The lite reasoning model
(gemini-3.5-flash-lite, the only reasoning model with free quota left) inferred "the latest artefact is a banana,
so the objection is resolved". That is exactly the "latest statement wins" error the temporal design is meant to
prevent. The structured memory didn't prevent it either: C's turn-263 objection was not extracted at all. The only
fruit-related `disagreement` record for ES2005d (r012, B versus D on how many fruit shapes to offer, status
`unresolved`) is a different dispute, so nothing in memory said "C still objects".

**Stage.** Generation (temporal reasoning), with a memory-extraction gap behind it.

**What I'd change.** (a) Treat the d-meeting evaluation section as a first-class source: extract per-person
evaluation verdicts as `disagreement` records whose status can only become `resolved` through an explicit
agreement link. (b) For "is X still the case?" questions, pass the latest record on that topic *per speaker* to the
answerer, not just the latest artefact. (c) Use a stronger reasoning model when quota allows (the requested
`gemini-3.6-flash` was unavailable all day).

---

## 3. E07 - mis-attributed speaker role and the wrong concern (memory: noisy role table)

**Question.** "Team ES2005 discussed an 'easy finder' gimmick. What form was first suggested and by whom, what
concern did the project manager raise, what alternative did another member suggest, and did speech technology end
up in the final design?"

**Agent answered.** D suggested a whistle finder (correct); "the project manager (Speaker C) raised the concern that
a loud movie would cause the remote to constantly beep"; the alternative was left vague; speech technology ended up
in the design (correct).

**What the evidence supports.** ES2005b: Speaker A asks *"have we done any research into how many people can
whistle?"*, and Speaker C proposes the alternative: *"instead of a whistle if it's got the voice recognition you
could have it just, you know, where are you?."* Speaker C did also raise a loud-movie false-trigger concern, so that
quote is real, but the agent attached it to the wrong role and missed C's actual alternative.

**Why it failed.** The per-meeting speaker-role table built at ingest is inconsistent for this team. For ES2005c the
extractor recorded *both* A and C as Project Manager and gave B two roles; for ES2005b it recorded C as Project
Manager. The answerer trusted the table, so "project manager" resolved to C and it chose C's concern. The citation
validator confirmed the quotes were verbatim, but it can't confirm a role.

**Stage.** Memory (role extraction), then generation.

**What I'd change.** Make roles deterministic where possible: one role per speaker per meeting, enforced by code;
prefer self-introductions in meeting a and carry them forward only when the speaker's voice/name evidence matches;
drop conflicting roles instead of storing both; and show the answerer the role's evidence quote, not just a label.

---

## Additional observed failure (graded question, answer verified by hand)

**Q15 (ES2016).** The transcript supports: total **15.5** (ES2016d, A: *"So our total is fifteen point five."*),
limit **12.5**, and the **LCD display** was removed (C: *"you could maybe take out the L_C_D_ dis display even"*,
then A: *"Well there we go. Twelve point five."*). The agent's draft actually said "removed the LCD screen", but:
(1) the intent planner wrote abstract queries ("cost over budget remove component") instead of spoken words, so
the decisive chunks ES2016d-c013/c014 were never retrieved; (2) the model nevertheless marked the evidence
*sufficient*, so no second retrieval round ran; (3) the support judge then flagged "LCD" as unsupported and the
revision step removed a claim that was in fact true. Final answer: vague ("removed a component").
**Fixes:** a deterministic sufficiency rule (every answer part must be covered by at least one valid citation,
otherwise force another round with the uncovered part as the query); query expansion with numbers spelled out the
way people speak ("fifteen point five", "twelve fifty"); and let revision hedge but never delete the direct answer
to a question part.

## Patterns across failures

* **The verifier works, but it only checks that quotes are real.** All 4 failures above had 100% verbatim, valid
  citations. Exact-quote validation stops fabrication, not wrong reasoning or wrong attribution.
* **The agent almost never loops.** Mean retrieval iterations = 1.0: the lite model's self-assessment is overconfident.
  The loop exists and works (see unit tests and traces), but sufficiency should be decided partly by code.
* **Model availability shaped quality.** Every answer was produced by flash-lite models because `gemini-3.6-flash` and
  `gemini-3-flash-preview` were unavailable or quota-capped (20 requests/day) on the free tier.
