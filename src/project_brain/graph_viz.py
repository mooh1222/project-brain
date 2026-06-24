"""brain 객체 그래프를 vis-network 단일 HTML로 렌더한다 (graph export).

엣지는 정본 graph.edges(INBOUND_REF_FIELDS 기준)를 쓴다 — graph isolated와 같은
그래프를 보여줘, 왜 어떤 잎이 고립인지 화면에서 그대로 확인할 수 있다. vis-network는
CDN(unpkg)에서 받으므로 파이썬 의존성은 없고, 보려면 인터넷 연결이 필요하다.
"""
import json

from project_brain.graph import edges as graph_edges
from project_brain.store import BrainStore

# kind별 채움 색(노드 그룹).
KIND_COLORS = {
    "DomainContext": "#e74c3c",
    "DomainMapping": "#3498db",
    "GlossaryTerm": "#2ecc71",
    "DecisionRecord": "#9b59b6",
    "CodeLocator": "#f39c12",
    "EvidenceRef": "#95a5a6",
    "EvidenceManifest": "#7f8c8d",
    "ReviewRecord": "#1abc9c",
    "Insight": "#e91e63",
    "ContextProjection": "#34495e",
    "EventLedgerRecord": "#d35400",
}
DEFAULT_COLOR = "#bdc3c7"

# 노드 라벨 후보(앞에서부터 있는 것 사용).
LABEL_FIELDS = ["title", "term", "mapping_key", "symbol", "path"]
# 툴팁 본문 후보.
TIP_FIELDS = ["body", "summary", "definition", "meaning", "canonical_summary",
              "boundary_summary", "decision", "scope"]


def build_payload(store: BrainStore) -> dict:
    """store → vis-network payload {nodes, edges, details, kinds, groups}.

    엣지는 graph.edges(정본 INBOUND_REF_FIELDS)로 그린다. 노드 라벨·색·툴팁은
    표시용 휴리스틱이다."""
    objs = [o for o in store.all() if isinstance(o, dict) and o.get("id")]

    nodes, details, kinds = [], {}, {}
    for o in objs:
        oid = o["id"]
        kind = o.get("kind", "?")
        status = o.get("status", "")
        kinds[kind] = kinds.get(kind, 0) + 1

        label = next((str(o[f]) for f in LABEL_FIELDS if o.get(f)), oid.split(".")[-1])
        if len(label) > 30:
            label = label[:29] + "…"

        tip = [f"[{kind}] {status}".strip()]
        body = next((str(o[f]) for f in TIP_FIELDS if o.get(f)), "")
        if body:
            tip.append(body[:160] + ("…" if len(body) > 160 else ""))

        nodes.append({
            "id": oid,
            "label": label,
            "group": kind,
            "title": "\n".join(tip),
            "borderWidth": 3 if status == "reviewed" else 1,
            "shapeProperties": {"borderDashes": [5, 5] if status == "candidate" else False},
        })
        details[oid] = o

    edge_list = [{"from": f, "to": t} for f, t in graph_edges(store)]

    groups = {
        k: {"color": {"background": KIND_COLORS.get(k, DEFAULT_COLOR), "border": "#2c3e50"}}
        for k in kinds
    }
    return {"nodes": nodes, "edges": edge_list, "details": details,
            "kinds": kinds, "groups": groups}


def payload_to_html(payload: dict) -> str:
    """payload를 TEMPLATE에 주입해 단일 HTML 문자열로 만든다."""
    return TEMPLATE.replace("__DATA__", json.dumps(payload, ensure_ascii=False))


def render_html(store: BrainStore) -> str:
    """store를 단일 HTML로 렌더한다(build_payload → payload_to_html 편의 wrapper)."""
    return payload_to_html(build_payload(store))


TEMPLATE = r"""<!DOCTYPE html>
<html lang="ko">
<head>
<meta charset="utf-8">
<title>project-brain 객체 그래프</title>
<script src="https://unpkg.com/vis-network/standalone/umd/vis-network.min.js"></script>
<style>
  * { box-sizing: border-box; }
  body { margin: 0; font-family: -apple-system, "Apple SD Gothic Neo", sans-serif; }
  #top { padding: 8px 12px; background: #1f2937; color: #e5e7eb; font-size: 13px;
         display: flex; flex-wrap: wrap; gap: 10px; align-items: center; }
  #top input[type=text] { padding: 4px 8px; border-radius: 4px; border: 1px solid #4b5563;
         background: #111827; color: #e5e7eb; }
  #filters { display: flex; flex-wrap: wrap; gap: 8px; }
  #filters label { display: inline-flex; align-items: center; gap: 4px; cursor: pointer;
         background: #374151; padding: 2px 8px; border-radius: 12px; }
  #filters .sw { width: 11px; height: 11px; border-radius: 50%; display: inline-block; }
  #main { display: flex; height: calc(100vh - 42px); }
  #graph { flex: 1; background: #f9fafb; }
  #panel { width: 380px; overflow: auto; padding: 14px; border-left: 1px solid #e5e7eb;
           background: #fff; font-size: 13px; }
  #panel h3 { margin: 0 0 4px; font-size: 15px; }
  #panel .kind { color: #6b7280; margin-bottom: 10px; }
  #panel .row { margin: 6px 0; word-break: break-word; }
  #panel .row b { color: #2563eb; }
  #panel .hint { color: #9ca3af; }
  #count { color: #9ca3af; }
</style>
</head>
<body>
<div id="top">
  <strong>project-brain 그래프</strong>
  <span id="count"></span>
  <input type="text" id="search" placeholder="제목/id 검색 → Enter">
  <label style="display:inline-flex;align-items:center;gap:4px;cursor:pointer;background:#374151;padding:2px 8px;border-radius:12px;">
    <input type="checkbox" id="focusChk"> 선택 노드 이웃만
  </label>
  <div id="filters"></div>
</div>
<div id="main">
  <div id="graph"></div>
  <div id="panel"><p class="hint">노드를 클릭하면 객체 전체 내용이 여기 표시됩니다.</p></div>
</div>
<script>
const DATA = __DATA__;
function esc(s){return String(s).replace(/[&<>"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));}

const nodes = new vis.DataSet(DATA.nodes);
const edges = new vis.DataSet(DATA.edges);
document.getElementById('count').textContent =
  DATA.nodes.length + ' 노드 · ' + DATA.edges.length + ' 연결';

const network = new vis.Network(document.getElementById('graph'),
  {nodes, edges}, {
  groups: DATA.groups,
  nodes: {shape:'dot', size:12, font:{size:12, color:'#1f2937'}},
  edges: {arrows:{to:{enabled:true, scaleFactor:0.5}}, color:{color:'#d1d5db', highlight:'#2563eb'},
          smooth:{type:'continuous'}, width:0.5},
  physics: {solver:'barnesHut',
            barnesHut:{gravitationalConstant:-9000, springLength:130, springConstant:0.02},
            stabilization:{iterations:150, updateInterval:25}},
  interaction: {hover:true, tooltipDelay:120, navigationButtons:true, keyboard:false},
});
// 큰 그래프라 안정화 후 물리엔진을 꺼서 인터랙션을 가볍게 한다(드래그는 계속 가능).
network.once('stabilizationIterationsDone', () => network.setOptions({physics:false}));

// 가시성 = kind 필터(kindOff) + 이웃만 보기(focusSet). 한 함수로 합쳐 둘이 충돌하지 않게 한다.
const adj = {};
DATA.edges.forEach(e => {
  (adj[e.from] = adj[e.from] || new Set()).add(e.to);
  (adj[e.to] = adj[e.to] || new Set()).add(e.from);
});
let focusSet = null;            // null = 전체, Set = 이 집합만 표시
const kindOff = new Set();      // 꺼진 kind
function applyVisibility(){
  const upd = [];
  nodes.forEach(nd => {
    const hide = kindOff.has(nd.group) || (focusSet && !focusSet.has(nd.id));
    if (!!nd.hidden !== hide) upd.push({id: nd.id, hidden: hide});
  });
  if (upd.length) nodes.update(upd);
}

network.on('click', p => {
  if (p.nodes.length){
    const id = p.nodes[0];
    showDetail(id);
    if (document.getElementById('focusChk').checked){   // 이웃만 보기 ON → 선택+이웃만
      focusSet = new Set([id, ...(adj[id] || [])]);
      applyVisibility();
    }
  } else if (focusSet){                                  // 빈 곳 클릭 → 전체 복원
    focusSet = null;
    applyVisibility();
  }
});
document.getElementById('focusChk').addEventListener('change', e => {
  if (!e.target.checked){ focusSet = null; applyVisibility(); }  // 끄면 즉시 전체 복원
});

function showDetail(id){
  const o = DATA.details[id];
  if (!o) return;
  let h = '<h3>'+esc(o.title || id)+'</h3>';
  h += '<div class="kind">'+esc(o.kind||'')+' · '+esc(o.status||'')+'</div>';
  for (const [k,v] of Object.entries(o)){
    if (k === 'title') continue;
    const val = (v && typeof v === 'object') ? JSON.stringify(v, null, 1) : String(v);
    h += '<div class="row"><b>'+esc(k)+'</b>: '+esc(val)+'</div>';
  }
  document.getElementById('panel').innerHTML = h;
}

// kind 필터 체크박스
const fbox = document.getElementById('filters');
Object.entries(DATA.kinds).sort((a,b)=>b[1]-a[1]).forEach(([k,n])=>{
  const c = (DATA.groups[k]&&DATA.groups[k].color&&DATA.groups[k].color.background) || '#ccc';
  fbox.insertAdjacentHTML('beforeend',
    '<label><input type="checkbox" checked data-kind="'+esc(k)+'">'+
    '<span class="sw" style="background:'+c+'"></span>'+esc(k)+' ('+n+')</label>');
});
fbox.addEventListener('change', e=>{
  if (!e.target.dataset.kind) return;
  const kind = e.target.dataset.kind;
  if (e.target.checked) kindOff.delete(kind); else kindOff.add(kind);
  applyVisibility();
});

// 검색 → 일치 노드로 포커스
document.getElementById('search').addEventListener('keydown', e=>{
  if (e.key !== 'Enter') return;
  const q = e.target.value.trim().toLowerCase();
  if (!q) return;
  const hit = DATA.nodes.find(n =>
    n.id.toLowerCase().includes(q) || (n.label||'').toLowerCase().includes(q));
  if (hit){ network.focus(hit.id, {scale:1.2, animation:true}); network.selectNodes([hit.id]); showDetail(hit.id); }
});
</script>
</body>
</html>
"""
