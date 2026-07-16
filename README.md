# PRD: Pre-Inspect — AI Move-Out Pre-Inspection (MVP)

**Status:** Draft v6 (condensed) · July 12, 2026 · No priors — first build of a new idea, 4-week solo build

## Problem

Move-out inspections are slow and adversarial. Tenants find out about deposit deductions only after it's too late to fix anything. PMs spend 30–60 min/unit inspecting and still get disputes over pre-existing damage.

## Product

Tenant films their emptied unit on move-out day, right before returning keys. AI fills out an inspection checklist: **Good / Bad / Needs review** per item, each with a short rationale and a video timestamp. Report arrives within the hour, split into **Fixable now** (cleaning, nail holes, bulbs) and **For your awareness**. Doubles as a timestamped proof of departure condition. Tenant may optionally share the report with their PM; PM can spot-check flagged items instead of inspecting everything.

**Non-negotiable:** tenant films, consents, reviews first, and shares or withdraws freely — no penalty, no staff filming occupied units, no dollar estimates.

## Goals

| Assumption | How we test it | Target |
|---|---|---|
| AI is accurate on amateur video | Staged-defect footage | ≥90% caught, ≤1 false-Good |
| Tenants will participate | Hallway tests, then real pilot | ≥50% share rate |
| PM would trust it | Demo + parallel manual inspection | ≤10% override rate |

## Scope

**In:** one default checklist, mobile-web upload, consent screen, AI assessment w/ timestamps, tenant report (no $ figures), deletion on request. Sharing gate + PM view are **P1** — build only if time allows.
**Out:** charge estimates, other property types (student/VR/hotel — roadmap), baseline comparison, dashboards, native app, payments.

## 4-Week Build

1. **The brain.** AI pipeline: video → checklist assessment w/ rationale + timestamps. Test on self-filmed staged-defect footage. *Done: correct report, <1hr, on known defects.*
2. **The tenant's door.** Upload flow: consent → capture guidance → upload → report. *Done: phone video in, readable report out, <1hr, no manual steps.*
3. **Harden it.** Error states, deletion flow, latency tuning, real hosting. Stretch: re-upload after fixes. *Done: a stranger completes the full flow on an unseen unit unassisted.*
4. **(P1) The PM's door.** Share/withdraw gate + PM report view + overrides. *First thing cut if behind schedule — tenant product is complete without it.*

## Risks

- **AI accuracy fails** → know by end of week 1, before building more.
- **Tenants don't share** → product still stands alone as a tenant tool; estimates/incentives held in reserve.
- **1-hour latency misses** → documentation value still holds; shift framing to "film the day before."
- **No PM ever signs on** → fine — week 4 is optional; validate tenant demand first.

## Open Questions

- Pilot jurisdiction / consent law (Legal)
- Reintroduce charge estimates if share rate lags?
- Tenant-standalone product vs. PM-bridge — decide after validation, not now

## Roadmap (post-MVP)

Student housing, vacation rentals, hotels — same tenant/guest-driven model, staff only ever film vacant units. Charge estimates, baseline comparison, self-serve config, PM dashboards. Each phase gated on the previous one passing.
