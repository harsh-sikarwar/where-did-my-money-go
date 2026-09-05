# Demo script — 5-minute video

A run sheet for recording the submission video: what to have open, what order to show
things in, and roughly what to say. Total budget: 5 minutes. Rehearse once with a timer
before the real take — the numbers below assume you already know where to click.

**Record locally against `./scripts/demo.sh`**, not the live URL. Local is instant
(1.6s cold start — see README) and has zero risk of a free-tier cold-start stall
mid-recording. Mention the live link verbally / show it in the description; don't
demo *from* it.

---

## Before you hit record

```bash
./scripts/demo.sh
```

Confirm it lands on the overview (`/`) with the featured run's numbers rendered before
you start capturing.
Close other tabs/apps — screen real estate and a clean taskbar read as more finished than
they are. If your terminal will be visible at any point, make its font large enough to
read on a compressed video export.

---

## The 5 minutes

### 0:00–0:30 — The problem (talk over a blank slide or the terminal, no UI yet)

> "A merchant gets paid by Razorpay. The amount that lands almost never matches what
> they expected — fees, refunds, timing, silent subscription failures. Today that gap
> shows up as one word: 'unexplained.' Nobody owns figuring out why, because reconciliation,
> recovery, and cost are three different tools that don't talk to each other."

Say the track name once: "This is our submission for Track 04, AI Finance Controller."

### 0:30–1:30 — The overview and the verdict (`/` → `/analysis/[batch]`)

Land on the overview (`/`), then open the run's analysis page.

> "Here's the output. Not a table you have to interpret — a verdict. Expected 8.4 lakh,
> received 7.88 lakh, gap of 52,000. This much is just late settlement. This much is fees
> that match the contracted rate. This much is refunds that were never recorded. And this
> — six subscriptions that failed silently and are still recoverable — is the one thing
> that needs a human this week."

Click into one line item to expand the Evidence tab, or jump to `/orders/[batch]/[orderId]`
for a single order — land on a specific order/row to show the drill-down is real, not
decorative.

### 1:30–2:30 — The differentiator: correlation

Navigate to the correlation section on `/analysis/[batch]` (or the exceptions queue at
`/exceptions/[batch]`).

> "The core idea is this join: instead of treating 'money is missing' and 'a payment
> failed' as two separate problems, we correlate them. A gap that lines up with a failed
> payment retry isn't a mystery — it's a subscription that silently churned. That's what
> the 'before vs after' correlation number shows: how much of the unexplained pile this
> resolves."

Show the before/after correlation chart if it's on screen at this point — this is the
single most differentiating number in the product, worth a few extra seconds of pause on
it.

### 2:30–3:15 — Copilot / chat (optional, cut if running long)

> "You can also just ask it." Type a real question into `/copilot/[batch]` — something
> like "why is this gap different from last month" — and let the answer render.

> "Every number on this screen came from the deterministic engine before the model ever
> saw it. The model is only allowed to write the sentence — if its answer contains a
> number, we throw it away and use a template instead. So the model can't invent a
> figure, even by accident."

### 3:15–4:15 — Credibility (screen: README or docs/METRICS.md scrolled to the top table)

This is the section that separates "a nice demo" from "a measured claim" — don't skip it.

> "We didn't just build this, we measured it against 26 configurations — different
> volumes, payment mixes, settlement cycles — and planted over 2,200 adversarial payments
> designed to look exactly like the real thing. Zero false positives. Zero missed defects.
> And when we tested against Razorpay's own published sample data, we found and fixed two
> real parsing bugs — which is also the honest limit: we haven't reconciled a real
> merchant's full month yet, and we say so in the docs rather than hide it."

If time allows, show `docs/BROKE-FIXED.md` or `docs/LIMITATIONS.md` for one second as
visual proof this document exists — you don't need to read from it.

### 4:15–4:50 — Architecture in one breath

> "Under the hood: a Python reconciliation engine — deterministic, no AI in the money
> path — a thin FastAPI layer, and a Next.js dashboard. The model only ever writes
> prose. Everything is open source, fully tested, and there's a live link in the
> submission if you want to click through it yourself."

### 4:50–5:00 — Close

> "That's 'Where did my money go' — every rupee explained, and the one thing that
> actually needs your attention this week."

---

## What NOT to do

- Don't demo from the live Vercel/Render URL — a cold free-tier API waking up mid-recording
  is the single easiest way to lose a clean take. Record local, mention the link exists.
- Don't read metrics off a doc verbatim on camera — say the two or three numbers that
  matter (26 configs, 2,254 decoys, 0 false positives) from memory, glance at the screen
  for the rest.
- Don't apologize for the limitation on camera beyond one sentence. State it once,
  cleanly, and move on — over-explaining a caveat reads as less confident than stating it
  and continuing.
- Don't show a loading spinner for more than a second or two of footage — cut around it
  in editing if the API is slow on the day.

## If something breaks during recording

Kill and restart `./scripts/demo.sh` — it seeds a fresh deterministic batch every time,
so there's no state to corrupt. If a specific route errors, cut to a different route that
tells the same story; the four-line verdict and the correlation number are the two shots
you cannot lose, everything else is optional footage.
