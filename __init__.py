"""Product Manager plugin (id: pm) — a PM toolkit for protoAgent.

Contributes: 65 PM **skills** (skills/), a markdown-native **PM Brain** (brain.py — decisions,
hypotheses, stakeholders, knowledge, with provenance-enforced evidence), five PM specialist
**subagents** (subagents.py), and a **dashboard view** (view.py). Adapted from Paweł Huryn's
pm-skills + pm-brain (MIT) — see NOTICE.

register() is the only place plugin code runs. Host-only imports (graph.*) stay lazy (inside
functions), so the sibling modules import with just fastapi + langchain-core (the test deps).
"""

from __future__ import annotations

import logging

log = logging.getLogger("protoagent.plugins.pm")


def register(registry) -> None:
    from . import brain, subagents, view

    try:
        for t in brain.BRAIN_TOOLS:
            registry.register_tool(t)
    except Exception:  # noqa: BLE001 — one failing group must not sink the rest
        log.exception("[pm] registering brain tools failed")

    try:
        # The 65 PM skills (skills/*/SKILL.md) — auto-discovered by description.
        registry.register_skill_dir("skills")
    except Exception:  # noqa: BLE001
        log.exception("[pm] registering skill dir failed")

    try:
        subagents.register_subagents(registry)
    except Exception:  # noqa: BLE001
        log.exception("[pm] registering subagents failed")

    try:
        # PAGE public (iframe-loadable, base-derivation safe); DATA gated (operator bearer).
        registry.register_router(view.build_view_router(), prefix="/plugins/pm")
        registry.register_router(view.build_data_router(), prefix="/api/plugins/pm")
    except Exception:  # noqa: BLE001
        log.exception("[pm] registering view failed")
