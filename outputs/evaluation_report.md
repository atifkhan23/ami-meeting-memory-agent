# Evaluation report

Ground truth: 12 questions written and answered by reading the original transcripts (see `data/eval_questions.json`); 10 answerable + 2 abstention probes. Teams do not overlap with the 25 graded questions. Scores below are produced by `scripts/evaluate.py`; 'final' verdicts include the human review in `data/eval_manual_review.json` where present, automatic verdicts are regex key-fact matches.

## Summary

| Metric | Value |
|---|---|
| Final verdicts (correct / partial / incorrect) | 8 / 3 / 1 |
| Automatic verdicts (correct / partial / incorrect) | 6 / 5 / 1 |
| Citation exact-match accuracy (independent re-validation) | 1.0 |
| Citation support accuracy (gold meeting + judge) | 0.958 |
| Mean retrieval recall of gold evidence turns | 0.9 |
| Mean multi-meeting coverage of citations | 0.8 |
| Correct abstentions (of 2 unanswerable) | 1 |
| False abstentions (of 10 answerable) | 0 |
| Mean retrieval iterations | 1.0 |

## Per question

### E01 (IS1004; rejected proposals, historical vs current, decision changes): **correct**

**Q:** In Team IS1004's final costing, one member wanted a rubber case. Who was it, what happened to the rubber when the team went over budget, and what was the case made of in the end?

**Ground truth:** Speaker B wanted rubber (so it survives being dropped); Speakers A and D said it was too expensive. When the costing went over budget B (echoed by C) said to make it plastic instead of rubber, which brought them roughly on budget; the final case is plastic (plastic had already been recommended by C in meeting c).

**Agent:** Speaker B wanted a rubber case. When the team went over budget, they changed it to plastic to save money, and the final case was made of plastic.

facts 3/3 · auto=correct · citations valid 2/2 · supported 2 · retrieval recall 1.0 · coverage 0.5 · iterations 1
- [IS1004d] "Well no didn't we say we wanted to do a rubber" (judge supports: True)
- [IS1004d] "Make it plastic instead of rubber. And then we're basically o on budget" (judge supports: True)

_Reviewer note: Names B, the switch to plastic on going over budget, and the final plastic case. Omits that A and D objected (not asked)._

### E02 (ES2013; decision changes, historical vs current): **correct**

**Q:** Which energy source did Team ES2013 converge on in their conceptual design meeting, was it kept in the final costing, and what total cost did they reach against what budget?

**Ground truth:** Kinetic energy: the consensus in ES2013c was to use kinetic if at all possible; it was kept in ES2013d's costing (one kinetic unit), and the total came to 9.20 (pounds) against the 12.50 allowed.

**Agent:** During their conceptual design meeting, the team apparently converged on using kinetic energy. This energy source was kept in the final costing, where they reached a total cost of nine pounds and twenty pence against the allowed budget of twelve and a half.

facts 3/4 · auto=partial · citations valid 2/2 · supported 2 · retrieval recall 0.6666666666666666 · coverage 1.0 · iterations 1
- [ES2013c] "So the consensus seems to be use the kinetic if it's at all possible." (judge supports: True)
- [ES2013d] "the total cost has been calculated as nine Pounds twenty out of the twelve and a half we were allowed." (judge supports: True)

_Reviewer note: All four facts present; the regex missed the phrasing 'nine pounds and twenty pence'._

### E03 (IS1000; team member preferences, unresolved disagreements, decision changes): **correct**

**Q:** In Team IS1000, which speaker championed keeping an LCD screen and on what grounds, and what happened to the LCD and to speech recognition in the final costing?

**Ground truth:** Speaker C argued for the LCD (proposed it in IS1000c; in IS1000d said they really want an LCD or they would not get the market). In the final costing the LCD was cut (B: we should cut the LCD screen; replaced by extra buttons) and speech recognition was also taken out because of the budget, returning to the original, on-budget version.

**Agent:** Speaker C (the User Interface Designer) championed keeping an LCD screen on the grounds that it is essential for browsing multiple functionalities like TV, DVD, and VOD and targeting the four million sales audience. However, in the final costing (meeting d), both the LCD screen and speech recognition were cut entirely due to budget constraints, returning the team to the basic original design.

facts 3/4 · auto=partial · citations valid 2/2 · supported 2 · retrieval recall 1.0 · coverage 1.0 · iterations 1
- [IS1000c] "remote with L_C_D_ display for browsing because you have multiple functionalities" (judge supports: None)
- [IS1000d] "So um I I think we should we should cut the L_C_D_ screen. That that's that's my opinion." (judge supports: None)

_Reviewer note: C, sales/market grounds ('four million sales audience'), LCD and speech recognition both cut. Regex did not accept 'sales'._

### E04 (TS3005; decision changes, historical vs current): **partial**

**Q:** Team TS3005 designed an interface built around an LCD touch screen. To get within budget in their final meeting, what did they drop, and did the touch screen survive?

**Ground truth:** They dropped speech recognition together with the speaker/microphone and dropped the scroll wheel; the LCD touch screen stayed (the interface had been planned in TS3005c as only an LCD screen, no buttons).

**Agent:** The LCD touch screen apparently survived the final budget cuts in team TS3005. To meet the budget in the final meeting, the team decided to drop the scroll wheel.

facts 2/3 · auto=partial · citations valid 2/2 · supported 2 · retrieval recall 0.6666666666666666 · coverage 0.5 · iterations 1
- [TS3005d] "Okay, so we lose the scroll wheel, the s" (judge supports: True)
- [TS3005d] "so tha actually you could make an L_C_D_ screen but no mic, or it could make mic but no L_C_D_ screen," (judge supports: True)

_Reviewer note: Scroll wheel dropped and touch screen kept are right; misses that speech recognition and the speaker/microphone were dropped. The c-meeting gold turn was not retrieved._

### E05 (IS1006; who made a commitment, action ownership, commitment follow-up): **correct**

**Q:** In Team IS1006's second meeting, Speaker B asked for research into whether people really need to jump to high channel numbers. Who said they would look into it, and was an answer reported back in a later meeting?

**Ground truth:** Speaker D said they would have a look / check in their department for a specialist. No report-back of that research appears in IS1006c or IS1006d (not followed up in the transcripts).

**Agent:** In the second meeting, Speaker D offered to check in their department regarding user channel-switching habits, and apparently no follow-up report was ever provided in a later meeting.

facts 1/2 · auto=partial · citations valid 1/1 · supported 1 · retrieval recall 1.0 · coverage 1.0 · iterations 1
- [IS1006b] "Well I could could uh have a look at that maybe. I'll check in my department if there's someone specialist in that." (judge supports: True)

_Reviewer note: D, and correctly states no follow-up was reported; regex missed 'no follow-up report'._

### E06 (ES2015; team member preferences, unresolved disagreements, decision changes): **correct**

**Q:** In Team ES2015, which speaker found the fruit-and-vegetable trend a strange idea for a remote, how did another member propose adapting it, and how did the fruit theme show up in the final design?

**Ground truth:** Speaker A found fruit and vegetables a strange idea for a remote (ES2015c); Speaker B proposed a more abstract design stripped down to the basic shapes of fruits and vegetables; A then agreed to stick with the fruit and veggie theme. In ES2015d the design was mango-shaped and the colour combinations were named after fruits (e.g. banana black and yellow).

**Agent:** In Meeting C, Speaker A found the fruit and vegetable trend a strange idea for a remote control, and Speaker B proposed adapting it by using more abstract designs based on basic shapes. The fruit theme apparently showed up in the final design through color combinations named after different fruit like banana and watermelon.

facts 3/3 · auto=correct · citations valid 3/3 · supported 3 · retrieval recall 1.0 · coverage 1.0 · iterations 1
- [ES2015c] "um, do, according to our plans already, given the market. But fruits and vegetables seems a very strange idea for a remote control." (judge supports: True)
- [ES2015c] "I think we possibly could take a more abstract design. Like look at the basic shapes of different fruits and vegetables. And then just really like strip it down to like really basic shapes." (judge supports: True)
- [ES2015d] "Um and we're thinking to carry-on with the fruit and vegetable theme, the colour um combination just could just be named after different fruit, like banana could be black and yellow, watermelon red and green, or vanilla might be the most popular if it just uh blends in more settled cream instead of the others are all a bit garish." (judge supports: True)

### E07 (ES2005; rejected proposals, cross-meeting references): **partial**

**Q:** Team ES2005 discussed an 'easy finder' gimmick. What form was first suggested and by whom, what concern did the project manager raise, what alternative did another member suggest, and did speech technology end up in the final design?

**Ground truth:** Speaker D suggested an easy finder with a whistle function (ES2005b); Speaker A asked whether anyone had researched how many people can whistle; Speaker C suggested voice recognition instead, e.g. saying 'where are you?'. In the final evaluation (ES2005d) A said the remote has the latest trends in speech technology but no screen.

**Agent:** Speaker D (User Interface Designer) first suggested a whistle-activated easy finder feature, and the project manager (Speaker C) raised the concern that a loud movie would cause the remote to constantly beep. Another member apparently suggested an alternative, and speech technology ultimately ended up in the final design.

facts 4/4 · auto=correct · citations valid 3/3 · supported 2 · retrieval recall 1.0 · coverage 0.5 · iterations 1
- [ES2005a] "and as you say, we need to have some kind of gimmick, so um I thought maybe something like if you lose it and you can whistle, you know those things?" (judge supports: True)
- [ES2005b] "surely that would have to be um sort of specific rather than above a threshold 'cause if you had a loud movie on you're likely to get it beeping back at you." (judge supports: True)
- [ES2005b] "Excellent, so we'll go with speech recognition, yeah?" (judge supports: True)

_Reviewer note: Regex too lenient. Whistle finder by D is right and speech tech is in the design, but it labels Speaker C as project manager from a noisy role table, cites C's loud-movie concern instead of A's 'how many people can whistle' concern, and leaves the voice-recognition alternative vague._

### E08 (ES2005; unresolved disagreements, team member preferences): **partial**

**Q:** Who in Team ES2005 proposed a banana-shaped remote, who was sceptical of the fruit idea, and was that scepticism still present at the final evaluation?

**Ground truth:** Speaker A proposed the banana-shaped remote (ES2005c); Speaker D said they were not sure about the banana idea and C was sarcastic about fruit; at the final evaluation (ES2005d) Speaker C was still not 'swallowing the fruit' and would have liked an LCD screen, so the disagreement remained.

**Agent:** Speaker A apparently proposed a banana-shaped remote in meeting c, while Speaker D was sceptical of the fruit idea, but this scepticism was no longer present by meeting d when they presented a banana-based prototype.

facts 2/3 · auto=partial · citations valid 3/3 · supported 3 · retrieval recall 1.0 · coverage 1.0 · iterations 1
- [ES2005c] "Yeah. y I'm I'm not sure about the banana idea." (judge supports: True)
- [ES2005d] "So there we go and and um we have the banana-based one too." (judge supports: True)
- [ES2005d] "like we are having one banana design and the other one is orange, and Uh yeah, lower end." (judge supports: True)

_Reviewer note: A proposed and D was sceptical are right, but the temporal conclusion is wrong: it says the scepticism was gone by meeting d, while Speaker C was still 'not swallowing the fruit' at the final evaluation._

### E09 (ES2012; three or more meetings, decision changes): **correct**

**Q:** Trace Team ES2012's voice-recognition idea: who first floated a remote with no buttons using voice recognition, what risk did the designer raise in the next meeting, and was voice control in the final design?

**Ground truth:** Speaker A floated a remote with no buttons at all via voice recognition (ES2012b). In ES2012c Speaker B warned the voice technology was not highly developed / still experimental; A nonetheless confirmed it will have voice recognition. In ES2012d the final remote has a microphone for voice commands (and a speech 'where are you' function), alongside a few buttons.

**Agent:** Speaker A (Project Manager) first floated a remote control with no buttons using voice recognition in meeting b. In the next meeting (meeting c), the Industrial Designer raised the risk that the voice technology was still in an experimental form and not well developed. Voice control was included in the final design as part of a dual-function setup alongside essential physical buttons.

facts 3/3 · auto=correct · citations valid 3/3 · supported 3 · retrieval recall 1.0 · coverage 1.0 · iterations 1
- [ES2012b] "I wonder whether we could get the remote control with no buttons at all if we went for voice recognition," (judge supports: True)
- [ES2012c] "the voice technology is not really highly developed, it's sort of still still in an ex experimental form," (judge supports: True)
- [ES2012d] "the voice sensor is is expensive but we we made a a basic decision that that was absolutely fundamental to the to the design" (judge supports: True)

_Reviewer note: Three-meeting trail fully right._

### E10 (IS1001; indirect references, cross-meeting references): **correct**

**Q:** At the start of Team IS1001's final meeting, the project manager costed 'the aspect discussed last time'. What design did that refer to, and what did it cost against the limit?

**Ground truth:** It referred to the concept agreed in IS1001c: a standard battery, a yellow banana-shaped case with a spongy rubber cover, and a wheel; the cost came to 10.7 Euros against the 12.5 Euro limit.

**Agent:** At the start of the final meeting, Project Manager A costed the design aspects discussed previously, which included a standard battery, a yellow banana-shaped case with a rubber spongy material, and a wheel. This design cost 10.7 Euros, which was within the 12.5 Euro budget limit.

facts 4/4 · auto=correct · citations valid 3/3 · supported 3 · retrieval recall 0.6666666666666666 · coverage 0.5 · iterations 1
- [IS1001d] "so I look at the aspect discussed last time, that is to say uh to have a standard battery, to have a yellow banana shaped uh case with uh a rubber material around it to be uh to feel spongy," (judge supports: True)
- [IS1001d] "and uh also at the different aspect like having a wheel etcetera. And the cost ended to be ten point seven Euros." (judge supports: True)
- [IS1001d] "So which is uh good, because we had a price gap of twelve point five Euros." (judge supports: True)

_Reviewer note: Indirect reference resolved to the c-meeting concept; 10.7 vs 12.5 correct._

### E11 (IS1005; abstention): **incorrect**

**Q:** What final production cost did Team IS1005 report in their meeting d?

**Ground truth:** Cannot be answered: IS1005 has no meeting d in the corpus (only IS1005a-c). The agent should say the evidence is unavailable rather than invent a figure.

**Agent:** Team IS1005 reported a maximum production cost of 12.50 Euros per unit, initially proposed in meeting a and apparently reiterated by Speaker D in meeting b.

facts 0/1 · auto=incorrect · citations valid 2/2 · supported 2 · retrieval recall None · coverage None · iterations 1
- [IS1005a] "We expect a production cost of maximum uh twelve point fifty Euro." (judge supports: True)
- [IS1005b] "And our production cost of twelve fifty Euros per per unit is fairly high I think," (judge supports: True)

_Reviewer note: Abstention failure: IS1005 has no meeting d, but the agent answered with the 12.50 budget target from meetings a/b instead of saying meeting d is missing._

### E12 (IS1006; abstention, false premise): **correct**

**Q:** Why did Team IS1006 choose a wooden case for their remote control?

**Ground truth:** False premise: wood is never mentioned in any IS1006 transcript. The agent should say there is no evidence of a wooden case.

**Agent:** Team IS1006 apparently did not choose a wooden case, instead deciding to stick to titanium because it is a modern material.

facts 1/1 · auto=correct · citations valid 2/2 · supported 2 · retrieval recall None · coverage None · iterations 1
- [IS1006d] "But we still didn't want to go far from our titanium idea, 'cause it's the most of the moder the m the modern material we can p select." (judge supports: True)
- [IS1006d] "Material, we want to stick to titanium. We will send, we want to" (judge supports: True)

_Reviewer note: Rejected the false premise (no wooden case; titanium)._

