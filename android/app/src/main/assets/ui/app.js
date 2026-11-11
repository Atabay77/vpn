/* Tasarym bilen hakyky programmanyň arasyndaky köpri.
   Tasarymyň görkeziş maglumatlary (ýasama serwerler, tizlik, habarlar) şu ýerde hakykylary bilen çalşylýar.
   NB = Kotlin köprüsi (Main.kt → Bridge). */
(function () {
  'use strict';
  const NB = window.NB;
  const J = (s, d) => { try { return JSON.parse(s); } catch (e) { return d; } };
  const LS = {
    get(k, d) { try { const v = localStorage.getItem('tv.' + k); return v == null ? d : JSON.parse(v); } catch (e) { return d; } },
    set(k, v) { try { localStorage.setItem('tv.' + k, JSON.stringify(v)); } catch (e) {} }
  };
  const DAY = 86400000;
  const dayKey = (t) => { const x = new Date(t); return x.getFullYear() + '-' + (x.getMonth() + 1) + '-' + x.getDate(); };
  const two = (n) => (n < 10 ? '0' : '') + n;

  // ýurtlar: baýdak → ýer (Dünýä üçin) we üç dilde at
  const CO = {
    NL: [52.37, 4.9, 'Niderlandlar', 'Нидерланды', 'Hollanda'], FI: [60.17, 24.94, 'Finlýandiýa', 'Финляндия', 'Finlandiya'], GB: [51.51, -0.13, 'Beýik Britaniýa', 'Великобритания', 'Birleşik Krallık'],
    DE: [52.52, 13.4, 'Germaniýa', 'Германия', 'Almanya'], CH: [46.95, 7.45, 'Şweýsariýa', 'Швейцария', 'İsviçre'], PL: [52.23, 21.01, 'Polşa', 'Польша', 'Polonya'],
    TR: [39.93, 32.86, 'Türkiýe', 'Турция', 'Türkiye'], FR: [48.86, 2.35, 'Fransiýa', 'Франция', 'Fransa'], RU: [55.75, 37.62, 'Russiýa', 'Россия', 'Rusya'],
    SE: [59.33, 18.07, 'Şwesiýa', 'Швеция', 'İsveç'], US: [40.71, -74.0, 'ABŞ', 'США', 'ABD'], AT: [48.21, 16.37, 'Awstriýa', 'Австрия', 'Avusturya'],
    IT: [41.9, 12.5, 'Italiýa', 'Италия', 'İtalya'], ES: [40.42, -3.7, 'Ispaniýa', 'Испания', 'İspanya'], LV: [56.95, 24.1, 'Latwiýa', 'Латвия', 'Letonya'],
    LT: [54.69, 25.28, 'Litwa', 'Литва', 'Litvanya'], EE: [59.44, 24.75, 'Estoniýa', 'Эстония', 'Estonya'], RO: [44.43, 26.1, 'Rumyniýa', 'Румыния', 'Romanya'],
    BG: [42.7, 23.32, 'Bolgariýa', 'Болгария', 'Bulgaristan'], CZ: [50.08, 14.44, 'Çehiýa', 'Чехия', 'Çekya'], HU: [47.5, 19.04, 'Wengriýa', 'Венгрия', 'Macaristan'],
    UA: [50.45, 30.52, 'Ukraina', 'Украина', 'Ukrayna'], KZ: [43.24, 76.89, 'Gazagystan', 'Казахстан', 'Kazakistan'], AE: [25.2, 55.27, 'BAE', 'ОАЭ', 'BAE'],
    SG: [1.35, 103.82, 'Singapur', 'Сингапур', 'Singapur'], JP: [35.68, 139.69, 'Ýaponiýa', 'Япония', 'Japonya'], HK: [22.32, 114.17, 'Gonkong', 'Гонконг', 'Hong Kong'],
    CA: [43.65, -79.38, 'Kanada', 'Канада', 'Kanada'], IR: [35.69, 51.39, 'Eýran', 'Иран', 'İran'], MD: [47.01, 28.86, 'Moldowa', 'Молдова', 'Moldova'],
    RS: [44.79, 20.45, 'Serbiýa', 'Сербия', 'Sırbistan'], NO: [59.91, 10.75, 'Norwegiýa', 'Норвегия', 'Norveç'], DK: [55.68, 12.57, 'Daniýa', 'Дания', 'Danimarka'],
    BE: [50.85, 4.35, 'Belgiýa', 'Бельгия', 'Belçika'], IE: [53.35, -6.26, 'Irlandiýa', 'Ирландия', 'İrlanda'], GE: [41.72, 44.79, 'Gruziýa', 'Грузия', 'Gürcistan'],
    AM: [40.18, 44.51, 'Ermenistan', 'Армения', 'Ermenistan'], AZ: [40.41, 49.87, 'Azerbaýjan', 'Азербайджан', 'Azerbaycan'], IN: [28.61, 77.21, 'Hindistan', 'Индия', 'Hindistan']
  };
  const cc = (flag) => { const c = Array.from(flag || '').map((x) => x.codePointAt(0)).filter((x) => x >= 0x1F1E6 && x <= 0x1F1FF); return c.length >= 2 ? String.fromCharCode(c[0] - 0x1F1E6 + 65, c[1] - 0x1F1E6 + 65) : ''; };
  const COLORS = ['#6FA8DC', '#E3A372', '#6FDB9C', '#C9A0DC', '#E0B04A', '#F3E7D0', '#F7BFB3', '#A6EBC4', '#B4D3F2'];
  const colorOf = (id) => { let h = 0; for (const ch of String(id)) h = (h * 31 + ch.charCodeAt(0)) >>> 0; return COLORS[h % COLORS.length]; };
  const ini = (n) => (String(n).match(/[A-Z]/g) || [String(n).charAt(0) || '?']).slice(0, 2).join('');

  let INFO = J(NB.info(), {});
  let SV = [];          // serwerler (tasarym görnüşinde)
  let G = [];           // Global chat habarlary
  let gDel = {};
  let lastSt = 'off', lastOn = 0, lastRx = 0, sessKB = 0;
  let PH = LS.get('ph', {});   // başgalaryň profil suratlary: telefon → {d, at}
  const phAsked = {};

  function loadServers() {
    const r = J(NB.servers(), { list: [], pings: {} });
    SV = r.list.map((s) => {
      const c = CO[cc(s.flag)];
      return { id: s.key, f: s.flag, n: c ? { tk: c[2], ru: c[3], tr: c[4] } : { tk: s.country, ru: s.country, tr: s.country }, t: s.title || s.country, p: s.proto, lat: c ? c[0] : 50, lon: c ? c[1] : 10, game: s.game };
    });
    return r.pings;
  }

  window.DC_BEFORE = function (Comp) {
    const P = Comp.prototype;
    P.srvs = function () {
      return SV.length ? SV : [{ id: '', f: '🌐', n: { tk: 'Serwer ýok', ru: 'Нет серверов', tr: 'Sunucu yok' }, t: '—', p: '', lat: 39.2, lon: 59.6 }];
    };
    P.connect = function () { const n = J(NB.state(), {}); if (n.st !== 'on' && n.st !== 'wait') NB.connect(); };   // bagly wagty serwer çalşylanda NB.select özi täzeden birikýär
    P.runTest = function () { NB.test(); this.setState({ testing: true }); };
    P.gSeed = function () { return []; };
    P.gPool = function () { return []; };
    P.aiAnswer = function () { return ''; };
    P.shareText = function () { return this.T()[this.state.lang].r_msg.replace('{c}', INFO.code || ''); };

    /** Admine ýaz: habar bota gidýär (AI derrew, admin Telegramda jogap berýär). */
    P.sendMsg = function (text) {
      text = String(text || '').trim().slice(0, 1000); if (!text) return;
      const s = this.state, id = Date.now(), tx = this.T()[s.lang];
      this.setState({ chat: s.chat.concat([{ id, who: 'u', t: text, time: this.hm(id), tick: '✓' }]), chatIn: '', fb: '',
        myTkSt: s.myTkSt === 'closed' || !s.myTkSt ? 'open' : s.myTkSt, aiTyping: !!INFO.ai && !s.human });
      NB.send(JSON.stringify({ k: 'tk', t: text, nick: this.meName, tid: s.tkId || 0 }));
      if (s.st !== 'on') this.say(tx.q_wait);
      clearTimeout(this.aiT); this.aiT = setTimeout(() => this.setState({ aiTyping: false }), 90000);
    };

    const rv0 = P.renderVals;
    P.renderVals = function () {
      const r = rv0.call(this), s = this.state, tx = r.tx, on = s.st === 'on', now = Date.now();
      if (INFO.ver) ['s_updS', 'i_ver'].forEach((k) => { tx[k] = String(tx[k]).replace(/1\.\d+(\.\d+)?/, INFO.ver); });
      const kexp = s.kexp; // -1 ýok, 0 çäksiz, >0 möhlet (sn)
      const keyLeft = kexp > 0 ? Math.max(0, kexp - now / 1000) : 0;
      const fmtLeft = (sec) => { const hh = Math.floor(sec / 3600), mm = Math.floor(sec % 3600 / 60); return hh >= 24 ? Math.floor(hh / 24) + ' ' + tx.days + ' ' + (hh % 24) + ' ' + tx.hh : hh + ' ' + tx.hh + ' ' + two(mm) + ' ' + tx.mm; };
      const keyTxt = s.hasKey ? (kexp === 0 ? '♾' : fmtLeft(keyLeft)) : '—';
      // wagt / açar
      r.timerLbl = s.hasKey ? tx.keyL : tx.left;
      r.timer = s.hasKey ? keyTxt : two(Math.floor(s.left / 3600)) + ':' + two(Math.floor(s.left % 3600 / 60)) + ':' + two(s.left % 60);
      r.showUl = on && !s.hasKey;
      r.showWarn = s.hasKey && kexp > 0 && keyLeft <= 43200 && !s.warnHidden;
      r.warnText = tx.w_text.replace('{t}', fmtLeft(keyLeft));
      r.keyCur = !s.hasKey ? tx.k_none : kexp === 0 ? tx.k_unl : tx.k_daysL.replace('{n}', String(Math.ceil(keyLeft / 86400)));
      if (s.keyMsg === 'ok') r.keyMsg = '✓ ' + (kexp === 0 ? tx.k_okU : tx.k_okN.replace('{n}', String(Math.ceil(keyLeft / 86400))));
      if (s.keyMsg === 'wait') { r.keyMsg = tx.k_wait; r.keyMsgCls = 'ok'; }
      r.refLeftText = keyTxt;
      // tizlik
      r.totalText = on ? '↓ ' + szKB(s.tot) + '  ↑ ' + szKB(s.totUp) : '—';
      // çagyryş
      r.myCode = INFO.code || '—'; r.invites = String(s.invites || 0);
      if (s.refMsg === 'wait') { r.refMsg = tx.r_wait; r.refMsgCls = 'ok'; }
      if (s.refSet) r.refMsg = '✓ ' + tx.r_okMsg.replace('{c}', s.refSet);
      // ulanyş grafigi (hakyky)
      const U = s.usage || {}, mbd = (t) => (U[dayKey(t)] || 0) / 1024;
      const daysV = [6, 5, 4, 3, 2, 1, 0].map((i) => mbd(now - i * DAY));
      const wk = [3, 2, 1, 0].map((w) => [0, 1, 2, 3, 4, 5, 6].reduce((a, i) => a + mbd(now - (w * 7 + i) * DAY), 0));
      const vals = s.uMode === 'd' ? daysV : wk, mx = Math.max(1, ...vals), mb = (v) => (v >= 1024 ? (v / 1024).toFixed(2) + ' GB' : Math.round(v) + ' MB');
      r.bars = r.bars.map((b, i) => Object.assign({}, b, { v: i === s.uSel ? mb(vals[i] || 0) : '', h: Math.max(4, Math.round((vals[i] || 0) / mx * 100)), aria: b.l + ': ' + mb(vals[i] || 0) }));
      const weekSum = daysV.reduce((a, b) => a + b, 0);
      r.uToday = mb(daysV[6]); r.uWeekT = mb(weekSum); r.uAvg = mb(weekSum / 7);
      // taryh (hakyky)
      const H = s.hist2 || [], hfmt = (sec) => { const hh = Math.floor(sec / 3600), mm = Math.floor(sec % 3600 / 60); return hh ? hh + ' ' + tx.hh + ' ' + two(mm) + ' ' + tx.mm : mm + ' ' + tx.mm; };
      const dlabel = (t) => { const k = dayKey(t), x = new Date(t), hm = two(x.getHours()) + ':' + two(x.getMinutes()); return (k === dayKey(now) ? tx.hi_today : k === dayKey(now - DAY) ? tx.hi_yday : x.getDate() + '.' + (x.getMonth() + 1)) + ' ' + hm; };
      r.hiSess = String(H.length); r.hiTime = hfmt(H.reduce((a, h) => a + h.dur, 0)); r.hiData = szKB(H.reduce((a, h) => a + h.kb, 0));
      r.histRows = H.slice(0, 30).map((h, i) => ({ date: dlabel(h.at), f: h.f, name: h.n, dur: hfmt(h.dur), mb: szKB(h.kb), d: (i * 0.04).toFixed(2) }));
      r.liveDur = on && s.onAt ? hfmt((now - s.onAt) / 1000) : '—'; r.liveData = szKB(s.tot + s.totUp);
      // profil
      const first = LS.get('first', now);
      r.pfStats = [[tx.pf_since, new Date(first).toLocaleDateString('ru-RU'), '#F3E7D0'], [tx.pf_time, hfmt(H.reduce((a, h) => a + h.dur, 0)), '#FFD27A'],
        [tx.pf_inv, String(s.invites || 0), '#6FDB9C'], [tx.pf_key, keyTxt, '#FFD27A']].map((q) => ({ k: q[0], v: q[1], c: q[2] }));
      // bilet belgisi
      const tn = s.tkId ? '#' + s.tkId : '#…';
      r.myTkT = r.myTk ? tn + ' · ' + r.myTkT.replace(/^#\d+ · /, '') : '';
      r.myTkNo = tx.ad_ticket + ' ' + tn;
      r.news = r.news.map((n) => (n.isTk ? Object.assign({}, n, { title: tx.n_tkT.replace('{n}', s.tkId || '…') }) : n));
      if (r.banTitle && /#1045/.test(r.banTitle)) r.banTitle = tx.n_tkT.replace('{n}', s.tkId || '…');
      r.cStatus = INFO.ai ? tx.c_aiStatus : tx.c_status; r.cNote = INFO.ai ? tx.c_aiNote : tx.c_note;
      // Global chat (hakyky)
      const bans = INFO.bans || [], me = INFO.dev;
      const gl = G.filter((m) => !gDel[m.id] && bans.indexOf(m.i) < 0);
      r.gMsgs = gl.map((m) => {
        const mine = m.i === me, nm = mine ? this.meName : m.n || '?';
        const ph = mine ? s.photo : ((PH[m.i] || {}).d || '');
        return { name: nm + (mine ? ' · ' + tx.g_you : ''), ini: ini(nm), bg: mine ? '#E0B04A' : colorOf(m.i), nc: mine ? '#06100B' : colorOf(m.i), photo: ph, hasPh: !!ph, noPh: !ph,
          t: m.t, time: this.hm((m.time || 0) * 1000 || now), gk: m.id, cls: mine ? 'gm-me' : 'gm-o', bcls: mine ? 'gb-me' : 'gb-o', canDel: false, del: null };
      });
      const onl = INFO.online > 0 ? tx.g_online.replace('{n}', String(INFO.online)) : '';
      r.gOnline = onl; r.gHead = tx.p_global.toUpperCase() + (onl ? ' · ' + onl : '');
      r.ticker = gl.length ? gl.slice(-2).map((m) => ({ n: m.i === me ? this.meName : m.n, c: m.i === me ? '#E0B04A' : colorOf(m.i), t: m.t })) : [{ n: '🌐', c: '#6FDB9C', t: tx.g_empty }];
      // sazlamalar
      r.opts = r.opts.map((o) => {
        if (o.t === tx.s_snd) return Object.assign({}, o, { on: () => { const v = !this.state.snd; NB.snd(v); this.setState({ snd: v }); } });
        if (o.t === tx.s_ref) return Object.assign({}, o, { on: () => { if (this.state.refreshing) return; this.setState({ refreshing: true }); NB.refresh(); } });
        if (o.t === tx.s_upd) return Object.assign({}, o, { s: s.upd ? tx.s_updN.replace('{v}', s.upd) : tx.s_updS, on: () => NB.update() });
        if (o.t === tx.s_tile) return Object.assign({}, o, { on: () => NB.tile() });
        if (o.t === tx.s_key) return Object.assign({}, o, { s: s.hasKey ? r.keyCur : tx.s_keyS });
        return o;
      });
      const ic = this.icons();
      r.opts = r.opts.concat([{ i1: ic.global[0], i2: ic.global[1], t: tx.s_diag, s: s.diag ? tx[s.diag] : tx.s_diagS, isSw: false, isBtn: true, arrow: 'M9 6l6 6-6 6', icCls: '', isSeg: false, segs: [], aria: 'false', swCls: '', d: '0.35',
        on: () => { this.setState({ diag: 'dg_wait' }); NB.diag(); } }]);
      // menýu: admin bölümi 1.15-de
      r.menuItems = r.menuItems.filter((m) => m.t !== tx.p_admin).map((m) => (m.t === tx.p_global ? Object.assign({}, m, { badge: INFO.online > 0, bt: '● ' + INFO.online }) : m));
      return r;
    };
  };

  function szKB(k) { return k >= 1048576 ? (k / 1048576).toFixed(2) + ' GB' : k >= 1024 ? (k / 1024).toFixed(1) + ' MB' : Math.round(k) + ' KB'; }

  window.DC_READY = function (C) {
    const now = Date.now();
    if (!LS.get('first')) LS.set('first', now);
    // ýatda saklanýanlar
    const keep = ['bgMode', 'favs', 'read', 'chat', 'tkId', 'myTkSt', 'fb', 'human', 'photo', 'rateCount', 'rateNext', 'tkNews', 'svTab', 'uMode', 'refSet', 'invites', 'warnHidden', 'usage', 'hist2', 'seenNews'];
    const st = {};
    keep.forEach((k) => { const v = LS.get(k); if (v !== undefined && v !== null) st[k] = v; });
    if (st.rateNext == null) st.rateNext = LS.get('first') + DAY;   // «Baha ber» 1 gün soň
    C.meName = LS.get('nick') || C.meName; LS.set('nick', C.meName);
    Object.assign(C.state, { lang: INFO.lang || 'tk', snd: INFO.snd !== false, refLeft: 0, giftKey: false, invites: 0, streak: 0, claimed: false, pings: {}, testing: false, kexp: -1, totUp: 0, onAt: 0, usage: {}, hist2: [], seenNews: [], tkNews: [], human: false, tkId: 0 }, st);
    gift(C, false);
    // tasarymyň görkeziş funksiýalary hakykysy bilen
    C.toggle = () => NB.toggle();
    C.checkKey = () => { const k = C.state.keyIn; if (k.replace(/-/g, '').length !== 12) { C.setState({ keyMsg: 'bad' }); return; } C.setState({ keyMsg: 'wait' }); NB.key(k); };
    C.copyCode = () => { NB.copy(INFO.code || ''); C.say('✓ ' + C.T()[C.state.lang].r_copied); };
    C.share = () => NB.share(C.shareText());
    C.copyMsg = () => { NB.copy(C.shareText()); C.setState({ sharing: false }); };
    C.submitRef = () => {
      const c = C.state.refIn;
      if (c === INFO.code) { C.setState({ refMsg: 'own' }); return; }
      if (!/^TM-[A-Z0-9]{5}$/.test(c)) { C.setState({ refMsg: 'bad' }); return; }
      C.setState({ refMsg: 'wait' }); NB.send(JSON.stringify({ k: 'ref', c }));
    };
    C.claim = () => gift(C, true);
    C.reroll = ((f) => () => { f(); LS.set('nick', C.meName); })(C.reroll);
    C.fbUp = () => { C.setState({ fb: 'up' }); NB.send(JSON.stringify({ k: 'fb', v: 'up', tid: C.state.tkId })); };
    C.fbDown = () => { C.setState({ fb: 'down' }); NB.send(JSON.stringify({ k: 'fb', v: 'down', tid: C.state.tkId })); };
    C.sendG = () => {
      const t = C.state.gIn.trim().slice(0, 600); if (!t) return;
      NB.gsend(C.meName, t); C.setState({ gIn: '' });
      if (C.state.st !== 'on') C.say(C.T()[C.state.lang].q_wait);
    };
    const sr0 = C.sendRate;
    C.sendRate = () => {
      const s = C.state; if (!s.stars || s.rateCount >= 3) return sr0();
      const tx = C.T()[s.lang], tg = [tx.r_t1, tx.r_t2, tx.r_t3, tx.r_t4, tx.r_t5].filter((_, i) => s.tags[i]);
      NB.send(JSON.stringify({ k: 'rate', n: s.stars, tags: tg, c: s.comment.slice(0, 500), nick: C.meName }));
      sr0();
    };
    C.titleTap = () => {};       // admin bölümi 1.15-de
    C.toHuman = () => { C.setState({ human: true }); NB.send(JSON.stringify({ k: 'human', tid: C.state.tkId })); };
    // bot telefony tanasyn (çagyryş kody işlesin): günde bir gezek
    if (LS.get('hiDay') !== dayKey(Date.now())) { LS.set('hiDay', dayKey(Date.now())); NB.send(JSON.stringify({ k: 'hi', nick: C.meName })); }
    poll(C, true);
    setInterval(() => poll(C, false), 1000);
    setInterval(() => { const evs = J(NB.take(), []); if (!evs.length) return; const up = {}; for (const e of evs) handle(C, e, up); C.setState(up); }, 350);
  };

  /** Günlük sowgat: her gün bir gezek; 7-nji gün bot 2 günlük açar berýär. */
  function gift(C, doClaim) {
    const g = LS.get('gift', { last: '', streak: 0 }), today = dayKey(Date.now()), yday = dayKey(Date.now() - DAY);
    let streak = g.last === today || g.last === yday ? g.streak : 0;
    if (streak >= 7 && g.last !== today) streak = 0;
    if (!doClaim) { C.state.streak = streak; C.state.claimed = g.last === today; return; }
    if (g.last === today) return;
    streak += 1; LS.set('gift', { last: today, streak });
    const tx = C.T()[C.state.lang];
    C.setState({ streak, claimed: true });
    if (streak >= 7) { NB.send(JSON.stringify({ k: 'gift' })); C.say('🎁 ' + tx.q_wait); }
    else C.say('🎁 ' + tx.g_ok.replace('{n}', String(7 - streak)));
  }

  let saveAt = 0, lastPick = null, lastLang = null, lastPage = null;
  function poll(C, first) {
    const s = C.state, now = Date.now(), up = {};
    const n = J(NB.state(), null);
    if (n) {
      const st = n.st === 'fail' ? 'off' : n.st;
      if (first) { const p = loadServers(); up.pings = p; }
      const idx = (k) => (k ? SV.findIndex((v) => v.id === k) : -1);
      up.st = st; up.ms = n.ms > 0 ? n.ms : 0; up.testing = n.testing;
      up.si = Math.max(0, idx(n.act) >= 0 ? idx(n.act) : (idx(n.sel) >= 0 ? idx(n.sel) : 0));
      if (lastPick === null || lastPick === s.pick) { up.pick = idx(n.sel); lastPick = up.pick; }
      up.hasKey = n.left < 0; up.left = n.left >= 0 ? n.left : 0; up.kexp = n.kexp; up.upd = n.upd;
      up.dn = n.dn / 1024; up.up = n.up / 1024; up.tot = n.rxT / 1024; up.totUp = n.txT / 1024; up.onAt = n.onAt;
      if (st === 'on') {
        up.hist = s.hist.concat([up.dn]).slice(-40);
        const kb = (n.rxT + n.txT) / 1024, d = Math.max(0, kb - lastRx); lastRx = kb; sessKB = kb;
        if (d > 0) { const U = Object.assign({}, s.usage), k = dayKey(now); U[k] = (U[k] || 0) + d; up.usage = U; }
        if (lastSt !== 'on') lastOn = n.onAt || now;
      } else up.hist = [];
      if (lastSt === 'on' && st !== 'on' && lastOn) {
        const sv = SV[s.si] || {}, rec = { at: lastOn, f: sv.f || '🌐', n: (sv.n || {})[s.lang] || '', dur: Math.round((now - lastOn) / 1000), kb: Math.round(sessKB) };
        if (rec.dur > 5) up.hist2 = [rec].concat(s.hist2 || []).slice(0, 60);
        lastRx = 0; sessKB = 0; lastOn = 0;
      }
      lastSt = st;
    }
    const evs = J(NB.take(), []);
    for (const e of evs) handle(C, e, up);
    if (Object.keys(up).length) C.setState(up);
    // UI → Kotlin
    const s2 = C.state;
    if (lastPick !== null && s2.pick !== lastPick) { lastPick = s2.pick; const v = SV[s2.pick]; NB.select(v ? v.id : ''); }
    if (lastLang !== s2.lang) { if (lastLang !== null) { NB.lang(s2.lang); INFO = J(NB.info(), INFO); } lastLang = s2.lang; }
    if (lastPage !== s2.page) { NB.gwatch(s2.page === 'global'); lastPage = s2.page; }
    if (INFO.relay) syncPhoto(C);
    if (now - saveAt > 2000) {
      saveAt = now;
      ['bgMode', 'favs', 'read', 'chat', 'tkId', 'myTkSt', 'fb', 'human', 'photo', 'rateCount', 'rateNext', 'tkNews', 'svTab', 'uMode', 'refSet', 'invites', 'warnHidden', 'usage', 'hist2', 'seenNews']
        .forEach((k) => LS.set(k, s2[k]));
    }
    if (dayKey(now) !== C._day) { C._day = dayKey(now); gift(C, false); }
  }

  /** Global chat-da görünýän adamlaryň suratlary (6 sagatda bir täzelenýär). */
  function askPhotos() {
    const now = Date.now(); let n = 0;
    for (const m of G) {
      if (m.i === INFO.dev || phAsked[m.i] || n >= 6) continue;
      const c = PH[m.i]; if (c && now - c.at < 6 * 3600000) continue;
      phAsked[m.i] = 1; n++; NB.getPhoto(m.i);
    }
  }

  /** Öz suratyň: kiçeldip serwere (hemmeler görsün). */
  let sentPh = null, phWait = 0;
  function syncPhoto(C) {
    const d = C.state.photo || '';
    if (sentPh === null) { sentPh = LS.get('phSent', ''); }
    if (d === sentPh || Date.now() < phWait) return;
    sentPh = d; LS.set('phSent', d);
    if (!d) { NB.photo(''); return; }
    const img = new Image();
    img.onload = () => {
      const z = 128, k = Math.max(z / img.width, z / img.height), cv = document.createElement('canvas'); cv.width = z; cv.height = z;
      cv.getContext('2d').drawImage(img, (z - img.width * k) / 2, (z - img.height * k) / 2, img.width * k, img.height * k);
      NB.photo(cv.toDataURL('image/jpeg', 0.8));
    };
    img.src = d;
  }

  function news(C, up) {
    INFO = J(NB.info(), INFO);
    const list = (INFO.news || []).map((n) => { const j = J(n.j, {}); return { id: n.id, t: j.t || '', x: j.x || '', time: new Date(n.ts * 1000).toLocaleDateString('ru-RU') }; })
      .sort((a, b) => (a.id < b.id ? 1 : -1));
    up.bcast = list;
    const seen = C.state.seenNews || [], fresh = list.filter((n) => seen.indexOf(n.id) < 0);
    if (fresh.length) { up.newsBan = true; up.banHidden = false; up.seenNews = seen.concat(fresh.map((n) => n.id)).slice(-50); }
  }

  function handle(C, e, up) {
    const s = C.state, tx = C.T()[s.lang], t = Date.now();
    if (e.k === 'srv') {
      up.pings = loadServers(); news(C, up);
      if (e.manual) { up.refreshing = false; C.say((e.ok ? '✅ ' : '⚠️ ') + (e.ok ? tx.t_ref : tx.s_refS)); }
    } else if (e.k === 'key') {
      up.keyMsg = e.r; up.keyOk = e.r === 'ok';
    } else if (e.k === 'go') {
      up.page = e.page; up.menu = false; if (e.page === 'chat') up.unreadReply = 0;
    } else if (e.k === 'ad') {
      showAd(e.link);
    } else if (e.k === 'gfail') {
      C.say(tx.g_fail);
    } else if (e.k === 'phfail') {
      C.say(tx.ph_fail); sentPh = '\u0000'; phWait = Date.now() + 60000;
    } else if (e.k === 'ph') {
      PH[e.dev] = { d: /^data:image\/(jpeg|png);base64,/.test(e.d || '') ? e.d : '', at: Date.now() };
      const ks = Object.keys(PH); if (ks.length > 80) ks.sort((a, b) => PH[a].at - PH[b].at).slice(0, ks.length - 80).forEach((k) => delete PH[k]);
      LS.set('ph', PH); up.gTick = (s.gTick || 0) + 1;
    } else if (e.k === 'diag') {
      const r = e.r || {}; up.diag = r.tun === 200 ? 'dg_tun' : r.direct === 200 ? 'dg_dir' : 'dg_bad';
    } else if (e.k === 'g') {
      G = (e.list || []).sort((a, b) => a.time - b.time).slice(-150);
      askPhotos();
      (e.del || []).forEach((id) => { gDel[id] = true; });
      INFO = J(NB.info(), INFO);
      up.gTick = (s.gTick || 0) + 1;
    } else if (e.k === 'in') {
      const m = e.m || {}, chat = (up.chat || s.chat).map((x) => (x.who === 'u' ? Object.assign({}, x, { tick: '✓✓' }) : x));
      if (m.k === 'tko') {
        up.tkId = m.tid; up.chat = chat.concat([{ id: t, who: 's', t: tx.c_opened.replace('{n}', String(m.tid)), time: C.hm(t), tick: '' }]);
      } else if (m.k === 'tk') {
        up.chat = chat.concat([{ id: t + Math.random(), who: m.who === 'ai' ? 'ai' : 'a', t: m.t, time: C.hm(t), tick: '' }]);
        if (m.tid) up.tkId = m.tid;
        up.aiTyping = false;
        if (m.who !== 'ai') {
          up.myTkSt = 'ans'; if (s.page !== 'chat') up.unreadReply = (s.unreadReply || 0) + 1;
          up.tkNews = [{ id: t, x: m.t, time: C.hm(t) }].concat(up.tkNews || s.tkNews || []).slice(0, 20);
          up.newsBan = true; up.banHidden = false;
        }
      } else if (m.k === 'tkst') {
        up.myTkSt = m.st; if (m.st === 'closed') { up.human = false; up.chat = chat.concat([{ id: t, who: 's', t: '🔒 #' + (m.tid || s.tkId), time: C.hm(t), tick: '' }]); }
      } else if (m.k === 'key') {
        if (m.invites != null) up.invites = m.invites;
        C.party(m.why === 'gift' ? tx.gift_got : m.why === 'ref' ? tx.ref_got.replace('{d}', String(m.days || 1)) : tx.k_ext);
      } else if (m.k === 'refok') { up.refSet = m.c || s.refIn; up.refMsg = 'ok'; }
      else if (m.k === 'refbad') up.refMsg = m.why === 'own' ? 'own' : 'bad';
      else if (m.k === 'kbad') { up.keyMsg = 'used'; }
    }
  }

  function showAd(link) {
    if (document.getElementById('tvad')) return;
    const w = document.createElement('div'); w.id = 'tvad';
    w.style.cssText = 'position:fixed;right:10px;top:70px;z-index:99;max-width:62vw;border:2px solid #E0B04A;border-radius:14px;overflow:hidden;background:#081610;box-shadow:0 8px 26px rgba(0,0,0,.6);animation:pop .35s ease';
    const img = document.createElement('img'); img.src = 'ad.img?' + Date.now(); img.style.cssText = 'display:block;max-width:62vw;max-height:60vh';
    img.onclick = () => { if (link) NB.open(link); };
    const x = document.createElement('button'); x.textContent = '✕'; x.setAttribute('aria-label', 'Ýap');
    x.style.cssText = 'position:absolute;right:4px;top:4px;width:26px;height:26px;border-radius:13px;border:1px solid #E0B04A;background:rgba(10,28,20,.9);color:#fff;font-size:12px';
    const close = () => w.remove(); x.onclick = close; setTimeout(close, 7000);
    w.appendChild(img); w.appendChild(x); document.body.appendChild(w);
  }

  /** Telefonyň «Yza» düwmesi. */
  window.NBack = function () {
    const C = window.C; if (!C) return false; const s = C.state;
    if (document.getElementById('tvad')) { document.getElementById('tvad').remove(); return true; }
    if (s.menu) { C.setState({ menu: false }); return true; }
    if (s.fan) { C.setState({ fan: false }); return true; }
    if (s.sharing) { C.setState({ sharing: false }); return true; }
    if (s.page !== 'main') { C.goBack(); return true; }
    return false;
  };

  // çat: täze habar gelende aşak süýşür
  DC.after.push(() => {
    const C = window.C; if (!C || !C.chatEl || !C.chatEl.isConnected) return;
    const el = C.chatEl, h = el.scrollHeight;
    if (el.__h !== h) { const near = !el.__h || el.scrollTop + el.clientHeight >= el.__h - 80; el.__h = h; if (near) el.scrollTop = h; }
  });

  // ekrana sygdyrmak
  function fit() {
    const k = window.innerWidth / 390, app = document.getElementById('app');
    const Hh = Math.max(560, window.innerHeight / k);
    document.documentElement.style.setProperty('--H', Hh + 'px');
    app.style.transform = 'scale(' + k + ')'; app.style.height = Hh + 'px';
  }
  window.addEventListener('resize', fit);
  document.addEventListener('DOMContentLoaded', () => {
    fit();
    DC.boot('main.dc.html', document.getElementById('app')).then((C) => {
      if (location.hash === '#chat') C.setState({ page: 'chat', unreadReply: 0 });
      document.addEventListener('click', (e) => { if (e.target.closest && e.target.closest('button')) NB.tap(); }, true);
    });
  });
})();
