# pm-plugin — Product Manager for protoAgent

A product-management toolkit for [protoAgent](https://github.com/protoLabsAI/protoAgent): the
tools, skills, subagents, and a console view that an AI agent — or a human PM working through
one — needs to **research and manage a product end to end**, from discovery to strategy,
execution, launch, growth, and shipping.

It bundles four things into one plugin:

- **65 PM skills** — discovery, strategy, execution, research, go-to-market, marketing/growth,
  analytics, AI-shipping, and PM utilities. Loaded by description, so the agent reaches for the
  right framework automatically.
- **The PM Brain** — a markdown-native, **provenance-enforced** knowledge base (decisions,
  hypotheses, stakeholders, knowledge areas, with an ingestion/source audit split), managed by
  tools so the agent's product memory persists and stays auditable.
- **Five PM specialist subagents** — a brain operator plus discovery, strategy, execution, and
  analytics specialists the lead agent can delegate to.
- **A PM Brain dashboard** — a console view surfacing decision debt, active hypotheses, stale
  stakeholders, and recent ingestion.

> Adapted from Paweł Huryn's excellent open-source work — [pm-skills](https://github.com/phuryn/pm-skills)
> and [pm-brain](https://github.com/phuryn/pm-brain) (MIT). This is an adaptation, not a verbatim
> copy: nine separate Claude Code plugins are unified into one, redundant skill variants are
> consolidated, and the PM Brain is re-implemented as protoAgent tools + a view. See [NOTICE](./NOTICE).

## Install

In the protoAgent console: **Plugins → Download → install from a git URL**
(`https://github.com/protoLabsAI/pm-plugin`), then **enable** it. It ships **disabled** — enabling
is your trust decision (ADR 0027). Needs a host serving the DS plugin-kit at `/_ds/` (≥ v0.34.0).

## The skill library (65)

Every skill is a `SKILL.md` loaded by description — the agent picks the right one for the task.

| Area | Skills |
|---|---|
| **Discovery** (10) | `brainstorm-ideas` · `identify-assumptions` · `design-experiments` · `opportunity-solution-tree` · `prioritize-assumptions` · `prioritize-features` · `interview-script` · `summarize-interview` · `analyze-feature-requests` · `metrics-dashboard` |
| **Strategy** (12) | `product-vision` · `product-strategy` · `value-proposition` · `lean-canvas` · `business-model` · `startup-canvas` · `swot-analysis` · `pestle-analysis` · `porters-five-forces` · `ansoff-matrix` · `monetization-strategy` · `pricing-strategy` |
| **Execution** (16) | `create-prd` · `brainstorm-okrs` · `outcome-roadmap` · `sprint-plan` · `user-stories` · `job-stories` · `prioritization-frameworks` · `pre-mortem` · `stakeholder-map` · `strategy-red-team` · `retro` · `release-notes` · `test-scenarios` · `summarize-meeting` · `wwas` · `dummy-dataset` |
| **Market research** (7) | `competitor-analysis` · `customer-journey-map` · `market-segments` · `market-sizing` · `sentiment-analysis` · `user-personas` · `user-segmentation` |
| **Go-to-market** (6) | `gtm-strategy` · `gtm-motions` · `growth-loops` · `beachhead-segment` · `ideal-customer-profile` · `competitive-battlecard` |
| **Marketing & growth** (5) | `north-star-metric` · `positioning-ideas` · `value-prop-statements` · `marketing-ideas` · `product-name` |
| **Data & analytics** (3) | `sql-queries` · `cohort-analysis` · `ab-test-analysis` |
| **AI shipping** (2) | `intended-vs-implemented` · `shipping-artifacts` |
| **PM toolkit** (4) | `review-resume` · `draft-nda` · `privacy-policy` · `grammar-check` |

> Consolidated from phuryn's 68: the existing/new variants of idea-brainstorming,
> assumption-identification, and experiment-design are merged into single mode-aware skills.

## The PM Brain

A second brain for product work — markdown files the agent reads before a task and writes after,
so product memory persists and stays greppable, diffable, and human-editable.

**Areas:** `decisions/` · `hypotheses/` · `stakeholders/` · `knowledge/` (strategy, product,
users, market) · `ingestion/` (synthesized records) · `source/` (verbatim audit anchors) ·
`rules/` · `maintenance/`.

**Provenance is enforced, not suggested.** Every evidence row on a decision or hypothesis must
carry one tag — a markdown link to `../ingestion/…` or `../source/…`, or one of
`(stakeholder-verbal, …)` / `(intuition, PM, …)` / `(industry-knowledge)` / `(chat, no artifact)`.
`pm_log_decision` **rejects** an untagged evidence row, so a decision always wears how much of its
reasoning is collected-and-fresh vs inherited-and-stale on its face. (Upstream pm-brain enforced
this with an editor hook; here it's baked into the tool.)

**Tools:**

| Tool | What |
|---|---|
| `pm_brain_init` | Scaffold the brain (idempotent). |
| `pm_brain_status` | Maintenance sweep: decision debt, active hypotheses, stale stakeholders, recent ingestion. |
| `pm_log_decision` | Log a decision record (provenance-validated evidence; observable reverse-condition). |
| `pm_upsert_hypothesis` | Create/replace a feature's hypotheses (orphan-evidence warnings). |
| `pm_upsert_stakeholder` / `pm_touch_stakeholder` | Map a stakeholder; log a touchpoint (updates last-touched). |
| `pm_ingest` | Write a verbatim source + a synthesized ingestion record; returns a citation tag. |
| `pm_note` | Append to a knowledge area. |
| `pm_list` / `pm_get` / `pm_search` | Read / browse / full-text search (traversal-guarded). |

The brain lives at `brain_dir` (Settings ▸ Plugins) or `PM_BRAIN_DIR`; empty → `~/.protoagent/pm-brain`
(instance-scoped). Point it at a repo path to keep the brain git-versioned.

## Subagents (5)

Delegatable PM specialists (`task` them). The 65 skills are available to all of them; each adds a
focused persona + tool allowlist.

- **`pm_brain`** — the second-brain operator: load context before a task, write back after; ingest,
  prep a 1:1, log decisions, run a maintenance sweep. Retrieves before asking.
- **`pm_discovery`** — discovery & user research: ideation, assumptions, experiments, interviews,
  personas, segmentation, sentiment, competitive/market research, prioritization.
- **`pm_strategy`** — strategy & go-to-market: vision, canvases, SWOT/PESTLE/Porter, pricing,
  positioning, GTM, growth.
- **`pm_execution`** — delivery: PRDs, OKRs, roadmaps, sprints, stories, pre-mortems, stakeholder
  maps, retros.
- **`pm_analytics`** — product data: SQL, cohorts, A/B tests, metric definition.

## The dashboard

A right-rail **PM Brain** view: decision debt (pending decisions), hypotheses by status, stale or
never-touched stakeholders, recent ingestion, and area counts — click any item to read the file.
Themed by the DS plugin-kit, so it follows the console's live theme.

## Configuration

| Setting (Settings ▸ Plugins) | Env override | Default | What |
|---|---|---|---|
| **PM Brain directory** | `PM_BRAIN_DIR` | `~/.protoagent/pm-brain` | Where the brain markdown lives. Set a repo path to git-version it. |
| **Stakeholder staleness (days)** | `PM_STALE_STAKEHOLDER_DAYS` | `21` | A stakeholder not touched within this window is flagged stale. |

## Development

```bash
pip install -r requirements-dev.txt
pytest -q
ruff check . && ruff format --check .
```

The suite is **host-free** (no protoAgent install) — host-only imports stay lazy. CI runs the same
on every PR.

---
Built for [protoAgent](https://github.com/protoLabsAI/protoAgent). Skills & brain model © Paweł
Huryn (MIT); adaptation © protoLabs AI (MIT). See [LICENSE](./LICENSE) and [NOTICE](./NOTICE).
