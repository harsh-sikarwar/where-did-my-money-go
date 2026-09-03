# Documentation Index

The running record of this build, maintained as the work happens rather than
reconstructed at the end.

**Reading it cold, in order:** [../README.md](../README.md) for what this is and how the
stages map to code → [BEHAVIOR.md](BEHAVIOR.md) for what each stage promises and refuses →
[METRICS.md](METRICS.md) for what it measurably does (read the caveats above the table
first) → [LIMITATIONS.md](LIMITATIONS.md) for what it does not. [DECISIONS.md](DECISIONS.md)
and [JOURNAL.md](JOURNAL.md) are reference depth — 35 ADRs and a chronological log — rather
than front-to-back reads.

| File | What's in it | Read it when |
|---|---|---|
| [DECISIONS.md](DECISIONS.md) | Every fork taken — context, options, choice, why, consequences | You want to know *why* something is built the way it is |
| [JOURNAL.md](JOURNAL.md) | Chronological log: what was done, what broke, how it was fixed | You want the story, including the obstacles |
| [PRIOR-ART.md](PRIOR-ART.md) | What was borrowed and from whom; what was deliberately not | A judge asks "how is this different from Hyperswitch?" |
| [BEHAVIOR.md](BEHAVIOR.md) | Each stage's contract — promises, refusals, bad-input handling | Before writing or changing a stage |
| [METRICS.md](METRICS.md) | Measured results from test day | You need the numbers |
| [LIMITATIONS.md](LIMITATIONS.md) | Deliberate cuts and discovered limits | A judge asks what this doesn't do |
| [BLIND-TEST.md](BLIND-TEST.md) | The protocol for running against unseen and hand-edited batches | You want to know how we tested honestly |

## How these are maintained

- **`BEHAVIOR.md` is written before the code**, so it is a specification. Where the code
  and the contract disagree, one is a bug — and the disagreement gets named.
- **`DECISIONS.md` gets an entry at the fork**, not afterwards. An ADR written in
  hindsight records the justification, not the reasoning.
- **`JOURNAL.md` records obstacles including the ones that were embarrassing.** The
  diagnosis is the useful part.
- **`METRICS.md` is empty until real runs exist.** Placeholder numbers are how fabricated
  figures reach a submission.
- **`LIMITATIONS.md` grows the moment a limit is found**, not at writeup time.

Three of these — `DECISIONS.md`, `PRIOR-ART.md`, `LIMITATIONS.md` — are direct submission
source material. Judging criteria 1 (problem taste), 3 (AI judgment) and 4 (failure
recovery) ask for precisely what they contain.
