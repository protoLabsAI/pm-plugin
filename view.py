"""PM Brain console view — a dashboard over the brain: decision debt, active hypotheses,
stale stakeholders, recent ingestion, area counts, and a click-to-read file panel.

Two routers (plugin-view rules): the PAGE is public on /plugins/pm (an iframe page-load can't
carry a bearer and the page derives its slug base from /plugins/…); the DATA routes are gated
under /api/plugins/pm. Chrome is the DS plugin-kit (/_ds/), so the panel follows the live theme.
"""

from __future__ import annotations


def build_view_router():
    from fastapi import APIRouter
    from fastapi.responses import HTMLResponse

    router = APIRouter()

    @router.get("/view")
    async def _view():
        return HTMLResponse(_SHELL_HTML)

    return router


def build_data_router():
    from fastapi import APIRouter, HTTPException, Query

    from . import brain  # type: ignore  # resolved via the synthetic package (host + tests)

    router = APIRouter()

    @router.get("/status")
    async def _status() -> dict:
        return brain.brain_status()

    @router.get("/file")
    async def _file(path: str = Query(...)) -> dict:
        root = brain._brain_root()
        target = (root / path).resolve()
        try:
            target.relative_to(root.resolve())
        except ValueError:
            raise HTTPException(400, "path must be inside the PM Brain") from None
        if not target.exists() or target.suffix != ".md":
            raise HTTPException(404, "no such brain file")
        return {"path": path, "content": brain._read(target)}

    return router


_SHELL_HTML = r"""<!doctype html><html><head><meta charset="utf-8">
<script>
  window.__base = location.pathname.split("/plugins/")[0];
  document.write('<link rel="stylesheet" href="' + window.__base + '/_ds/plugin-kit.css">');
</script>
<style>
  html,body{margin:0;height:100%;background:var(--pl-color-bg,#0a0a0c);color:var(--pl-color-fg,#ededed);
    font-family:var(--pl-font-sans,ui-sans-serif,system-ui,sans-serif)}
  #wrap{display:flex;flex-direction:column;height:100%}
  #bar{display:flex;align-items:center;gap:10px;padding:10px 14px;
    border-bottom:1px solid var(--pl-color-border,#2a2a30);font-size:13px}
  #bar h1{font-size:14px;margin:0;font-weight:600}
  #root{margin-left:auto;color:var(--pl-color-fg-muted,#9aa0aa);font-size:11px;
    font-family:var(--pl-font-mono,ui-monospace,Menlo,monospace);overflow:hidden;text-overflow:ellipsis;max-width:50%}
  #body{flex:1;min-height:0;display:flex}
  #cols{flex:1;min-width:0;overflow:auto;padding:14px;display:grid;
    grid-template-columns:repeat(auto-fill,minmax(280px,1fr));gap:14px;align-content:start}
  .card{border:1px solid var(--pl-color-border,#2a2a30);border-radius:8px;padding:12px 14px;background:rgba(127,127,127,.05)}
  .card h2{font-size:12px;margin:0 0 8px;text-transform:uppercase;letter-spacing:.04em;color:var(--pl-color-fg-muted,#9aa0aa)}
  .row{display:flex;align-items:center;gap:8px;padding:4px 0;font-size:13px;cursor:pointer;border-radius:4px}
  .row:hover{background:rgba(127,127,127,.10)}
  .row .meta{margin-left:auto;color:var(--pl-color-fg-muted,#9aa0aa);font-size:11px;white-space:nowrap}
  .chip{display:inline-block;padding:1px 7px;border-radius:999px;font-size:11px;background:rgba(127,127,127,.16);margin:2px 4px 2px 0}
  .pill{padding:1px 8px;border-radius:999px;font-size:11px;font-weight:600}
  .warn{background:rgba(245,158,11,.18);color:#f59e0b}
  .ok{background:rgba(34,197,94,.16);color:#22c55e}
  .stat{display:flex;justify-content:space-between;font-size:12px;padding:2px 0;color:var(--pl-color-fg-muted,#9aa0aa)}
  .stat b{color:var(--pl-color-fg,#ededed);font-variant-numeric:tabular-nums}
  #empty{margin:auto;text-align:center;max-width:380px;color:var(--pl-color-fg-muted,#9aa0aa);font-size:14px;line-height:1.6}
  #panel{width:0;flex-shrink:0;border-left:1px solid var(--pl-color-border,#2a2a30);overflow:auto;transition:width .12s;background:var(--pl-color-bg,#0a0a0c)}
  #panel.open{width:46%}
  #panel .ph{display:flex;align-items:center;gap:8px;padding:10px 12px;border-bottom:1px solid var(--pl-color-border,#2a2a30);font-size:12px}
  #panel pre{margin:0;padding:12px 14px;white-space:pre-wrap;word-break:break-word;font-family:var(--pl-font-mono,ui-monospace,Menlo,monospace);font-size:12px;line-height:1.55}
  #pclose{margin-left:auto}
  .muted{color:var(--pl-color-fg-muted,#9aa0aa)}
</style></head><body>
<div id="wrap">
  <div id="bar">
    <h1>PM Brain</h1>
    <button id="refresh" class="pl-btn pl-btn--sm" type="button">Refresh</button>
    <span id="root" title=""></span>
  </div>
  <div id="body">
    <div id="cols"><div id="empty" style="display:none"></div></div>
    <div id="panel"><div class="ph"><span id="ptitle" class="muted"></span><button id="pclose" class="pl-btn pl-btn--sm" type="button">Close</button></div><pre id="pbody"></pre></div>
  </div>
</div>
<script type="module">
  let kit;
  try { kit = await import(window.__base + "/_ds/plugin-kit.js"); }
  catch (e) { kit = { initPluginView(){}, apiFetch: (p, i) => fetch(window.__base + p, i) }; }
  var $cols=document.getElementById("cols"), $empty=document.getElementById("empty"),
      $root=document.getElementById("root"), $panel=document.getElementById("panel"),
      $pbody=document.getElementById("pbody"), $ptitle=document.getElementById("ptitle");
  function esc(s){ return String(s).replace(/&/g,"&amp;").replace(/</g,"&lt;"); }

  async function openFile(path){
    $panel.classList.add("open"); $ptitle.textContent=path; $pbody.textContent="Loading…";
    try{ var r=await kit.apiFetch("/api/plugins/pm/file?path="+encodeURIComponent(path));
      if(!r.ok) throw 0; var d=await r.json(); $pbody.textContent=d.content||"(empty)"; }
    catch(e){ $pbody.textContent="Couldn't load "+path; }
  }
  document.getElementById("pclose").addEventListener("click",function(){ $panel.classList.remove("open"); });

  function card(title, inner){ return '<div class="card"><h2>'+title+'</h2>'+inner+'</div>'; }
  function fileRow(path, label, meta){
    return '<div class="row" data-path="'+esc(path)+'"><span>'+esc(label)+'</span>'+(meta?'<span class="meta">'+esc(meta)+'</span>':'')+'</div>';
  }

  function render(s){
    $root.textContent=s.root; $root.title=s.root;
    if(!s.exists){
      $cols.innerHTML=""; $empty.style.display="block";
      $empty.innerHTML='<b>No PM Brain here yet.</b><br>Ask the agent to <code>pm_brain_init</code> '
        +'(or run the <code>pm_brain</code> subagent), then ingest an interview, log a decision, '
        +'or map a stakeholder. This dashboard surfaces decision debt, active hypotheses, and stale relationships.';
      $cols.appendChild($empty); return;
    }
    $empty.style.display="none";
    var d=s.decisions, h=s.hypotheses, st=s.stakeholders, html="";

    // Decision debt
    var pend = d.pending.map(function(p){ return fileRow(p.file, p.title, "pending"); }).join("") || '<div class="muted">No open decisions. </div>';
    html += card('Decision debt &nbsp;<span class="pill '+(d.pending.length?'warn':'ok')+'">'+d.pending.length+'</span>',
      pend + '<div class="stat" style="margin-top:8px"><span>decided</span><b>'+d.decided+'</b></div>'
      +'<div class="stat"><span>superseded</span><b>'+d.superseded+'</b></div>');

    // Hypotheses
    var chips = Object.keys(h.by_status).map(function(k){ return '<span class="chip">'+k+' · '+h.by_status[k]+'</span>'; }).join("") || '<span class="muted">none</span>';
    var feats = h.features.slice(0,8).map(function(f){ return fileRow(f.file, f.file.replace("hypotheses/",""), f.status); }).join("");
    html += card('Hypotheses', chips + (feats?('<div style="margin-top:6px">'+feats+'</div>'):''));

    // Stakeholders
    var stale = st.stale.map(function(x){ return fileRow(x.file, x.name, x.last); }).join("") || '<div class="muted">All current. </div>';
    html += card('Stale stakeholders &nbsp;<span class="pill '+(st.stale.length?'warn':'ok')+'">'+st.stale.length+'/'+st.total+'</span>', stale);

    // Recent ingestion
    if(s.ingestion_recent.length){
      html += card('Recent ingestion', s.ingestion_recent.map(function(i){ return fileRow(i.file, i.title, ""); }).join(""));
    }

    // Counts
    var counts = Object.keys(s.counts).map(function(k){ return '<div class="stat"><span>'+k+'</span><b>'+s.counts[k]+'</b></div>'; }).join("");
    html += card('Areas', counts);

    $cols.innerHTML=html;
    $cols.querySelectorAll(".row[data-path]").forEach(function(el){
      el.addEventListener("click", function(){ openFile(el.getAttribute("data-path")); });
    });
  }

  async function load(){
    try{ var r=await kit.apiFetch("/api/plugins/pm/status"); render(await r.json()); }
    catch(e){ /* transient */ }
  }
  document.getElementById("refresh").addEventListener("click", load);
  var booted=false; function boot(){ if(booted) return; booted=true; load(); }
  kit.initPluginView(boot); setTimeout(boot, 800);
  document.addEventListener("visibilitychange", function(){ if(!document.hidden && booted) load(); });
</script></body></html>"""
