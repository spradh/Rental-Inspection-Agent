# Business Requirements Document: Loom & Co. Data Analyst Agent

| | |
|---|---|
| **Document** | Business Requirements Document (BRD) |
| **Product** | Loom & Co. BI Analyst Agent |
| **Status** | Proposal (in review) |
| **Version** | 1.0 |
| **Owner** | Data / Analytics |
| **Stakeholders** | Leadership (CEO/COO), Finance, Marketing, Merchandising/Product, Operations, Data Engineering, Security & Compliance |
| **Last updated** | June 2026 |

> Companion docs: architecture in [`project/README.md`](README.md); dataset and KPI definitions in [`data/README.md`](../data/README.md) and [`data/docs/metric-definitions.md`](../data/docs/metric-definitions.md).

---

## 1. Problem Statement

Loom & Co. runs on its data, but **getting a trustworthy answer out of it is slow, manual, and inconsistent.** Today:

- **Every question is a project.** A business question ("why did West-region conversion drop?", "what's our margin this quarter?") requires an analyst to hand-write SQL, know which tables to join, and remember how each KPI is *defined*. Leaders wait hours to days for answers.
- **Definitions drift.** "Net revenue", "gross margin", "active customer", and "return rate" are computed slightly differently by different people, so numbers disagree across decks and nobody fully trusts them.
- **Problems are found late.** Margin compression, return spikes, churned cohorts, and conversion drops surface in the *monthly* business review, after the damage is done.
- **Analysts are a bottleneck.** Skilled analysts spend most of their time on repetitive, ad-hoc pulls instead of high-value investigation, and there is no self-serve path for non-technical stakeholders.

**We need a self-serve analyst agent** that answers business questions in natural language, **grounded in the warehouse and the canonical metric definitions**, with cited evidence. It must be fast enough to use in the moment, trustworthy enough to act on, and safe enough to expose across roles.

## 2. Background & Context

**Loom & Co.** is a direct-to-consumer (DTC) apparel brand. Its operational data lives across **8 core tables** (`customers`, `products`, `orders`, `order_items`, `returns`, `web_sessions`, `marketing_campaigns`, `inventory`) spanning **Jan 2024 to present**, alongside a knowledge base of **canonical KPI definitions**, a data dictionary, a business glossary, and a data-access policy.

**Current state.** Analysis is done through ad-hoc SQL and one-off dashboards. The metric dictionary exists but is not consistently applied. There is no governed, conversational interface to the data, and no proactive monitoring, so issues are reviewed on a monthly cadence.

**Why now.** Recent business episodes show the cost of slow, manual analysis, and are representative of the recurring questions the agent must handle:

| Episode | What happened | Why it matters |
|---|---|---|
| **SPRING26 promo** (Apr 2026) | A 25%-off code lifted volume but **compressed gross margin (~65% to ~59%)** | Promo profitability needs to be caught in-month, not in the quarterly review |
| **Rivet Slim Jeans returns** | A fit issue drove a **~30% return rate vs ~6% baseline** | Product and returns problems erode margin and CX silently until flagged |
| **"flashdeal" churn** | Customers acquired via flashdeal **repeat ~23% vs ~50–63%** for other channels | Channel CAC is wasted on low-loyalty cohorts |
| **West-region conversion** | Web conversion **slipped from ~6% to ~2% from Mar 2026** | A funnel regression went undiagnosed for weeks |

These are exactly the "what happened / why / what next" questions the agent is being built to answer in seconds, with evidence, instead of weeks after the fact.

Mature, AI-native tooling now makes this feasible: LLMs that reliably generate SQL and reason over results, retrieval for grounding answers in the company's own definitions, and a multi-agent design that decomposes a question across specialist domains.

## 3. Business Impact Metrics

Success is measured against today's manual baseline. Targets are for the first two quarters post-launch.

| Metric | Baseline (today) | Target | Why it matters |
|---|---|---|---|
| **Time-to-insight** (median question to answer) | Hours to days | **< 1 minute** | Decisions happen in the moment, not next week |
| **Self-serve rate** (questions answered without an analyst) | ~0% | **≥ 60%** | Frees analysts for high-value work |
| **Analyst hours on ad-hoc pulls** | Baseline | **−50%** | Direct productivity and cost savings |
| **Answer accuracy** (vs SQL ground truth on the eval set) | N/A | **≥ 90%** | Trust: answers must be correct to be acted on |
| **Hallucination / unsupported-claim rate** | N/A | **≤ 5%** | Wrong-but-confident answers are worse than none |
| **Metric-definition consistency** (answers using canonical KPI defs) | Inconsistent | **100%** | One source of truth for the numbers |
| **Anomaly detection latency** (margin/returns/conversion/churn) | Monthly | **Weekly or faster** | Catch margin, return, and conversion issues early |
| **Adoption** (weekly active business users) | N/A | Grow QoQ | Realized value scales with usage |

> Illustrative value: detecting a SPRING26-style margin compression or a Rivet-style return spike **weeks earlier** protects gross margin and CX, and reducing wasted CAC on low-loyalty channels improves marketing efficiency.

## 4. Business Requirements

### 4.1 Functional requirements (what the agent must do)

| # | Requirement | Description |
|---|---|---|
| FR-1 | **Ask** (grounded Q&A) | Answer natural-language questions over the warehouse with a specific, **cited** answer. Look up the **canonical metric definition** before computing a KPI. |
| FR-2 | **Investigate** (root cause) | For "why" questions, decompose across domains (sales, marketing, product, forecasting) and return a root-cause answer with evidence. |
| FR-3 | **Predict** (forecasting) | Project net revenue and per-product demand months ahead using a real forecasting model. |
| FR-4 | **Act** (scenarios & recommendations) | Run what-if scenarios and produce ranked, actionable recommendations; surface inventory reorder needs and at-risk (churn) cohorts. |
| FR-5 | **Watch** (proactive monitoring) | Detect KPI anomalies (margin dip, conversion drop, high-return subcategory, low-repeat channel) vs. the prior period. |
| FR-6 | **Report** (autonomous review) | Generate a leadership-ready weekly business review (headline, what changed with root cause, outlook, ranked actions). |
| FR-7 | **Visualize** | Produce charts (trends, comparisons) rendered alongside the written answer, built from real query results. |
| FR-8 | **Converse** | Support multi-turn dialog so follow-ups ("now chart that", "why?") resolve against the conversation. |
| FR-9 | **Provenance** | Every answer exposes the **evidence**, the **SQL that actually ran**, and **source citations** so a human can verify it. |
| FR-10 | **Role-aware access** | Honor user roles (e.g. analyst, marketing-viewer, data-admin) for which data each caller may see. |

### 4.2 Non-functional requirements (how well it must do it)

| # | Requirement | Target / Description |
|---|---|---|
| NFR-1 | **Accuracy & grounding** | Answers derive from real tool calls (SQL, retrieval, models), not model memory; numeric claims trace to executed queries. |
| NFR-2 | **Trustworthiness** | Decline gracefully on false-premise or unknowable questions rather than inventing answers; honest confidence on every answer. |
| NFR-3 | **Security & privacy** | RBAC on data sources, PII redaction for non-privileged roles, and prompt-injection defense, all enforced **outside** the model. |
| NFR-4 | **Auditability** | Each request is logged with provenance (who asked, what ran) for compliance. |
| NFR-5 | **Performance** | Interactive latency (seconds) for typical questions; streamed responses for long-running ones. |
| NFR-6 | **Availability & deployability** | Runs as a service (API and UI), containerized, deployable to the cloud with a health check and a quality gate (evals) gating releases. |
| NFR-7 | **Cost efficiency** | Bounded per-query cost via caching, model selection/cascading, and token controls. |
| NFR-8 | **Extensibility** | New tools, data sources, and specialists can be added without re-architecting; the warehouse backend is swappable (local or cloud). |

### 4.3 Scope

**In scope:** conversational Q&A, investigation, forecasting, recommendations, anomaly detection, the weekly report, charts, role-based access, and a deployed API and Streamlit workbench over the Loom & Co. data.

**Out of scope (this phase):** write-back to operational systems (the agent reads, it does not place orders or change inventory), real-time streaming ingestion, fine-tuned or self-hosted models, and natural-language access to systems outside the defined warehouse and knowledge base.

### 4.4 Assumptions & dependencies

- The warehouse (SQLite locally, BigQuery in the cloud) is seeded and current; the KPI definitions in the knowledge base are the agreed source of truth.
- An LLM provider and, optionally, a vector store, cache, and tracing backend are available and funded.
- Role definitions and the data-access policy are signed off by Security & Compliance.

### 4.5 Key risks

- **Hallucination or wrong-but-confident answers:** mitigated by tool-grounding, cited provenance, an eval gate, and graceful refusals.
- **Metric drift:** mitigated by forcing canonical-definition lookup before computing.
- **Data-access or PII exposure:** mitigated by RBAC and PII redaction enforced in code, plus audit logging.
- **Model/provider variability and cost:** mitigated by evals, a model-agnostic design, and cost controls.

## 5. Key Dates

Phased delivery aligned to the build program (June to August 2026). Each phase ends with a working, demoable increment.

| Milestone | Target date | Deliverable |
|---|---|---|
| **Kickoff** | Tue, Jun 16, 2026 | BRD approved; environment and seeded data ready |
| **M1: Ask (MVP)** | Thu, Jun 26, 2026 | Grounded, cited text-to-SQL Q&A over the warehouse; retrieval-backed definitions |
| **M2: Analyst Agent** | Thu, Jul 9, 2026 | Multi-agent Investigate plus Predict/Act, conversation memory, eval suite, deployed to the cloud (API and UI) |
| **M3: Production hardening** | Tue, Jul 21, 2026 | Cost and performance optimization; security (RBAC, PII, audit, injection defense) |
| **M4: Review & sign-off** | Thu, Jul 30, 2026 | Stakeholder review against business-impact metrics; go/no-go |
| **GA / Launch** | Thu, Aug 6, 2026 | General availability to business users; adoption and metrics tracking begins |

> Dates are the proposed program timeline and may be adjusted at the M4 review based on eval results and stakeholder feedback.

---

### Appendix: capability to business-question mapping

| Capability | Example question it answers |
|---|---|
| Ask | "What was net revenue in March 2026?" |
| Investigate | "Why did West-region conversion drop last quarter?" |
| Predict | "Forecast net revenue for the next 3 months." |
| Act | "What needs reordering right now?"; "Which customer segments are at churn risk?" |
| Watch | "What changed vs last period?" (margin, returns, conversion, repeat rate) |
| Report | The autonomous Monday-morning business review |
| Visualize | "Plot monthly net revenue." |
