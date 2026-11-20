# Evaluation report

Ground truth: 12 questions written and answered by reading the original transcripts (see `data/eval_questions.json`); 10 answerable + 2 abstention probes. Teams do not overlap with the 25 graded questions. Scores below are produced by `scripts/evaluate.py`; 'final' verdicts include the human review in `data/eval_manual_review.json` where present, automatic verdicts are regex key-fact matches.

## Summary

| Metric | Value |
|---|---|
| Final verdicts (correct / partial / incorrect) | 0 / 0 / 1 |
| Automatic verdicts (correct / partial / incorrect) | 1 / 0 / 0 |
| Citation exact-match accuracy (independent re-validation) | 1.0 |
| Citation support accuracy (gold meeting + judge) | 0.0 |
| Mean retrieval recall of gold evidence turns | None |
| Mean multi-meeting coverage of citations | None |
| Correct abstentions (of 1 unanswerable) | 1 |
| False abstentions (of 0 answerable) | 0 |
| Mean retrieval iterations | 1.0 |

## Per question

### E11 (IS1005; abstention): **incorrect**

**Q:** What final production cost did Team IS1005 report in their meeting d?

**Ground truth:** Cannot be answered: IS1005 has no meeting d in the corpus (only IS1005a-c). The agent should say the evidence is unavailable rather than invent a figure.

**Agent:** Team IS1005 apparently has no meeting d in the corpus, so their final production cost for that meeting cannot be reported.

facts 1/1 · auto=correct · citations valid 2/2 · supported 0 · retrieval recall None · coverage None · iterations 1
- [IS1005c] "So uh seven not seven but let's say five by ten it's I think it's that's my opinion." (judge supports: False)
- [IS1005c] "Okay, so five to ten, I I think it's it's feasible. I'll make it." (judge supports: False)

_Reviewer note: Abstention failure: IS1005 has no meeting d, but the agent answered with the 12.50 budget target from meetings a/b instead of saying meeting d is missing._

