# finctl engine

The reconciliation engine. Python, uv-managed, **no web dependencies** — it is a library
with a CLI, and the web API is a thin wrapper over it (ADR-001).

That separation is deliberate: the Day-1 go/no-go checkpoint is a number printed to a
console. If reaching it required a running server, a frontend and an API key, every
debugging session would drag three extra moving parts along with it.

```bash
uv sync --group dev
uv run finctl doctor
uv run pytest          # 547 tests
```

For the stage-by-stage map of the pipeline, the CLI reference and the API routes, see the
[root README](../README.md). For what each stage *promises and refuses*, see
[docs/BEHAVIOR.md](../docs/BEHAVIOR.md).

---

## The invariants

These hold everywhere in this package. A violation is a bug regardless of how good the
output looks. Full statements in [docs/BEHAVIOR.md](../docs/BEHAVIOR.md).

1. **Money is an integer count of paise.** No floats, no rupee decimals, anywhere inside
   the engine. Rupees exist only in display formatting. (ADR-003)
2. **No stage before `explain` may call an LLM.** Matching, fee arithmetic, classification
   and correlation are deterministic. A hard architectural boundary, not a preference.
3. **Every classification carries its proof** — the arithmetic, as data, not prose. A row
   that cannot show its working is `UNEXPLAINED`, not guessed.
4. **Same input, same output.** Fixed seed + fixed config → byte-identical runs. This is
   what makes the golden-file tests possible.
5. **Fail loudly, never guess.** Unmappable input raises. Silent coercion of ambiguous
   data is the failure mode that produces confident wrong answers.
6. **The lines must sum to the gap.** Asserted on every run (ADR-024). This invariant has
   caught four bugs that component tests could not see, because each individual number was
   correct and the *relationship between* them was wrong.

---

## Layout

```
finctl/
  config/       loader + defaults/*.yaml — rates, tolerances, archetypes, defects
  generate/     generator, ground_truth, writer
  normalize/    arbitrary columns → canonical schema, integer paise, UTC
  stage/        immutable staging, content-hash duplicate detection
  match/        two-pass matcher
  classify/     deterministic rules with proof
  correlate/    the differentiator — failed payments, halted subscriptions
  rank/         benign vs actionable
  explain/      the only stage permitted to call an LLM
  adapters/     live Razorpay API
  audit/        JSONL decision log

  pipeline.py   run() — the single entry point the API calls
  money.py      integer paise
  fees.py       MDR + GST arithmetic
  gap.py        gap decomposition (ADR-024)
  cycle.py      settlement cycle, observed from the batch (ADR-030)
  calendar.py   working days
  score.py      scoring against ground truth
  matrix.py     the metrics matrix
  blind.py      blind testing
  cli.py        the CLI surface

tests/
  golden/       golden files — byte-identical output is the contract
  fixtures/     Razorpay response shapes (each declares live_capture: true|false)
```

## Configuration is data, never constants

Every rate that could vary by merchant, payment method or contract is in
`finctl/config/defaults/*.yaml`. The loader **refuses to supply a default MDR** — a
missing rate is an error, not an assumed 2%.

This is the single most likely place for the build to be quietly wrong, so the failure is
made loud by design.

```bash
uv run finctl rates --amount 4000     # contracted fee across every payment method
```

Note that **UPI is ~2%, not 0%**. Zero MDR on bank-to-bank UPI is real and statutory,
but it describes *interchange*, not the merchant's cost: Razorpay levies a platform fee
regardless, and that is what appears on the settlement row. Expecting zero would flag
every UPI row as a fee discrepancy — a real bug we shipped and fixed (ADR-035). GST at
18% applies **to the fee**, never to the transaction amount.

## Testing

```bash
uv run pytest                        # 547 tests
uv run pytest tests/test_golden.py   # golden files unchanged
uv run finctl golden --update        # rewrite them — only after reading the diff
uv run finctl matrix                 # 22-run metrics matrix → docs/matrix-results.json
uv run finctl blind new              # a batch whose answers you cannot see
```

The blind loop is the honest test: `blind new` prints nothing about what it planted,
`blind run` needs no ground truth, and `blind score` reveals the answers afterwards. The
protocol — including hand-editing batches to reach shapes the generator cannot produce —
is in [docs/BLIND-TEST.md](../docs/BLIND-TEST.md).
