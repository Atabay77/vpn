/* Türkmen VPN ekran motory: tasarym faýlyny (main.dc.html) okaýar, {{...}}, sc-if, sc-for, wakalar we ref goldaýar.
   Her täzelenmede DOM täzeden gurulmaýar — diňe üýtgän ýerleri çalyşýar (ýazyp otyrkaňyz klawiatura ýapylmaýar). */
(function () {
  'use strict';
  class DCLogic {
    constructor(p) { this.props = p || {}; }
    setState(o) { Object.assign(this.state, typeof o === 'function' ? o(this.state) : o); schedule(); }
    forceUpdate() { schedule(); }
  }
  window.DCLogic = DCLogic;

  const EV = { onclick: 'click', onchange: 'input', onpointerdown: 'pointerdown', onpointermove: 'pointermove', onpointerup: 'pointerup', onpointercancel: 'pointercancel', onpointerleave: 'pointerleave' };
  const HOLE = /\{\{\s*([\w.$]+)\s*\}\}/g;
  let uid = 0;

  function parts(str) {
    const out = []; let last = 0, m; HOLE.lastIndex = 0;
    while ((m = HOLE.exec(str))) { if (m.index > last) out.push(str.slice(last, m.index)); out.push({ p: m[1] }); last = m.index + m[0].length; }
    if (last < str.length) out.push(str.slice(last));
    return out;
  }
  function whole(str) { const m = /^\{\{\s*([\w.$]+)\s*\}\}$/.exec((str || '').trim()); return m ? m[1] : null; }

  /** Şablony bir gezek agaç görnüşine geçirýär. */
  function compile(node) {
    if (node.nodeType === 3) { const ps = parts(node.nodeValue); return ps.length ? { k: 't', id: ++uid, ps } : null; }
    if (node.nodeType !== 1) return null;
    const tag = node.localName;
    const kids = () => Array.from(node.childNodes).map(compile).filter(Boolean);
    if (tag === 'sc-if') return { k: 'if', p: whole(node.getAttribute('value')), kids: kids() };
    if (tag === 'sc-for') return { k: 'for', p: whole(node.getAttribute('list')), as: node.getAttribute('as'), kids: kids() };
    const d = { k: 'e', id: ++uid, tag, ns: node.namespaceURI, at: [], ev: [], ref: null, kids: [] };
    for (const a of Array.from(node.attributes)) {
      const n = a.name;
      if (n.indexOf('hint-') === 0) continue;
      if (EV[n]) { d.ev.push([EV[n], whole(a.value)]); continue; }
      if (n === 'ref') { d.ref = whole(a.value); continue; }
      const w = whole(a.value);
      d.at.push(w ? { n, w } : { n, ps: parts(a.value) });
    }
    if (tag !== 'canvas') d.kids = kids();
    return d;
  }

  function look(path, scope) {
    if (path === 'true') return true; if (path === 'false') return false;
    const ks = path.split('.'); let v;
    for (let i = scope.length - 1; i >= 0; i--) if (scope[i] && ks[0] in scope[i]) { v = scope[i][ks[0]]; break; }
    for (let j = 1; j < ks.length && v != null; j++) v = v[ks[j]];
    return v;
  }
  function str(ps, scope) { let s = ''; for (const p of ps) { if (typeof p === 'string') s += p; else { const v = look(p.p, scope); if (v != null) s += v; } } return s; }

  /** Şablon + maglumat → wirtual agaç (açarlary: şablon ýeri + sanaw belgisi). */
  function build(list, scope, path, out) {
    for (const d of list) {
      if (d.k === 'if') { if (d.p && look(d.p, scope)) build(d.kids, scope, path, out); continue; }
      if (d.k === 'for') {
        const arr = (d.p && look(d.p, scope)) || [];
        for (let i = 0; i < arr.length; i++) build(d.kids, scope.concat([{ [d.as]: arr[i], $index: i }]), path + '.' + i, out);
        continue;
      }
      if (d.k === 't') { out.push({ t: 1, key: d.id + path, s: str(d.ps, scope) }); continue; }
      const at = {};
      for (const a of d.at) { const v = a.w ? look(a.w, scope) : str(a.ps, scope); at[a.n] = v == null ? '' : String(v); }
      const ev = {};
      for (const e of d.ev) { const f = e[1] && look(e[1], scope); if (typeof f === 'function') ev[e[0]] = f; }
      const ref = d.ref ? look(d.ref, scope) : null;
      const kids = [];
      if (d.kids.length) build(d.kids, scope, path, kids);
      out.push({ t: 0, key: d.id + path, d, at, ev, ref, kids });
    }
    return out;
  }

  const refs = [];
  function create(v) {
    if (v.t) { const n = document.createTextNode(v.s); n.__k = v.key; return n; }
    const n = document.createElementNS(v.d.ns || 'http://www.w3.org/1999/xhtml', v.d.tag);
    n.__k = v.key; n.__tag = v.d.tag; n.__a = {}; n.__h = {};
    for (const e of v.d.ev) n.addEventListener(e[0], (ev) => { const f = n.__h[e[0]]; if (f) f(ev); });
    if (v.ref) refs.push([v.ref, n]);
    return n;
  }
  function update(n, v) {
    if (v.t) { if (n.nodeValue !== v.s) n.nodeValue = v.s; return; }
    const old = n.__a, tag = v.d.tag;
    for (const k in v.at) {
      const val = v.at[k];
      if (k === 'value' && (tag === 'input' || tag === 'textarea')) { if (n.value !== val) n.value = val; continue; }
      if (old[k] !== val) n.setAttribute(k, val);
    }
    for (const k in old) if (!(k in v.at)) n.removeAttribute(k);
    n.__a = v.at; n.__h = v.ev;
    if (tag !== 'canvas') patch(n, v.kids);
  }
  function patch(parent, kids) {
    const byKey = new Map();
    for (let c = parent.firstChild; c; c = c.nextSibling) if (c.__k) byKey.set(c.__k, c);
    let ref = parent.firstChild;
    for (const v of kids) {
      let n = byKey.get(v.key);
      if (n && (v.t ? n.nodeType !== 3 : n.__tag !== v.d.tag)) n = null;
      if (n) byKey.delete(v.key); else n = create(v);
      if (n === ref) ref = ref.nextSibling; else parent.insertBefore(n, ref);
      update(n, v);
    }
    while (ref) { const nx = ref.nextSibling; parent.removeChild(ref); ref = nx; }
  }

  let C = null, tree = null, root = null, queued = false;
  const after = [];
  function render() {
    queued = false;
    if (!C) return;
    const rv = C.renderVals();
    patch(root, build(tree, [rv], '', []));
    while (refs.length) { const r = refs.shift(); try { r[0](r[1]); } catch (e) { console.error(e); } }
    for (const f of after) { try { f(); } catch (e) { console.error(e); } }
  }
  function schedule() { if (!queued) { queued = true; requestAnimationFrame(render); } }

  /** Tasarym faýlyny ýükläp işledýär. */
  async function boot(file, mount) {
    const t = await (await fetch(file)).text();
    const helmet = (/<helmet>([\s\S]*?)<\/helmet>/.exec(t) || [, ''])[1];
    document.head.insertAdjacentHTML('beforeend', helmet);
    const tpl = /<x-dc>([\s\S]*?)<\/x-dc>/.exec(t)[1].replace(/<helmet>[\s\S]*?<\/helmet>/, '');
    const js = /data-dc-script[^>]*>([\s\S]*?)<\/script>/.exec(t)[1];
    const doc = new DOMParser().parseFromString('<!doctype html><body>' + tpl + '</body>', 'text/html');
    tree = Array.from(doc.body.childNodes).map(compile).filter(Boolean);
    root = mount;
    const Comp = (0, eval)(js + '\n;Component');
    if (window.DC_BEFORE) window.DC_BEFORE(Comp);
    C = new Comp({}); window.C = C;
    if (window.DC_READY) window.DC_READY(C);
    render();
    if (C.componentDidMount) C.componentDidMount();
    return C;
  }
  window.DC = { boot, render, schedule, after };
})();
