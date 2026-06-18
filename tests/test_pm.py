"""Tests for the Product Manager plugin — the skill library, the PM Brain tools (incl.
provenance enforcement), the subagents, register() wiring, and the dashboard view routes.
Host-free: needs only requirements-dev.txt."""

from __future__ import annotations

import sys
import types
from pathlib import Path

import pytest
from pm import brain  # via the synthetic package (conftest)

ROOT = Path(__file__).resolve().parent.parent


# ── the skill library ────────────────────────────────────────────────────────────


def _skill_files():
    return sorted((ROOT / "skills").glob("*/SKILL.md"))


def _frontmatter(text: str) -> dict:
    if not text.startswith("---"):
        return {}
    end = text.find("\n---", 3)
    fm = {}
    for line in text[3:end].splitlines():
        if ":" in line:
            k, _, v = line.partition(":")
            fm[k.strip()] = v.strip().strip('"')
    return fm


def test_skill_library_is_substantial_and_well_formed():
    files = _skill_files()
    assert len(files) >= 60, f"expected the full PM library, found {len(files)}"
    names = []
    for f in files:
        fm = _frontmatter(f.read_text(encoding="utf-8"))
        assert fm.get("name"), f"{f} missing name"
        assert fm.get("description"), f"{f} missing description"
        # dir name should match the frontmatter name (clean discovery)
        assert fm["name"] == f.parent.name, f"{f}: name {fm['name']!r} != dir {f.parent.name!r}"
        names.append(fm["name"])
    assert len(names) == len(set(names)), "duplicate skill names"


def test_no_claude_code_argument_token_leaked():
    for f in _skill_files():
        assert "$ARGUMENTS" not in f.read_text(encoding="utf-8"), f"{f} still has $ARGUMENTS"


def test_redundant_variants_were_consolidated():
    names = {f.parent.name for f in _skill_files()}
    # the existing/new pairs are merged into single mode-aware skills
    for merged in ("brainstorm-ideas", "identify-assumptions", "design-experiments"):
        assert merged in names
    for gone in (
        "brainstorm-ideas-new",
        "identify-assumptions-existing",
        "brainstorm-experiments-new",
    ):
        assert gone not in names


# ── manifest / version coherence ───────────────────────────────────────────────


def test_manifest_and_pyproject_versions_match():
    import tomllib

    import yaml

    m = yaml.safe_load((ROOT / "protoagent.plugin.yaml").read_text())
    pp = tomllib.loads((ROOT / "pyproject.toml").read_text())
    assert m["version"] == pp["project"]["version"]
    assert m["id"] == "pm" and m["config_section"] == "pm"
    assert m["enabled"] is False  # ships disabled — enabling is the operator's call
    assert m["views"][0]["path"] == "/plugins/pm/view"  # public, not /api


# ── provenance enforcement (the audit spine) ────────────────────────────────────


@pytest.mark.parametrize(
    "row",
    [
        "claim  [x](../ingestion/interviews/2026-06-15-acme.md)",
        "claim  [x](../source/meetings/2026-06-15-sync.md)",
        "claim  (stakeholder-verbal, Naomi, 2026-06-15)",
        "claim  (intuition, PM, 2026-06-15)",
        "claim  (industry-knowledge)",
        "claim  (chat, no artifact)",
    ],
)
def test_provenance_accepts_every_tag_form(row):
    assert brain._has_provenance(row)


def test_provenance_rejects_untagged_and_prose_citation():
    assert not brain._has_provenance("Acme said batches are unusable")
    assert not brain._has_provenance(
        "Acme reported X (Acme interview, 2026-04-22)"
    )  # prose, not a link


# ── the brain tools ─────────────────────────────────────────────────────────────


def test_brain_init_scaffolds_and_is_idempotent():
    out = brain.pm_brain_init.invoke({})
    assert "ready" in out.lower()
    root = brain._brain_root()
    for f in (
        "INDEX.md",
        "operating-manual.md",
        "decisions/_SCHEMA.md",
        "hypotheses/_SCHEMA.md",
        "stakeholders/_SCHEMA.md",
        "knowledge/strategy.md",
        "rules/prioritization.md",
    ):
        assert (root / f).exists(), f"missing {f}"
    again = brain.pm_brain_init.invoke({})
    assert "already initialized" in again


def test_log_decision_rejects_orphan_evidence():
    brain.pm_brain_init.invoke({})
    out = brain.pm_log_decision.invoke(
        {
            "title": "Default to weekly batches",
            "context": "Customers split on cadence.",
            "evidence": ["Acme ops lead said weekly is unusable"],  # NO provenance tag
        }
    )
    assert "Rejected" in out and "provenance" in out.lower()
    assert not list((brain._brain_root() / "decisions").glob("2*.md"))  # nothing written


def test_log_decision_writes_tagged_decision_and_shows_as_debt():
    brain.pm_brain_init.invoke({})
    out = brain.pm_log_decision.invoke(
        {
            "title": "Adopt weekly digest default",
            "context": "Cadence fork.",
            "status": "pending",
            "evidence": [
                "Three accounts asked for it  [x](../ingestion/interviews/2026-06-15-x.md)"
            ],
            "reverse_when": "If weekly opt-out exceeds 30% in 60 days.",
        }
    )
    assert "Logged decision" in out
    files = [
        f for f in (brain._brain_root() / "decisions").glob("*.md") if not f.name.startswith("_")
    ]
    assert len(files) == 1
    s = brain.brain_status()
    assert len(s["decisions"]["pending"]) == 1
    assert s["decisions"]["pending"][0]["title"].startswith("Decision: Adopt weekly")


def test_stakeholder_upsert_touch_and_staleness(monkeypatch):
    brain.pm_brain_init.invoke({})
    brain.pm_upsert_stakeholder.invoke(
        {"name": "Naomi Park", "role": "VP Eng", "influence": "high"}
    )
    s = brain.brain_status()
    assert s["stakeholders"]["total"] == 1
    assert len(s["stakeholders"]["stale"]) == 1  # never touched → stale
    out = brain.pm_touch_stakeholder.invoke(
        {"name": "Naomi Park", "summary": "Confirmed Q3 priority"}
    )
    assert "Logged touchpoint" in out
    txt = (brain._brain_root() / "stakeholders" / "naomi-park.md").read_text()
    assert "Confirmed Q3 priority" in txt and brain._today() in txt
    s2 = brain.brain_status()
    assert len(s2["stakeholders"]["stale"]) == 0  # touched today → current


def test_ingest_writes_source_and_ingestion_with_citation():
    brain.pm_brain_init.invoke({})
    out = brain.pm_ingest.invoke(
        {
            "kind": "interviews",
            "title": "Acme ops",
            "synthesis": "Batch notifications unusable.",
            "source_text": "JAMIE: we stopped acting on daily pings.",
        }
    )
    assert "ingestion/interviews/" in out and "source:" in out
    root = brain._brain_root()
    assert list((root / "source" / "interviews").glob("*.md"))
    assert list((root / "ingestion" / "interviews").glob("*.md"))


def test_hypothesis_upsert_warns_on_orphan_evidence():
    brain.pm_brain_init.invoke({})
    body = (
        "## Value risk\n### H-V1: users want this\n- Evidence for:\n  - they said so\n"  # untagged
    )
    out = brain.pm_upsert_hypothesis.invoke({"feature": "weekly-digest", "body": body})
    assert "Saved hypotheses" in out and "missing a provenance tag" in out
    assert (brain._brain_root() / "hypotheses" / "weekly-digest.md").exists()


def test_list_get_search_and_traversal_guard():
    brain.pm_brain_init.invoke({})
    assert "INDEX.md" not in brain.pm_list.invoke({"area": "decisions"})  # decisions empty
    got = brain.pm_get.invoke({"path": "INDEX.md"})
    assert "Master Index" in got
    assert "inside the PM Brain" in brain.pm_get.invoke({"path": "../../etc/passwd"})
    brain.pm_note.invoke(
        {"area": "strategy", "content": "North star = weekly active teams.", "title": "NSM"}
    )
    assert "weekly active teams" in brain.pm_search.invoke({"query": "weekly active"})


# ── file browser + edit (read/edit-all-docs surface) ────────────────────────────


def test_brain_files_groups_everything_and_marks_source_read_only():
    brain.pm_brain_init.invoke({})
    brain.pm_note.invoke({"area": "product/roadmap", "content": "Now: ship digest."})
    brain.pm_ingest.invoke(
        {
            "kind": "interviews",
            "title": "Acme",
            "synthesis": "x",
            "source_text": "verbatim transcript",
        }
    )
    f = brain.brain_files()
    assert f["exists"] is True
    areas = {g["area"]: g for g in f["groups"]}
    # root-level docs (INDEX, operating-manual) surface under a "(root)" group, first
    assert f["groups"][0]["area"] == "(root)"
    assert any(x["path"] == "INDEX.md" for x in areas["(root)"]["files"])
    # a knowledge file the curated status sweep never surfaces is browsable here
    paths = {x["path"] for g in f["groups"] for x in g["files"]}
    assert "knowledge/product/roadmap.md" in paths
    # source/ is present but flagged read-only; every other group is editable
    assert areas["source"]["editable"] is False
    assert areas["knowledge"]["editable"] is True
    # each file carries a human title pulled from its first heading
    roadmap = next(x for x in areas["knowledge"]["files"] if x["path"].endswith("roadmap.md"))
    assert roadmap["title"] and "mtime" in roadmap


def test_write_brain_file_creates_new_file_with_parent_dirs():
    brain.pm_brain_init.invoke({})
    res = brain.write_brain_file("knowledge/product/pricing.md", "# Pricing\n\nFlat tier.\n")
    assert res["ok"] is True and res["warnings"] == []
    assert (brain._brain_root() / "knowledge" / "product" / "pricing.md").exists()


def test_write_brain_file_guards_traversal_extension_and_source():
    brain.pm_brain_init.invoke({})
    assert brain.write_brain_file("../../etc/passwd", "x")["ok"] is False
    assert "inside" in brain.write_brain_file("../../etc/passwd.md", "x")["error"]
    assert brain.write_brain_file("knowledge/notes.txt", "x")["ok"] is False
    src = brain.write_brain_file("source/interviews/2026-06-16-acme.md", "tampered")
    assert src["ok"] is False and "read-only" in src["error"]


def test_write_brain_file_warns_on_untagged_decision_but_saves():
    brain.pm_brain_init.invoke({})
    body = "# Decision: ship\n\n## Status\npending\n\n## Evidence\n- users want it\n"  # untagged
    res = brain.write_brain_file("decisions/2026-06-16-ship.md", body)
    assert res["ok"] is True  # warn, don't block
    assert res["warnings"] and "users want it" in res["warnings"][0]
    assert (brain._brain_root() / "decisions" / "2026-06-16-ship.md").read_text() == body
    # a properly tagged row produces no warning
    ok = brain.write_brain_file(
        "decisions/2026-06-16-ship.md",
        "# Decision: ship\n\n## Evidence\n- users want it  (intuition, PM, 2026-06-16)\n",
    )
    assert ok["ok"] is True and ok["warnings"] == []


def test_write_brain_file_detects_stale_edit_conflict():
    brain.pm_brain_init.invoke({})
    r1 = brain.write_brain_file("knowledge/x.md", "# X\nv1\n")
    assert r1["ok"] is True and "mtime" in r1
    # a matching mtime saves fine
    ok = brain.write_brain_file("knowledge/x.md", "# X\nv2\n", expected_mtime=r1["mtime"])
    assert ok["ok"] is True
    # a stale (older) mtime is refused as a conflict, leaving the file untouched
    stale = brain.write_brain_file("knowledge/x.md", "# X\nv3\n", expected_mtime=r1["mtime"] - 100)
    assert stale["ok"] is False and stale.get("conflict") is True
    assert (brain._brain_root() / "knowledge" / "x.md").read_text() == "# X\nv2\n"


def test_write_brain_file_rejects_unknown_area():
    brain.pm_brain_init.invoke({})
    bad = brain.write_brain_file("competitors/acme.md", "# Acme\n")
    assert bad["ok"] is False and "area" in bad["error"].lower()
    # a root-level doc and a known area both save (matches what the UI offers)
    assert brain.write_brain_file("notes.md", "# Notes\n")["ok"] is True
    assert brain.write_brain_file("knowledge/ok.md", "# OK\n")["ok"] is True


def test_write_brain_file_must_be_new_refuses_existing():
    brain.pm_brain_init.invoke({})
    brain.write_brain_file("knowledge/dup.md", "# Dup\nv1\n")
    res = brain.write_brain_file("knowledge/dup.md", "# Dup\nv2\n", must_be_new=True)
    assert res["ok"] is False and res.get("conflict") is True
    assert (brain._brain_root() / "knowledge" / "dup.md").read_text() == "# Dup\nv1\n"
    # must_be_new on a genuinely new path still saves
    assert brain.write_brain_file("knowledge/fresh.md", "# Fresh\n", must_be_new=True)["ok"] is True


def test_title_of_uses_first_nonempty_line():
    brain.pm_brain_init.invoke({})
    brain.write_brain_file("knowledge/z.md", "\n\n# Heading Z\n\nbody\n")
    f = brain.brain_files()
    z = next(x for g in f["groups"] for x in g["files"] if x["path"].endswith("z.md"))
    assert z["title"] == "Heading Z"


# ── register() wiring ───────────────────────────────────────────────────────────


def test_register_wires_tools_skills_subagents_and_two_routers(registry, monkeypatch):
    import pm as pkg

    # subagents need a host module; inject a minimal fake SubagentConfig.
    fake = types.ModuleType("graph.subagents.config")

    class SubagentConfig:
        def __init__(self, name, description, system_prompt, tools=None, **kw):
            self.name, self.description, self.system_prompt = name, description, system_prompt
            self.tools = tools or []

    fake.SubagentConfig = SubagentConfig
    monkeypatch.setitem(sys.modules, "graph", types.ModuleType("graph"))
    monkeypatch.setitem(sys.modules, "graph.subagents", types.ModuleType("graph.subagents"))
    monkeypatch.setitem(sys.modules, "graph.subagents.config", fake)

    pkg.register(registry)

    assert len(registry.tools) == len(brain.BRAIN_TOOLS) == 11
    assert registry.skill_dirs == ["skills"]
    names = {s.name for s in registry.subagents}
    assert names == {"pm_brain", "pm_discovery", "pm_strategy", "pm_execution", "pm_analytics"}
    prefixes = [p for p, _ in registry.routers]
    assert "/plugins/pm" in prefixes and "/api/plugins/pm" in prefixes


def test_subagent_tool_allowlists_reference_real_tools(registry, monkeypatch):
    """Every tool a subagent allowlists must be a real brain tool or a known host tool —
    a typo'd name silently gives the subagent no access to it."""
    import pm.subagents as sub

    fake = types.ModuleType("graph.subagents.config")

    class SubagentConfig:
        def __init__(self, name, description, system_prompt, tools=None, **kw):
            self.name, self.description, self.tools = name, description, tools or []

    fake.SubagentConfig = SubagentConfig
    monkeypatch.setitem(sys.modules, "graph", types.ModuleType("graph"))
    monkeypatch.setitem(sys.modules, "graph.subagents", types.ModuleType("graph.subagents"))
    monkeypatch.setitem(sys.modules, "graph.subagents.config", fake)

    brain_names = {t.name for t in brain.BRAIN_TOOLS}
    host_tools = {
        "current_time",
        "web_search",
        "fetch_url",
        "memory_recall",
        "memory_list",
        "memory_ingest",
    }
    for cfg in sub._configs():
        for t in cfg.tools:
            assert t in brain_names or t in host_tools, f"{cfg.name} references unknown tool {t!r}"


# ── the view routes ──────────────────────────────────────────────────────────────


def _app():
    from fastapi import FastAPI
    from pm import view

    app = FastAPI()
    app.include_router(view.build_view_router(), prefix="/plugins/pm")
    app.include_router(view.build_data_router(), prefix="/api/plugins/pm")
    return app


def test_view_page_public_and_data_gated_prefix():
    from fastapi.testclient import TestClient

    c = TestClient(_app())
    assert c.get("/plugins/pm/view").status_code == 200  # public page
    assert c.get("/api/plugins/pm/view").status_code == 404  # not under /api
    st = c.get("/api/plugins/pm/status").json()
    assert "decisions" in st and st["exists"] is False  # no brain yet


def test_view_status_and_file_routes_reflect_the_brain():
    from fastapi.testclient import TestClient

    brain.pm_brain_init.invoke({})
    brain.pm_log_decision.invoke(
        {
            "title": "Ship it",
            "context": "x",
            "status": "pending",
            "evidence": ["because  (intuition, PM, 2026-06-15)"],
        }
    )
    c = TestClient(_app())
    st = c.get("/api/plugins/pm/status").json()
    assert st["exists"] is True and len(st["decisions"]["pending"]) == 1
    f = c.get("/api/plugins/pm/file", params={"path": "INDEX.md"}).json()
    assert "Master Index" in f["content"]
    assert c.get("/api/plugins/pm/file", params={"path": "../../etc/passwd"}).status_code == 400


def test_files_route_lists_all_brain_docs():
    from fastapi.testclient import TestClient

    brain.pm_brain_init.invoke({})
    brain.pm_note.invoke({"area": "product/roadmap", "content": "Now: ship digest."})
    c = TestClient(_app())
    f = c.get("/api/plugins/pm/files").json()
    assert f["exists"] is True
    paths = {x["path"] for g in f["groups"] for x in g["files"]}
    assert "INDEX.md" in paths and "knowledge/product/roadmap.md" in paths


def test_put_file_route_saves_creates_and_guards():
    from fastapi.testclient import TestClient

    brain.pm_brain_init.invoke({})
    c = TestClient(_app())
    # create a brand-new file through the editor route
    r = c.put(
        "/api/plugins/pm/file", json={"path": "knowledge/notes.md", "content": "# Notes\nhi\n"}
    )
    assert r.status_code == 200 and r.json()["warnings"] == []
    got = c.get("/api/plugins/pm/file", params={"path": "knowledge/notes.md"}).json()
    assert "hi" in got["content"]
    # source/ is read-only, traversal is refused — both 400
    assert (
        c.put("/api/plugins/pm/file", json={"path": "source/x.md", "content": "tamper"}).status_code
        == 400
    )
    assert (
        c.put(
            "/api/plugins/pm/file", json={"path": "../../etc/passwd.md", "content": "x"}
        ).status_code
        == 400
    )
    # an untagged decision still saves (warn, don't block) but reports the warning
    w = c.put(
        "/api/plugins/pm/file",
        json={"path": "decisions/2026-06-16-x.md", "content": "## Evidence\n- nope\n"},
    )
    assert w.status_code == 200 and w.json()["warnings"]


def test_put_file_route_flags_stale_edit_as_409():
    from fastapi.testclient import TestClient

    brain.pm_brain_init.invoke({})
    c = TestClient(_app())
    c.put("/api/plugins/pm/file", json={"path": "knowledge/y.md", "content": "# Y\nv1\n"})
    got = c.get("/api/plugins/pm/file", params={"path": "knowledge/y.md"}).json()
    assert "mtime" in got
    # a stale mtime → 409 conflict, not a silent overwrite
    stale = c.put(
        "/api/plugins/pm/file",
        json={"path": "knowledge/y.md", "content": "# Y\nv2\n", "mtime": got["mtime"] - 100},
    )
    assert stale.status_code == 409
    # the matching mtime saves and returns the fresh mtime
    ok = c.put(
        "/api/plugins/pm/file",
        json={"path": "knowledge/y.md", "content": "# Y\nv2\n", "mtime": got["mtime"]},
    )
    assert ok.status_code == 200 and "mtime" in ok.json()


def test_put_file_route_new_flag_refuses_existing_file():
    from fastapi.testclient import TestClient

    brain.pm_brain_init.invoke({})
    c = TestClient(_app())
    c.put("/api/plugins/pm/file", json={"path": "knowledge/n.md", "content": "# N\nv1\n"})
    # creating with new=True over an existing path is refused (409), not overwritten
    r = c.put(
        "/api/plugins/pm/file",
        json={"path": "knowledge/n.md", "content": "clobber", "new": True},
    )
    assert r.status_code == 409
    assert (
        "v1" in c.get("/api/plugins/pm/file", params={"path": "knowledge/n.md"}).json()["content"]
    )


def test_shell_page_is_four_rules_compliant():
    from pm import view

    html = view._SHELL_HTML
    assert "/_ds/plugin-kit.css" in html and "/_ds/plugin-kit.js" in html
    assert 'location.pathname.split("/plugins/")[0]' in html  # slug-aware base
    assert 'apiFetch("/api/plugins/pm/status")' in html  # gated data via the kit
    assert "kit.initPluginView" in html  # kit owns theming
    assert ":root{" not in html[: html.index("</style>")]  # no hand-rolled theme


def test_shell_page_has_browser_and_editor_surface():
    from pm import view

    html = view._SHELL_HTML
    assert 'apiFetch("/api/plugins/pm/files")' in html  # browse-everything index
    assert '"/api/plugins/pm/file"' in html and 'method:"PUT"' in html  # save route
    assert 'id="ptext"' in html and 'id="psave"' in html  # editor textarea + save
    assert 'id="newform"' in html  # create-new-file affordance


def test_shell_page_renders_rows_without_interpolating_user_data():
    from pm import view

    html = view._SHELL_HTML
    # user-controlled values go into the DOM via textContent/setAttribute, never an HTML string
    assert "hydrateRows" in html
    assert 'setAttribute("data-path"' in html
    assert "textContent=r.label" in html
    # the old, injection-prone pattern is gone
    assert "data-path=\"'+esc(path)" not in html
    # dashboard fetches run in parallel, and a new file can't silently overwrite an existing one
    assert "Promise.all" in html
    assert "new:cur.isNew" in html
