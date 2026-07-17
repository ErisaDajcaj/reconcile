# StepUp — Charter

**Mentee:** Erisa Dajcaj — backend engineer, 6y payments/banking, individual contributor.
**Mentor:** StepUp (Claude, acting as growth mentor in every session + a biweekly cloud review).
**North Star:** become an **AI Architect** — see `[[ai-architect-path]]` in memory for the full staged path.
**Repo:** `https://github.com/ErisaDajcaj/stepUp` (the project + this charter + reviews live here).
**Born:** 2026-07-17. **Stands down when:** the 7 exit criteria below are all met (then graduates to a Stage 2/3 charter).

---

## The identity we're building

Not "the person with the most cutting-edge RAG" — she won't out-ML the ML people. The defensible architect identity is:

> **The person who makes agentic systems production-safe.**

Payments-grade reliability — idempotency, reconciliation, fail-closed, audit — ported into a field that is mostly demos. This through-line runs every decision, every review, every line of the project.

---

## The project — "Reconcile" (greenfield, from scratch)

A **new agentic reconciliation & verification service**, built from zero in the `stepUp` repo. NOT an evolution of any prior tool.

Input: a bank statement (PDF/CSV) + a set of expected records (invoices / expected payments). Output: proposed matches, flagged discrepancies, and **no silent auto-confirmation below a confidence threshold** — anything uncertain routes to a human-review queue.

The reconciliation is not the star. The **production-safety scaffolding is** — because that's the architect identity, and it's the exact thing that separates *builds agents* from *architects agent systems*. This domain (reconciliation + fail-closed + audit) is her payments DNA made concrete, not claimed.

Target architecture (the architect showcase — reusable patterns, documented):
- **Ingest/normalize agent** — parses heterogeneous statement formats into a canonical shape.
- **Matcher agent** — proposes each match with a confidence score and a rationale.
- **Verifier agent (the fail-closed gate)** — independently checks each proposed match; **never auto-confirms below threshold**; routes uncertain matches to a human-review queue. This is the payments DNA made concrete.
- **Eval harness** — labeled match dataset + metrics (match precision/recall, false-match rate), run in CI, gates merges on a documented threshold.
- **Observability** — per-job traces, token cost, latency, match-rate, false-match-rate. A dashboard.
- **Guardrails + runbook** — documented failure modes and the system's response to each (low confidence / parse failure / model disagreement → fail closed / human-review queue).

Why this project: it's greenfield (nothing recycled), its users are real and reachable (freelancers/bookkeepers who reconcile by hand monthly), the architect-grade work is precisely the ops layer, and verified-fail-closed reconciliation is her reliability identity demonstrated, not asserted. It also produces Stage-0 (README/design doc) and Stage-3 (reusable patterns) artifacts along the way.

*(Exact final name + the precise first vertical get locked in Sprint 1's brainstorm. The architecture above — production-safety as the star — is fixed regardless of which vertical we pick.)*

---

## Goals — the 7 exit criteria (StepUp stands down when ALL true)

1. **Legible** — project public on GitHub (`stepUp` repo) with an architecture README + one design doc explaining the multi-agent + verifier + eval design.
2. **Deployed** — running in production (real URL) with **≥5 real external users** who aren't her.
3. **Evaluated** — eval harness in CI: match precision/recall + false-match rate measured on a labeled set, with a documented threshold that gates merges.
4. **Observable** — per-job traces + cost/latency/match-rate dashboard live.
5. **Guarded** — the verifier agent enforces fail-closed (no auto-confirm below threshold); a failure-mode runbook is written.
6. **Published** — one public write-up (blog/repo doc) framing the reusable production-safety pattern.
7. **In motion** — applied to **≥3 AI-adjacent backend roles** with this project as the centerpiece.

---

## Review rubric (scored 1–5 each, every review, trend tracked)

| Axis | Question | Weight |
|---|---|---|
| Shipping | Did something reach a user / production this sprint? | high |
| **Production-safety depth** | Did the eval / guardrail / observability layer advance? | **highest** |
| Legibility | Is the thinking written down — README, design doc, commit hygiene? | high |
| Career motion | Applications, interviews, visible proof out in the world? | medium |
| Architect behaviour | Did she make AND document a design decision, not just implement? | high |

Mentor stance: rigorous and kind. Name gaps plainly, never inflate. A green light she didn't earn is worthless to her.

---

## Cadence

**Biweekly** — 1st and 15th of each month, 09:00 Europe/Rome. Enough to ship something between reviews alongside a full-time job; frequent enough to keep momentum and catch drift. (Cadence chosen by StepUp per delegation.)

---

## Sprint 1 — to 2026-08-01

1. **Bootstrap the `stepUp` repo** — brainstorm + lock the exact vertical and name; commit this CHARTER, an architecture README (first cut), and a design doc stub for the multi-agent + verifier design (Goal 1; also arms the cloud heartbeat).
2. **Write ONE real eval test** — a tiny labeled match set + a match-precision check that actually runs and passes/fails in CI. First brick of the eval harness — the differentiator (Goal 3).
3. **Career motion** — verify Deel is still open (deadline was approximate, ~15/07, may have closed); if open, apply. If closed, open the two Docplanner AI-Integration links by hand and apply. **≥1 application out** (Goal 7).

---

## Heartbeat prompt (run by the cloud StepUp routine every review)

> You are StepUp, Erisa Dajcaj's AI-Architect growth mentor. Read `CHARTER.md` in this repo — it defines her North Star, the project, the 7 exit criteria, and the scoring rubric. Read `reviews/` for prior reviews. Assess concrete progress by inspecting the actual repo: is there an eval harness in CI? a verifier/guardrail agent? a production deploy? README/design docs? Score each rubric axis 1–5 with evidence from the code (not vibes), name what advanced and what stalled, then set 3 concrete objectives for the next 2 weeks. Be rigorous and kind; never inflate a score she didn't earn. Write the review to `reviews/YYYY-MM-DD.md` and commit it. If ALL 7 exit criteria are met, declare Stage 0–1 complete and recommend graduating the charter. Do not modify anything outside `reviews/`.

---

## Review log

*(reviews land in `reviews/` — none yet; first on 2026-08-01)*
