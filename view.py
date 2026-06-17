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
    from fastapi import APIRouter, Body, HTTPException, Query

    from . import brain  # type: ignore  # resolved via the synthetic package (host + tests)

    router = APIRouter()

    @router.get("/status")
    async def _status() -> dict:
        return brain.brain_status()

    @router.get("/files")
    async def _files() -> dict:
        """Every brain file grouped by area — the browse-everything index for the editor."""
        return brain.brain_files()

    @router.get("/file")
    async def _file(path: str = Query(...)) -> dict:
        target = brain._safe_target(path)
        if target is None:
            raise HTTPException(400, "path must be inside the PM Brain")
        if not target.exists() or target.suffix != ".md":
            raise HTTPException(404, "no such brain file")
        return {"path": path, "content": brain._read(target)}

    @router.put("/file")
    async def _save(payload: dict = Body(...)) -> dict:
        """Save (or create) a brain file. Guards live in brain.write_brain_file; a guard
        failure is a 400, a successful save returns any provenance warnings (warn, don't block)."""
        res = brain.write_brain_file(str(payload.get("path", "")), str(payload.get("content", "")))
        if not res.get("ok"):
            raise HTTPException(400, res.get("error", "could not save"))
        return res

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
  .files{grid-column:1/-1}
  .grp{margin-bottom:6px}
  .grphead{display:flex;align-items:center;gap:6px;font-size:11px;text-transform:uppercase;letter-spacing:.04em;
    color:var(--pl-color-fg-muted,#9aa0aa);margin:10px 0 2px}
  .row.active{background:rgba(127,127,127,.16)}
  #newform{display:none;align-items:center;gap:8px;margin-left:8px}
  #newform select,#newform input{background:var(--pl-color-bg,#0a0a0c);color:var(--pl-color-fg,#ededed);
    border:1px solid var(--pl-color-border,#2a2a30);border-radius:6px;padding:4px 8px;font-size:12px;font-family:inherit}
  #newform input{width:200px}
  #panel{width:0;flex-shrink:0;border-left:1px solid var(--pl-color-border,#2a2a30);overflow:auto;transition:width .12s;background:var(--pl-color-bg,#0a0a0c)}
  #panel.open{width:52%}
  #panel .ph{display:flex;align-items:center;gap:8px;padding:10px 12px;border-bottom:1px solid var(--pl-color-border,#2a2a30);font-size:12px}
  #ptitle{overflow:hidden;text-overflow:ellipsis;white-space:nowrap;font-family:var(--pl-font-mono,ui-monospace,Menlo,monospace)}
  #panel .ph .sp{margin-left:auto}
  #panel pre{margin:0;padding:12px 14px;white-space:pre-wrap;word-break:break-word;font-family:var(--pl-font-mono,ui-monospace,Menlo,monospace);font-size:12px;line-height:1.55}
  #ptext{display:none;width:100%;box-sizing:border-box;min-height:62vh;border:0;outline:none;resize:vertical;
    background:transparent;color:var(--pl-color-fg,#ededed);padding:12px 14px;
    font-family:var(--pl-font-mono,ui-monospace,Menlo,monospace);font-size:12px;line-height:1.55}
  #pnote{display:none;padding:8px 14px;font-size:12px;line-height:1.5;border-bottom:1px solid var(--pl-color-border,#2a2a30)}
  #pnote.bad{background:rgba(239,68,68,.14);color:#ef4444}
  #pnote.warnnote{background:rgba(245,158,11,.14);color:#f59e0b}
  .muted{color:var(--pl-color-fg-muted,#9aa0aa)}
</style></head><body>
<div id="wrap">
  <div id="bar">
    <h1>PM Brain</h1>
    <button id="refresh" class="pl-btn pl-btn--sm" type="button">Refresh</button>
    <button id="new" class="pl-btn pl-btn--sm" type="button">New file</button>
    <span id="newform">
      <select id="narea"></select>
      <input id="nname" type="text" placeholder="file-name.md" spellcheck="false">
      <button id="ncreate" class="pl-btn pl-btn--sm" type="button">Create</button>
      <button id="ncancel" class="pl-btn pl-btn--sm" type="button">Cancel</button>
    </span>
    <span id="root" title=""></span>
  </div>
  <div id="body">
    <div id="cols"><div id="empty" style="display:none"></div></div>
    <div id="panel">
      <div class="ph">
        <span id="ptitle" class="muted"></span>
        <span id="pro" class="pill warn" style="display:none">read-only</span>
        <span class="sp"></span>
        <button id="pedit" class="pl-btn pl-btn--sm" type="button" style="display:none">Edit</button>
        <button id="psave" class="pl-btn pl-btn--sm" type="button" style="display:none">Save</button>
        <button id="pcancel" class="pl-btn pl-btn--sm" type="button" style="display:none">Cancel</button>
        <button id="pclose" class="pl-btn pl-btn--sm" type="button">Close</button>
      </div>
      <div id="pnote"></div>
      <pre id="pbody"></pre>
      <textarea id="ptext" spellcheck="false"></textarea>
    </div>
  </div>
</div>
<script type="module">
  let kit;
  try { kit = await import(window.__base + "/_ds/plugin-kit.js"); }
  catch (e) { kit = { initPluginView(){}, apiFetch: (p, i) => fetch(window.__base + p, i) }; }
  var $cols=document.getElementById("cols"), $empty=document.getElementById("empty"),
      $root=document.getElementById("root"), $panel=document.getElementById("panel"),
      $pbody=document.getElementById("pbody"), $ptitle=document.getElementById("ptitle"),
      $ptext=document.getElementById("ptext"), $pnote=document.getElementById("pnote"),
      $pro=document.getElementById("pro"), $pedit=document.getElementById("pedit"),
      $psave=document.getElementById("psave"), $pcancel=document.getElementById("pcancel"),
      $newform=document.getElementById("newform"), $narea=document.getElementById("narea"),
      $nname=document.getElementById("nname");
  // Areas a human PM can author into from the UI (source/ is read-only audit anchors).
  var NEW_AREAS=["knowledge","decisions","hypotheses","stakeholders","ingestion","rules","maintenance","(root)"];
  $narea.innerHTML=NEW_AREAS.map(function(a){ return '<option value="'+a+'">'+a+'</option>'; }).join("");
  function esc(s){ return String(s).replace(/&/g,"&amp;").replace(/</g,"&lt;"); }

  // ── editor panel state ──
  var cur={path:null, editable:false, content:"", isNew:false};
  function note(msg, kind){
    if(!msg){ $pnote.style.display="none"; return; }
    $pnote.className=kind||""; $pnote.innerHTML=msg; $pnote.style.display="block";
  }
  function viewMode(){
    $ptext.style.display="none"; $pbody.style.display="block";
    $psave.style.display="none"; $pcancel.style.display="none";
    $pedit.style.display=cur.editable?"":"none";
  }
  function editMode(){
    $ptext.value=cur.content; $ptext.style.display="block"; $pbody.style.display="none";
    $pedit.style.display="none"; $psave.style.display=""; $pcancel.style.display="";
    $ptext.focus();
  }
  function showFile(path, editable, content, isNew){
    cur={path:path, editable:editable, content:content, isNew:!!isNew};
    $panel.classList.add("open"); $ptitle.textContent=path; $ptitle.classList.remove("muted");
    $pro.style.display=editable?"none":""; note("");
    $pbody.textContent=content||"(empty)";
    markActive(path);
    if(isNew) editMode(); else viewMode();
  }
  async function openFile(path, editable){
    $panel.classList.add("open"); $ptitle.textContent=path; $pbody.textContent="Loading…";
    $pbody.style.display="block"; $ptext.style.display="none"; note("");
    $pedit.style.display="none"; $psave.style.display="none"; $pcancel.style.display="none"; $pro.style.display="none";
    try{ var r=await kit.apiFetch("/api/plugins/pm/file?path="+encodeURIComponent(path));
      if(!r.ok) throw 0; var d=await r.json(); showFile(path, editable, d.content||"", false); }
    catch(e){ $pbody.textContent="Couldn't load "+path; }
  }
  async function save(){
    var body=$ptext.value;
    try{
      var r=await kit.apiFetch("/api/plugins/pm/file", {method:"PUT",
        headers:{"Content-Type":"application/json"}, body:JSON.stringify({path:cur.path, content:body})});
      var d=await r.json().catch(function(){ return {}; });
      if(!r.ok){ note(esc(d.detail||"Could not save."), "bad"); return; }
      cur.content=body; cur.isNew=false; $pbody.textContent=body||"(empty)"; viewMode();
      if(d.warnings&&d.warnings.length){
        note("Saved — "+d.warnings.length+" provenance warning(s):<br>"+d.warnings.map(esc).join("<br>"), "warnnote");
      } else { note("Saved.", "warnnote"); setTimeout(function(){ if($pnote.textContent==="Saved.") note(""); }, 1500); }
      load();  // reflect new files / retitled docs in the browser
    }catch(e){ note("Could not save (network).", "bad"); }
  }
  $pedit.addEventListener("click", editMode);
  $pcancel.addEventListener("click", function(){ if(cur.isNew){ $panel.classList.remove("open"); } else { note(""); viewMode(); } });
  $psave.addEventListener("click", save);
  document.getElementById("pclose").addEventListener("click", function(){ $panel.classList.remove("open"); markActive(null); });

  function markActive(path){
    $cols.querySelectorAll(".row.active").forEach(function(el){ el.classList.remove("active"); });
    if(path){ var el=$cols.querySelector('.row[data-path="'+(window.CSS&&CSS.escape?CSS.escape(path):path)+'"]'); if(el) el.classList.add("active"); }
  }

  // ── new file ──
  function toggleNew(on){ $newform.style.display=on?"inline-flex":"none"; if(on){ $nname.value=""; $nname.focus(); } }
  document.getElementById("new").addEventListener("click", function(){ toggleNew($newform.style.display==="none"||!$newform.style.display); });
  document.getElementById("ncancel").addEventListener("click", function(){ toggleNew(false); });
  document.getElementById("ncreate").addEventListener("click", function(){
    var area=$narea.value, name=$nname.value.trim();
    if(!name){ $nname.focus(); return; }
    if(!/\.md$/i.test(name)) name+=".md";
    var path=area==="(root)" ? name : area+"/"+name;
    toggleNew(false); showFile(path, true, "", true);
  });
  $nname.addEventListener("keydown", function(e){ if(e.key==="Enter") document.getElementById("ncreate").click(); });

  // ── dashboard cards + file browser ──
  function card(title, inner, cls){ return '<div class="card'+(cls?' '+cls:'')+'"><h2>'+title+'</h2>'+inner+'</div>'; }
  function fileRow(path, label, meta, editable){
    return '<div class="row" data-path="'+esc(path)+'" data-editable="'+(editable===false?0:1)+'">'
      +'<span>'+esc(label)+'</span>'+(meta?'<span class="meta">'+esc(meta)+'</span>':'')+'</div>';
  }
  function browser(f){
    if(!f||!f.exists||!f.groups.length) return "";
    var total=f.groups.reduce(function(n,g){ return n+g.files.length; }, 0);
    var inner=f.groups.map(function(g){
      var rows=g.files.map(function(x){ return fileRow(x.path, x.title||x.path, g.editable?"":"read-only", g.editable); }).join("");
      return '<div class="grp"><div class="grphead">'+esc(g.area)+' <span class="muted">· '+g.files.length+'</span></div>'+rows+'</div>';
    }).join("");
    return card('All files &nbsp;<span class="pill ok">'+total+'</span>', inner, "files");
  }

  function render(s, f){
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

    html += browser(f);  // browse + open + edit every file, first

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
      el.addEventListener("click", function(){ openFile(el.getAttribute("data-path"), el.getAttribute("data-editable")!=="0"); });
    });
    if(cur.path) markActive(cur.path);
  }

  async function load(){
    try{
      var rs=await kit.apiFetch("/api/plugins/pm/status");
      var rf=await kit.apiFetch("/api/plugins/pm/files");
      render(await rs.json(), await rf.json());
    }catch(e){ /* transient */ }
  }
  document.getElementById("refresh").addEventListener("click", load);
  var booted=false; function boot(){ if(booted) return; booted=true; load(); }
  kit.initPluginView(boot); setTimeout(boot, 800);
  document.addEventListener("visibilitychange", function(){ if(!document.hidden && booted) load(); });
</script></body></html>"""
