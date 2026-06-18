# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

A **protoAgent plugin** (id: `pm`) — not a standalone app. It contributes four things to a
protoAgent host: 65 PM skills, the PM Brain (a markdown knowledge base + tools), five specialist
subagents, and a dashboard view. At runtime `fastapi` + `langchain-core` and the `graph.*` host
modules are provided by protoAgent; this repo only carries plugin code + a host-free test harness.

Adapted from Paweł Huryn's pm-skills + pm-brain (MIT) — see `NOTICE`. Read `README.md` for the
full feature surface.

## Commands

```bash
pip install -r requirements-dev.txt   # test/lint deps (host deps are not installed here)
pytest -q                             # full suite (host-free)
pytest -q tests/test_pm.py::<name>    # a single test
ruff check . && ruff format --check . # lint + format check (line-length 100, py311, isort via "I")
ruff format .                         # apply formatting
```

CI (`.github/workflows`) runs exactly `ruff check . && ruff format --check .` then `pytest -q`.

## Architecture

**`__init__.py` `register(registry)` is the only entry point where plugin code runs.** It wires up
the four contributions, each in its own try/except so one failing group can't sink the rest:

- `brain.BRAIN_TOOLS` → `register_tool` (the `pm_*` tools)
- `register_skill_dir("skills")` → the 65 `skills/*/SKILL.md` dirs, auto-discovered by description
- `subagents.register_subagents(registry)` → the five specialist subagents
- two routers from `view.py` → `/plugins/pm` (page) and `/api/plugins/pm` (data)

**Host-only imports stay lazy — this is the central constraint.** Anything importing `graph.*`
(the protoAgent host SDK) must be done *inside a function*, never at module top level. That's why
`brain.py`, `subagents.py`, and `view.py` import with only the dev deps, which is what lets the
test suite run with no protoAgent install. `tests/conftest.py` loads the package under a synthetic
`pm` module name so the relative imports (`from . import brain`) resolve host-free. **If you add a
top-level `graph.*` import, the suite breaks.**

### `brain.py` — the PM Brain

A markdown-native, provenance-enforced knowledge base. State lives **on disk**, not in memory —
the tool process and the route process are different processes under the ACP runtime, so disk is
the only shared channel.

- **Brain root resolution** (`_brain_root`): `PM_BRAIN_DIR` env > plugin config `brain_dir` >
  `~/.protoagent/pm-brain/<PROTOAGENT_INSTANCE>` (instance-scoped). The env-over-config-over-default
  pattern repeats in `_stale_days` (`PM_STALE_STAKEHOLDER_DAYS`, default 21).
- **Provenance enforcement is the core invariant** (`_PROVENANCE_RE`, `_has_provenance`,
  `_orphans`): every evidence row on a decision/hypothesis must carry exactly one provenance tag
  (an `../ingestion/` or `../source/` markdown link, or one of the literal `(stakeholder-verbal…)`
  / `(intuition, PM…)` / `(industry-knowledge)` / `(chat, no artifact)` forms). The write *tools*
  (`pm_log_decision`) **reject** untagged rows; the editor view (`write_brain_file`) only **warns**
  (the human PM has final say). When touching this logic, keep the tool-rejects / view-warns split.
- The eight brain `AREAS` are fixed. `source/` files are verbatim audit anchors and are
  treated read-only by the view.
- `@tool`-decorated functions are the agent-facing API; `BRAIN_TOOLS` (bottom of file) is the
  registration list — **add new tools there**. Lowercase helpers (`_safe_target`, `brain_status`,
  `brain_files`, `write_brain_file`) back the view's data routes.
- Path safety: every path that crosses a trust boundary goes through `_safe_target`, which
  traversal-guards to the brain root. Use it for any new path-taking entry point.

### `view.py` — the dashboard

Two routers reflecting protoAgent plugin-view rules: the **page** (`/plugins/pm/view`) is public
(an iframe page-load carries no bearer and derives its base from the path), the **data** routes
(`/api/plugins/pm/{status,files,file}`) are gated. The UI is a single self-contained HTML/JS shell
themed via the DS plugin-kit CSS (`/_ds/`, host ≥ 0.34.0) so it follows the console's live theme.

### `subagents.py` — specialists

Five `SubagentConfig`s (built lazily inside `_configs`, since `SubagentConfig` is a `graph.*`
import). All 65 skills are available to every agent; a subagent adds only a persona system prompt +
a tool allowlist. The persona prompts encode task-shape rules (ingestion vs synthesis vs decision)
that matter to behavior — preserve them when editing.

## Conventions

- Python ≥ 3.11, ruff line-length 100, double quotes / standard ruff formatting, imports sorted by
  ruff's isort rule. `from __future__ import annotations` at the top of every module.
- `# noqa: BLE001` on the deliberate broad `except Exception` guards in `register()` and config
  resolution — these are intentional (a missing host must degrade gracefully, not raise).
- This plugin ships **disabled** (`enabled: false` in `protoagent.plugin.yaml`); enabling is the
  operator's trust decision. Config defaults in the yaml are the source of truth (editable in
  Settings ▸ Plugins).
