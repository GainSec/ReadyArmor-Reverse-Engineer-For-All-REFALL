"""REF-All operator console — a self-contained SPA served at :8900/.

Subject selector + per-subject: coverage, plan progress, findings + funnel, context (view/edit/
generate), wishlist, per-class exhaustiveness. Fetches every endpoint client-side and polls to
stay live. Theme-aware (--wb-* vars); no external assets.
"""


def render():
    return r"""<!doctype html><html lang=en><head><meta charset=utf-8>
<meta name=viewport content="width=device-width,initial-scale=1">
<title>REF-All — Operator Console</title><style>
:root{--bg:var(--wb-bg,#0d1020);--surf:var(--wb-surface,#171b31);--surf2:var(--wb-surface-2,#1e2440);
--ink:var(--wb-ink,#f4f7ff);--mut:var(--wb-muted,#9aa6c7);--acc:var(--wb-accent,#e51b2d);
--acc2:var(--wb-accent-2,#6ee85a);--rule:var(--wb-rule,#2b3156);
--crit:#ff4d5e;--high:#ff9f40;--med:#ffce54;--low:#7a83a6}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--ink);font:14px/1.5 "Trebuchet MS",Verdana,sans-serif;padding:16px;max-width:1200px;margin:auto}
a{color:var(--acc2)}
h1{color:var(--acc);margin:0;font-size:23px;letter-spacing:.3px}
h3{margin:0 0 8px;font-size:12px;color:var(--acc2);text-transform:uppercase;letter-spacing:.06em}
.mono{font-family:"JetBrains Mono",Menlo,monospace;font-size:11px;color:var(--mut);word-break:break-all}
.top{display:flex;align-items:center;justify-content:space-between;flex-wrap:wrap;gap:10px;margin-bottom:6px}
.subjects{display:flex;gap:8px;flex-wrap:wrap;margin:10px 0 4px}
.sbtn{background:var(--surf);border:1px solid var(--rule);color:var(--ink);border-radius:8px;padding:8px 12px;cursor:pointer;font:inherit;text-align:left}
.sbtn.on{border-color:var(--acc2);border-left:3px solid var(--acc2)}
.sbtn b{display:block} .sbtn small{color:var(--mut);font-size:11px}
.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(120px,1fr));gap:10px;margin:12px 0}
.card{background:var(--surf);border:1px solid var(--rule);border-left:3px solid var(--acc2);border-radius:8px;padding:11px}
.card .lab{color:var(--mut);font-size:10px;text-transform:uppercase;letter-spacing:.05em}
.card .big{font-size:24px;color:var(--acc2);font-weight:700}
.card .sm{font-size:11px;color:var(--mut)}
.bar{height:8px;background:var(--rule);border-radius:5px;overflow:hidden;margin-top:6px}.bar>i{display:block;height:100%;background:var(--acc2)}
.panels{display:grid;grid-template-columns:1fr 1fr;gap:14px;margin-top:14px}
@media(max-width:820px){.panels{grid-template-columns:1fr}}
.panel{background:var(--surf);border:1px solid var(--rule);border-radius:9px;padding:13px}
.panel.wide{grid-column:1/-1}
textarea{width:100%;min-height:150px;background:var(--bg);color:var(--ink);border:1px solid var(--rule);border-radius:6px;padding:8px;font-family:"JetBrains Mono",monospace;font-size:12px;resize:vertical}
button.act{background:var(--acc2);color:#0a0d18;border:none;border-radius:6px;padding:6px 12px;cursor:pointer;font:inherit;font-weight:700;margin-top:8px}
button.ghost{background:var(--surf2);color:var(--ink);border:1px solid var(--rule)}
table{width:100%;border-collapse:collapse}td,th{padding:6px 8px;text-align:left;border-bottom:1px solid var(--rule);font-size:12.5px;vertical-align:top}
th{color:var(--mut);text-transform:uppercase;font-size:10px}
.sev{font-family:"JetBrains Mono",monospace;font-size:10px;font-weight:700;padding:1px 6px;border-radius:4px;color:#0a0d18}
.sev.CRITICAL{background:var(--crit)}.sev.HIGH{background:var(--high)}.sev.MEDIUM{background:var(--med)}.sev.LOW{background:var(--low);color:#dfe4f5}
.chips{display:flex;flex-wrap:wrap;gap:5px}
.chip{font-family:"JetBrains Mono",monospace;font-size:11px;padding:2px 8px;border-radius:20px;background:var(--surf2);border:1px solid var(--rule);color:var(--mut)}
.muted{color:var(--mut)} .empty{color:var(--mut);font-size:12px;padding:8px 0}
.wl{display:flex;justify-content:space-between;gap:8px;border-bottom:1px solid var(--rule);padding:6px 0}
.wl small{color:var(--mut)}
.fp-section{margin-top:14px;background:var(--surf);border:1px solid var(--rule);border-radius:9px;padding:8px 13px}
.fp-section summary{cursor:pointer;color:var(--mut);font-weight:700;text-transform:uppercase;font-size:11px;letter-spacing:.06em;padding:5px 0}
.fp-section[open] summary{color:var(--acc2)}
.finding-details{margin-top:6px;background:var(--surf2);border:1px solid var(--rule);border-radius:7px;padding:6px 8px}
.finding-details summary{cursor:pointer;color:var(--acc2);font-size:11px;font-weight:700;text-transform:uppercase;letter-spacing:.05em}
.trace-mini{display:grid;grid-template-columns:repeat(auto-fit,minmax(145px,1fr));gap:6px;margin-top:7px}
.trace-mini-step{background:var(--bg);border:1px solid var(--rule);border-radius:6px;padding:7px;min-height:72px}
.trace-mini-label{color:var(--acc2);font-size:9px;font-weight:700;text-transform:uppercase;letter-spacing:.05em}
.trace-mini-body{font-size:11px;color:var(--ink);overflow-wrap:anywhere}
.runtime{font-size:11.5px;color:var(--mut);margin-top:7px}.runtime b{color:var(--ink)}
.live{display:inline-block;width:8px;height:8px;border-radius:50%;background:var(--acc2);margin-right:5px;animation:pulse 1.6s infinite}
@keyframes pulse{50%{opacity:.35}}
</style></head><body>
<div class=top>
  <h1>REF-All &mdash; Operator Console</h1>
  <div class=mono><span class=live></span>live &middot; <span id=host></span> &middot; <span id=clock></span></div>
</div>
<div class=subjects id=subjects></div>
<div id=main></div>

<script>
var S=null, subjects=[];
function h(s){return (s==null?'':String(s)).replace(/[&<>"]/g,function(c){return{'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]})}
function j(u,o){return fetch(u,o).then(function(r){return r.json()}).catch(function(){return null})}
function pj(u,b){return j(u,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(b)})}

function loadSubjects(){
  return j('/subjects').then(function(list){
    subjects=list||[];
    document.getElementById('subjects').innerHTML=subjects.map(function(s){
      return '<button class="sbtn'+(s.subject===S?' on':'')+'" onclick="pick(\''+h(s.subject)+'\')">'+
        '<b>'+h(s.subject)+'</b><small>'+(s.coverage||0).toLocaleString()+' lines &middot; '+
        (s.plan||0)+' inv &middot; '+(s.findings||0)+' find'+(s.has_context?' &middot; ctx&#10003;':'')+'</small></button>';
    }).join('');
    if(!S && subjects.length){var d=subjects.filter(function(x){return x.coverage>0})[0]||subjects[0];S=d.subject;}
  });
}
function pick(name){S=name;loadSubjects();refresh();}

function card(lab,big,sm,pct){return '<div class=card><div class=lab>'+lab+'</div><div class=big>'+big+'</div>'+
  (sm?'<div class=sm>'+sm+'</div>':'')+(pct!=null?'<div class=bar><i style="width:'+pct+'%"></i></div>':'')+'</div>'}
function clip(s,n){s=(s==null?'':String(s)).trim();return s.length>n?s.slice(0,n-1).trim()+'...':s}
function firstSentence(s,fallback,limit){s=(s||fallback||'').trim();limit=limit||180;if(!s)return fallback||'';
  var markers=['. ','.\n'];for(var i=0;i<markers.length;i++){var p=s.indexOf(markers[i]);if(p>0&&p<limit)return s.slice(0,p+1)}
  return clip(s,limit)}
function reproSentence(text,prefix){var parts=String(text||'').replace(/\n/g,' ').split('. ');
  for(var i=0;i<parts.length;i++){var p=parts[i].trim();if(p.toLowerCase().indexOf(prefix.toLowerCase())===0)return p.replace(/\.$/,'')+'.'}
  return ''}
function runtimeViability(f){if(f.production_viability)return clip(f.production_viability,360);
  var dyn=reproSentence(f.repro_hints,'Dynamic repro'),exp=reproSentence(f.repro_hints,'Expected dynamic proof');
  if(dyn)return clip('Runtime validation is directly actionable. '+dyn,360);
  if(exp)return clip('Runtime validation is viable but not yet executed. '+exp,360);
  if(f.repro_status==='evidence_anchored')return 'Runtime validation still needs execution; the static anchors and reviewer note define the dynamic proof step.';
  return 'Runtime validation has not been attempted yet; use the trace, code anchor, and repro/proof note as the starting point.'}
function attackerInput(f){return clip(reproSentence(f.repro_hints,'Dynamic repro')||
  reproSentence(f.repro_hints,'Evidence-anchored repro plan')||
  ((f.attacker_position||'Attacker')+' input reaches this path with privileges '+(f.privileges_required||'?')+'.'),170)}
function findingTrace(f){var paths=f.code_paths||[],anchors=paths.slice(0,3).join(' -> ');
  if(paths.length>3)anchors+=' -> +'+(paths.length-3)+' more anchors';
  var steps=[
    ['Attacker input',attackerInput(f)],
    ['Source to sink',firstSentence(f.description,'Root cause not recorded.',190)],
    ['Code anchor',anchors||'no code path recorded'],
    ['Review gate',firstSentence(f.reasoning,'Reviewer rationale not recorded.',190)]
  ];
  var stat=reproSentence(f.repro_hints,'Static proof'),exp=reproSentence(f.repro_hints,'Expected dynamic proof');
  if(stat)steps.push(['Static proof',clip(stat,190)]);
  if(exp)steps.push(['Runtime proof target',clip(exp,190)]);
  return '<details class=finding-details><summary>End-to-end trace</summary><div class=trace-mini>'+
    steps.map(function(s){return '<div class=trace-mini-step><div class=trace-mini-label>'+h(s[0])+'</div><div class=trace-mini-body>'+h(s[1])+'</div></div>'}).join('')+
    '</div><div class=runtime><b>Runtime validation viability.</b> '+h(runtimeViability(f))+'</div>'+
    (f.critic_reasoning?'<div class=runtime><b>Validation artifact.</b> '+h(clip(f.critic_reasoning,420))+'</div>':'')+'</details>'}

function refresh(){
  if(!S){document.getElementById('main').innerHTML='<div class=empty>No subjects found under refallsub.</div>';return;}
  Promise.all([j('/coverage?subject='+S),j('/plan_progress?subject='+S),j('/findings_summary?subject='+S),
    j('/funnel?subject='+S),j('/context?subject='+S),j('/wishlist?subject='+S),
    j('/findings?subject='+S),j('/class_coverage?subject='+S),j('/investigations?subject='+S+'&state=open')
  ]).then(function(r){
    var cov=r[0]||{},pp=r[1]||{},fs=r[2]||{},fn=r[3]||{},ctx=r[4]||{},wl=r[5]||[],fds=r[6]||[],cc=r[7]||[],inv=r[8]||[];
    var planDone=pp.total?Math.round(100*pp.done/pp.total):0;
    var sev=fs.by_severity||{};
    var m='<div class=grid>'+
      card('Sensitive plan',(pp.done||0)+'/'+(pp.total||0),'investigations',planDone)+
      card('Findings',fs.total||0,Object.keys(sev).map(function(k){return k[0]+':'+sev[k]}).join(' ')||'none')+
      card('Precision',fn.precision!=null?Math.round(fn.precision*100)+'%':'—',(fn.valid||0)+' valid / '+(fn.false_positive||0)+' FP')+
      card('Line coverage',(cov.characterized_pct||0)+'%',(cov.lines_covered||0).toLocaleString()+' / '+(cov.lines_total||0).toLocaleString(),cov.characterized_pct)+
      card('Wishlist',wl.filter(function(w){return w.status==='open'}).length,'open requests')+
    '</div>';

    var hasCtx=ctx&&ctx.info_md;
    function isRejectedFinding(f){return f.status==='FALSE_POSITIVE'||f.status==='DUPLICATE'}
    function isChainableDeferred(f){return f.status==='CHAINABLE_DEFERRED'}
    var rejectedFindings=fds.filter(isRejectedFinding);
    var chainableFindings=fds.filter(isChainableDeferred);
    var nonRejectedFindings=fds.filter(function(f){return !isRejectedFinding(f)&&!isChainableDeferred(f)});
    function findingsTable(rows, emptyText){
      return rows.length?'<table><tr><th>sev</th><th>status</th><th>title</th><th>anchor</th><th>class</th></tr>'+
        rows.slice(0,60).map(function(f){return '<tr><td><span class="sev '+h(f.severity)+'">'+h(f.severity||'?')+'</span></td>'+
          '<td class=mono>'+h(f.status)+'</td><td><b>'+h(f.title)+'</b>'+(!isRejectedFinding(f)?findingTrace(f):'')+'</td>'+
          '<td class=mono>'+h((f.code_paths||[]).slice(0,2).join(', '))+'</td><td class=mono>'+h(f.vuln_class||'')+'</td></tr>'}).join('')+'</table>'
        :'<div class=empty>'+emptyText+'</div>';
    }
    m+='<div class=panels><div class=panel><h3>Subject context (INFO.md)</h3>'+
      '<textarea id=ctxbox placeholder="No context yet. Click Generate to have an agent write the briefing, or write it here.">'+h(hasCtx?ctx.info_md:'')+'</textarea>'+
      '<button class=act onclick=saveCtx()>Save</button> '+
      '<button class="act ghost" onclick=genCtx()>Generate with agent</button>'+
      '<span id=ctxmsg class=muted style="margin-left:8px;font-size:12px"></span></div>';

    m+='<div class=panel><h3>Wishlist &mdash; what researchers need</h3>'+
      (wl.length?wl.map(function(w){return '<div class=wl><div><b>'+h(w.item)+'</b> <span class=chip>'+h(w.kind||'?')+'</span><br>'+
        '<small>'+h(w.reason||'')+' &middot; '+h(w.requested_by||'')+'</small></div>'+
        (w.status==='open'?'<button class="act ghost" onclick="resolveWish(\''+w.id+'\')">provided</button>':'<span class=chip>'+h(w.status)+'</span>')+
        '</div>'}).join(''):'<div class=empty>No requests logged.</div>')+'</div></div>';

    m+='<div class="panel wide" style="margin-top:14px"><h3>Findings</h3>'+
      findingsTable(nonRejectedFindings,'No non-rejected findings yet. Seed the plan and run the researcher.')+'</div>';

    m+='<div class=panels style="margin-top:14px"><div class=panel><h3>Per-class exhaustiveness</h3>'+
      (cc.length?'<div class=chips>'+cc.map(function(c){return '<span class=chip>'+h(c.vuln_class)+': '+h(c.state)+'</span>'}).join('')+'</div>'
        :'<div class=empty>No vuln-class checks recorded yet.</div>')+'</div>';
    m+='<div class=panel><h3>Next investigations (by priority)</h3>'+
      (inv.length?inv.slice(0,8).map(function(v){return '<div class=wl><div><b>'+h(v.title)+'</b><br><small class=mono>p'+v.priority+' &middot; '+h((v.target_files||[]).join(', '))+'</small></div></div>'}).join('')
        :'<div class=empty>No open investigations.</div>')+'</div></div>';
    m+='<details class="fp-section"><summary>False positives / duplicates ('+rejectedFindings.length+')</summary>'+
      findingsTable(rejectedFindings,'No rejected findings recorded.')+'</details>';
    m+='<details class="fp-section"><summary>Chainable / deferred findings ('+chainableFindings.length+')</summary>'+
      findingsTable(chainableFindings,'No chainable deferred findings recorded.')+'</details>';

    document.getElementById('main').innerHTML=m;
  });
}
function saveCtx(){pj('/context',{subject:S,info_md:document.getElementById('ctxbox').value}).then(function(){msg('saved');loadSubjects();})}
function genCtx(){if(!confirm('Launch an agent to write '+S+' context? (spends tokens)'))return;
  pj('/generate_context',{subject:S}).then(function(){msg('agent launched — refresh in ~1-2 min');})}
function resolveWish(id){pj('/wishlist_resolve',{id:id,status:'provided'}).then(refresh)}
function msg(t){var e=document.getElementById('ctxmsg');if(e){e.textContent=t;}}

document.getElementById('host').textContent=location.host;
function tick(){document.getElementById('clock').textContent=new Date().toLocaleTimeString();}
tick();setInterval(tick,1000);
loadSubjects().then(refresh);
setInterval(function(){loadSubjects().then(refresh)},6000);
</script>
</body></html>"""
