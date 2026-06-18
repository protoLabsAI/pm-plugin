"""PM Brain — a markdown-native, provenance-enforced knowledge base for product work.

Adapted from Paweł Huryn's pm-brain (MIT, https://github.com/phuryn/pm-brain) and
re-implemented as protoAgent tools over a configurable brain directory. The brain holds
decisions, hypotheses, stakeholders, knowledge areas, and an ingestion/source split.

The key improvement over the upstream scaffold: provenance enforcement is baked into the
write tools (a decision can't be saved with an untagged evidence row) rather than relying
on a separate editor hook, and `brain_status()` powers a live dashboard view.

State lives on disk (instance-scoped), so it survives restarts and is shared between the
tool process and the route process (which, under the ACP runtime, are different processes).
"""

from __future__ import annotations

import os
import re
import time
from datetime import datetime, timezone
from pathlib import Path

from langchain_core.tools import tool

# ── brain root resolution (config > env > default), instance-scoped ──────────────
# A human PM who wants the brain git-versioned can point `brain_dir` at a repo path;
# otherwise it lives under the protoagent data dir, isolated per PROTOAGENT_INSTANCE.


def _plugin_cfg() -> dict:
    try:
        from graph.sdk import config

        return (getattr(config(), "plugin_config", {}) or {}).get("pm", {}) or {}
    except Exception:  # noqa: BLE001 — no host (tests) / not loaded → env+default
        return {}


def _brain_root() -> Path:
    raw = os.environ.get("PM_BRAIN_DIR") or _plugin_cfg().get("brain_dir") or ""
    if raw:
        base = Path(raw).expanduser()
    else:
        base = Path.home() / ".protoagent" / "pm-brain"
        inst = os.environ.get("PROTOAGENT_INSTANCE", "").strip()
        if inst:
            base = base / inst
    return base


def _stale_days() -> int:
    raw = os.environ.get("PM_STALE_STAKEHOLDER_DAYS") or _plugin_cfg().get("stale_stakeholder_days")
    try:
        return max(1, int(raw)) if raw not in (None, "") else 21
    except (TypeError, ValueError):
        return 21


# ── small helpers ────────────────────────────────────────────────────────────────

AREAS = (
    "decisions",
    "hypotheses",
    "stakeholders",
    "knowledge",
    "ingestion",
    "source",
    "rules",
    "maintenance",
)


def _today() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def _slug(text: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", (text or "").lower()).strip("-")
    return s or "untitled"


def _write(path: Path, content: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return path


def _rel(path: Path) -> str:
    try:
        return str(path.relative_to(_brain_root()))
    except ValueError:
        return str(path)


# ── provenance enforcement (the audit spine, from pm-brain) ──────────────────────
# Every Evidence / Explicitly-NOT row on a decision or hypothesis must carry exactly one
# tag from this enum, so a reader can tell collected-and-fresh from inherited-and-stale.

_PROVENANCE_PATTERNS = (
    r"\]\((?:\.\./)*(?:ingestion|source)/[^)]+\)",  # [text](../ingestion|source/...) link
    r"\(stakeholder-verbal,[^)]+\)",
    r"\(intuition, ?PM,[^)]+\)",
    r"\(industry-knowledge\)",
    r"\(chat, ?no artifact\)",
)
_PROVENANCE_RE = re.compile("|".join(_PROVENANCE_PATTERNS))

PROVENANCE_HELP = (
    "Every evidence row needs one provenance tag: a markdown link "
    "`[text](../ingestion/...)` or `[text](../source/...)`, or one of "
    "`(stakeholder-verbal, <name>, <YYYY-MM-DD>)`, `(intuition, PM, <YYYY-MM-DD>)`, "
    "`(industry-knowledge)`, `(chat, no artifact)`. Move untagged commentary to ambiguities."
)


def _has_provenance(row: str) -> bool:
    return bool(_PROVENANCE_RE.search(row))


def _orphans(rows: list[str]) -> list[str]:
    return [r for r in rows if r.strip() and not _has_provenance(r)]


# Hypothesis fields that END an evidence block (so their bullets aren't mistaken for evidence).
_HYP_FIELD_KEYS = (
    "open questions",
    "test:",
    "test ",
    "decision trigger",
    "status",
    "resolution",
    "origin",
    "confidence",
)


def _scan_body_orphans(body: str) -> list[str]:
    """Best-effort: flag bullet rows under an 'Evidence for/against' block that lack a tag.
    Tolerant of the bullet/bold variants the schema uses (`- **Evidence for:**`, `Evidence for:`)."""
    orphans, in_evidence = [], False
    for line in body.splitlines():
        s = line.strip()
        if not s:
            continue
        bare = s.lstrip("-*• ").lower()
        if bare.startswith("evidence for") or bare.startswith("evidence against"):
            in_evidence = True
            continue
        if s.startswith("#") or any(bare.startswith(k) for k in _HYP_FIELD_KEYS):
            in_evidence = False
            continue
        if in_evidence and s.startswith("-") and "_(none" not in bare and not _has_provenance(s):
            orphans.append(s)
    return orphans


# ── status (powers the dashboard + the maintenance sweep) ────────────────────────


def _read(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except (FileNotFoundError, OSError):
        return ""


def _field(text: str, header: str) -> str:
    """Return the first non-empty line under a `## <header>` markdown section."""
    m = re.search(rf"^##\s+{re.escape(header)}\s*$(.*?)(?=^##\s|\Z)", text, re.M | re.S)
    if not m:
        return ""
    for line in m.group(1).splitlines():
        s = line.strip()
        if s and not s.startswith("<!--"):
            return s
    return ""


def brain_status() -> dict:
    """A snapshot of the brain for the dashboard + maintenance: decision debt, active
    hypotheses, stale/under-touched stakeholders, recent ingestion. Pure read."""
    root = _brain_root()
    out: dict = {
        "root": str(root),
        "exists": (root / "INDEX.md").exists(),
        "decisions": {"pending": [], "decided": 0, "superseded": 0},
        "hypotheses": {"by_status": {}, "features": []},
        "stakeholders": {"stale": [], "total": 0},
        "ingestion_recent": [],
        "counts": {},
    }
    if not root.exists():
        return out

    for area in AREAS:
        out["counts"][area] = (
            sum(1 for _ in (root / area).rglob("*.md")) if (root / area).exists() else 0
        )

    # decisions — surface pending (decision debt)
    for f in sorted((root / "decisions").glob("*.md")) if (root / "decisions").exists() else []:
        if f.name.startswith("_"):
            continue
        txt = _read(f)
        status = (_field(txt, "Status") or "pending").lower()
        title = txt.splitlines()[0].lstrip("# ").strip() if txt else f.stem
        if status.startswith("pending") or status.startswith("proposed"):
            out["decisions"]["pending"].append({"file": _rel(f), "title": title})
        elif status.startswith("superseded"):
            out["decisions"]["superseded"] += 1
        else:
            out["decisions"]["decided"] += 1

    # hypotheses — per file status
    for f in sorted((root / "hypotheses").rglob("*.md")) if (root / "hypotheses").exists() else []:
        if f.name.startswith("_"):
            continue
        txt = _read(f)
        m = re.search(r"^-?\s*\*?\*?Status:?\*?\*?\s*[:\-]?\s*`?(\w[\w-]*)", txt, re.M)
        status = m.group(1).lower() if m else "active"
        out["hypotheses"]["by_status"][status] = out["hypotheses"]["by_status"].get(status, 0) + 1
        out["hypotheses"]["features"].append({"file": _rel(f), "status": status})

    # stakeholders — stale = last-touched older than threshold, or never
    if (root / "stakeholders").exists():
        cutoff = time.time() - _stale_days() * 86400
        for f in sorted((root / "stakeholders").glob("*.md")):
            if f.name.startswith("_"):
                continue
            out["stakeholders"]["total"] += 1
            txt = _read(f)
            last = _field(txt, "Last touched")
            name = txt.splitlines()[0].lstrip("# ").strip() if txt else f.stem
            stale = True
            if last and re.match(r"\d{4}-\d{2}-\d{2}", last):
                try:
                    ts = (
                        datetime.strptime(last[:10], "%Y-%m-%d")
                        .replace(tzinfo=timezone.utc)
                        .timestamp()
                    )
                    stale = ts < cutoff
                except ValueError:
                    stale = True
            if stale:
                out["stakeholders"]["stale"].append(
                    {"file": _rel(f), "name": name, "last": last or "never"}
                )

    # recent ingestion
    ing = (
        sorted((root / "ingestion").rglob("*.md"), key=lambda p: p.stat().st_mtime, reverse=True)
        if (root / "ingestion").exists()
        else []
    )
    out["ingestion_recent"] = [
        {"file": _rel(f), "title": (_read(f).splitlines() or [f.stem])[0].lstrip("# ").strip()}
        for f in ing[:5]
    ]
    return out


# ── file browser + edit (powers the dashboard's read/edit-all-docs surface) ──────
# A human PM needs to see and edit every file the brain produced — not just the curated
# slices the status sweep surfaces. These back the view's /files, /file, PUT /file routes.


def _safe_target(path: str) -> Path | None:
    """Resolve a brain-relative path, refusing anything that escapes the brain root."""
    root = _brain_root()
    target = (root / (path or "").strip().lstrip("/")).resolve()
    try:
        target.relative_to(root.resolve())
    except ValueError:
        return None
    return target


def _title_of(path: Path) -> str:
    # Read only up to the first non-empty line — don't slurp the whole file just for a title.
    try:
        with path.open(encoding="utf-8") as fh:
            for line in fh:
                if line.strip():
                    return line.lstrip("# ").strip()
    except OSError:
        pass
    return path.stem


def _decision_orphans(text: str) -> list[str]:
    """Bullet rows under a decision's `## Evidence` / `## Explicitly NOT doing` that lack a
    provenance tag — the same audit rule pm_log_decision enforces, applied to a hand edit."""
    orphans, in_evidence = [], False
    for line in text.splitlines():
        s = line.strip()
        if s.startswith("## "):
            head = s[3:].strip().lower()
            in_evidence = head.startswith("evidence") or head.startswith("explicitly not")
            continue
        if in_evidence and s.startswith("-") and s.lstrip("-* ") and not _has_provenance(s):
            orphans.append(s)
    return orphans


def file_warnings(rel_path: str, content: str) -> list[str]:
    """Provenance warnings for an edited file (decisions/hypotheses only). Warn, don't block —
    the human PM has final say; the audit signal stays visible."""
    area = next(iter(Path(rel_path).parts), "")
    if area == "decisions":
        return [f"Untagged evidence row: {o}" for o in _decision_orphans(content)]
    if area == "hypotheses":
        return [f"Untagged evidence row: {o}" for o in _scan_body_orphans(content)]
    return []


def write_brain_file(
    rel_path: str,
    content: str,
    expected_mtime: float | None = None,
    must_be_new: bool = False,
) -> dict:
    """Write a brain file from the UI editor. Guards: must stay inside the brain, `.md` only,
    `source/` is read-only (verbatim audit anchors), and the area must be a real brain area.
    When `must_be_new` is set, an existing file at the path is refused (a fresh "New file"
    must not clobber an existing one). When `expected_mtime` is given and the file on disk has
    changed since (optimistic concurrency), the write is refused as a conflict rather than
    clobbering a concurrent edit. Decisions/hypotheses get provenance *warnings* but still save.
    Creates parent dirs, so a brand-new file just works. Returns
    {ok, path, warnings, mtime} or {ok: False, error[, conflict]}."""
    rel = (rel_path or "").strip().lstrip("/")
    if not rel:
        return {"ok": False, "error": "A file path is required."}
    target = _safe_target(rel)
    if target is None:
        return {"ok": False, "error": "Path must be inside the PM Brain."}
    if target.suffix != ".md":
        return {"ok": False, "error": "Only .md files can be edited."}
    parts = Path(rel).parts
    area = parts[0] if len(parts) > 1 else ""  # "" → a root-level doc (INDEX.md, etc.)
    if area == "source":
        return {"ok": False, "error": "source/ holds verbatim audit anchors and is read-only."}
    if area and area not in AREAS:
        return {"ok": False, "error": f"'{area}/' is not a PM Brain area."}
    if must_be_new and target.exists():
        return {
            "ok": False,
            "conflict": True,
            "error": "A file already exists at that path — pick a different name.",
        }
    if expected_mtime is not None and target.exists():
        if abs(target.stat().st_mtime - expected_mtime) > 1e-6:
            return {
                "ok": False,
                "conflict": True,
                "error": "This file changed on disk since you opened it.",
            }
    _write(target, content)
    return {
        "ok": True,
        "path": _rel(target),
        "warnings": file_warnings(rel, content),
        "mtime": target.stat().st_mtime,
    }


def brain_files() -> dict:
    """Every markdown file in the brain, grouped by area (root-level docs first), each with its
    title and last-modified time, and whether the group is editable. Pure read — the dashboard's
    browse-everything surface, beyond the curated slices in brain_status()."""
    root = _brain_root()
    out: dict = {"root": str(root), "exists": (root / "INDEX.md").exists(), "groups": []}
    if not root.exists():
        return out
    grouped: list[tuple[str, list[Path]]] = []
    top = sorted(root.glob("*.md"))
    if top:
        grouped.append(("(root)", top))
    for area in AREAS:
        d = root / area
        if d.exists():
            files = sorted(d.rglob("*.md"))
            if files:
                grouped.append((area, files))
    for area, files in grouped:
        out["groups"].append(
            {
                "area": area,
                "editable": area != "source",
                "files": [
                    {"path": _rel(f), "title": _title_of(f), "mtime": f.stat().st_mtime}
                    for f in files
                ],
            }
        )
    return out


# ── scaffold templates (the deterministic structure, condensed from pm-brain) ─────

_INDEX = """# PM Brain — Master Index

Start here. Every task begins by routing through this file.

| Area | Path | Load when |
| --- | --- | --- |
| Strategy | [knowledge/strategy.md](./knowledge/strategy.md) | Planning, prioritization, drift checks |
| Product | [knowledge/product/](./knowledge/product/) | Feature work, metrics, roadmap |
| Users | [knowledge/users/](./knowledge/users/) | Discovery, interviews, segmentation |
| Market | [knowledge/market/](./knowledge/market/) | Competitive analysis, positioning |
| Stakeholders | [stakeholders/](./stakeholders/) | Prep for any 1:1 or cross-functional touchpoint |
| Hypotheses | [hypotheses/](./hypotheses/) | Pre-ship feature work, experiments, post-launch eval |
| Decisions | [decisions/](./decisions/) | Anything that commits future effort or reverses a choice |
| Rules | [rules/](./rules/) | How this PM runs discovery, prioritization, shipping, writing |
| Ingestion | [ingestion/](./ingestion/) | Synthesized records from interviews/meetings/market intel |
| Source | [source/](./source/) | Verbatim audit anchors — never edited |
| Maintenance | [maintenance/](./maintenance/) | Periodic system reviews |

Operating manual: [operating-manual.md](./operating-manual.md).
"""

_MANUAL = """# Operating manual — PM Brain

You are the PM's second brain. Load context before tasks, update knowledge after tasks,
and keep hypotheses, decisions, stakeholders, and strategy aligned proactively.

## Hard rules
- **Pre-task load, post-task update.** Before a task, load the relevant area files (start at
  INDEX). After it, write back what changed. No exceptions.
- **Retrieve before asking.** Search the brain, inspect linked files and recent ingestion,
  infer from prior decisions. Ask the PM only when the answer materially affects direction
  and isn't recoverable from the brain.
- **Provenance or it didn't happen.** Every evidence row on a decision or hypothesis carries
  one provenance tag. The write tools enforce this — don't fight it, tag honestly.
- **Signal density over completeness.** A short high-signal synthesis beats exhaustive capture.

## Task shapes (getting this wrong is the #1 quality failure)
- **Ingestion / routing** — PM hands you a raw artifact. Preserve the source, synthesize an
  ingestion record, route observations to hypotheses/stakeholders. Output: a short routing
  summary (what was created/updated, what's open). The value is in the files.
- **Synthesis / analysis** — "walk through", "what's the strongest evidence", "lay out the
  case". Output: the substantive analysis itself, citing prior artifacts by slug, naming
  contradictions explicitly, naming what's still missing. Do NOT collapse this into a routing
  summary.
- **Decision** — draft a decision record (use the decisions schema). Every evidence row tagged.
  Output: the file path + a one-line summary + what's still open for PM sign-off.

When an ask blends shapes ("synthesize then decide"), do them in order — synthesis first.
"""

_DECISION_SCHEMA = """# Decision Record Schema

Filename: `YYYY-MM-DD-<slug>.md`. Decisions are append-only — to reverse, write a new decision
that supersedes the old (set the old one's Status to `superseded`).

Every row under `## Evidence` and `## Explicitly NOT doing` MUST carry one provenance tag:
- `[text](../ingestion/<path>)` — went through synthesis (highest trust)
- `[text](../source/<path>)` — direct citation to a raw artifact
- `(stakeholder-verbal, <name>, <YYYY-MM-DD>)`
- `(intuition, PM, <YYYY-MM-DD>)`
- `(industry-knowledge)` — flag for replacement by product-specific evidence
- `(chat, no artifact)`

A tagless evidence row is an orphan and is rejected. Commentary / "things we don't yet know"
go under `## Remaining ambiguities`, never under Evidence.

```
# Decision: <one-line statement>
## Status            pending | decided | superseded
## Date              YYYY-MM-DD
## Context           2-4 sentences. The fork in the road.
## Options considered
## Decision          What we picked (empty for pending).
## Why               The actual reasoning.
## Evidence          <claim>  <provenance-tag>   (every row tagged)
## Explicitly NOT doing   <not-doing>  <provenance-tag>
## What would reverse this   A specific, observable condition (metric / signal / date).
## Remaining ambiguities
## Linked            hypotheses / strategy / stakeholders
```
"""

_HYPOTHESIS_SCHEMA = """# Hypothesis File Schema

Feature-scoped: one file per feature, `<feature-slug>.md`. Organize by the risk areas
(Value, Usability, Feasibility, Viability, Other). Each hypothesis:

```
### H-V1: <one-sentence belief>
- Origin: proactive | data-derived (from <source>)
- Confidence: low | medium | high
- Evidence for:
  - <claim>  <provenance-tag>
- Evidence against:
  - <claim>  <provenance-tag>
- Open questions / caveats:   (commentary lives here, not under Evidence — no tag needed)
- Test: <experiment / interview / analysis>
- Decision trigger: <what promotes? what demotes?>
- Status: active | promoted | demoted | killed
```

Provenance tags are the same enum as decisions. File-level Status is one of
`active | partially-validated | promoted | demoted | archived`. When a hypothesis is
promoted, spawn a decision in `decisions/` that references it.
"""

_STAKEHOLDER_SCHEMA = """# Stakeholder File Schema

Filename: `<slug>.md` (lowercase, hyphenated). One file per stakeholder.

```
# <Name> — <Role>
## Snapshot
- Role:
- Influence on my work: low | medium | high
- Friction level: low | medium | high
## What they care about
## Concerns / watch-outs
## Communication style
## Open asks
## Touchpoint log
- YYYY-MM-DD — <one-line summary, link to ../ingestion/meetings/<file> if applicable>
## Last touched
YYYY-MM-DD   (auto-maintained; leave blank if no touchpoint yet — never write TODO here)
```
"""

_RULES = {
    "discovery.md": "# Rules — Discovery\n\nHow this PM runs discovery: interview cadence, who to talk to, what counts as enough evidence to act. (Fill in.)\n",
    "prioritization.md": "# Rules — Prioritization\n\nNever let customers design solutions. Prioritize problems (opportunities), not features. Default framework + thresholds. (Fill in.)\n",
    "shipping.md": "# Rules — Shipping\n\nDefinition of done, release gates, what must have a decision record before it ships. (Fill in.)\n",
    "writing.md": "# Rules — Writing\n\nVoice, length, where docs live, what a PRD must contain. (Fill in.)\n",
    "data.md": "# Rules — Data\n\nSource-of-truth metrics, what we trust, how we segment, what a 'real' signal looks like. (Fill in.)\n",
}

_KNOWLEDGE = {
    "strategy.md": "# Strategy\n\n## North-star metric\n\n## Priorities (Now)\n\n## Non-goals\n\n## Bets / theses\n",
    "product/roadmap.md": "# Roadmap\n\n## Now\n\n## Next\n\n## Later\n",
    "product/metrics.md": "# Product metrics\n\n| Metric | Definition | Source | Current |\n|---|---|---|---|\n",
    "users/personas.md": "# Personas\n\n",
    "users/segments.md": "# Segments\n\n",
    "market/landscape.md": "# Market landscape\n\n## Competitors\n\n## Positioning\n",
}


@tool
def pm_brain_init() -> str:
    """Initialize (scaffold) the PM Brain — a markdown-native knowledge base for product
    work: decisions, hypotheses, stakeholders, knowledge areas, and an ingestion/source
    audit split, plus an operating manual and schemas. Idempotent (won't overwrite files
    that already exist). Run this once before logging decisions/hypotheses/stakeholders.
    Returns the brain location and what was created."""
    root = _brain_root()
    created = []

    def put(rel: str, content: str) -> None:
        p = root / rel
        if not p.exists():
            _write(p, content)
            created.append(rel)

    put("INDEX.md", _INDEX)
    put("operating-manual.md", _MANUAL)
    put("decisions/_SCHEMA.md", _DECISION_SCHEMA)
    put("hypotheses/_SCHEMA.md", _HYPOTHESIS_SCHEMA)
    put("stakeholders/_SCHEMA.md", _STAKEHOLDER_SCHEMA)
    for name, body in _RULES.items():
        put(f"rules/{name}", body)
    for name, body in _KNOWLEDGE.items():
        put(f"knowledge/{name}", body)
    for area in ("ingestion", "source", "maintenance"):
        (root / area).mkdir(parents=True, exist_ok=True)
    return (
        f"PM Brain ready at {root} "
        f"({'created ' + str(len(created)) + ' files' if created else 'already initialized'}). "
        f"Areas: {', '.join(AREAS)}. Start tasks at INDEX.md; log decisions with pm_log_decision."
    )


@tool
def pm_brain_status() -> str:
    """Maintenance sweep / dashboard: surface decision debt (pending decisions), active
    hypotheses, stale or never-touched stakeholders, and recent ingestion. Read-only.
    Use at the start of a working session or for a weekly review."""
    s = brain_status()
    if not s["exists"]:
        return f"No PM Brain at {s['root']} yet — run pm_brain_init first."
    pend = s["decisions"]["pending"]
    stale = s["stakeholders"]["stale"]
    lines = [
        f"PM Brain @ {s['root']}",
        f"Decisions: {len(pend)} pending (debt), {s['decisions']['decided']} decided, {s['decisions']['superseded']} superseded.",
    ]
    for d in pend[:10]:
        lines.append(f"  · PENDING — {d['title']}  ({d['file']})")
    by = s["hypotheses"]["by_status"]
    lines.append(
        f"Hypotheses: {sum(by.values())} across {len(s['hypotheses']['features'])} files — "
        + (", ".join(f"{k}:{v}" for k, v in by.items()) or "none")
    )
    lines.append(
        f"Stakeholders: {s['stakeholders']['total']} total, {len(stale)} stale (> {_stale_days()}d / never touched)."
    )
    for st in stale[:10]:
        lines.append(f"  · STALE — {st['name']} (last: {st['last']})")
    if s["ingestion_recent"]:
        lines.append("Recent ingestion: " + "; ".join(i["title"] for i in s["ingestion_recent"]))
    return "\n".join(lines)


@tool
def pm_log_decision(
    title: str,
    context: str,
    evidence: list[str],
    status: str = "decided",
    options: list[str] | None = None,
    decision: str = "",
    why: str = "",
    not_doing: list[str] | None = None,
    reverse_when: str = "",
    ambiguities: str = "",
) -> str:
    """Log a decision record to the PM Brain (the audit anchor for anything that commits
    future effort). ``evidence`` is a list of claim rows — EACH must carry one provenance
    tag (a markdown link to ../ingestion/.. or ../source/.., or one of
    (stakeholder-verbal, <name>, <date>) / (intuition, PM, <date>) / (industry-knowledge) /
    (chat, no artifact)); untagged rows are rejected. ``status`` is decided|pending|superseded;
    ``reverse_when`` is the observable condition that would revisit this. Returns the file path."""
    orphans = _orphans(list(evidence or []) + list(not_doing or []))
    if orphans:
        return (
            "Rejected — these evidence rows lack a provenance tag:\n"
            + "\n".join(f"  · {o}" for o in orphans)
            + "\n"
            + PROVENANCE_HELP
        )
    st = (status or "decided").strip().lower()
    if st not in ("decided", "pending", "proposed", "superseded"):
        return "status must be one of: decided | pending | superseded."
    date = _today()
    body = [
        f"# Decision: {title.strip()}",
        "",
        f"## Status\n{st}",
        f"## Date\n{date}",
        f"## Context\n{context.strip()}",
    ]
    if options:
        body.append(
            "## Options considered\n" + "\n".join(f"{i + 1}. {o}" for i, o in enumerate(options))
        )
    if decision:
        body.append(f"## Decision\n{decision.strip()}")
    if why:
        body.append(f"## Why\n{why.strip()}")
    body.append("## Evidence\n" + "\n".join(f"- {e}" for e in evidence))
    if not_doing:
        body.append("## Explicitly NOT doing\n" + "\n".join(f"- {n}" for n in not_doing))
    if reverse_when:
        body.append(f"## What would reverse this\n{reverse_when.strip()}")
    if ambiguities:
        body.append(f"## Remaining ambiguities\n{ambiguities.strip()}")
    path = _write(
        _brain_root() / "decisions" / f"{date}-{_slug(title)}.md", "\n\n".join(body) + "\n"
    )
    return f"Logged decision → {_rel(path)} (status: {st})."


@tool
def pm_upsert_hypothesis(feature: str, body: str, status: str = "active") -> str:
    """Create or replace the hypothesis file for a feature (one file per feature, organized
    by risk area — Value/Usability/Feasibility/Viability/Other). ``body`` is the markdown of
    the hypotheses following the hypotheses schema; evidence rows should carry provenance tags
    (orphan rows are flagged as a warning, not rejected — hypotheses are exploratory). Returns
    the file path and any untagged-evidence warnings."""
    slug = _slug(feature)
    header = f"# Hypotheses — {feature.strip()}\n\n## Meta\n- Status: {status.strip().lower()}\n- Updated: {_today()}\n"
    path = _write(_brain_root() / "hypotheses" / f"{slug}.md", header + "\n" + body.strip() + "\n")
    warn = _scan_body_orphans(body)
    msg = f"Saved hypotheses → {_rel(path)}."
    if warn:
        msg += (
            f"\n⚠ {len(warn)} evidence row(s) missing a provenance tag (kept, but tag them):\n"
            + "\n".join(f"  · {w}" for w in warn[:6])
        )
    return msg


@tool
def pm_upsert_stakeholder(
    name: str,
    role: str = "",
    influence: str = "",
    friction: str = "",
    cares_about: str = "",
    concerns: str = "",
    comm_style: str = "",
) -> str:
    """Create or update a stakeholder file (role, influence/friction level, what they care
    about, concerns, communication style). Use pm_touch_stakeholder to log a touchpoint.
    Returns the file path."""
    slug = _slug(name)
    path = _brain_root() / "stakeholders" / f"{slug}.md"
    existing = _read(path)
    touchlog = ""
    if existing:
        m = re.search(r"^## Touchpoint log\s*$(.*?)(?=^## |\Z)", existing, re.M | re.S)
        touchlog = m.group(1).strip() if m else ""
        last = _field(existing, "Last touched")
    else:
        last = ""
    body = (
        f"# {name.strip()} — {role.strip() or 'Stakeholder'}\n\n"
        f"## Snapshot\n- Role: {role.strip()}\n- Influence on my work: {influence.strip() or 'medium'}\n- Friction level: {friction.strip() or 'low'}\n\n"
        f"## What they care about\n{cares_about.strip() or 'TODO — what they are measured on, what makes them look good'}\n\n"
        f"## Concerns / watch-outs\n{concerns.strip() or 'TODO'}\n\n"
        f"## Communication style\n{comm_style.strip() or 'TODO — async/sync, terse/detailed, data-first/narrative'}\n\n"
        f"## Open asks\n\n"
        f"## Touchpoint log\n{touchlog}\n\n"
        f"## Last touched\n{last}\n"
    )
    _write(path, body)
    return f"Saved stakeholder → {_rel(path)}."


@tool
def pm_touch_stakeholder(name: str, summary: str) -> str:
    """Record a touchpoint with a stakeholder (a 1:1, a thread, a decision you informed them
    of). Appends to their Touchpoint log and updates Last touched to today. Returns the path."""
    slug = _slug(name)
    path = _brain_root() / "stakeholders" / f"{slug}.md"
    if not path.exists():
        return f"No stakeholder {name!r} yet — create one with pm_upsert_stakeholder first."
    txt = _read(path)
    date = _today()
    txt = re.sub(
        r"(^## Touchpoint log\s*$)",
        rf"\1\n- {date} — {summary.strip()}",
        txt,
        count=1,
        flags=re.M,
    )
    txt = re.sub(r"(^## Last touched\s*$\n).*", rf"\g<1>{date}", txt, count=1, flags=re.M)
    _write(path, txt)
    return f"Logged touchpoint with {name} ({date}) → {_rel(path)}."


@tool
def pm_ingest(kind: str, title: str, synthesis: str, source_text: str = "") -> str:
    """Ingest a raw artifact (interview / meeting / market intel / ad-hoc). Writes a verbatim
    SOURCE record (never edited — the audit anchor) and a synthesized INGESTION record that
    decisions/hypotheses can cite. ``kind`` is interviews|meetings|market|adhoc. Returns both
    paths so you can reference them as provenance tags."""
    k = (kind or "adhoc").strip().lower()
    if k not in ("interviews", "meetings", "market", "adhoc"):
        k = "adhoc"
    date = _today()
    stem = f"{date}-{_slug(title)}"
    root = _brain_root()
    src_path = None
    if source_text.strip():
        src_path = _write(
            root / "source" / k / f"{stem}.md",
            f"# Source: {title} ({date})\n\n<!-- verbatim, never edited -->\n\n{source_text.strip()}\n",
        )
    link = (
        f"  [source/{k}/{stem}.md](../source/{k}/{stem}.md)"
        if src_path
        else "  (chat, no artifact)"
    )
    ing_path = _write(
        root / "ingestion" / k / f"{stem}.md",
        f"# {title} ({date})\n\n## Synthesis\n{synthesis.strip()}\n\n## Source\n-{link}\n",
    )
    out = f"Ingested → {_rel(ing_path)}"
    if src_path:
        out += f" (source: {_rel(src_path)})"
    out += f". Cite as: [ingestion/{k}/{stem}.md](../ingestion/{k}/{stem}.md)"
    return out


@tool
def pm_note(area: str, content: str, title: str = "") -> str:
    """Append a note to a knowledge area file (strategy, product/roadmap, product/metrics,
    users/personas, users/segments, market/landscape, …) or any path under knowledge/. Use
    for keeping the brain's knowledge current after a task. Returns the file path."""
    rel = area.strip().strip("/")
    if not rel.endswith(".md"):
        rel += ".md"
    path = _brain_root() / "knowledge" / rel
    stamp = f"\n\n## {title.strip()} ({_today()})\n" if title else f"\n\n<!-- {_today()} -->\n"
    existing = _read(path)
    _write(
        path,
        (existing + stamp + content.strip() + "\n")
        if existing
        else (f"# {rel[:-3]}\n" + stamp + content.strip() + "\n"),
    )
    return f"Noted → knowledge/{rel}."


@tool
def pm_list(area: str = "") -> str:
    """List files in the PM Brain (optionally just one area: decisions, hypotheses,
    stakeholders, knowledge, ingestion, source, rules). Read-only."""
    root = _brain_root()
    base = root / area.strip() if area.strip() else root
    if not base.exists():
        return (
            f"No such area {area!r}. Areas: {', '.join(AREAS)}."
            if area.strip()
            else f"No PM Brain at {root} — run pm_brain_init."
        )
    files = sorted(p for p in base.rglob("*.md") if not p.name.startswith("_"))
    if not files:
        return f"(empty) {_rel(base)}"
    return "\n".join(_rel(f) for f in files)


@tool
def pm_get(path: str) -> str:
    """Read a file from the PM Brain by its brain-relative path (as shown by pm_list, e.g.
    `decisions/2026-06-15-weekly-batch.md`). Read-only."""
    root = _brain_root()
    target = (root / path.strip()).resolve()
    try:
        target.relative_to(root.resolve())  # no traversal outside the brain
    except ValueError:
        return "Path must be inside the PM Brain."
    if not target.exists():
        return f"No file at {path!r}. Use pm_list to see what's there."
    return _read(target)


@tool
def pm_search(query: str) -> str:
    """Full-text search the PM Brain for a string (case-insensitive); returns matching files
    with the first matching line each. Use to retrieve before asking the PM. Read-only."""
    root = _brain_root()
    if not root.exists():
        return f"No PM Brain at {root} — run pm_brain_init."
    q = query.strip().lower()
    if not q:
        return "Provide a search query."
    hits = []
    for f in sorted(root.rglob("*.md")):
        for line in _read(f).splitlines():
            if q in line.lower():
                hits.append(f"{_rel(f)}: {line.strip()[:120]}")
                break
    return "\n".join(hits[:40]) if hits else f"No matches for {query!r}."


BRAIN_TOOLS = [
    pm_brain_init,
    pm_brain_status,
    pm_log_decision,
    pm_upsert_hypothesis,
    pm_upsert_stakeholder,
    pm_touch_stakeholder,
    pm_ingest,
    pm_note,
    pm_list,
    pm_get,
    pm_search,
]
