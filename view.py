"""PM Brain console view — a dashboard over the brain: decision debt, active hypotheses,
stale stakeholders, recent ingestion, area counts, and a click-to-read file panel.

Two routers (plugin-view rules): the PAGE is public on /plugins/pm (an iframe page-load can't
carry a bearer and the page derives its slug base from /plugins/…); the DATA routes are gated
under /api/plugins/pm. Chrome is the DS plugin-kit (/_ds/), so the panel follows the live theme.
"""

from __future__ import annotations


def build_view_router():
    from pathlib import Path

    from fastapi import APIRouter, HTTPException
    from fastapi.responses import HTMLResponse, Response

    router = APIRouter()

    _VENDOR = Path(__file__).resolve().parent / "vendor"
    _VENDOR_FILES = {"marked.min.js", "purify.min.js"}  # exact allowlist — no FS-path input

    @router.get("/view")
    async def _view():
        return HTMLResponse(_SHELL_HTML)

    @router.get("/vendor/{name}")
    async def _vendor(name: str):
        """Serve the self-contained markdown deps (marked + DOMPurify) same-origin. Public,
        like the page itself — a <script src> can't carry a bearer. Allowlisted by exact name,
        so the request never reaches the filesystem with caller-controlled path components."""
        if name not in _VENDOR_FILES:
            raise HTTPException(404, "no such asset")
        f = _VENDOR / name
        if not f.exists():
            raise HTTPException(404, "asset missing")
        return Response(
            f.read_bytes(),
            media_type="application/javascript",
            headers={"Cache-Control": "public, max-age=86400"},
        )

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
        return {"path": path, "content": brain._read(target), "mtime": target.stat().st_mtime}

    @router.put("/file")
    async def _save(payload: dict = Body(...)) -> dict:
        """Save (or create) a brain file. Guards live in brain.write_brain_file; a guard
        failure is a 400, a stale-edit conflict is a 409, a successful save returns any
        provenance warnings (warn, don't block) and the new mtime."""
        mt = payload.get("mtime")
        res = brain.write_brain_file(
            str(payload.get("path", "")),
            str(payload.get("content", "")),
            expected_mtime=float(mt) if isinstance(mt, (int, float)) else None,
            must_be_new=bool(payload.get("new")),
        )
        if not res.get("ok"):
            code = 409 if res.get("conflict") else 400
            raise HTTPException(code, res.get("error", "could not save"))
        return res

    return router


_SHELL_HTML = r"""<!doctype html><html><head><meta charset="utf-8">
<script>
  window.__base = location.pathname.split("/plugins/")[0];
  document.write('<link rel="stylesheet" href="' + window.__base + '/_ds/plugin-kit.css">');
  // Self-contained markdown renderer + sanitizer, served same-origin by this plugin (no CDN).
  // Written during parse so window.marked / window.DOMPurify exist before the deferred module
  // script runs; if a fetch fails the panel falls back to raw text (see paintBody()).
  document.write('<scr'+'ipt src="' + window.__base + '/plugins/pm/vendor/marked.min.js"><\/scr'+'ipt>');
  document.write('<scr'+'ipt src="' + window.__base + '/plugins/pm/vendor/purify.min.js"><\/scr'+'ipt>');
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
    grid-template-columns:repeat(var(--pm-ncols,3),minmax(0,1fr));gap:14px;align-content:start}
  .card{position:relative;border:1px solid var(--pl-color-border,#2a2a30);border-radius:8px;padding:12px 14px;background:rgba(127,127,127,.05)}
  .card.dragging{opacity:.45}
  .cardgrip{position:absolute;top:3px;right:8px;display:flex;align-items:center;justify-content:center;
    width:28px;height:26px;cursor:grab;color:var(--pl-color-fg-muted,#9aa0aa);font-size:13px;letter-spacing:-2px;
    line-height:1;opacity:.45;border-radius:6px;user-select:none;-webkit-user-select:none;touch-action:none}
  .cardgrip:hover{opacity:1;background:rgba(127,127,127,.18)}
  .cardgrip:active{cursor:grabbing}
  .cardresize{position:absolute;top:0;right:0;width:9px;height:100%;cursor:col-resize;border-radius:0 8px 8px 0}
  .cardresize:hover{background:linear-gradient(to right,transparent,rgba(127,127,127,.28))}
  .card h2{font-size:12px;margin:0 0 8px;padding-right:30px;text-transform:uppercase;letter-spacing:.04em;
    color:var(--pl-color-fg-muted,#9aa0aa);cursor:grab;user-select:none;-webkit-user-select:none}
  .card h2:active{cursor:grabbing}
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
  #pgrip{flex:0 0 0;cursor:col-resize;background:transparent}
  #body.panelopen #pgrip{flex-basis:6px}
  #body.panelopen #pgrip:hover{background:var(--pl-color-border,#2a2a30)}
  #panel{width:0;flex-shrink:0;border-left:1px solid var(--pl-color-border,#2a2a30);overflow:auto;transition:width .12s;background:var(--pl-color-bg,#0a0a0c)}
  #panel.open{width:52%}
  #panel.resizing{transition:none}
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
  /* rendered-markdown panel (DOMPurify-sanitized marked output) */
  #prender{display:none;padding:12px 16px;font-size:13px;line-height:1.6;overflow-wrap:anywhere}
  #prender h1,#prender h2,#prender h3,#prender h4{line-height:1.3;margin:1.1em 0 .5em;font-weight:600}
  #prender h1{font-size:1.5em}#prender h2{font-size:1.25em}#prender h3{font-size:1.08em}#prender h4{font-size:1em}
  #prender h1,#prender h2{border-bottom:1px solid var(--pl-color-border,#2a2a30);padding-bottom:.25em}
  #prender p{margin:.6em 0}#prender ul,#prender ol{margin:.5em 0;padding-left:1.5em}#prender li{margin:.2em 0}
  #prender a{color:var(--pl-color-accent,#6ea8fe);text-decoration:none}#prender a:hover{text-decoration:underline}
  #prender code{font-family:var(--pl-font-mono,ui-monospace,Menlo,monospace);font-size:.9em;
    background:rgba(127,127,127,.16);padding:.1em .35em;border-radius:4px}
  #prender pre{background:rgba(127,127,127,.10);border:1px solid var(--pl-color-border,#2a2a30);
    border-radius:6px;padding:10px 12px;overflow:auto}
  #prender pre code{background:none;padding:0}
  #prender blockquote{margin:.6em 0;padding:.1em .9em;border-left:3px solid var(--pl-color-border,#2a2a30);color:var(--pl-color-fg-muted,#9aa0aa)}
  #prender table{border-collapse:collapse;margin:.6em 0;font-size:.95em}
  #prender th,#prender td{border:1px solid var(--pl-color-border,#2a2a30);padding:4px 8px;text-align:left}
  #prender hr{border:0;border-top:1px solid var(--pl-color-border,#2a2a30);margin:1em 0}
  #prender img{max-width:100%}
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
    <div id="pgrip" title="Drag to resize"></div>
    <div id="panel">
      <div class="ph">
        <span id="ptitle" class="muted"></span>
        <span id="pro" class="pill warn" style="display:none">read-only</span>
        <span class="sp"></span>
        <button id="praw" class="pl-btn pl-btn--sm" type="button" style="display:none">Raw</button>
        <button id="pedit" class="pl-btn pl-btn--sm" type="button" style="display:none">Edit</button>
        <button id="psave" class="pl-btn pl-btn--sm" type="button" style="display:none">Save</button>
        <button id="pcancel" class="pl-btn pl-btn--sm" type="button" style="display:none">Cancel</button>
        <button id="pclose" class="pl-btn pl-btn--sm" type="button">Close</button>
      </div>
      <div id="pnote"></div>
      <div id="prender"></div>
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
      $prender=document.getElementById("prender"), $praw=document.getElementById("praw"),
      $newform=document.getElementById("newform"), $narea=document.getElementById("narea"),
      $nname=document.getElementById("nname");
  // Markdown rendering is available only if both vendored libs loaded; otherwise we stay on raw.
  var MD = !!(window.marked && window.DOMPurify);
  var rawView = false;  // view-mode toggle: rendered (default) ↔ raw markdown
  function mdToHtml(src){
    try { return window.DOMPurify.sanitize(window.marked.parse(src||"", {gfm:true})); }
    catch(e){ return null; }  // any parser/sanitizer failure → caller falls back to raw
  }

  // ── adjustable layout (mirrors the DS AppShell: drag-to-reorder + edge-resize, persisted) ──
  // Cards reorder by dragging their grip, resize their column span by dragging the right edge,
  // and the read-panel split is a draggable gutter. State persists to localStorage by card key.
  var $body=document.getElementById("body"), $pgrip=document.getElementById("pgrip");
  var LKEY="pm-brain:layout:v1", ncols=3;
  function loadLayout(){ try{ return JSON.parse(localStorage.getItem(LKEY))||{}; }catch(e){ return {}; } }
  function saveLayout(){ try{ localStorage.setItem(LKEY, JSON.stringify(LAYOUT)); }catch(e){} }
  var LAYOUT=loadLayout();  // { order:[key…], spans:{key:span}, panelw:"<n>px" }

  // Read panel open/close also drives the split gutter + restores the saved width.
  function panelOpen(){ $panel.classList.add("open"); $body.classList.add("panelopen");
    $panel.style.width = LAYOUT.panelw || ""; }            // "" → CSS .open default (52%)
  function panelClose(){ $panel.classList.remove("open"); $body.classList.remove("panelopen");
    $panel.style.width = ""; }                              // clear inline px so width:0 applies

  function computeCols(){
    var w=$cols.clientWidth||$cols.offsetWidth||0;
    ncols=Math.max(1, Math.min(4, Math.floor((w+14)/(300+14))||1));   // ~300px tracks, 1..4
    $cols.style.setProperty("--pm-ncols", ncols);
  }
  function clampSpans(){
    $cols.querySelectorAll(".card").forEach(function(c){
      var s=LAYOUT.spans && LAYOUT.spans[c.getAttribute("data-key")];
      c.style.gridColumn = s ? ("span "+Math.max(1,Math.min(ncols,s))) : "";  // "" → CSS default
    });
  }
  function applyLayout(){
    var cards=[].slice.call($cols.querySelectorAll(".card"));
    if(!cards.length) return;
    var byKey={}; cards.forEach(function(c){ byKey[c.getAttribute("data-key")]=c; });
    var order=(LAYOUT.order||[]).filter(function(k){ return byKey[k]; });    // saved, still-present
    cards.forEach(function(c){ var k=c.getAttribute("data-key"); if(k && order.indexOf(k)<0) order.push(k); });
    order.forEach(function(k){ $cols.appendChild(byKey[k]); });             // saved order, new cards last
    clampSpans();
  }
  function persistOrder(){
    LAYOUT.order=[].map.call($cols.querySelectorAll(".card"), function(c){ return c.getAttribute("data-key"); });
    saveLayout();
  }
  function persistSpan(key, span){ (LAYOUT.spans=LAYOUT.spans||{})[key]=span; saveLayout(); }

  // Drop target = the card the dragged one inserts before (null → append): nearest center, side-aware.
  function dropTarget(x, y){
    var cards=[].slice.call($cols.querySelectorAll(".card:not(.dragging)"));
    var best=null, bestD=Infinity, after=false;
    cards.forEach(function(c){ var r=c.getBoundingClientRect(), cx=r.left+r.width/2, cy=r.top+r.height/2;
      var d=Math.hypot(x-cx, y-cy); if(d<bestD){ bestD=d; best=c; after=(x>cx); } });
    if(!best) return null;
    return after ? best.nextElementSibling : best;
  }
  function wireResize(c, handle){
    handle.addEventListener("pointerdown", function(e){
      e.preventDefault(); e.stopPropagation();
      try{ handle.setPointerCapture(e.pointerId); }catch(_){}
      function move(ev){
        var grid=$cols.getBoundingClientRect(), gap=14, col=(grid.width-(ncols-1)*gap)/ncols;
        var left=c.getBoundingClientRect().left;
        var span=Math.max(1, Math.min(ncols, Math.round((ev.clientX-left+gap)/(col+gap))));
        c.style.gridColumn="span "+span; c._span=span;
      }
      function up(){ document.removeEventListener("pointermove",move); document.removeEventListener("pointerup",up);
        if(c._span) persistSpan(c.getAttribute("data-key"), c._span); }
      document.addEventListener("pointermove",move); document.addEventListener("pointerup",up);
    });
  }
  function wireCards(){
    $cols.querySelectorAll(".card").forEach(function(c){
      var rez=c.querySelector(".cardresize");
      if(!c._w){ c._w=1;
        // native DnD: arm draggable only while a handle (the grip OR the whole card header) is
        // held, so the drag target is generous but row clicks elsewhere stay unaffected.
        var arm=function(){ c.setAttribute("draggable","true"); };
        var disarm=function(){ c.removeAttribute("draggable"); };
        [c.querySelector(".cardgrip"), c.querySelector("h2")].forEach(function(handle){
          if(handle){ handle.addEventListener("mousedown", arm); handle.addEventListener("mouseup", disarm); }
        });
        c.addEventListener("dragstart", function(e){ c.classList.add("dragging");
          if(e.dataTransfer){ e.dataTransfer.effectAllowed="move"; try{ e.dataTransfer.setData("text/plain",""); }catch(_){} } });
        c.addEventListener("dragend", function(){ c.classList.remove("dragging"); c.removeAttribute("draggable"); persistOrder(); });
      }
      if(rez && !rez._w){ rez._w=1; wireResize(c, rez); }
    });
    if(!$cols._dnd){ $cols._dnd=1;
      $cols.addEventListener("dragover", function(e){
        var d=$cols.querySelector(".card.dragging"); if(!d) return; e.preventDefault();
        var t=dropTarget(e.clientX, e.clientY);
        if(t!==d) $cols.insertBefore(d, t);   // t null → append to end
      });
    }
  }
  // Draggable read-panel split gutter.
  $pgrip.addEventListener("pointerdown", function(e){
    if(!$panel.classList.contains("open")) return;
    e.preventDefault(); try{ $pgrip.setPointerCapture(e.pointerId); }catch(_){}
    $panel.classList.add("resizing"); document.body.style.cursor="col-resize";
    function move(ev){
      var b=$body.getBoundingClientRect(), w=Math.max(300, Math.min(b.width*0.8, b.right-ev.clientX));
      $panel.style.width=w+"px"; LAYOUT.panelw=w+"px";
    }
    function up(){ $panel.classList.remove("resizing"); document.body.style.cursor="";
      document.removeEventListener("pointermove",move); document.removeEventListener("pointerup",up); saveLayout(); }
    document.addEventListener("pointermove",move); document.addEventListener("pointerup",up);
  });
  // Re-clamp spans when the cards area changes width (panel resize / open-close / window).
  if(window.ResizeObserver){ new ResizeObserver(function(){ computeCols(); clampSpans(); }).observe($cols); }
  // Areas a human PM can author into from the UI (source/ is read-only audit anchors).
  var NEW_AREAS=["knowledge","decisions","hypotheses","stakeholders","ingestion","rules","maintenance","(root)"];
  $narea.innerHTML=NEW_AREAS.map(function(a){ return '<option value="'+a+'">'+a+'</option>'; }).join("");
  function esc(s){ return String(s).replace(/&/g,"&amp;").replace(/</g,"&lt;")
    .replace(/>/g,"&gt;").replace(/"/g,"&quot;").replace(/'/g,"&#39;"); }

  // ── editor panel state ──
  var cur={path:null, editable:false, content:"", isNew:false};
  function note(msg, kind){
    if(!msg){ $pnote.style.display="none"; return; }
    $pnote.className=kind||""; $pnote.innerHTML=msg; $pnote.style.display="block";
  }
  // View-mode body painter: rendered markdown by default, raw <pre> when toggled or MD missing.
  function paintBody(){
    var c=cur.content||"", useRaw = rawView || !MD, html = useRaw ? null : mdToHtml(c);
    if(html==null){  // raw, or render failed → show the source verbatim
      $pbody.textContent = c || "(empty)"; $pbody.style.display="block"; $prender.style.display="none";
    } else {
      $prender.innerHTML = c ? html : '<span class="muted">(empty)</span>';
      $prender.style.display="block"; $pbody.style.display="none";
    }
    if(MD){ $praw.style.display=""; $praw.textContent = useRaw ? "Rendered" : "Raw"; }
    else { $praw.style.display="none"; }
  }
  function viewMode(){
    $ptext.style.display="none";
    $psave.style.display="none"; $pcancel.style.display="none";
    $pedit.style.display=cur.editable?"":"none";
    paintBody();
  }
  function editMode(){
    $ptext.value=cur.content; $ptext.style.display="block";
    $pbody.style.display="none"; $prender.style.display="none"; $praw.style.display="none";
    $pedit.style.display="none"; $psave.style.display=""; $pcancel.style.display="";
    $ptext.focus();
  }
  function showFile(path, editable, content, isNew, mtime){
    cur={path:path, editable:editable, content:content, isNew:!!isNew,
         mtime:(mtime==null?null:mtime), force:false};
    panelOpen(); $ptitle.textContent=path; $ptitle.classList.remove("muted");
    $pro.style.display=editable?"none":""; note("");
    markActive(path);
    if(isNew) editMode(); else viewMode();
  }
  async function openFile(path, editable){
    panelOpen(); $ptitle.textContent=path; $pbody.textContent="Loading…";
    $pbody.style.display="block"; $prender.style.display="none"; $ptext.style.display="none"; note("");
    $pedit.style.display="none"; $psave.style.display="none"; $pcancel.style.display="none";
    $pro.style.display="none"; $praw.style.display="none";
    try{ var r=await kit.apiFetch("/api/plugins/pm/file?path="+encodeURIComponent(path));
      if(!r.ok) throw 0; var d=await r.json(); showFile(path, editable, d.content||"", false, d.mtime); }
    catch(e){ $pbody.textContent="Couldn't load "+path; }
  }
  async function save(){
    var body=$ptext.value;
    try{
      var r=await kit.apiFetch("/api/plugins/pm/file", {method:"PUT",
        headers:{"Content-Type":"application/json"},
        body:JSON.stringify({path:cur.path, content:body, mtime:cur.force?null:cur.mtime, new:cur.isNew})});
      var d=await r.json().catch(function(){ return {}; });
      if(!r.ok){
        if(r.status===409 && cur.isNew){
          // a brand-new file collided with an existing one — never silently overwrite; rename
          note(esc(d.detail||"A file already exists at that path."), "bad");
        } else if(r.status===409){
          cur.force=true;  // user's edits stay in the textarea; next Save overwrites
          note("This file changed on disk since you opened it. Click Save again to overwrite, "
            +"or Close and reopen to get the latest.", "bad");
        } else { note(esc(d.detail||"Could not save."), "bad"); }
        return;
      }
      cur.content=body; cur.isNew=false; cur.force=false;
      if(d.mtime!=null) cur.mtime=d.mtime;
      viewMode();  // repaint (rendered or raw, per the current toggle)
      if(d.warnings&&d.warnings.length){
        note("Saved — "+d.warnings.length+" provenance warning(s):<br>"+d.warnings.map(esc).join("<br>"), "warnnote");
      } else { note("Saved.", "warnnote"); setTimeout(function(){ if($pnote.textContent==="Saved.") note(""); }, 1500); }
      load();  // reflect new files / retitled docs in the browser
    }catch(e){ note("Could not save (network).", "bad"); }
  }
  $pedit.addEventListener("click", editMode);
  $pcancel.addEventListener("click", function(){ if(cur.isNew){ panelClose(); } else { note(""); viewMode(); } });
  $psave.addEventListener("click", save);
  $praw.addEventListener("click", function(){ rawView=!rawView; paintBody(); });
  // Links inside rendered markdown must not navigate the iframe. A brain-relative *.md link
  // (e.g. a provenance pointer like ../ingestion/foo.md) opens that file in this panel instead.
  $prender.addEventListener("click", function(e){
    var a=(e.target && e.target.closest) ? e.target.closest("a") : null; if(!a) return;
    e.preventDefault();
    var href=(a.getAttribute("href")||"").trim();
    if(!href || /^[a-z]+:/i.test(href) || href[0]==="#") return;   // external / in-page anchor
    if(!/\.md(\?|#|$)/i.test(href)) return;                        // only resolve brain docs
    var segs=cur.path.split("/").slice(0,-1);                      // dir of the current file
    href.split("#")[0].split("?")[0].split("/").forEach(function(p){
      if(p===".."){ segs.pop(); } else if(p && p!=="."){ segs.push(p); }
    });
    var target=segs.join("/");
    if(target) openFile(target, target.split("/")[0]!=="source");  // source/ stays read-only
  });
  document.getElementById("pclose").addEventListener("click", function(){ panelClose(); markActive(null); });

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
  function card(title, inner, cls, key){
    return '<div class="card'+(cls?' '+cls:'')+'"'+(key?' data-key="'+key+'"':'')
      +'><span class="cardgrip" title="Drag to reorder">⋮⋮</span><h2>'+title+'</h2>'+inner
      +'<span class="cardresize" title="Drag to resize width"></span></div>';
  }
  // Rows carry user-controlled text (filenames, doc titles, stakeholder names). Never interpolate
  // those into an HTML string — stash them and write them into the DOM via textContent/setAttribute
  // after the card shells exist (hydrateRows), so a crafted filename can't inject markup.
  var rowReg=[];
  function fileRow(path, label, meta, editable){
    var i=rowReg.push({path:path, label:label, meta:meta||"", editable:editable!==false})-1;
    return '<div class="row" data-i="'+i+'"></div>';
  }
  function hydrateRows(){
    $cols.querySelectorAll(".row[data-i]").forEach(function(el){
      var r=rowReg[+el.getAttribute("data-i")];
      if(!r) return;
      el.setAttribute("data-path", r.path);
      el.setAttribute("data-editable", r.editable?"1":"0");
      var s=document.createElement("span"); s.textContent=r.label; el.appendChild(s);
      if(r.meta){ var m=document.createElement("span"); m.className="meta"; m.textContent=r.meta; el.appendChild(m); }
      el.addEventListener("click", function(){ openFile(r.path, r.editable); });
    });
  }
  function browser(f){
    if(!f||!f.exists||!f.groups.length) return "";
    var total=f.groups.reduce(function(n,g){ return n+g.files.length; }, 0);
    var inner=f.groups.map(function(g){
      var rows=g.files.map(function(x){ return fileRow(x.path, x.title||x.path, g.editable?"":"read-only", g.editable); }).join("");
      return '<div class="grp"><div class="grphead">'+esc(g.area)+' <span class="muted">· '+g.files.length+'</span></div>'+rows+'</div>';
    }).join("");
    return card('All files &nbsp;<span class="pill ok">'+total+'</span>', inner, "files", "files");
  }

  function render(s, f){
    rowReg=[];  // fresh per render; data-i indices point into this
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
      +'<div class="stat"><span>superseded</span><b>'+d.superseded+'</b></div>', null, "decisions");

    // Hypotheses
    var chips = Object.keys(h.by_status).map(function(k){ return '<span class="chip">'+k+' · '+h.by_status[k]+'</span>'; }).join("") || '<span class="muted">none</span>';
    var feats = h.features.slice(0,8).map(function(f){ return fileRow(f.file, f.file.replace("hypotheses/",""), f.status); }).join("");
    html += card('Hypotheses', chips + (feats?('<div style="margin-top:6px">'+feats+'</div>'):''), null, "hypotheses");

    // Stakeholders
    var stale = st.stale.map(function(x){ return fileRow(x.file, x.name, x.last); }).join("") || '<div class="muted">All current. </div>';
    html += card('Stale stakeholders &nbsp;<span class="pill '+(st.stale.length?'warn':'ok')+'">'+st.stale.length+'/'+st.total+'</span>', stale, null, "stakeholders");

    // Recent ingestion
    if(s.ingestion_recent.length){
      html += card('Recent ingestion', s.ingestion_recent.map(function(i){ return fileRow(i.file, i.title, ""); }).join(""), null, "ingestion");
    }

    // Counts
    var counts = Object.keys(s.counts).map(function(k){ return '<div class="stat"><span>'+k+'</span><b>'+s.counts[k]+'</b></div>'; }).join("");
    html += card('Areas', counts, null, "areas");

    $cols.innerHTML=html;
    hydrateRows();
    computeCols(); applyLayout(); wireCards();
    if(cur.path) markActive(cur.path);
  }

  async function load(){
    try{
      var res=await Promise.all([
        kit.apiFetch("/api/plugins/pm/status"),
        kit.apiFetch("/api/plugins/pm/files")
      ]);
      render(await res[0].json(), await res[1].json());
    }catch(e){ /* transient */ }
  }
  document.getElementById("refresh").addEventListener("click", load);
  var booted=false; function boot(){ if(booted) return; booted=true; load(); }
  kit.initPluginView(boot); setTimeout(boot, 800);
  document.addEventListener("visibilitychange", function(){ if(!document.hidden && booted) load(); });
</script></body></html>"""
