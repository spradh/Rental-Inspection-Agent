# PRD: Pre-Inspect — AI Move-In/Move-Out Documentation Assistant (MVP)

**Status:** Draft v8 · July 18, 2026 · Pivoted from tenant-filmed inspection to PM-only documentation tool · MVP testing uses AI-generated videos, not real PM-filmed footage

## Problem

Move-in and move-out documentation is slow and inconsistent. PMs spend 30–60 min/unit walking through and writing up condition notes by hand. Move-in documentation is often skipped or done sloppily, so there's no reliable baseline when a tenant eventually moves out — fueling disputes over what was pre-existing vs. new damage, and leaving PMs without a clean record to fall back on.

## Product

PM walks the **vacant** unit — once before a new tenant moves in, and again after a tenant moves out — filming and narrating what they see as they go ("scuff on the hallway wall," "stain on the counter," "blinds missing in bedroom"). AI transcribes the narration, notes what's visible in each timestamped segment, and compiles it into a formatted, room-by-room condition report. The AI also flags anything visually obvious that the PM didn't call out, for the PM to confirm or dismiss — it does not make an independent Good/Bad judgment.

Two sessions, two independent reports:
- **Move-in report** — PM can hand this to the incoming tenant as a record of starting condition.
- **Move-out report** — for the PM's own records.

**Non-negotiables:** PM only ever films a vacant unit (never an occupied one); report documents condition, never a dollar figure; raw video is discarded after the report is generated.

## Goals

| Assumption | How we test it | Target |
|---|---|---|
| AI accurately transcribes/organizes narration into the report | Compare AI-compiled report vs. the known script on AI-generated test videos (scripted narration + staged defects, ground truth known in advance) | `[NEEDS INPUT — proposed: ≥90% of scripted items captured correctly]` |
| AI's unnarrated-but-visible flags are useful, not noisy | Review flagged items on AI-generated test videos against known ground truth | `[NEEDS INPUT — proposed: ≤3 false/irrelevant flags per unit]` |
| A 1BD/1BA walkthrough fits the target format | Timed test walkthroughs on AI-generated videos | Video under 5 min, target 2–3 min; report generated within `[NEEDS INPUT — carry over 1hr from prior draft?]` |

## Scope

**In:** PM-only workflow (no tenant-facing screens), video+narration upload (under 5 min, target 2–3 min, 1BD/1BA units), AI transcription + visual documentation compiled into a formatted report organized by standard categories (walls/paint, floors, cleanliness, appliances, fixtures/hardware, windows/screens, general condition), light AI flagging of unnarrated-but-visible items, video deleted after processing.

**Out:** tenant-facing app/sharing/consent flow, automatic move-in-vs-move-out comparison, dollar/cost estimates, unit types beyond 1BD/1BA, native app, payments, PM portfolio dashboards.

## 4-Week Build

1. **The brain.** AI pipeline: narrated video → timestamped, categorized documentation + light flagging of unnarrated visible items. MVP test corpus is **AI-generated videos** (scripted narration + staged defects, ground truth known in advance) — test on an initial batch, **then on a fresh, unseen batch of AI-generated videos before week 2 starts**, so the risk gate checks generalization within the test corpus, not just memorized examples. *Done: report accurately reflects a generated walkthrough not previewed by the builder.*
2. **The PM's door.** Upload flow: video (with narration) → generated report, supporting both move-in and move-out sessions. *Done: an AI-generated (or real, if available) 1BD/1BA walkthrough uploads and produces a readable report with no manual steps.*
3. **Harden it.** Error states (poor narration, bad lighting, video too long), deletion of raw video post-processing, latency tuning, real hosting. *Done: the full flow completes unassisted on an unseen test video.*
4. **(P1) Compare.** Auto-diff move-in vs. move-out reports to surface likely new damage. *First thing cut if behind schedule — independent reports are the complete MVP without it.*

## Risks

- **AI documentation accuracy fails** → know by end of week 1, before building more.
- **AI-generated test videos don't match real PM-filmed footage** — lighting, camera shake, audio quality, and narration style from a real phone walkthrough may differ significantly from generated video, so MVP accuracy results may not transfer directly to real footage. Needs a real-footage validation pass before pilot, not just before general launch.
- **PM narration habits vary widely** (some narrate everything, some barely speak) → AI must lean more on visual flagging when narration is sparse; test both styles in week 1.
- **Report quality is capped by what the PM chooses to film/say** → garbage in, garbage out; not an AI failure mode, but worth setting PM expectations/guidance in the upload flow.
- **No PM adopts move-in documentation habit** → move-out-only still has standalone value as a documentation aid.

## Open Questions

- Report retention period (raw video is discarded post-processing, but how long is the generated report itself kept?)
- Numeric accuracy/flagging targets — placeholders above need real numbers once sample output exists
- Product naming — "Pre-Inspect" reads tenant-facing; consider a name reflecting the PM-documentation-assistant framing
- Real-footage validation: at what point (end of week 1? before pilot?) do we test against actual phone-filmed video instead of AI-generated test videos, and who films it?
- How are AI-generated test videos produced — what tool, and how is staged/scripted ground truth (which defects, which narration) tracked so accuracy can be scored against it?

## Roadmap (post-MVP)

Automatic move-in vs. move-out comparison (surfacing likely tenant-caused damage), unit types beyond 1BD/1BA, tenant-facing sharing, PM portfolio dashboards, cost/dollar estimates.
