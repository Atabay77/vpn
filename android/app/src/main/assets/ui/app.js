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
  // fon: her gün başga ýer (Garaşsyzlyk / Bagt köşgi / Älem), gündiz we agşam görnüşi
  (function bgDay() {
    const d = new Date(), n = Math.floor((d.getTime() - d.getTimezoneOffset() * 60000) / DAY) % 3, r = document.documentElement.style;
    r.setProperty('--bgN', 'url(img/bg' + n + '_n.jpg)'); r.setProperty('--bgD', 'url(img/bg' + n + '_d.jpg)'); r.setProperty('--bgS', 'url(img/bg' + n + '_s.jpg)');
    setTimeout(bgDay, 600000);
  })();
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
  let A = null;         // admin paneli: botdan gelen ýagdaý (biletler, ulanyjylar, açarlar…)
  let admAt = 0, admPend = 0;
  const ADM_PAGES = ['admin', 'adm_t', 'adm_u', 'adm_b', 'adm_k', 'adm_kd', 'adm_x', 'adm_l', 'adm_s', 'adm_st', 'adm_ai', 'adm_or'];
  const act = (a, o) => { NB.adm(JSON.stringify(Object.assign({ a }, o || {}))); if (!admPend) admPend = Date.now(); };
  const admMe = () => (A && A.me) || INFO.admMe || {};

  // ---- 1.16: profil, hususy habarlar, nyşanlar ----
  const P2 = {};          // telefon → {th, ph, bg, n, dm} (doly profil)
  const DMS = {};         // garşydaş → {st, msgs: [], un, n, lt}
  const MUTE = LS.get('dmMute', {}) || {};   // 1.21: sessize alnanlar (sanalmaýar, duýduryş ýok)
  const DGW = { tk: [108, 118], ru: [116, 125], tr: [107, 116] };   // 1.27: «VPN-i gizle» düwmesiniň giňligi (ýazga görä ölçeldi; käbir telefonda awtomatik giňlik bozulýar)
  const UPX = {};         // 1.21: eýesiniň beren bal/derejesiniň netijesi
  // 1.22: tegelek baýdaklar (img/flags/xx.svg) — emoji baýdagyndan ýurt kody
  const FLAGS = new Set('ac,ad,ae,af,ag,ai,al,am,an,ao,aq,ar,as,at,au,aw,ax,az,ba,bb,bd,be,bf,bg,bh,bi,bj,bl,bm,bn,bo,bq,br,bs,bt,bv,bw,by,bz,ca,cc,cd,cf,cg,ch,ci,ck,cl,cm,cn,co,cp,cq,cr,cu,cv,cw,cx,cy,cz,de,dg,dj,dk,dm,do,dz,ea,ec,ee,eg,eh,er,es,et,eu,fi,fj,fk,fm,fo,fr,fx,ga,gb,gd,ge,gf,gg,gh,gi,gl,gm,gn,gp,gq,gr,gs,gt,gu,gw,gy,hk,hm,hn,hr,ht,hu,ic,id,ie,il,im,in,io,iq,ir,is,it,je,jm,jo,jp,ke,kg,kh,ki,km,kn,kp,kr,kw,ky,kz,la,lb,lc,li,lk,lr,ls,lt,lu,lv,ly,ma,mc,md,me,mf,mg,mh,mk,ml,mm,mn,mo,mp,mq,mr,ms,mt,mu,mv,mw,mx,my,mz,na,nc,ne,nf,ng,ni,nl,no,np,nr,nu,nz,om,pa,pe,pf,pg,ph,pk,pl,pm,pn,pr,ps,pt,pw,py,qa,re,ro,rs,ru,rw,sa,sb,sc,sd,se,sg,sh,si,sj,sk,sl,sm,sn,so,sr,ss,st,su,sv,sx,sy,sz,ta,tc,td,tf,tg,th,tj,tk,tl,tm,tn,to,tr,tt,tv,tw,tz,ua,ug,uk,um,un,us,uy,uz,va,vc,ve,vg,vi,vn,vu,wf,ws,xk,xx,ye,yt,yu,za,zm,zw'.split(','));
  const fcc = (f) => { const c = Array.from(String(f || '')).map((ch) => ch.codePointAt(0)).filter((x) => x >= 0x1F1E6 && x <= 0x1F1FF);
    if (c.length !== 2) return ''; const k = String.fromCharCode(c[0] - 0x1F1E6 + 97, c[1] - 0x1F1E6 + 97); return FLAGS.has(k) ? k : ''; };
  const withFc = (o) => { if (!o) return o; const fc = fcc(o.f); return Object.assign({}, o, { fc, hasFc: !!fc, noFc: !fc }); };
  const dmPrev = (m, tx, me) => (m.f === me ? '↩ ' : '') + (m.ph ? '📷 ' + tx.dm_photo : m.st ? m.st : m.sys === 'acc' ? tx.dm_acced : m.x || '');
  const GI = {}, NI = {}, imgAsked = {};   // Global chat / habar suratlary
  const EMOJI = ['😀', '😁', '😂', '🤣', '😊', '🙂', '😉', '😍', '🥰', '😘', '😎', '🤔', '😅', '😴', '😭', '😡', '😱', '🥳', '👍', '👎', '🙏', '👏', '💪', '🤝', '👋', '🔥', '❤️', '💔', '💯', '🎉', '✅', '❌', '⚡', '🚀', '⭐', '🌙', '☀️', '🎮', '📶', '🔒', '💬', '🇹🇲'];
  // tepkiler: {re: habaryň kimligi, e: emoji, off: aýyrmak}; her adamyň bir habara bir tepkisi
  const RX_E = ['❤️', '👍', '😂', '🔥', '😮'];
  let LRX = [];
  let LGM = [];   // ugradylan, entek serwerden gelmedik öz Global habarlarym   // ugradylan, entek serwerden gelmedik Global tepkiler
  const isCtl = (m) => !!(m.re || m.ty || m.rd);   // tepki / ýazýar / okaldy — habar däl
  // 1.20: derejeler (bot bilen deň: APP_LVL, APP_LVL_GIFT)
  const RK_L = [0, 50, 120, 250, 400, 600, 850, 1150, 1500, 2000], RK_G = { 3: 1, 5: 3, 7: 5, 10: 7 };
  const RK_PK = { 2: ['pk_chat'], 3: ['g', 'pk_fr3'], 4: ['pk_fr4'], 5: ['g', 'pk_sh'], 6: ['pk_fr6', 'pk_tw'], 7: ['g', 'pk_nm7', 'pk_ry'], 8: ['pk_fr8', 'pk_em'], 9: ['pk_fr9', 'pk_nm9'], 10: ['g', 'pk_fr10', 'pk_au'] };
  const rkT = (lv) => Math.max(1, Math.min(10, Math.floor(+lv) || 1));
  const rkNm = (t) => (t >= 10 ? 'nm10' : t >= 9 ? 'nm9' : t >= 7 ? 'nm7' : '');   // chatdaky nik
  const rkNc = (t) => rkNm(t) || 'rc' + t;   // derejäniň ady
  const rkPk = (t, tx) => (RK_PK[t] || []).map((k) => ({ t: k === 'g' ? '🎁 ' + tx.pk_gift.replace('{d}', String(RK_G[t])) : tx[k], c: k === 'g' ? 'pkg' : '' }));
  function rxAgg(rows) {
    const m = {};
    rows.filter((r) => r.re).sort((a, b) => (a.time || a.t || 0) - (b.time || b.t || 0)).forEach((r) => {
      const by = r.i || r.f; if (!by) return; const x = m[r.re] || (m[r.re] = {});
      if (r.off) { if (x[by] === r.e) delete x[by]; } else x[by] = r.e;
    });
    return m;
  }
  function rxList(map, key, me, tog) {
    const x = map[key] || {}, c = {}; Object.keys(x).forEach((d) => { c[x[d]] = (c[x[d]] || 0) + 1; });
    return Object.keys(c).sort((a, b) => c[b] - c[a]).map((e) => ({ e, n: String(c[e]), cls: x[me] === e ? 'me' : '', tog: () => tog(e) }));
  }
  const STICKERS = ['😂', '🤣', '😍', '🥰', '😎', '😭', '😡', '👍', '🙏', '🔥', '❤️', '💯', '🎉', '🤝', '😱', '🤔', '😴', '🥳', '💪', '👑', '🇹🇲', '🚀', '😘', '👋'];
  const LINK_RE = /(https?:\/\/|www\.|t\.me\/|\b[\w-]{2,}\.(com|net|org|ru|tm|me|io|xyz|info|top|site|online|link|app|dev|tk|ly|gg|uz|kz|tr|de|co|su|pro|club|shop|store|live|tv|cc|biz|ua|by)\b)/i;
  const roleOf = (dev) => (((INFO.roles || {})[dev] || [])[0] || '');
  const nameOf = (dev) => { const r = (INFO.roles || {})[dev], p = P2[dev], d = DMS[dev], g = G.slice().reverse().find((m) => m.i === dev);
    return (p && p.n) || (r && r[1]) || (d && d.n) || (g && g.n) || '?'; };
  const thumbOf = (dev) => (P2[dev] && (P2[dev].th || P2[dev].ph)) || ((PH[dev] || {}).d || '');
  const askImg = (kind, id) => { const k = kind + id; if (!id || imgAsked[k]) return; imgAsked[k] = 1; NB.img(kind, id); };
  /** Surat kiçeltmek: iň uly tarapy max piksel, JPEG. */
  function shrink(file, max, q, cb, square) {
    const rd = new FileReader();
    rd.onload = () => {
      const img = new Image();
      img.onload = () => {
        const c = document.createElement('canvas');
        if (square) { const k = Math.max(max / img.width, max / img.height); c.width = max; c.height = max; c.getContext('2d').drawImage(img, (max - img.width * k) / 2, (max - img.height * k) / 2, img.width * k, img.height * k); }
        else { const k = Math.min(1, max / Math.max(img.width, img.height)); c.width = Math.round(img.width * k); c.height = Math.round(img.height * k); c.getContext('2d').drawImage(img, 0, 0, c.width, c.height); }
        cb(c.toDataURL('image/jpeg', q));
      };
      img.onerror = () => cb('');
      img.src = String(rd.result);
    };
    rd.onerror = () => cb('');
    rd.readAsDataURL(file);
  }
  /** Chat suraty: mümkin boldugyça uly we arassa (WebP), emma çäkden (simwol) geçmesin. */
  function fitShrink(file, max, limit, cb) {
    const rd = new FileReader();
    rd.onload = () => {
      const img = new Image();
      img.onload = () => {
        let dim = max, out = '';
        while (dim >= 420 && !out) {
          const k = Math.min(1, dim / Math.max(img.width, img.height)), c = document.createElement('canvas');
          c.width = Math.round(img.width * k); c.height = Math.round(img.height * k); c.getContext('2d').drawImage(img, 0, 0, c.width, c.height);
          for (let q = 0.9; q >= 0.44 && !out; q -= 0.06) {
            let d = c.toDataURL('image/webp', q); if (d.indexOf('data:image/webp') !== 0) d = c.toDataURL('image/jpeg', q);
            if (d.length <= limit) out = d;
          }
          dim = Math.round(dim * 0.85);
        }
        cb(out);
      };
      img.onerror = () => cb('');
      img.src = String(rd.result);
    };
    rd.onerror = () => cb('');
    rd.readAsDataURL(file);
  }
  function shrinkData(src, max, q, cb) { const img = new Image(); img.onload = () => { const k = Math.min(1, max / Math.max(img.width, img.height)), c = document.createElement('canvas'); c.width = Math.round(img.width * k); c.height = Math.round(img.height * k); c.getContext('2d').drawImage(img, 0, 0, c.width, c.height); cb(c.toDataURL('image/jpeg', q)); }; img.onerror = () => cb(''); img.src = src; }
  const fileOf = (e) => e && e.target && e.target.files && e.target.files[0];
  // 1.16.4: tekstdäki açarlar (XXXX-XXXX-XXXX) basyp göçürilýär
  const KEY_RE = /\b[A-Z0-9]{4}-[A-Z0-9]{4}-[A-Z0-9]{4}\b/g;
  function withKeys(parts, C) {
    const out = [];
    for (const q of parts || []) {
      if (!q.isT || !KEY_RE.test(q.t)) { out.push(Object.assign({ isK: false, cp: null, use: null }, q)); continue; }
      KEY_RE.lastIndex = 0; let last = 0, m;
      while ((m = KEY_RE.exec(q.t))) {
        if (m.index > last) out.push({ t: q.t.slice(last, m.index), isT: true, isL: false, href: '', isK: false, cp: null, use: null });
        const k = m[0]; out.push({ t: k, isT: false, isL: false, href: '', isK: true, cp: () => { NB.copy(k); C.say('✓ ' + C.T()[C.state.lang].copied + ': ' + k); },
          use: () => { NB.copy(k); C.setState({ page: 'key', menu: false, keyIn: k, keyMsg: '' }); } });
        last = m.index + k.length;
      }
      if (last < q.t.length) out.push({ t: q.t.slice(last), isT: true, isL: false, href: '', isK: false, cp: null, use: null });
    }
    return out;
  }
  // habaryň düwmeleri: kimlik → sahypa
  const NBTN = { invite: ['🎁', 'p_invite', 'invite'], key: ['🔑', 'p_key', 'key'], global: ['🌐', 'p_global', 'global'], chat: ['💬', 'p_chat', 'chat'],
    servers: ['🌍', 'p_servers', 'servers'], gift: ['🎁', 'p_gift', 'gift'], dms: ['✉️', 'p_dms', 'dms'], update: ['', 'nb_update', ''], vpn: ['', 'nb_vpn', ''] };
  const NDEL = {};   // eýesiniň pozan habarlary (bot täzeläýänçä görünmesin)
  /** Kota duýduryşy (telefonda saklanýar): şol duýduryş öň pozulan bolsa gaýtadan çykmaýar, täzesi (başga wagt) çykýar. */
  function qAdd(id, t, at) {
    if (!id) return; const q = LS.get('qAlerts', {}), cur = q[id];
    if (cur && cur.at === (at || 0)) { cur.t = t || cur.t; LS.set('qAlerts', q); return; }
    q[id] = { t: t || '', at: at || 0, x: 0 }; LS.set('qAlerts', q);
  }
  const rpOf = (m, nm) => ({ i: m.id || m.gk || '', n: nm || '', t: (m.st || (m.pi || m.ph ? '📷' : '') || m.x || m.t || '').slice(0, 90) });

  function loadServers() {
    const r = J(NB.servers(), { list: [], pings: {} });
    SV = r.list.map((s) => {
      const c = CO[cc(s.flag)];
      const num = (String(s.country || '').match(/\s(\d{1,2})$/) || [])[1], sfx = num ? ' ' + num : '';
      return { id: s.key, f: s.flag, n: c ? { tk: c[2] + sfx, ru: c[3] + sfx, tr: c[4] + sfx } : { tk: s.country, ru: s.country, tr: s.country }, t: s.title || s.country, p: s.proto, lat: c ? c[0] : 50, lon: c ? c[1] : 10, game: s.game };
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
    // admin paneli: tasarymyň ýasama maglumatlary deregine botdan geleni
    P.admUsers = function () {
      const us = (A && A.us) || {}, out = Object.keys(us).map((id) => { const u = us[id]; return { id, name: u.name || '?', bg: colorOf(id), code: u.code || '', model: u.model || '', ver: u.ver || '', lang: u.lang || 'tk', srv: 0, first: u.first || '', seen: u.seen || '', key: u.key || '—', inv: u.inv || 0 }; });
      ((A && A.tk) || []).forEach((t) => { if (!us[t.u]) { us[t.u] = { name: '?' }; out.push({ id: t.u, name: '?', bg: colorOf(t.u), code: '', model: '', ver: '', lang: 'tk', srv: 0, first: '', seen: '', key: '—', inv: 0 }); } });
      return out;
    };
    P.seedTickets = function () { return ((A && A.tk) || []).filter((t) => t.msgs && t.msgs.length).map((t) => ({ id: t.id, u: t.u, st: t.st, fb: t.fb, msgs: t.msgs.map((m) => [m[0] === 'u' ? 'u' : m[0] === 'ai' ? 'ai' : 'a', m[1], m[2]]) })); };
    P.allTickets = function () { return this.seedTickets(); };
    P.codes = function () { return ((A && A.codes) || []).map((c) => ({ code: c.code, role: c.role, u: c.u, made: c.made })); };
    P.allKeys = function () { return (A && A.keys) || []; };
    P.notes = function () { return (A && A.notes) || []; };
    P.adminReply = function (text) {
      text = String(text || '').trim(); const t = A && A.tk.find((x) => x.id === this.state.admT); if (!text || !t) return;
      act('reply', { tid: t.id, t: text });
      t.msgs = t.msgs.concat([['a', text, this.hm(Date.now())]]); t.st = 'ans';
      this.setState({ admIn: '', admTick: (this.state.admTick || 0) + 1 });
    };
    // çagyryş: göni ýükleme linki (googleapis.com — VPN-siz açylýar); link ýok bolsa köne tekst (e-poçta)
    const SHARE = { tk: 'Türkmen VPN — Türkmenistan üçin çalt VPN 🇹🇲\nÝükläp al (VPN gerek däl): {u}\nProgrammany açanyňda meniň kodymy ýaz: {c}',
      ru: 'Türkmen VPN — быстрый VPN для Туркменистана 🇹🇲\nСкачать (без VPN): {u}\nПри первом запуске введи мой код: {c}',
      tr: 'Türkmen VPN — Türkmenistan için hızlı VPN 🇹🇲\nİndir (VPN gerekmez): {u}\nUygulamayı açınca kodumu yaz: {c}' };
    P.shareText = function () {
      const l = this.state.lang, c = INFO.code || '';
      return INFO.dl ? (SHARE[l] || SHARE.tk).replace('{u}', INFO.dl).replace('{c}', c) : this.T()[l].r_msg.replace('{c}', c);
    };

    /** Admine ýaz: habar bota gidýär (AI derrew, admin Telegramda jogap berýär). */
    P.sendMsg = function (text) {
      text = String(text || '').trim().slice(0, 1000); if (!text) return;
      if (this._isBan && this._isBan()) return;
      const s = this.state, id = Date.now(), tx = this.T()[s.lang];
      this.setState({ chat: s.chat.concat([{ id, who: 'u', t: text, time: this.hm(id), tick: '✓' }]), chatIn: '', fb: '',
        myTkSt: s.myTkSt === 'closed' || !s.myTkSt ? 'open' : s.myTkSt, aiTyping: !!INFO.ai && !s.human });
      NB.send(JSON.stringify({ k: 'tk', t: text, nick: this.meName, tid: s.tkId || 0 }));
      if (s.st !== 'on' && !INFO.fs) this.say(tx.q_wait);
      clearTimeout(this.aiT); this.aiT = setTimeout(() => this.setState({ aiTyping: false }), 90000);
    };

    const rv0 = P.renderVals;
    P.renderVals = function () {
      const r = rv0.call(this), s = this.state, tx = r.tx, on = s.st === 'on', now = Date.now();
      if (r.phase && document.documentElement.className !== 'ph-' + r.phase) document.documentElement.className = 'ph-' + r.phase;   // wagta görä tema
      if (INFO.ver) ['s_updS', 'i_ver'].forEach((k) => { tx[k] = String(tx[k]).replace(/1\.\d+(\.\d+)?/, INFO.ver); });
      const kexp = s.kexp; // -1 ýok, 0 çäksiz, >0 möhlet (sn)
      const keyLeft = kexp > 0 ? Math.max(0, kexp - now / 1000) : 0;
      const fmtLeft = (sec) => { const hh = Math.floor(sec / 3600), mm = Math.floor(sec % 3600 / 60); return hh >= 24 ? Math.floor(hh / 24) + ' ' + tx.days + ' ' + (hh % 24) + ' ' + tx.hh : hh + ' ' + tx.hh + ' ' + two(mm) + ' ' + tx.mm; };
      const keyTxt = s.hasKey ? (kexp === 0 ? '♾' : fmtLeft(keyLeft)) : '—';
      // wagt / açar
      r.timerLbl = s.hasKey ? tx.keyL : tx.left;
      r.timer = s.hasKey ? keyTxt : two(Math.floor(s.left / 3600)) + ':' + two(Math.floor(s.left % 3600 / 60)) + ':' + two(s.left % 60);
      r.showUl = on && !s.hasKey;
      r.showUpd = !!s.upd && !s.menu;
      r.updTxt = s.dl >= 0 ? tx.u_dl.replace('{p}', String(s.dl)) : 'Türkmen VPN ' + s.upd;
      r.updBtn = s.dl >= 0 ? '…' : tx.u_btn; r.doUpd = () => NB.update();
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
      const UH = s.usageH || {}, today = dayKey(now);
      const hrs = [0, 1, 2, 3, 4, 5].map((q) => [0, 1, 2, 3].reduce((a, j) => a + (UH[today + '-' + (q * 4 + j)] || 0), 0) / 1024);
      const vals = s.uMode === 't' ? hrs : s.uMode === 'd' ? daysV : wk, mx = Math.max(1, ...vals), mb = (v) => (v >= 1024 ? (v / 1024).toFixed(2) + ' GB' : (v < 10 && v > 0 ? v.toFixed(1) : Math.round(v)) + ' MB');
      if (s.uMode === 't') {
        const b0 = r.bars[0] || {}, curQ = Math.floor(new Date(now).getHours() / 4), sel = s.uSel > 5 ? curQ : s.uSel;
        r.bars = hrs.map((v, i) => Object.assign({}, b0, { v: i === sel ? mb(v) : '', h: Math.max(4, Math.round(v / mx * 100)), l: two(i * 4) + '–' + two(i * 4 + 4), lc: i === curQ ? '#FFD27A' : '#C9BFA8',
          cls: (i === curQ ? 'ubar-today' : '') + (i === sel ? ' ubar-sel' : ''), d: (i * 0.06).toFixed(2), aria: two(i * 4) + ':00: ' + mb(v), pick: () => this.setState({ uSel: i }) }));
      } else r.bars = r.bars.map((b, i) => Object.assign({}, b, { v: i === s.uSel ? mb(vals[i] || 0) : '', h: Math.max(4, Math.round((vals[i] || 0) / mx * 100)), aria: b.l + ': ' + mb(vals[i] || 0) }));
      r.uTodayGo = () => this.setState({ uMode: 't', uSel: 9 }); r.uTodayP = s.uMode === 't' ? 'true' : 'false'; r.uTodayCls = s.uMode === 't' ? 'seg-on' : 'seg-off';
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
      const gl = G.filter((m) => !m.re && !gDel[m.id] && bans.indexOf(m.i) < 0).concat(LGM), RXG = rxAgg(G.concat(LRX));
      gl.forEach((m) => { if (m.pi && !GI[m.pi]) askImg('g', m.pi); });
      r.gMsgs = gl.map((m) => {
        const mine = m.i === me, nm = mine ? this.meName : m.n || '?', lvq = mine ? (LS.get('lvl', {}) || {}).lv || 0 : m.lv || 0, rt = rkT(lvq);
        const ph = mine ? s.photo : ((PH[m.i] || {}).d || '');
        return { name: nm + (mine ? ' · ' + tx.g_you : ''), ini: ini(nm), bg: mine ? '#E0B04A' : colorOf(m.i), nc: mine ? '#06100B' : colorOf(m.i), photo: ph, hasPh: !!ph, noPh: !ph,
          t: m.st ? '' : m.t, time: this.hm((m.time || 0) * 1000 || now) + (m.pend ? ' ⏳' : ''), gk: m.id, cls: mine ? 'gm-me' : 'gm-o', bcls: mine ? 'gb-me' : 'gb-o', canDel: false, del: null,
          prof: () => this.openProf(m.i), isO: roleOf(m.i) === 'o', isA: roleOf(m.i) === 'a', ncls: roleOf(m.i) === 'o' ? 'goldtxt' : (lvq ? rkNm(rt) : ''), fr: lvq && rt >= 3 ? 'fr' + rt : '',
          isSt: !!m.st, st: m.st || '', hasImg: !!(m.pi && GI[m.pi]), img: (m.pi && GI[m.pi]) || '', zoom: () => this.setState({ zoom: GI[m.pi] || '' }),
          hasRp: !!(m.rp && m.rp.n), rpN: m.rp ? m.rp.n : '', rpT: m.rp ? m.rp.t : '',
          hasLv: lvq >= 2, lv: String(rt),
          rx: rxList(RXG, m.id, me, (e) => this.gReact(m.id, e)), hasRx: !!RXG[m.id] && Object.keys(RXG[m.id]).length > 0,
          rxOpen: s.rxFor === m.id, rxPick: RX_E.map((e) => ({ e, go: () => { this.setState({ rxFor: null }); this.gReact(m.id, e); } })), rpGo: () => this.replyTo(m.id) };
      });
      const onl = INFO.online > 0 ? tx.g_online.replace('{n}', String(INFO.online)) : '';
      r.gOnline = onl; r.gHead = tx.p_global.toUpperCase() + (onl ? ' · ' + onl : '');
      r.ticker = gl.length ? gl.slice(-2).map((m) => ({ n: m.i === me ? this.meName : m.n, c: m.i === me ? '#E0B04A' : colorOf(m.i), t: m.st || (m.pi ? '📷 ' + tx.dm_photo : m.t) })) : [{ n: '🌐', c: '#6FDB9C', t: tx.g_empty }];
      // sazlamalar
      r.opts = r.opts.map((o) => {
        if (o.t === tx.s_snd) return Object.assign({}, o, { on: () => { const v = !this.state.snd; NB.snd(v); this.setState({ snd: v }); } });
        if (o.t === tx.s_ref) return Object.assign({}, o, { on: () => { if (this.state.refreshing) return; this.setState({ refreshing: true }); NB.refresh(); } });
        if (o.t === tx.s_upd) return Object.assign({}, o, { s: s.upd ? tx.s_updN.replace('{v}', s.upd) : tx.s_updS, on: () => NB.update() });
        if (o.t === tx.s_tile) return Object.assign({}, o, { on: () => NB.tile() });
        if (o.t === tx.s_key) return Object.assign({}, o, { s: s.hasKey ? r.keyCur : tx.s_keyS });
        return o;
      });
      r.svRef = () => { if (this.state.refreshing) return; this.setState({ refreshing: true }); NB.refresh(); };
      r.svRefCls = s.refreshing ? 'spin' : '';
      const ic = this.icons();
      r.opts = r.opts.concat([{ i1: ic.global[0], i2: ic.global[1], t: tx.s_diag, s: s.diag ? tx[s.diag] : tx.s_diagS, isSw: false, isBtn: true, arrow: 'M9 6l6 6-6 6', icCls: '', isSeg: false, segs: [], aria: 'false', swCls: '', d: '0.35',
        on: () => { this.setState({ diag: 'dg_wait' }); NB.diag(); } }]);
      // admin paneli (rugsada görä)
      const am = admMe(), isF = am.role === 'f', full = isF || am.perm === 'all', us = (A && A.us) || {};
      const openN = ((A && A.tk) || []).filter((t) => t.st === 'open').length;
      r.menuItems = r.menuItems.filter((m) => (s.admOn || m.t !== tx.p_admin) && m.t !== tx.p_history).map((m) => (m.t === tx.p_global ? Object.assign({}, m, { badge: INFO.online > 0, bt: '● ' + INFO.online })
        : m.t === tx.p_admin ? Object.assign({}, m, { badge: openN > 0, bt: String(openN) })
        : m.t === tx.p_invite ? Object.assign({}, m, { badge: true, bt: tx.r_freeB, bc: 'mbadge-gold' }) : m));
      { const at = r.menuItems.findIndex((m) => m.t === tx.p_servers), base = r.menuItems[at] || r.menuItems[0];
        if (base) r.menuItems.splice(at + 1, 0, Object.assign({}, base, { t: tx.p_buy, i1: 'M3 5h2.5l2.2 10.5h10.6L20.5 8H7', i2: 'M9.5 19.5h.01M17 19.5h.01', badge: false,
          cls: s.page === 'buy' ? 'mi-on' : '', ic: s.page === 'buy' ? '#6FDB9C' : '#E0B04A', go: () => this.setState({ page: 'buy', menu: false }) })); }
      if (!full) { r.tabUsCls = 'hid'; r.tabIsUs = false; }
      if (!isF) { r.tabAdCls = 'hid'; r.tabBotCls = 'hid'; r.tabIsAd = false; r.tabIsBot = false; if (s.admTab !== 'tk' && !(full && s.admTab === 'us')) r.tabIsTk = true; }
      { const staff = (d) => d === INFO.dev || !!roleOf(d); r.banCls = isF && !(s.admU && staff(s.admU)) ? '' : 'hid'; r.bcCls = isF ? '' : 'hid'; }   // özüňi / admini gadagan etmek bolmaýar
      const byName = (b) => (/^app:/.test(b) ? b.slice(4) : b === 'ref' ? '🤝' : b === 'gift' ? '🎁' : /^\d+$/.test(b) ? 'Telegram' : b || '?');
      if (A && A.codes) r.codeList = A.codes.map((c, i) => {
        const mine = c.u === INFO.dev, u = c.u ? us[c.u] || { name: '?' } : null;
        if (c.once) {
          return { code: c.code, icon: '🔑', ibg: 'rgba(224,176,74,.3)', role: tx.oa_once + ' · ' + (c.perm === 'all' ? tx.oa_all : tx.oa_tk) + ' · ' + c.name,
            who: u ? u.name : tx.ad_free, sub: u ? (u.model || '') + ' · ' + tx.ad_seen + ': ' + c.seen : tx.oa_unused,
            stT: !u ? tx.ad_unused : c.vpn ? '🟢 ' + tx.ad_vpnOn : '⚪ ' + tx.ad_vpnOff, stCls: !u ? 'tk-closed' : c.vpn ? 'on-g' : 'on-n', d: (i * 0.05).toFixed(2),
            canKick: isF, kick: () => { act('kick', { id: c.id }); A.codes = A.codes.filter((x) => x.id !== c.id); this.setState({ admTick: (this.state.admTick || 0) + 1 }); this.say('🔓 ' + tx.ad_kicked); } }; }
        return { code: c.code, icon: c.role === 'f' ? '👑' : '👮', ibg: c.role === 'f' ? 'linear-gradient(145deg,#F2CD7A,#C8902E)' : 'rgba(111,168,220,.35)',
          role: (c.role === 'f' ? tx.ad_founder : tx.ad_helper + ' · ' + tx.ad_made.replace('{n}', String(c.made || 0))) + ' · ' + c.name + (c.ok ? '' : ' · ⛔'),
          who: u ? u.name + (mine ? ' · ' + tx.g_you : '') : tx.ad_free, sub: u ? (u.model || '') + ' · ' + tx.ad_seen + ': ' + (mine ? tx.ad_now : c.seen) : tx.ad_freeS,
          stT: !u ? tx.ad_unused : c.vpn || mine ? '🟢 ' + tx.ad_vpnOn : '⚪ ' + tx.ad_vpnOff, stCls: !u ? 'tk-closed' : c.vpn || mine ? 'on-g' : 'on-n', d: (i * 0.05).toFixed(2),
          canKick: isF && !!c.u && !mine, kick: () => { act('kick', { id: c.id }); c.u = null; this.setState({ admTick: (this.state.admTick || 0) + 1 }); this.say('🔓 ' + tx.ad_kicked); } };
      });
      // 1 girişlik admin açary
      r.onceN = s.onceN || ''; r.onOnceN = (e) => this.setState({ onceN: e.target.value });
      r.oncePerms = [['tk', tx.oa_tk], ['all', tx.oa_all]].map(([k, t]) => { const on = (s.oncePerm || 'tk') === k; return { t, p: on ? 'true' : 'false', cls: on ? 'chip-on' : '', pick: () => this.setState({ oncePerm: k }) }; });
      r.mkOnce = () => { const n = (s.onceN || '').replace(/\s+/g, ''); if (n.length < 2) { this.say('⚠️ ' + tx.oa_short); return; } act('mkadm', { perm: s.oncePerm || 'tk', n }); this.say(tx.k_wait); };
      r.hasOnceK = !!s.onceK; r.onceK = s.onceK || ''; r.cpOnceK = () => { NB.copy(s.onceK); this.say('✓ ' + tx.copied); };
      r.keyList = ((A && A.keys) || []).map((k, i) => { const u = k.used ? us[k.used] : null;
        return { cp: () => this.setState({ page: 'adm_kd', kSel: k.k, kdLb: null, kdDays: '', kdN: '' }), k: k.k, sub: (k.lb ? '🏷 ' + k.lb + ' · ' : '') + (k.d === 0 ? '♾' : k.d === 30 ? tx.bk_month : k.d + ' ' + tx.days) + ((k.n || 1) > 1 ? ' · 👥 ' + (k.u || 0) + '/' + k.n : '') + ' · ' + tx.bk_by + ': ' + byName(k.by) + ' · ' + k.at + (u ? ' · ' + u.name : ''), stT: k.used ? tx.bk_used : tx.bk_new, stCls: k.used ? 'tk-closed' : 'tk-ans', d: (i * 0.04).toFixed(2) }; });
      if (A) {
        r.logText = A.logs || '—';
        if (A.next != null) r.sysLine = s.sysOn ? tx.bt_on.replace(/\d+/, String(Math.max(1, Math.round(A.next / 60)))) : tx.bt_off;
        r.srcList = (A.src || []).map((q, i) => ({ i: q[0], n: q[1], sub: q[2], stT: q[3] ? tx.bt_ok : tx.bt_wait, stCls: q[3] ? 'tk-ans' : 'tk-open', d: (i * 0.05).toFixed(2) }));
        const S = A.stats || {};
        r.statTiles = [[tx.st_users, S.users, '#F3E7D0'], [tx.st_today, S.today, '#6FDB9C'], [tx.st_vpn, S.vpn, '#6FDB9C'], [tx.st_new, S.new, '#FFD27A'], [tx.st_keys, S.keys, '#FFD27A'],
          [tx.st_open, S.open, '#FFB0A6'], [tx.st_ai, S.ai, '#A8D4FF'], [tx.st_admins, (S.admins || [0, 0]).join(' / '), '#F3E7D0']].map((q) => ({ k: q[0], v: String(q[1] == null ? '—' : q[1]), c: q[2] }));
      }
      r.cfOn = !!s.cf; r.cfText = s.cf ? s.cf.text : ''; r.cfOk = s.cf ? s.cf.ok : ''; r.cfNo = this.cfNo; r.cfYes = this.cfYes;
      r.cfBg = s.cf && s.cf.danger ? 'linear-gradient(90deg,#FF8A78,#E05A48)' : 'linear-gradient(90deg,#E0B04A,#C8902E)';
      // Awtomatik kartasy: haýsy ýurtlar bar we näçe serwer
      const real = SV.filter((v) => !v.game), fl = [];
      real.forEach((v) => { if (fl.indexOf(v.f) < 0) fl.push(v.f); });
      r.svFlags = fl.slice(0, 9).join(' ') + (fl.length > 9 ? ' …' : '') || r.offCard.sub;
      r.svCount = ({ tk: '{n} serwer', ru: '{n} серв.', tr: '{n} sunucu' }[s.lang] || '{n}').replace('{n}', String(SV.length));
      r.myCode = INFO.code || '—';
      // açar döret: 3/7/30 + möhletsiz; elle gün ýazylsa şol
      r.kDays = [[3, '3 ' + tx.days, '15 TMT'], [7, '7 ' + tx.days, '30 TMT'], [30, tx.bk_month, '100 TMT'], [0, '♾', tx.bk_unl.replace('♾ ', '')]].map((q) => {
        const on = !(parseInt(s.kCustom, 10) > 0) && s.kDay === q[0];
        return { t: q[1], p2: q[2], p: on ? 'true' : 'false', cls: on ? 'chip-on' : 'seg-off', pick: () => this.setState({ kDay: q[0], kCustom: '' }) };
      });
      r.kCustom = s.kCustom || ''; r.kN = s.kN || ''; r.onKCustom = this.onKCustom; r.onKN = this.onKN; r.kDayPh = '—';
      { const c = parseInt(s.kCustom, 10), dd = c > 0 ? Math.min(3650, c) : s.kDay, nn = Math.max(1, Math.min(1000, parseInt(s.kN, 10) || 1));
        r.kSum = tx.bk_sum.replace('{d}', dd === 0 ? tx.bk_unl : dd === 30 ? tx.bk_month : dd + ' ' + tx.days).replace('{n}', String(nn)); }
      // goşmaça kodlar (Telegram kanaly + admin)
      r.isAdmX = s.page === 'adm_x' && s.admOn;
      if (r.isAdmX) r.pageTitle = '🧩 ' + tx.x_title;
      if (isF) r.botTiles = r.botTiles.concat([{ i: '🧩', t: tx.x_title, go: () => this.setState({ page: 'adm_x' }), st: '' }]);
      { const ow = ((A && A.orders) || []).filter((o) => o.st === 'w').length;
        if (isF) r.botTiles = r.botTiles.concat([{ i: '🧾', t: tx.or_title + (ow ? ' (' + ow + ')' : ''), go: () => this.setState({ page: 'adm_or' }), st: '' }]);
        r.isAdmOr = s.page === 'adm_or' && s.admOn; if (r.isAdmOr) r.pageTitle = '🧾 ' + tx.or_title;
        r.orList = ((A && A.orders) || []).map((o) => { if (o.pi && !GI[o.pi]) askImg('g', o.pi);
          return { id: '#' + o.id, who: o.nm, sub: (o.d === 30 ? tx.bk_month : o.d + ' ' + tx.days) + ' · ' + o.p + ' TMT · ' + o.at, note: o.n || '', hasNote: !!o.n,
            isW: o.st === 'w', stT: o.st === 'w' ? tx.or_wait : o.st === 'ok' ? tx.or_ok : tx.or_no, stCls: o.st === 'w' ? 'tk-open' : o.st === 'ok' ? 'on-g' : 'tk-closed',
            hasImg: !!(o.pi && GI[o.pi]), img: (o.pi && GI[o.pi]) || '', zoom: () => this.setState({ zoom: GI[o.pi] || '' }),
            ok: () => this.confirm(tx.or_okQ, '✅ ' + tx.or_okB, () => { act('ordok', { id: o.id }); o.st = 'ok'; this.setState({ admTick: (this.state.admTick || 0) + 1 }); }),
            no: () => this.confirm(tx.or_noQ, '❌ ' + tx.or_noB, () => { act('ordno', { id: o.id }); o.st = 'no'; this.setState({ admTick: (this.state.admTick || 0) + 1 }); }) }; });
        r.orEmpty = !r.orList.length; }
      r.xIn = s.xIn || ''; r.onXIn = this.onXIn; r.xAdd = this.xAdd; r.xChIn = s.xChIn || ''; r.onXChIn = this.onXChIn; r.xChAdd = this.xChAdd;
      r.xChs = ((A && A.tgsrc) || []).map((ch) => ({ ch, del: () => this.confirm('@' + ch + ' ?', '🗑 ' + tx.cf_yes, () => act('chdel', { ch })) }));
      r.qSubs = ((A && A.qsubs) || []).map((q) => ({ label: q.label, t: q.t || tx.q_wait, c: (q.pct || 0) >= 0.85 ? '#FF6B5C' : '#6FDB9C',
        del: () => this.confirm(q.label + ' ?', '🗑 ' + tx.cf_yes, () => act('qdel', { u: q.u })) }));
      r.qIn = s.qIn || ''; r.onQIn = this.onQIn; r.qAddB = this.qAddB;
      const xl = (A && A.xc) || [];
      r.xCount = tx.x_count.replace('{n}', String(xl.length));
      r.xList = xl.map((x) => ({ n: (x.name || x.hp), sub: (x.src === 'tg' ? '📡 @' + x.ch : '👤 ' + tx.x_m) + ' · ' + x.hp + ' · ' + x.at,
        stT: x.ms > 0 ? x.ms + ' ms' : x.bad > 0 ? tx.x_bad + ' ×' + x.bad : tx.x_wait, stCls: x.ms > 0 ? 'tk-ans' : x.bad > 0 ? 'tk-open' : 'tk-closed',
        del: () => this.confirm(tx.x_delQ, '🗑 ' + tx.cf_yes, () => act('xdel', { id: x.id })) }));
      // açar dolandyrmak
      r.isAdmKd = s.page === 'adm_kd' && s.admOn && !!s.kSel;
      { const kk = ((A && A.keys) || []).find((x) => x.k === s.kSel) || { k: s.kSel || '', n: 1, u: 0, exp: 0 };
        const nowS = Date.now() / 1000, leftD = kk.exp ? Math.ceil((kk.exp - nowS) / 86400) : null;
        r.kd = { k: kk.k, lb: s.kdLb == null ? (kk.lb || '') : s.kdLb, days: s.kdDays || '', n: s.kdN || '',
          daysPh: leftD == null ? '♾' : String(Math.max(0, leftD)), nPh: String(kk.n || 1),
          info: tx.bk_by + ': ' + (/^app:/.test(kk.by || '') ? kk.by.slice(4) : kk.by || '?') + ' · ' + (kk.at || '') + ' · ' + tx.bk_devs.replace('{u}', String(kk.u || 0)).replace('{n}', String(kk.n || 1)),
          left: leftD == null ? '♾ ' + tx.bk_unl.replace('♾ ', '') : leftD <= 0 ? '⛔ ' + tx.bk_expired : tx.bk_leftT.replace('{d}', leftD + ' ' + tx.days),
          cp: () => { NB.copy(kk.k); this.say('✓ ' + tx.copied + ': ' + kk.k); },
          save: () => { const o = { k: kk.k, lb: r.kd.lb }; if (String(s.kdDays).trim() !== '') o.days = parseInt(s.kdDays, 10) || 0; if (String(s.kdN).trim() !== '') o.n = parseInt(s.kdN, 10) || 1; act('kedit', o); this.say(tx.k_wait); },
          del: () => this.confirm(tx.bk_delQ, '🗑 ' + tx.cf_yes, () => { act('kdel', { k: kk.k }); this.setState({ page: 'adm_k' }); }) };
        r.onKdLb = this.onKdLb; r.onKdDays = this.onKdDays; r.onKdN = this.onKdN;
        if (r.isAdmKd) r.pageTitle = tx.bk_edit; }
      r.updLbl = s.bUpd ? tx.s_refing : '⚡ ' + tx.bt_upd;
      r.botTiles = r.botTiles.map((b, i) => (i === 5 ? Object.assign({}, b, { t: s.bUpd ? tx.s_refing : tx.bt_upd }) : b));
      r.aiNotes = this.notes().map((t, i) => ({ t, del: () => { act('notedel', { i }); A.notes = A.notes.filter((_, j) => j !== i); this.setState({ admTick: (this.state.admTick || 0) + 1 }); } }));
      const au = s.admU && us[s.admU];
      if (au) {
        const ph = (PH[s.admU] || {}).d || '';
        if (!ph && !phAsked[s.admU]) { phAsked[s.admU] = 1; NB.getPhoto(s.admU); }
        r.au = Object.assign({}, r.au, { photo: ph, hasPh: !!ph, noPh: !ph });
        r.auInfo = [['ID', au.code], [tx.ad_model, au.model], [tx.ad_ver, au.ver], [tx.ad_lang, { tk: '🇹🇲 Türkmençe', ru: '🇷🇺 Русский', tr: '🇹🇷 Türkçe' }[au.lang] || au.lang], [tx.ad_first, au.first], [tx.ad_seen, au.seen], [tx.ad_key, au.key], [tx.ad_inv, String(au.inv || 0)]].map((q) => ({ k: q[0], v: q[1] || '—' }));
        r.banT = au.ban ? '✅ ' + tx.ad_unban : '🚫 ' + tx.ad_ban; r.banC = au.ban ? '#6FDB9C' : '#FFB0A6'; r.banBc = au.ban ? 'rgba(111,219,156,.6)' : 'rgba(255,138,120,.6)';
      }
      const at = s.admT != null && A ? A.tk.find((x) => x.id === s.admT) : null;
      if (at && at.fb && at.st === 'closed') r.atMsgs = r.atMsgs.concat([{ t: at.fb === '👍' ? tx.fb_aUp : tx.fb_aDown, time: '', cls: 'bub-s', isAi: false }]);
      // ---- 1.16 ----
      const pg = s.page, me1 = INFO.dev, myRole = roleOf(me1);
      // kota duýduryşy: diňe eýesine, «Sil» basylýança durýar
      { const QA = LS.get('qAlerts', {}), own = myRole === 'o' || admMe().role === 'f';
        r.qAlerts = own ? Object.keys(QA).filter((id) => !QA[id].x).map((id) => ({ t: QA[id].t, del: () => { const q = LS.get('qAlerts', {}); if (q[id]) q[id].x = 1; LS.set('qAlerts', q); this.setState({ qTick: (this.state.qTick || 0) + 1 }); } })) : []; }
      r.isOwner = myRole === 'o'; r.isAdminR = myRole === 'a'; r.ownerTag = r.isOwner && pg === 'main'; r.appVer = INFO.ver || '';
      // oýun serwerleri: hemmesi jogap bermese bellik; täzele + ping
      { const gp = SV.filter((v) => v.game).map((v) => s.pings[v.id]);
        r.gAllNa = gp.length > 0 && gp.every((m) => m != null && m < 0); r.gHasNa = !r.gAllNa;
        r.gRefCls = s.refreshing || s.testing ? 'spin' : '';
        r.gRefresh = () => { if (this.state.refreshing) return; this.setState({ refreshing: true, gRetest: true }); NB.refresh(); }; } r.meNcls = myRole === 'o' ? 'goldtxt' : '';
      r.nkBonT = INFO.nkb ? tx.nk_bonYes : tx.nk_bonNo;
      r.nkIn = s.nkIn == null ? this.meName : s.nkIn; r.onNk = this.onNk; r.saveNk = this.saveNk;
      r.nkMsg = s.nkSt ? tx['nk_' + s.nkSt] : ''; r.nkCls = s.nkSt === 'ok' ? 'nk-ok' : s.nkSt === 'wait' ? '' : s.nkSt ? 'nk-bad' : '';
      const bgUrl = (d) => (d ? 'linear-gradient(rgba(6,16,11,.45),rgba(6,16,11,.88)),url(' + d + ')' : 'none');
      r.pfBgImg = bgUrl(s.pbg); r.hasBg = !!s.pbg; r.onBg = this.onBg; r.delBg = this.delBg;
      r.stOn = !!s.stOn; r.stToggle = this.stToggle; r.stickers = STICKERS.map((e) => ({ e, pick: () => this.pickSticker(e) }));
      // emoji: ýazga goşulýar (Telegram ýaly); stiker: uly bolup gidýär
      { const tab = s.stTab || 'e'; r.stIsEmo = tab === 'e'; r.stIsSt = tab === 's';
        r.stTabs = [['e', tx.st_emo], ['s', tx.st_st]].map(([k, t]) => ({ t, p: tab === k ? 'true' : 'false', cls: tab === k ? 'on' : '', pick: () => this.setState({ stTab: k }) }));
        r.emojis = EMOJI.map((e) => ({ e, pick: () => { if (this.state.page === 'dm') this.setState({ dmIn: (this.state.dmIn || '') + e }); else this.setState({ gIn: (this.state.gIn || '') + e }); } })); }
      r.tgbgCls = 'bgl';
      { const L = LS.get('lvl', null), top = LS.get('top', []) || [];
        if (pg === 'profile' && Date.now() - (this._lvQ || 0) > 120000) { this._lvQ = Date.now(); NB.send(JSON.stringify({ k: 'lvlq' })); }
        r.hasLvl = !!L; r.lvN = L ? String(L.lv) : '1'; r.lvXp = L ? tx.lv_xp.replace('{x}', String(L.xp)).replace('{n}', L.next ? String(L.next) : '—') : '';
        r.lvBar = L && L.next ? Math.max(3, Math.min(100, Math.round((L.xp - L.cur) * 100 / Math.max(1, L.next - L.cur)))) : 100;
        r.lvHow = tx.lv_how; r.hasTop = top.length > 0;
        r.topList = top.map((q, i) => ({ n: (i < 3 ? ['🥇', '🥈', '🥉'][i] : (i + 1) + '.') + ' ' + q[0], c: tx.lv_inv.replace('{n}', String(q[1])), lv: String(rkT(q[2])) })); }
      // 1.19: açar satyn almak
      r.isBuy = pg === 'buy'; if (r.isBuy) r.pageTitle = tx.p_buy;
      { const pay = LS.get('payInfo', null), plans = (pay && pay.p) || [[3, 15], [7, 30], [30, 100]], sel = s.buyD || plans[1][0];
        if (r.isBuy && (!pay || Date.now() - (pay.at || 0) > 600000) && Date.now() - (this._payQ || 0) > 60000) { this._payQ = Date.now(); NB.send(JSON.stringify({ k: 'payq' })); }
        r.buyPlans = plans.map(([d2, p2]) => ({ t: (d2 === 30 ? tx.bk_month : d2 + ' ' + tx.days), p: p2 + ' TMT', cls: d2 === sel ? 'bp-on' : '', pick: () => this.setState({ buyD: d2 }) }));
        r.payInfo = (pay && pay.i) || tx.by_noInfo;
        if (r.isBuy && pay && pay.pi) askImg('n', pay.pi);
        r.payPic = (pay && pay.pi && NI[pay.pi]) || ''; r.hasPayPic = !!r.payPic; r.zoomPay = () => this.setState({ zoom: r.payPic }); r.cpPay = () => { NB.copy(r.payInfo); this.say('✓ ' + tx.copied); };
        r.hasBuyImg = !!s.buyImg; r.noBuyImg = !s.buyImg; r.buyImg = s.buyImg || ''; r.onBuyImg = this.onBuyImg; r.buyN = s.buyN || ''; r.onBuyN = (e) => this.setState({ buyN: e.target.value.slice(0, 200) });
        r.buyBtn = s.buySending ? tx.g_sending : tx.by_send; r.buyGo = () => this.buySend(sel);
        r.buyOrders = (LS.get('orders', []) || []).slice(0, 5).map((o) => ({ t: '#' + o.id + ' · ' + (o.d === 30 ? tx.bk_month : o.d + ' ' + tx.days), st: o.st === 'ok' ? tx.or_ok : o.st === 'no' ? tx.or_no : tx.or_wait,
          cls: o.st === 'ok' ? 'on-g' : o.st === 'no' ? 'tk-closed' : 'tk-open' }));
        r.hasBuyOrders = r.buyOrders.length > 0; }
      // 1.19: tizlik synagy
      { const sp = s.spd || {}, run = !!sp.ph && sp.ph !== 'done' && sp.ph !== 'err', f1 = (v) => (v > 0 ? (v >= 100 ? Math.round(v) : v.toFixed(1)) : '—');
        r.spDl = f1(sp.ph === 'dl' ? sp.live : sp.dl); r.spUl = f1(sp.ph === 'ul' ? sp.live : sp.ul); r.spPing = sp.ping > 0 ? String(sp.ping) : '—';
        r.spBar = run ? Math.max(4, Math.round(((sp.ph === 'ul' ? 50 : 0) + (sp.p || 0) / 2))) : sp.ph === 'done' ? 100 : 0;
        r.spBtn = run ? tx.sp_run : sp.ph === 'done' ? tx.sp_again : tx.sp_go; r.spRunCls = run ? 'sp-run' : '';
        r.spVia = sp.ph ? (sp.via ? tx.sp_via : tx.sp_direct) : (s.st === 'on' ? tx.sp_via : tx.sp_direct);
        r.spErr = sp.ph === 'err'; r.spGo = () => { if (run) return; this.setState({ spd: { ph: 'ping', via: this.state.st === 'on' } }); NB.speed(); }; }
      if (Array.isArray(r.opts)) r.opts = r.opts.filter((o) => o.t !== tx.bg_t);
      // 1.19: gizli nyşan (Kalkulýator)
      if (Array.isArray(r.opts)) { const sn = r.opts.find((o) => o.t === tx.s_snd), dg = !!(s.disg != null ? s.disg : INFO.disg);
        if (sn) r.opts.push(Object.assign({}, sn, { i1: 'M7 3h10a2 2 0 0 1 2 2v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2z', i2: 'M8.5 7h7M9 12h.01M12 12h.01M15 12h.01M9 16h.01M12 16h.01M15 16h.01',
          t: tx.dg_t, s: dg ? tx.dg_on : tx.dg_off, aria: dg ? 'true' : 'false', swCls: dg ? 'sw-on' : '', d: '0.4',
          on: () => this.confirm(dg ? tx.dg_qOff : tx.dg_qOn, dg ? tx.dg_yOff : tx.dg_yOn, () => { NB.disguise(!dg); this.setState({ disg: !dg }); this.say(dg ? tx.dg_doneOff : tx.dg_doneOn); }) })); }
      // 1.20: derejeler — baş sahypadaky düwme, profil kartoçkasy, «Derejeler» sahypasy, nyşany ýakyndan görmek
      { const L = LS.get('lvl', null), t0 = L ? rkT(L.lv) : 1, xp = L ? +L.xp || 0 : 0, nx = t0 < 10 ? (L && L.next) || RK_L[t0] : 0;
        r.rkT = String(t0); r.rkName = tx['rk_n' + t0]; r.rkNcls = rkNc(t0); r.rkAria = tx.p_rank + ': ' + r.rkName + ' · ' + t0;
        r.rkXpT = tx.rk_pts.replace('{x}', t0 < 10 ? xp + ' / ' + nx : String(xp));
        r.rkHeroSub = tx.rk_lv.replace('{n}', String(t0)) + ' · ' + tx.rk_pts.replace('{x}', String(xp));
        r.rkNext = t0 >= 10 ? tx.rk_max : tx.rk_left.replace('{n}', tx['rk_n' + (t0 + 1)]).replace('{x}', String(Math.max(0, nx - xp)));
        if (!L) r.lvBar = 0;
        r.goRank = () => { this._rkBack = this.state.page; this.setState({ page: 'rank', menu: false, fan: false }); };
        r.isRank = pg === 'rank'; if (r.isRank) r.pageTitle = tx.p_rank;
        if (r.isRank && Date.now() - (this._lvQ || 0) > 120000) { this._lvQ = Date.now(); NB.send(JSON.stringify({ k: 'lvlq' })); }
        r.rkRows = RK_L.map((need, i) => { const t = i + 1, got = t <= t0, cur = t === t0;
          return { t: String(t), name: tx['rk_n' + t], ncls: got ? rkNc(t) : '', lk: cur ? 'fx' : got ? 'lite' : 'lock',
            need: cur ? tx.rk_now2 + ' · ' + tx.rk_pts.replace('{x}', String(xp)) : got ? tx.rk_got : tx.rk_need.replace('{x}', String(need)),
            pk: rkPk(t, tx), st: cur ? tx.rk_now : got ? '✓' : '🔒', stc: cur ? 'cur' : got ? 'ok' : 'lk', cls: cur ? 'rk-cur' : got ? 'rk-got' : 'rk-lk',
            open: () => this.setState({ rkm: { t, up: false } }) }; });
        const M = s.rkm, mt = M ? rkT(M.t) : 1, mgot = mt <= t0;
        r.rkmOn = !!M; r.rkmT = String(mt); r.rkmCls = M && M.up ? 'up' : mgot ? '' : 'lkd';
        r.rkmTitle = M && M.up ? tx.rk_upT : tx.rk_lv.replace('{n}', String(mt)); r.rkmName = tx['rk_n' + mt]; r.rkmNcls = rkNc(mt);
        r.rkmSub = M && M.up ? (M.days ? tx.rk_upGift.replace('{d}', String(M.days)) : tx.rk_upSub) : mgot ? tx.rk_gotL : tx.rk_wait.replace('{x}', String(RK_L[mt - 1]));
        r.rkmPk = rkPk(mt, tx); r.rkmBtn = M && M.up ? tx.rk_ok : tx.close; r.rkmX = () => this.setState({ rkm: null }); }
      // 1.20: gizli nyşan — baş sahypadaky kiçi düwme (Sazlamalardaky bilen birmeňzeş)
      { const dg = !!(s.disg != null ? s.disg : INFO.disg);
        r.dgCls = dg ? 'on' : ''; r.dgAria = dg ? 'true' : 'false';
        r.dgTap = () => this.confirm(dg ? tx.dg_qOff : tx.dg_qOn, dg ? tx.dg_yOff : tx.dg_yOn, () => { NB.disguise(!dg); this.setState({ disg: !dg }); this.say(dg ? tx.dg_doneOff : tx.dg_doneOn); }); }
      r.zoomOn = !!s.zoom; r.zoomSrc = s.zoom || ''; r.zoomClose = () => this.setState({ zoom: '' });
      r.onGPhoto = this.onGPhoto;
      // habarlar: eýesiniň habary altyn, surat
      let bi = 0;
      r.news = r.news.map((n) => {
        if (n.isTk) return n;
        const b = (s.bcast || [])[bi++] || {};
        if (b.img && !NI[b.img]) askImg('n', b.img);
        const btns = (b.btn || []).filter((k) => NBTN[k]).map((k) => ({ t: (NBTN[k][0] ? NBTN[k][0] + ' ' : '') + tx[NBTN[k][1]], go: () => { if (k === 'update') NB.update(); else if (k === 'vpn') { const st = J(NB.state(), {}).st; if (st !== 'on' && st !== 'wait') NB.connect(); this.setState({ page: 'main', menu: false }); } else this.setState({ page: NBTN[k][2], menu: false }); } }));
        const canDel = !!(s.admOn && admMe().role === 'f' && b.id);
        const pl = b.poll, pv = LS.get('votes', {}), mv = pv[b.id] ? pv[b.id].i : -1;
        let pc = pl ? pl.o.map((_, i) => +((pl.c || [])[i] || 0)) : [];
        if (pl && pv[b.id] && JSON.stringify(pv[b.id].base) === JSON.stringify(pl.c || [])) { pc = pc.slice(); pc[mv] = (pc[mv] || 0) + 1; if (pv[b.id].prev >= 0) pc[pv[b.id].prev] = Math.max(0, pc[pv[b.id].prev] - 1); }   // ses entek serwerde görünmedik
        const ptot = pc.reduce((a2, v) => a2 + v, 0);
        const pollOpts = pl ? pl.o.map((t2, i) => { const pct = ptot ? Math.round(pc[i] * 100 / ptot) : 0;
          return { t: t2, pct, pctT: (mv >= 0 ? pct + '%' : ''), cls: i === mv ? 'pon' : '', go: () => { if (i === mv) return; const v2 = LS.get('votes', {}); v2[b.id] = { i, prev: mv, base: pl.c || [] }; LS.set('votes', v2);
            NB.send(JSON.stringify({ k: 'vote', n: b.id, o: i })); this.say('📊 ' + tx.pl_ok); this.setState({ gTick: (this.state.gTick || 0) + 1 }); } }; }) : [];
        return Object.assign({}, n, { hasPoll: !!pl, pollQ: pl ? pl.q : '', pollOpts, pollTot: tx.pl_tot.replace('{n}', String(ptot)), canDel, del: () => this.confirm(tx.cf_ndel, '🗑 ' + tx.cf_yes, () => { act('ndel', { id: b.id }); NDEL[b.id] = true; this.setState({ bcast: (this.state.bcast || []).filter((x) => x.id !== b.id) }); }), hasBtn: btns.length > 0, btns, isO: true, tcls: 'goldtxt', date: b.time || '', hasImg: !!(b.img && NI[b.img]), img: (b.img && NI[b.img]) || '', zoom: () => this.setState({ zoom: NI[b.img] || '' }) });
      });
      r.news = r.news.map((n) => Object.assign({}, n, { parts: withKeys(n.parts, this) }));
      r.msgs = r.msgs.map((m) => Object.assign({}, m, { parts: withKeys(this.lk(m.t || ''), this) }));
      r.gRpOn = !!s.gRp && pg === 'global'; r.gRpN = s.gRp ? s.gRp.n : ''; r.gRpT = s.gRp ? s.gRp.t : ''; r.rpX = this.rpX;
      r.bcPollOn = !!s.bcPoll; r.bcPollCls = s.bcPoll ? 'chip-on' : ''; r.bcPollTog = () => this.setState({ bcPoll: !this.state.bcPoll, bcO: this.state.bcO || ['', '', '', ''] });
      r.bcQ = s.bcQ || ''; r.onBcQ = (e) => this.setState({ bcQ: e.target.value.slice(0, 120) });
      r.bcOpts = (s.bcO || ['', '', '', '']).map((v, i) => ({ v, ph: tx.pl_opt.replace('{n}', String(i + 1)), on: (e) => { const o2 = (this.state.bcO || ['', '', '', '']).slice(); o2[i] = e.target.value.slice(0, 40); this.setState({ bcO: o2 }); } }));
      r.bcBtns = Object.keys(NBTN).map((k) => { const on = (s.bcBtn || []).indexOf(k) >= 0;
        return { t: (NBTN[k][0] ? NBTN[k][0] + ' ' : '') + tx[NBTN[k][1]], p: on ? 'true' : 'false', cls: on ? 'chip-on' : '',
          tog: () => { const cur = this.state.bcBtn || []; this.setState({ bcBtn: on ? cur.filter((x) => x !== k) : cur.concat([k]).slice(-4) }); } }; });
      // baş ýazgy: öz suratym ýa-da logo; «Dostuňy çagyr»: ýükläp almak linki
      r.hdAv = s.photo || 'img/logo.png'; r.hasDl = !!INFO.dl; r.dlLink = INFO.dl || '';
      r.copyDl = () => { NB.copy(INFO.dl || ''); this.say('✓ ' + tx.copied); };
      r.onBcImg = this.onBcImg; r.bcHasImg = !!s.bcImg; r.bcImg = s.bcImg || ''; r.bcImgDel = () => this.setState({ bcImg: '' });
      const ava = (dev) => { const ph = dev === me1 ? s.photo : thumbOf(dev), nm = dev === me1 ? this.meName : nameOf(dev);
        if (!ph && dev !== me1 && !phAsked[dev]) { phAsked[dev] = 1; NB.getPhoto(dev); }
        return { photo: ph || '', hasPh: !!ph, noPh: !ph, bg: colorOf(dev), ini: ini(nm), name: nm, isO: roleOf(dev) === 'o', isA: roleOf(dev) === 'a', ncls: roleOf(dev) === 'o' ? 'goldtxt' : '' }; };
      // başga adamyň profili
      r.isUprof = pg === 'uprof' && !!s.upDev;
      if (r.isUprof) {
        const d = s.upDev, p = P2[d], st = (DMS[d] || {}).st || '', a = ava(d), mine = d === me1;
        const canDm = !mine && st !== 'blk' && ((p && p.dm) || !!DMS[d]);
        r.up = Object.assign(a, { photo: (p && p.ph) || a.photo, hasPh: !!((p && p.ph) || a.photo), noPh: !((p && p.ph) || a.photo), bgImg: bgUrl(p && p.bg),
          sub: a.isO ? tx.vip_o : a.isA ? tx.vip_a : '', canDm, noDm: !canDm, notMe: !mine,
          why: mine ? tx.dm_me : st === 'blk' ? tx.dm_blocked : !p ? tx.nk_wait : tx.dm_noKey,
          write: () => this.openDm(d), zoom: () => this.setState({ zoom: (p && p.ph) || a.photo || '' }),
          blockT: st === 'blk' ? '✅ ' + tx.dm_unblk : '🚫 ' + tx.dm_blk, block: () => this.blockDm(d) });
        let ul = mine ? (LS.get('lvl', {}) || {}).lv || 0 : 0;   // derejesi: Global chatdaky iň soňky habaryndan
        if (!mine) G.forEach((q) => { if (q.i === d && q.lv) ul = q.lv; });
        Object.assign(r.up, { hasRk: ul >= 1, rkT: String(rkT(ul)), rkName: tx['rk_n' + rkT(ul)], rkNcls: rkNc(rkT(ul)) });
        // 1.21: sessiz; eýesine — ID we bal/dereje bermek
        const own = myRole === 'o' || admMe().role === 'f', canGive = !!(s.admOn && isF), au2 = (A && A.us && A.us[d]) || null, ux = UPX[d];
        const xpK = ux ? ux.xp : au2 && au2.xp != null ? au2.xp : null, lvK = ux ? ux.lv : xpK != null ? RK_L.filter((q) => xpK >= q).length : ul;
        Object.assign(r.up, { hasMute: !mine && !!DMS[d], muteT: MUTE[d] ? tx.dm_unmute : tx.dm_mute, mute: () => this.muteDm(d),
          isOwnV: own && !mine, code: own && !mine && typeof NB.codeOf === 'function' ? NB.codeOf(d) || '—' : '—', cpId: () => { NB.copy(r.up.code); this.say('✓ ' + tx.copied); },
          lvNow: lvK ? tx.gv_now.replace('{n}', tx['rk_n' + rkT(lvK)]).replace('{l}', String(rkT(lvK))).replace('{x}', xpK != null ? String(xpK) : '?') : tx.gv_unk,
          canGive, needAdm: own && !mine && !canGive, goAdm: () => this.setState({ page: 'admin' }),
          giveX: () => { const x = parseInt(this.state.gvX, 10); if (!x) { this.say('⚠️ ' + tx.gv_bad); return; }
            this.confirm(tx.gv_qX.replace('{n}', a.name).replace('{x}', String(x)), '✅ ' + tx.gv_btn, () => { act('xpgive', { dev: d, x }); this.setState({ gvX: '' }); }, false); },
          lvBtns: RK_L.map((q, i) => ({ t: String(i + 1), name: tx['rk_n' + (i + 1)], cls: lvK === i + 1 ? 'on' : '',
            go: () => this.confirm(tx.gv_qLv.replace('{n}', a.name).replace('{r}', tx['rk_n' + (i + 1)]).replace('{l}', String(i + 1)), '✅ ' + tx.gv_lv, () => act('xpgive', { dev: d, lv: i + 1 }), false) })) });
      } else r.up = { name: '', photo: '', hasPh: false, noPh: true, bg: '', ini: '', bgImg: 'none', sub: '', canDm: false, noDm: false, notMe: false, why: '', isO: false, isA: false, ncls: '', hasRk: false, rkT: '1', rkName: '', rkNcls: '', hasMute: false, muteT: '', mute: null, isOwnV: false, code: '', cpId: null, lvNow: '', canGive: false, needAdm: false, goAdm: null, giveX: null, lvBtns: [] };
      r.gvX = s.gvX || ''; r.onGvX = (e) => this.setState({ gvX: String(e.target.value || '').replace(/[^0-9-]/g, '').slice(0, 7) });
      // hususy habarlar sanawy
      r.isDms = pg === 'dms';
      const rows = Object.keys(DMS).filter((d) => d !== me1).sort((a, b) => (DMS[b].lt || 0) - (DMS[a].lt || 0));
      r.dmEmpty = !rows.length;
      r.dmRows = rows.map((d, i) => { const x = DMS[d], m = x.msgs.filter((q) => !isCtl(q)).pop(), av = ava(d);
        return Object.assign(av, { d: (i * 0.04).toFixed(2), isReq: x.st === 'in', isBlk: x.st === 'blk', hasUn: (x.un || 0) > 0, un: String(x.un || 0),
          last: m ? dmPrev(m, tx, me1) : x.ls ? x.ls : x.st === 'in' ? tx.dm_req : '', lastCls: (x.un || 0) > 0 ? 'dmlast-un' : '',
          dev: d, muted: !!MUTE[d], unCls: MUTE[d] ? 'mut' : '',
          open: () => { if (Date.now() - (window.__lpDm || 0) < 900) return; this.openDm(d); } }); });
      r.dmHint = rows.length > 0;
      // 1.21: söhbeti açmazdan görmek — okaldy belligi iberilmeýär, okalmadyk san üýtgemeýär
      r.pkOn = !!s.dmPeek;
      if (r.pkOn) { const d = s.dmPeek, x = DMS[d] || { msgs: [] }, list = x.msgs.filter((q) => !isCtl(q)).slice(-15);
        r.pk = Object.assign(ava(d), { empty: !list.length, emptyT: x.ls || tx.dm_peekEmpty,
          msgs: list.map((m) => { const mn = m.f === me1;
            if (m.sys) return { cls: 'dmm-s', bcls: '', t: m.sys === 'acc' ? tx.dm_acced : m.sys === 'key' ? tx.dm_keyChg.replace('{n}', nameOf(d)) : m.sys, hasImg: false, img: '', isSt: false, st: '', time: '' };
            return { cls: mn ? 'dmm-me' : 'dmm-o', bcls: mn ? 'gb-me' : 'gb-o', t: m.x || '', hasImg: !!m.ph, img: m.ph || '', isSt: !!m.st, st: m.st || '', time: this.hm((m.t || 0) * 1000 || now) }; }),
          muteT: MUTE[d] ? tx.dm_unmute : tx.dm_mute, mute: () => this.muteDm(d), open: () => { this.setState({ dmPeek: null }); this.openDm(d); } });
      } else r.pk = { name: '', photo: '', hasPh: false, noPh: true, bg: '', ini: '', ncls: '', empty: true, emptyT: '', msgs: [], muteT: '', mute: null, open: null };
      r.pkX = () => this.setState({ dmPeek: null });
      // hususy habar otagy
      r.isDm = pg === 'dm' && !!s.dmPeer;
      if (r.isDm) {
        const d = s.dmPeer, x = DMS[d] || { st: '', msgs: [] }, p = P2[d], mineN = x.msgs.filter((m) => m.f === me1 && !m.sys && !isCtl(m)).length;
        r.dp = ava(d); r.dmProf = () => this.openProf(d);
        r.dmIsReq = x.st === 'in';
        r.dmReqText = tx.dm_reqText.replace('{n}', r.dp.name);
        const noKey = !x.st && p && !p.dm;
        const waitMax = x.st === 'out' && mineN >= 3;
        r.dmCanWrite = x.st !== 'blk' && x.st !== 'in' && !noKey && !waitMax;
        r.dmNoWrite = !r.dmCanWrite && !r.dmIsReq;
        r.dmNoWriteT = x.st === 'blk' ? tx.dm_blocked : noKey ? tx.dm_noKey : tx.dm_wait.replace('{n}', r.dp.name);
        const RXD = rxAgg(x.msgs);
        const nowS = Date.now() / 1000, peerRd = x.msgs.reduce((a, m) => (m.f === d && m.rd > a ? m.rd : a), 0),
          typing = x.msgs.some((m) => m.f === d && m.ty && nowS - (m.t || 0) < 7);
        if (typing && !this._tyT) this._tyT = setTimeout(() => { this._tyT = null; this.setState({ dmTick: (this.state.dmTick || 0) + 1 }); }, 3000);
        r.dmSub = typing ? tx.dm_typing : tx.dm_e2e; r.dmSubCls = typing ? 'tytxt' : '';
        r.dmMsgs = x.msgs.filter((m) => !isCtl(m)).map((m) => {
          if (m.sys) return { id: m.id, hasRp: false, rpN: '', rpT: '', cls: 'dmm-s', isSys: true, isMsg: false, t: m.sys === 'acc' ? tx.dm_acced : m.sys === 'key' ? tx.dm_keyChg.replace('{n}', r.dp.name) : m.sys, bcls: '', hasImg: false, img: '', zoom: null, isSt: false, st: '', parts: [], time: '' };
          const mine2 = m.f === me1;
          return { id: m.id, cls: mine2 ? 'dmm-me' : 'dmm-o', bcls: mine2 ? 'gb-me' + (!m.pend && (m.t || 0) <= peerRd ? ' rd' : ' nrd') : 'gb-o', isSys: false, isMsg: true, t: '', hasImg: !!m.ph, img: m.ph || '', zoom: () => this.setState({ zoom: m.ph }),
            isSt: !!m.st, st: m.st || '', parts: m.x ? withKeys(this.lk(m.x), this) : [], time: this.hm((m.t || 0) * 1000 || now) + (m.pend ? ' ⏳' : ''),
            hasRp: !!(m.rp && m.rp.n), rpN: m.rp ? m.rp.n : '', rpT: m.rp ? m.rp.t : '',
            rx: rxList(RXD, m.id, me1, (e) => this.dmReact(d, m.id, e)), hasRx: !!RXD[m.id] && Object.keys(RXD[m.id]).length > 0,
            rxOpen: s.rxFor === m.id, rxPick: RX_E.map((e) => ({ e, go: () => { this.setState({ rxFor: null }); this.dmReact(d, m.id, e); } })), rpGo: () => this.replyTo(m.id) };
        });
        r.dmRpOn = !!s.dmRp; r.dmRpN = s.dmRp ? s.dmRp.n : ''; r.dmRpT = s.dmRp ? s.dmRp.t : '';
        r.dmIn = s.dmIn || ''; r.onDmIn = this.onDmIn; r.dmSendT = this.dmSendT; r.onDmPhoto = this.onDmPhoto; r.dmRef = this.dmRef;
        r.dmAccept = () => this.acceptDm(d); r.dmBlock = () => this.blockDm(d);
      } else Object.assign(r, { dmSub: '', dmSubCls: '', dmRpOn: false, dp: { name: '', photo: '', hasPh: false, noPh: true, bg: '', ini: '', isO: false, isA: false, ncls: '' }, dmIsReq: false, dmCanWrite: false, dmNoWrite: false, dmMsgs: [] });
      // ýörite adamlar
      r.isVip = pg === 'vip';
      r.vipRows = Object.keys(INFO.roles || {}).sort((a, b) => (roleOf(a) === 'o' ? 0 : 1) - (roleOf(b) === 'o' ? 0 : 1)).map((d, i) => Object.assign(ava(d), {
        cls: roleOf(d) === 'o' ? 'vo' : '', role: roleOf(d) === 'o' ? tx.vip_o : tx.vip_a, d: (i * 0.06).toFixed(2), open: () => this.openProf(d) }));
      // sahypa ady we menýu
      if (pg === 'uprof') r.pageTitle = tx.p_uprof; else if (pg === 'dms') r.pageTitle = tx.p_dms; else if (pg === 'vip') r.pageTitle = tx.p_vip; else if (pg === 'dm') r.pageTitle = r.dp.name;
      const dmUn = Object.keys(DMS).filter((d) => !MUTE[d]).reduce((a, d) => a + (DMS[d].un || 0) + (DMS[d].st === 'in' && !(DMS[d].seen) ? 1 : 0), 0);
      r.menuUn = dmUn > 0; r.menuUnT = dmUn > 9 ? '9+' : String(dmUn);
      const mk = (k, t, i1, i2, badge, bt) => ({ badge, bt, bc: '', t, i1, i2, d: '0.1', cls: pg === k ? 'mi-on' : '', ic: pg === k ? '#6FDB9C' : '#E0B04A', go: () => this.setState({ page: k, menu: false }) });
      const gi = r.menuItems.findIndex((m) => m.t === tx.p_global);
      r.menuItems.splice(gi + 1, 0, mk('dms', tx.p_dms, 'M4 6h16v10H8l-4 4z', 'M8 10h8M8 13h5', dmUn > 0, String(dmUn)),
        mk('vip', tx.p_vip, 'M3 8l4 4 5-7 5 7 4-4-2 11H5z', 'M5 21h14', false, ''));
      // 1.22: tegelek baýdaklar
      ['cur', 'offCard', 'sCur'].forEach((k) => { if (r[k]) r[k] = withFc(r[k]); });
      ['srvList', 'gList'].forEach((k) => { if (Array.isArray(r[k])) r[k] = r[k].map(withFc); });
      // 1.23: eýesi serweri basyp saklap 30 sekunt gizleýär (diňe öz ekranynda)
      window.__isOwn = myRole === 'o';
      r.isOwnP = myRole === 'o' && pg === 'servers';
      r.fakePing = () => { const f = {}; SV.forEach((v) => { f[v.id] = 100 + Math.floor(Math.random() * 71); }); this.setState({ pings: f, testing: false }); this.say(tx.fp_ok); };
      { const H = window.__svHide || {}, tn = Date.now(); ['srvList', 'gList'].forEach((k) => { if (Array.isArray(r[k])) r[k] = r[k].filter((x) => !(H[x.name] > tn)); }); r.hasG = Array.isArray(r.gList) && r.gList.length > 0; }
      { const all = SV.filter((v) => !v.game).map((v) => fcc(v.f)).filter(Boolean), uq = all.filter((c, i) => all.indexOf(c) === i);
        r.svFl = uq.slice(0, 9).map((fc) => ({ fc })); r.svFlMore = uq.length > 9; r.svFlNone = !uq.length; }
      r.langFc = fcc(r.langFlag) || 'tm'; if (Array.isArray(r.langs)) r.langs = r.langs.map((l) => Object.assign({}, l, { fc: fcc(l.flag) || 'tm' }));
      // 1.22: eýesi baş sahypada dereje ýa-da OWNER saýlap bilýär
      { const isOw = myRole === 'o', on = isOw && !!LS.get('ownTag', false);
        r.ownTagOn = on && pg === 'main'; r.rkPillOn = !on;
        if (isOw && Array.isArray(r.opts)) { const sn = r.opts.find((o) => o.t === tx.s_snd);
          if (sn) r.opts.push(Object.assign({}, sn, { i1: 'M3 8l4 4 5-7 5 7 4-4-2 11H5z', i2: 'M5 21h14', t: tx.ow_t, s: on ? tx.ow_on : tx.ow_off, aria: on ? 'true' : 'false', swCls: on ? 'sw-on' : '', d: '0.45',
            on: () => { LS.set('ownTag', !on); this.setState({ owTick: (this.state.owTick || 0) + 1 }); } })); } }
      r.dgLbl = r.dgCls === 'on' ? tx.dg_btnOff : tx.dg_btn;
      r.dgOnI = r.dgCls === 'on'; r.dgOffI = !r.dgOnI; r.dgW = String((DGW[s.lang] || DGW.tk)[r.dgOnI ? 1 : 0]);
      // 1.22: derejäni synap görmek (chatda we baş sahypada)
      { const mt = rkT(r.rkmT); r.rkmFr = mt >= 3 ? 'fr' + mt : ''; r.rkmNm = rkNm(mt); r.rkmMe = this.meName || '…'; r.rkmIni = ini(this.meName || '?'); r.rkmBg = '#E0B04A'; r.rkmHasB = mt >= 2; }
      // 1.22: admin — «Açar satyn al» sahypasynyň töleg maglumaty
      { const ap = (A && A.pay) || { t: '', img: '' };
        if (ap.img && s.admTab === 'bot') askImg('n', ap.img);
        r.payT = s.payT != null ? s.payT : ap.t; r.onPayT = (e) => this.setState({ payT: String(e.target.value || '').slice(0, 1500) });
        r.payEdImg = s.payImg || (!s.payNoImg && ap.img && NI[ap.img]) || ''; r.hasPayEd = !!r.payEdImg;
        r.onPayImg = this.onPayImg; r.payImgDel = () => this.setState({ payImg: '', payNoImg: true });
        r.paySave = () => { const t = String(r.payT || '').trim(), im = this.state.payImg;
          if (im) { const id = Math.random().toString(36).slice(2, 10), N = Math.ceil(im.length / 4000);
            for (let i = 0; i < N; i++) act('imgc', { id, i, n: N, d: im.slice(i * 4000, (i + 1) * 4000) });
            act('payset', { t, img: id }); } else act('payset', Object.assign({ t }, this.state.payNoImg ? { noimg: true } : {}));
          this.say(tx.k_wait); }; }
      if (s.admOn && isF) r.gMsgs = r.gMsgs.map((g) => Object.assign({}, g, { canDel: true, del: () => this.confirm(tx.cf_gdel, '🗑 ' + tx.cf_yes, () => { act('gdel', { id: g.gk }); gDel[g.gk] = true; this.setState({ gTick: (this.state.gTick || 0) + 1 }); }) }));
      return r;
    };
  };

  function szKB(k) { return k >= 1048576 ? (k / 1048576).toFixed(2) + ' GB' : k >= 1024 ? (k / 1024).toFixed(1) + ' MB' : Math.round(k) + ' KB'; }

  window.DC_READY = function (C) {
    const now = Date.now();
    if (!LS.get('first')) LS.set('first', now);
    // ýatda saklanýanlar
    const keep = ['usageH', 'favs', 'read', 'chat', 'tkId', 'myTkSt', 'fb', 'human', 'photo', 'rateCount', 'rateNext', 'tkNews', 'svTab', 'uMode', 'refSet', 'invites', 'warnHidden', 'usage', 'hist2', 'seenNews'];
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
    // ---- 1.16: nik (bot barlaýar: iki adam bir nigi ulanyp bilmeýär) ----
    Object.assign(C.state, { pbg: LS.get('pbg', ''), nkIn: null, nkSt: '', bgMode: 'auto' });
    C.onNk = (e) => C.setState({ nkIn: String(e.target.value || '').slice(0, 20), nkSt: '' });
    C.saveNk = (n0) => {
      const n = String(typeof n0 === 'string' ? n0 : (C.state.nkIn == null ? C.meName : C.state.nkIn)).replace(/\s+/g, ' ').trim();
      if (!/^[\p{L}\p{N}_ .\-]{3,20}$/u.test(n)) { C.setState({ nkSt: 'bad' }); return; }
      if (C._isBan && C._isBan()) return;
      C._nkCustom = typeof n0 !== 'string';   // 1.24: diňe özi ýazan nik (tötänleýin däl) — mugt wagt 1,5 sagat
      C.setState({ nkSt: 'wait', nkIn: n }); NB.send(JSON.stringify({ k: 'nick', n }));
    };
    C.reroll = ((f) => () => { const old = C.meName; f(); const cand = C.meName; C.meName = old; C.saveNk(cand); })(C.reroll);
    // ---- profil suraty (512 — ulaldyp görmek üçin) we fon ----
    C.onPhoto = (e) => { const f = fileOf(e); if (!f) return; shrink(f, 512, 0.82, (d) => { if (d) C.setState({ photo: d }); }, true); e.target.value = ''; };
    C.onBg = (e) => { const f = fileOf(e); if (!f) return; shrink(f, 900, 0.7, (d) => { if (d) { C.setState({ pbg: d }); LS.set('pbg', d); } else C.say(C.T()[C.state.lang].ph_big); }); e.target.value = ''; };
    C.delBg = () => { C.setState({ pbg: '' }); LS.set('pbg', ''); };
    // ---- profil / hususy habarlar ----
    J(NB.dmList(), []).forEach((q) => { if (q.p) DMS[q.p] = Object.assign(DMS[q.p] || { msgs: [], un: 0 }, { st: q.st || '', n: q.n || '' }); });
    { const meta = LS.get('dmMeta', {}); Object.keys(meta).forEach((d) => { const x = DMS[d] || (DMS[d] = { msgs: [], un: 0, st: '' }); x.lt = meta[d].lt || 0; x.un = meta[d].un || 0; x.n = x.n || meta[d].n || ''; x.seen = !!meta[d].seen; x.ls = meta[d].ls || ''; }); }
    const saveMeta = () => { const m = {}; Object.keys(DMS).forEach((d) => { m[d] = { lt: DMS[d].lt || 0, un: DMS[d].un || 0, n: DMS[d].n || '', seen: !!DMS[d].seen, ls: DMS[d].ls || '' }; }); LS.set('dmMeta', m); };
    C._saveMeta = saveMeta;
    const tick = () => C.setState({ dmTick: (C.state.dmTick || 0) + 1 });
    C.openProf = (dev) => {
      if (!dev) return;
      if (dev === INFO.dev) { C.setState({ page: 'profile', menu: false }); return; }
      if (C.state.page !== 'uprof') C._back = C.state.page;
      C.setState({ page: 'uprof', upDev: dev, menu: false }); NB.prof(dev);
    };
    C.openDm = (dev) => {
      if (!dev || dev === INFO.dev) return;
      const x = DMS[dev] || (DMS[dev] = { msgs: [], un: 0, st: '' }); x.un = 0; x.seen = true; saveMeta();
      if (C.state.page !== 'dm') C._dmBack = C.state.page;
      C.setState({ page: 'dm', dmPeer: dev, dmIn: '', menu: false }); NB.dmOpen(dev); if (!P2[dev]) NB.prof(dev);
    };
    C.muteDm = (dev) => { const tx = C.T()[C.state.lang]; if (MUTE[dev]) delete MUTE[dev]; else MUTE[dev] = 1; LS.set('dmMute', MUTE); C.say(MUTE[dev] ? '🔇 ' + tx.dm_mutedOk : '🔔 ' + tx.dm_unmutedOk); tick(); };
    C.peekDm = (dev) => { if (!dev || !DMS[dev]) return; C.setState({ dmPeek: dev }); NB.dmOpen(dev); };   // doly sanaw gelýär, «okaldy» iberilmeýär
    C.acceptDm = (dev) => { NB.dmSt(dev, 'acc'); (DMS[dev] || {}).st = 'acc'; tick(); };
    C.blockDm = (dev) => {
      const x = DMS[dev] || (DMS[dev] = { msgs: [], un: 0, st: '' }), tx = C.T()[C.state.lang];
      if (x.st === 'blk') { NB.dmSt(dev, 'del'); x.st = x.msgs.some((m) => m.f === dev) ? 'in' : ''; if (x.st) NB.dmSt(dev, 'in'); tick(); return; }
      C.confirm(tx.dm_blk + '?', '🚫 ' + tx.dm_blk, () => { NB.dmSt(dev, 'blk'); x.st = 'blk'; if (C.state.page === 'dm') C.setState({ page: 'dms' }); else tick(); });
    };
    let tyAt = 0;
    C.onDmIn = (e) => { const v = String(e.target.value || '').slice(0, 2000), peer = C.state.dmPeer, x = peer && DMS[peer];
      if (v && x && x.st === 'acc' && Date.now() - tyAt > 5000) { tyAt = Date.now(); NB.dmSend(peer, JSON.stringify({ ty: 1 }), C.meName); }   // «ýazýar…»
      C.setState({ dmIn: v }); };
    const dmPush = (dev, j) => {
      if (C._isBan && C._isBan()) return;
      if (C.state.dmRp && !j.sys) { j = Object.assign({ rp: C.state.dmRp }, j); C.setState({ dmRp: null }); }
      const x = DMS[dev] || (DMS[dev] = { msgs: [], un: 0, st: '' }); if (!x.st) x.st = 'out';
      x.msgs = x.msgs.concat([Object.assign({ id: 'p' + Date.now() + Math.random(), f: INFO.dev, t: Date.now() / 1000, pend: true }, j)]); x.lt = Date.now(); saveMeta();
      NB.dmSend(dev, JSON.stringify(j), C.meName); tick();
    };
    C.dmSendT = () => { const t = (C.state.dmIn || '').trim(); if (!t || !C.state.dmPeer) return; dmPush(C.state.dmPeer, { x: t }); C.setState({ dmIn: '' }); };
    C.onDmPhoto = (e) => { const f = fileOf(e), peer = C.state.dmPeer; if (!f || !peer) return; fitShrink(f, 1280, 140000, (d) => { if (!d) { C.say(C.T()[C.state.lang].ph_big); return; } dmPush(peer, { ph: d }); }); e.target.value = ''; };
    C.dmRef = (el) => { C.dmEl = el; if (el) setTimeout(() => { el.scrollTop = 1e6; }, 30); };
    // ---- Global chat: link ýok, surat, stiker, sögünç gadaganlygy ----
    C.stToggle = () => C.setState({ stOn: !C.state.stOn });
    const gBlocked = () => {
      const until = LS.get('muteUntil', 0);
      if (until > Date.now()) { C.say('🔇 ' + C.T()[C.state.lang].g_muted.replace('{m}', String(Math.ceil((until - Date.now()) / 60000)))); return true; }
      return false;
    };
    const isBan = () => { INFO = J(NB.info(), INFO); if (INFO.uban) { C.say('⛔ ' + C.T()[C.state.lang].ub_msg); return true; } return false; };
    C._isBan = isBan;
    const gSend = (j) => {
      if (isBan() || gBlocked()) return false;
      const o = Object.assign({ n: C.meName, t: '', lv: LS.get('lvl', {}).lv || 0 }, j); if (C.state.gRp) o.rp = C.state.gRp;
      NB.gsend2(JSON.stringify(o)); C.setState({ gRp: null });
      if (!o.ph && (o.t || o.st)) { LGM.push({ id: 'l' + Date.now(), i: INFO.dev, n: o.n, t: o.t || '', st: o.st || '', rp: o.rp || null, time: Date.now() / 1000, pend: true }); tick(); }
      return true;
    };
    C.gReact = (key, e) => {
      if (/^l\d/.test(key) || isBan() || gBlocked()) return;   // entek gitmedik habara tepki ýok
      const me = INFO.dev, cur = (rxAgg(G.concat(LRX))[key] || {})[me], off = cur === e;
      LRX.push({ re: key, e, off, i: me, time: Date.now() / 1000 });
      NB.gsend2(JSON.stringify({ n: C.meName, t: '', re: key, e, off })); tick();
    };
    C.dmReact = (dev, key, e) => {
      if (C._isBan && C._isBan()) return;
      const x = DMS[dev]; if (!x) return; const cur = (rxAgg(x.msgs)[key] || {})[INFO.dev], off = cur === e, j = { re: key, e, off };
      x.msgs = x.msgs.concat([Object.assign({ id: 'p' + Date.now() + Math.random(), f: INFO.dev, t: Date.now() / 1000, pend: true }, j)]);
      NB.dmSend(dev, JSON.stringify(j), C.meName); tick();
    };
    C.onBuyImg = (e) => { const f = fileOf(e); if (!f) return; e.target.value = ''; fitShrink(f, 1280, 108000, (d) => { if (d) C.setState({ buyImg: d }); else C.say(C.T()[C.state.lang].ph_big); }); };
    C.buySend = (d) => {
      const s0 = C.state, tx = C.T()[s0.lang];
      if (s0.buySending) return; if (!s0.buyImg) { C.say('📎 ' + tx.by_needImg); return; }
      C.setState({ buySending: true }); NB.buy(JSON.stringify({ d, ph: s0.buyImg, n: (s0.buyN || '').trim() }));
    };
    // alynty: habary saga süýşürmek → jogap
    C.replyTo = (id) => {
      const s0 = C.state;
      if (s0.page === 'global') { const m = G.find((q) => q.id === id); if (m) C.setState({ gRp: rpOf(m, m.i === INFO.dev ? C.meName : m.n) }); }
      else if (s0.page === 'dm' && s0.dmPeer) { const x = DMS[s0.dmPeer], m = x && x.msgs.find((q) => q.id === id); if (m && !m.sys) C.setState({ dmRp: rpOf(m, m.f === INFO.dev ? C.meName : nameOf(s0.dmPeer)) }); }
    };
    C.rpX = () => C.setState({ gRp: null, dmRp: null });
    C.pickSticker = (em) => { C.setState({ stOn: false }); if (C.state.page === 'dm' && C.state.dmPeer) dmPush(C.state.dmPeer, { st: em }); else gSend({ st: em }); };
    C.onGPhoto = (e) => {
      const f = fileOf(e); if (!f) return; e.target.value = '';
      if (gBlocked()) return;
      fitShrink(f, 1280, 108000, (d) => { const tx = C.T()[C.state.lang]; if (!d) { C.say(tx.ph_big); return; } if (gSend({ ph: d })) C.say(tx.g_sending); });
    };
    // admin: habara surat
    C.onPayImg = (e) => { const f = fileOf(e); if (!f) return; shrink(f, 1100, 0.8, (d) => { if (d) C.setState({ payImg: d, payNoImg: false }); else C.say(C.T()[C.state.lang].ph_big); }); e.target.value = ''; };
    C.onBcImg = (e) => { const f = fileOf(e); if (!f) return; shrink(f, 960, 0.65, (d) => { if (d) C.setState({ bcImg: d }); else C.say(C.T()[C.state.lang].ph_big); }); e.target.value = ''; };
    // yza: täze sahypalar
    const gb0 = C.goBack;
    C.goUnlim = () => C.setState({ page: 'invite', menu: false });
    C.goBack = () => {
      const p = C.state.page;
      if (p === 'adm_kd') { C.setState({ page: 'adm_k' }); return; }
      if (p === 'adm_x' || p === 'adm_or') { C.setState({ page: 'admin', admTab: 'bot' }); return; }
      if (p === 'dm') { C.setState({ page: C._dmBack && C._dmBack !== 'dm' && C._dmBack !== 'main' ? C._dmBack : 'dms' }); return; }
      if (p === 'uprof') { C.setState({ page: C._back && C._back !== 'uprof' ? C._back : 'global' }); return; }
      if (p === 'rank') { C.setState({ page: C._rkBack && C._rkBack !== 'rank' ? C._rkBack : 'main' }); return; }
      gb0();
    };
    C.fbUp = () => { C.setState({ fb: 'up' }); NB.send(JSON.stringify({ k: 'fb', v: 'up', tid: C.state.tkId })); };
    C.fbDown = () => { C.setState({ fb: 'down' }); NB.send(JSON.stringify({ k: 'fb', v: 'down', tid: C.state.tkId })); };
    C.sendG = () => {
      const t = C.state.gIn.trim().slice(0, 600); if (!t) return;
      const tx = C.T()[C.state.lang];
      if (LINK_RE.test(t)) { C.say('🚫 ' + tx.g_link); return; }
      if (!gSend({ t })) return;
      C.setState({ gIn: '' });
      if (C.state.st !== 'on' && !INFO.fs) C.say(tx.q_wait);
    };
    const sr0 = C.sendRate;
    C.sendRate = () => {
      const s = C.state; if (!s.stars || s.rateCount >= 3) return sr0();
      const tx = C.T()[s.lang], tg = [tx.r_t1, tx.r_t2, tx.r_t3, tx.r_t4, tx.r_t5].filter((_, i) => s.tags[i]);
      NB.send(JSON.stringify({ k: 'rate', n: s.stars, tags: tg, c: s.comment.slice(0, 500), nick: C.meName }));
      sr0();
    };
    // admin paneli: «Admine ýaz» adyna 10 gezek basmak (tasarymdaky ýaly) → açar söz
    if (INFO.adm) Object.assign(C.state, { admOn: true, admRole: (INFO.admMe || {}).role || 'h' });
    C.admLogin = () => {
      const s = C.state, tx = C.T()[s.lang];
      if (s.admLock > Date.now()) { C.setState({ admErr: tx.ad_locked.replace('{s}', String(Math.ceil((s.admLock - Date.now()) / 1000))) }); return; }
      const pw = s.admPw.replace(/\s+/g, '').toUpperCase();
      if (pw.length < 2) { C.setState({ admErr: tx.ad_bad, admShakeK: s.admShakeK + 1 }); return; }
      act('login', { pw }); C.setState({ admPw: '', admErr: tx.k_wait, admLogging: true });
    };
    C.admExit = () => { act('logout'); admPend = 0; A = null; C.setState({ admOn: false, page: 'main' }); C.say('🔒 ' + C.T()[C.state.lang].ad_closed); };
    C.tkToggle = () => {
      const t = A && A.tk.find((x) => x.id === C.state.admT); if (!t) return;
      act(t.st === 'closed' ? 'reopen' : 'close', { tid: t.id }); t.st = t.st === 'closed' ? 'open' : 'closed'; C.setState({ admTick: (C.state.admTick || 0) + 1 });
    };
    C.banToggle = () => { const d = C.state.admU, u = A && A.us[d]; if (!u) return; act('ban', { dev: d, on: !u.ban }); u.ban = !u.ban; C.setState({ admTick: (C.state.admTick || 0) + 1 }); };
    C.onQIn = (e) => C.setState({ qIn: String(e.target.value || '').trim().slice(0, 500) });
    C.qAddB = () => { const u = (C.state.qIn || '').trim(); if (!/^https?:\/\/\S{8,}/.test(u)) return; act('qadd', { u }); C.setState({ qIn: '' }); C.say(C.T()[C.state.lang].k_wait); };
    C.onXIn = (e) => C.setState({ xIn: String(e.target.value || '').slice(0, 20000) });
    C.onXChIn = (e) => C.setState({ xChIn: String(e.target.value || '').slice(0, 60) });
    C.xAdd = () => { const t = (C.state.xIn || '').trim(); if (!t) return; act('xadd', { t }); C.setState({ xIn: '' }); C.say(C.T()[C.state.lang].k_wait); };
    C.xChAdd = () => { const ch = (C.state.xChIn || '').trim(); if (!ch) return; act('chadd', { ch }); C.setState({ xChIn: '' }); C.say(C.T()[C.state.lang].k_wait); };
    C.onKdLb = (e) => C.setState({ kdLb: String(e.target.value || '').slice(0, 40) });
    C.onKdDays = (e) => C.setState({ kdDays: String(e.target.value || '').replace(/\D/g, '').slice(0, 4) });
    C.onKdN = (e) => C.setState({ kdN: String(e.target.value || '').replace(/\D/g, '').slice(0, 4) });
    C.onKCustom = (e) => C.setState({ kCustom: String(e.target.value || '').replace(/\D/g, '').slice(0, 4) });
    C.onKN = (e) => C.setState({ kN: String(e.target.value || '').replace(/\D/g, '').slice(0, 4) });
    const kDays = () => { const c = parseInt(C.state.kCustom, 10); return c > 0 ? Math.min(3650, c) : C.state.kDay; };
    C.mkKey = () => { act('mkkey', { d: kDays(), n: Math.max(1, Math.min(1000, parseInt(C.state.kN, 10) || 1)) }); C.say(C.T()[C.state.lang].k_wait); };
    C.sendBc = () => {
      const po_ = ((C.state.bcO || []).map((q) => String(q || '').trim()).filter(Boolean)).slice(0, 4), poll = C.state.bcPoll && po_.length >= 2 ? { poll: { q: String(C.state.bcQ || '').trim(), o: po_ } } : {};
      const s = C.state, tx = C.T()[s.lang], t = s.bcT.trim(), x = s.bcX.trim();
      if (!t || !x) { C.say(tx.ad_bcNeed); return; }
      const im = s.bcImg;
      if (im) {   // surat 4 KB-lyk böleklere bölünýär (bot ýygnap Firestore-a ýazýar)
        const id = Math.random().toString(36).slice(2, 10), N = Math.ceil(im.length / 4000);
        for (let i = 0; i < N; i++) act('imgc', { id, i, n: N, d: im.slice(i * 4000, (i + 1) * 4000) });
        act('bc', Object.assign({ t, x, img: id, btn: s.bcBtn || [] }, poll));
      } else act('bc', Object.assign({ t, x, btn: s.bcBtn || [] }, poll));
      C.setState({ bcT: '', bcX: '', bcImg: '', bcBtn: [], bcPoll: false, bcQ: '', bcO: ['', '', '', ''] }); C.say(tx.k_wait);
    };
    C.aiToggle = () => { act('ai', { on: !C.state.aiOn }); C.setState({ aiOn: !C.state.aiOn }); };
    C.aiAdd = () => { const t = C.state.aiIn.trim(); if (!t || !A) return; act('note', { t }); A.notes = (A.notes || []).concat([t]); C.setState({ aiIn: '' }); C.say('🤖 ' + C.T()[C.state.lang].ai_added); };
    C.sysToggle = () => { const on = !C.state.sysOn, tx = C.T()[C.state.lang]; act('sys', { on }); C.setState({ sysOn: on }); C.say(on ? '▶️ ' + tx.bt_started : '⏸ ' + tx.bt_stopped); };
    C.botUpd = () => { if (C.state.bUpd) return; act('upd'); C.setState({ bUpd: true }); };
    C.confirm = (text, ok, fn, danger) => { C._cfFn = fn; C.setState({ cf: { text, ok, danger: danger !== false } }); };
    C.cfNo = () => { C._cfFn = null; C.setState({ cf: null }); };
    C.cfYes = () => { const f = C._cfFn; C._cfFn = null; C.setState({ cf: null }); if (f) f(); };
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

  let saveAt = 0, lastPick = null, lastLang = null, lastPage = null, lastDmW = null;
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
      up.hasKey = n.left < 0; up.left = n.left >= 0 ? n.left : 0; up.kexp = n.kexp; up.upd = n.upd; up.dl = n.dl;
      up.dn = n.dn / 1024; up.up = n.up / 1024; up.tot = n.rxT / 1024; up.totUp = n.txT / 1024; up.onAt = n.onAt;
      if (st === 'on') {
        up.hist = s.hist.concat([up.dn]).slice(-40);
        const kb = (n.rxT + n.txT) / 1024, d = Math.max(0, kb - lastRx); lastRx = kb; sessKB = kb;
        if (d > 0) {
          const U = Object.assign({}, s.usage), k = dayKey(now); U[k] = (U[k] || 0) + d; up.usage = U;
          const UH = {}, hk = k + '-' + new Date(now).getHours(), old = s.usageH || {};
          Object.keys(old).forEach((q) => { if (q.indexOf(k + '-') === 0) UH[q] = old[q]; });   // diňe şu gün
          UH[hk] = (UH[hk] || 0) + d; up.usageH = UH;
        }
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
    if (lastPage !== s2.page) { NB.gwatch(s2.page === 'global'); NB.dmPage(s2.page === 'dms'); lastPage = s2.page; }
    const dmW = s2.page === 'dm' ? (s2.dmPeer || '') : '';
    if (dmW !== lastDmW) { NB.dmWatch(dmW); lastDmW = dmW; }
    if (INFO.relay) syncPhoto(C);
    if (s2.admOn && ADM_PAGES.indexOf(s2.page) >= 0 && now - admAt > (A ? 20000 : 8000) && !admPend) { admAt = now; act('get'); }
    if (admPend && now - admPend > (s2.admLogging ? 30000 : 60000)) {
      admPend = 0; const tx = C.T()[s2.lang];
      if (s2.admLogging) C.setState({ admLogging: false, admErr: tx.ad_noResp }); else if (s2.admOn && ADM_PAGES.indexOf(s2.page) >= 0) C.say(tx.ad_noResp);
      if (s2.bUpd) C.setState({ bUpd: false });
    }
    if (now - saveAt > 2000) {
      saveAt = now;
      ['usageH', 'favs', 'read', 'chat', 'tkId', 'myTkSt', 'fb', 'human', 'photo', 'rateCount', 'rateNext', 'tkNews', 'svTab', 'uMode', 'refSet', 'invites', 'warnHidden', 'usage', 'hist2', 'seenNews']
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
    const d = C.state.photo || '', bg = C.state.pbg || '', key = 'v2|' + d.length + d.slice(-40) + '|' + bg.length + bg.slice(-40) + '|' + C.meName;
    if (sentPh === null) { sentPh = LS.get('profSent', ''); }
    if (key === sentPh || Date.now() < phWait) return;
    sentPh = key; LS.set('profSent', key);
    const go = (th) => NB.profile(JSON.stringify({ th, big: d, bg, n: C.meName }));
    if (!d) { go(''); return; }
    const img = new Image();
    img.onload = () => {
      const z = 128, k = Math.max(z / img.width, z / img.height), cv = document.createElement('canvas'); cv.width = z; cv.height = z;
      cv.getContext('2d').drawImage(img, (z - img.width * k) / 2, (z - img.height * k) / 2, img.width * k, img.height * k);
      go(cv.toDataURL('image/jpeg', 0.8));
    };
    img.onerror = () => go('');
    img.src = d;
  }

  function news(C, up) {
    INFO = J(NB.info(), INFO);
    const list = (INFO.news || []).map((n) => { const j = J(n.j, {}); return { id: n.id, t: j.t || '', x: j.x || '', img: j.img || '', btn: Array.isArray(j.btn) ? j.btn : [], poll: j.poll && Array.isArray(j.poll.o) ? j.poll : null, time: new Date(n.ts * 1000).toLocaleDateString('ru-RU') }; })
      .filter((n) => !NDEL[n.id]).sort((a, b) => (a.id < b.id ? 1 : -1));
    up.bcast = list;
    const seen = C.state.seenNews || [], fresh = list.filter((n) => seen.indexOf(n.id) < 0);
    if (fresh.length) { up.newsBan = true; up.banHidden = false; up.seenNews = seen.concat(fresh.map((n) => n.id)).slice(-50); }
  }

  function handle(C, e, up) {
    const s = C.state, tx = C.T()[s.lang], t = Date.now();
    if (e.k === 'srv') {
      up.pings = loadServers(); news(C, up);
      if (e.manual) { up.refreshing = false; C.say((e.ok ? '✅ ' : '⚠️ ') + (e.ok ? tx.t_ref : tx.s_refS)); if (s.gRetest) { up.gRetest = false; setTimeout(() => C.runTest(), 300); } }
    } else if (e.k === 'key') {
      up.keyMsg = e.r; up.keyOk = e.r === 'ok';
    } else if (e.k === 'go') {
      up.page = e.page; up.menu = false; if (e.page === 'chat') up.unreadReply = 0;
      if (e.page === 'adm_t') { if (e.tid) up.admT = e.tid; if (!s.admOn) up.page = 'main'; admAt = 0; }
    } else if (e.k === 'ad') {
      showAd(e.link);
    } else if (e.k === 'gfail') {
      C.say(e.why === 'net' ? '📵 ' + tx.g_net : e.why === 'srv' ? '⚠️ ' + tx.g_srv : tx.g_fail);
    } else if (e.k === 'phfail') {
      C.say(tx.ph_fail); sentPh = '\u0000'; phWait = Date.now() + 60000;
    } else if (e.k === 'ph') {
      PH[e.dev] = { d: /^data:image\/(jpeg|png);base64,/.test(e.d || '') ? e.d : '', at: Date.now() };
      const ks = Object.keys(PH); if (ks.length > 80) ks.sort((a, b) => PH[a].at - PH[b].at).slice(0, ks.length - 80).forEach((k) => delete PH[k]);
      LS.set('ph', PH); up.gTick = (s.gTick || 0) + 1;
    } else if (e.k === 'diag') {
      const r = e.r || {}; up.diag = r.fs !== undefined ? (r.fs === 200 || r.fs === 404 ? 'dg_fs' : 'dg_bad') : r.tun === 200 ? 'dg_tun' : r.direct === 200 ? 'dg_dir' : 'dg_bad';
    } else if (e.k === 'g') {
      G = (e.list || []).sort((a, b) => a.time - b.time).slice(-400);
      LRX = LRX.filter((l) => Date.now() / 1000 - l.time < 90 && !G.some((g) => g.re === l.re && g.i === l.i && g.e === l.e && !!g.off === !!l.off));
      LGM = LGM.filter((l) => Date.now() / 1000 - l.time < 120 && !G.some((g) => g.i === l.i && (g.t || '') === (l.t || '') && (g.st || '') === (l.st || '') && g.time >= l.time - 30));
      askPhotos();
      (e.del || []).forEach((id) => { gDel[id] = true; });
      INFO = J(NB.info(), INFO);
      up.gTick = (s.gTick || 0) + 1;
    } else if (e.k === 'phretry') {
      sentPh = '\u0000'; phWait = Date.now() + 15 * 60000;
    } else if (e.k === 'prof') {
      P2[e.dev] = { th: e.th || '', ph: e.ph || '', bg: e.bg || '', n: e.n || '', dm: !!e.dm };
      if (e.th) PH[e.dev] = { d: e.th, at: Date.now() };
      up.dmTick = (s.dmTick || 0) + 1;
    } else if (e.k === 'dm') {
      const x = DMS[e.peer] || (DMS[e.peer] = { msgs: [], un: 0, st: '' }), me = INFO.dev;
      if (e.st) x.st = e.st;
      const list = (e.list || []).map((m) => ({ id: m.id, t: m.t, f: m.f, x: m.x || '', ph: m.ph || '', st: m.st || '', sys: m.sys || '', rp: m.rp && m.rp.n ? m.rp : null, re: m.re || '', e: m.e || '', off: !!m.off, ty: m.ty || 0, rd: m.rd || 0 }));
      const same = (a, b) => a.f === b.f && (a.x || '') === (b.x || '') && (a.ph || '') === (b.ph || '') && (a.st || '') === (b.st || '') && (a.sys || '') === (b.sys || '') && (a.re || '') === (b.re || '') && (a.e || '') === (b.e || '') && !!a.off === !!b.off;
      let pend = x.msgs.filter((m) => m.pend), msgs = e.full ? [] : x.msgs.filter((m) => !m.pend), fresh = 0;
      for (const m of list) {
        if (msgs.some((q) => q.id === m.id)) continue;
        const pi = pend.findIndex((q) => same(q, m)); if (pi >= 0) pend.splice(pi, 1);
        msgs.push(m);
        if (!e.full && m.f === e.peer && !m.sys && !isCtl(m)) fresh++;
      }
      x.msgs = msgs.concat(pend).sort((a, b) => (a.t || 0) - (b.t || 0)).slice(-300);
      const last = x.msgs[x.msgs.length - 1]; if (last) x.lt = Math.max(x.lt || 0, (last.t || 0) * 1000);
      const viewing = s.page === 'dm' && s.dmPeer === e.peer;
      if (viewing) { const lp = x.msgs.filter((m) => m.f === e.peer && !isCtl(m) && !m.sys).pop();   // okaldy bellik
        if (lp && (x.rdSent || 0) < (lp.t || 0)) { x.rdSent = lp.t; NB.dmSend(e.peer, JSON.stringify({ rd: lp.t }), C.meName); } }
      if (fresh && !viewing) { x.un = (x.un || 0) + fresh; x.seen = false; const m = list.filter((q) => q.f === e.peer && !isCtl(q)).pop(); if (!MUTE[e.peer]) C.say('✉️ ' + nameOf(e.peer) + ': ' + (m && (m.x || m.st || '📷') || '').slice(0, 60)); }
      { const lm = x.msgs.filter((q) => !isCtl(q) && !q.pend).pop(); if (lm) x.ls = dmPrev(lm, tx, me).slice(0, 120); }
      if (C._saveMeta) C._saveMeta();
      up.dmTick = (s.dmTick || 0) + 1;
    } else if (e.k === 'dmreq') {
      const x = DMS[e.peer] || (DMS[e.peer] = { msgs: [], un: 0, st: '' });
      if (!x.st) x.st = 'in'; if (e.n) x.n = e.n; x.lt = Date.now(); if (x.st === 'in') x.seen = false;
      if (C._saveMeta) C._saveMeta();
      if (x.st === 'in') C.say('✉️ ' + tx.dm_reqText.replace('{n}', e.n || '?'));
      up.dmTick = (s.dmTick || 0) + 1;
    } else if (e.k === 'dmerr') {
      C.say('⚠️ ' + (e.why === 'nokey' ? tx.dm_noKey : tx.dm_fail));
    } else if (e.k === 'dmkey') {
      const x = DMS[e.peer]; if (x) { x.msgs = x.msgs.concat([{ id: 'k' + t, f: '', t: t / 1000, sys: 'key' }]); up.dmTick = (s.dmTick || 0) + 1; }
    } else if (e.k === 'img') {
      (e.kind === 'n' ? NI : GI)[e.id] = e.d || '';
      up.gTick = (s.gTick || 0) + 1;
    } else if (e.k === 'gok') {
      // Global chat: habar gitdi
    } else if (e.k === 'adm') {
      admPend = 0; up.bUpd = false;
      if (e.err) {
        INFO = J(NB.info(), INFO);
        if (s.admLogging || !s.admOn) {
          up.admLogging = false; up.admShakeK = (s.admShakeK || 0) + 1;
          up.admErr = e.err === 'busy' ? tx.ad_busy : e.err === 'lock' ? tx.ad_locked.replace('{s}', String(e.s || 600)) : tx.ad_bad;
          if (e.err === 'lock') up.admLock = t + (e.s || 600) * 1000;
        } else { A = null; up.admOn = false; if (ADM_PAGES.indexOf(s.page) >= 0) up.page = 'main'; C.say('🔒 ' + (e.err === 'busy' ? tx.ad_busy : tx.ad_closed)); }
        return;
      }
      const d = e.d || {}; A = d; INFO.admMe = d.me; INFO.adm = true;
      (d.qal || []).forEach((q) => qAdd(q.id, q.t, q.at));
      if (s.admLogging || !s.admOn) { Object.assign(up, { admOn: true, admAsk: false, admLogging: false, admErr: '', admFails: 0, page: 'admin', admTab: 'tk' }); C.say('🔓 ' + tx.ad_ok); }
      up.admRole = (d.me || {}).role || 'h';
      if (d.sysOn != null) up.sysOn = d.sysOn;
      if (d.aiOn != null) up.aiOn = d.aiOn;
      up.aiCount = d.aiCount || 0;
      if (d.msg && d.msg.indexOf('key:') === 0) { const k = d.msg.slice(4); NB.copy(k); C.say('🛠 ' + k + ' · ' + tx.ad_keyOk); }
      else if (d.msg === 'bc') C.say('📢 ' + tx.ad_bcOk);
      else if ((d.a === 'kedit' || d.a === 'kdel') && !d.msg) C.say('⚠️ ' + (d.err || tx.ad_oldBot));
      else if (d.msg && d.msg.indexOf('xadd:') === 0) { const n = parseInt(d.msg.slice(5), 10) || 0; C.say(n ? '✅ ' + tx.x_added.replace('{n}', String(n)) : '⚠️ ' + tx.x_none); }
      else if (d.msg === 'qok') C.say('📊 ' + tx.q_ok);
      else if (d.msg === 'qnone') C.say('⚠️ ' + tx.q_none);
      else if (d.msg === 'kok') { C.say('✅ ' + tx.bk_saved); up.kdDays = ''; up.kdN = ''; up.kdLb = null; }
      else if (d.msg === 'kdel') C.say('🗑 ' + tx.bk_deleted);
      else if (d.msg === 'ndel') C.say('🗑 ' + tx.n_deleted);
      else if (d.msg === 'payok') { C.say('💳 ' + tx.ps_ok); up.payT = null; up.payImg = ''; up.payNoImg = false; LS.set('payInfo', null); }
      else if (d.msg && d.msg.indexOf('xp:') === 0) { const q = d.msg.split(':'); UPX[q[3]] = { lv: +q[1], xp: +q[2] }; C.say('✅ ' + tx.gv_ok.replace('{l}', q[1]).replace('{x}', q[2])); }
      else if (d.msg && d.msg.indexOf('adm:') === 0) { const k = d.msg.slice(4); NB.copy(k); up.onceK = k; up.onceN = ''; C.say('🔑 ' + tx.oa_ok); act('get'); }
      else if (d.msg === 'upd') C.say('⚡ ' + tx.ad_updGo);
      else if (d.msg === 'busy') C.say(tx.ad_updBusy);
      if (d.err) C.say('⚠️ ' + d.err);
      up.admTick = (s.admTick || 0) + 1;
    } else if (e.k === 'spd') {
      up.spd = Object.assign({}, s.spd || {}, e);
      if (e.ph === 'err') C.say('⚠️ ' + tx.sp_err);
    } else if (e.k === 'fo') {
      C.say('🔄 ' + tx.fo_t.replace('{s}', e.to || ''));
    } else if (e.k === 'buysent') {
      up.buySending = false; up.buyImg = ''; up.buyN = ''; C.say('🧾 ' + tx.by_sent);
    } else if (e.k === 'buyfail') {
      up.buySending = false; C.say('⚠️ ' + tx.by_fail);
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
      } else if (m.k === 'lvl') {
        LS.set('lvl', { lv: m.lv, xp: m.xp, cur: m.cur, next: m.next, inv: m.inv }); up.payTick = t; if (m.inv != null) up.invites = m.inv;
        if (m.up) { up.rkm = { t: rkT(m.lv), up: true, days: m.days || 0 }; C.party('⭐ ' + tx.lv_up.replace('{n}', String(m.lv)) + (m.days ? ' · +' + m.days + ' ' + tx.days : '')); }
      } else if (m.k === 'top') { LS.set('top', m.l || []); up.payTick = t; }
      else if (m.k === 'pay') { LS.set('payInfo', { p: m.p, i: m.i, pi: m.pi || '', at: Date.now() }); up.payTick = t; }
      else if (m.k === 'buy') {
        const os = LS.get('orders', []) || [];
        if (m.wait && m.oid) { LS.set('orders', [{ id: m.oid, d: m.days, st: 'w' }].concat(os).slice(0, 10)); up.payTick = t; }
        else if (m.why === 'many') C.say('⚠️ ' + tx.by_many);
        else { const o1 = os.find((o) => o.st === 'w' && o.d === m.days); if (o1) { o1.st = m.ok ? 'ok' : 'no'; LS.set('orders', os); }
          if (m.ok) { C.party('🔑 ' + tx.by_ok.replace('{d}', String(m.days || ''))); try { NB.refresh(); } catch (e2) {} } else C.say('❌ ' + tx.by_no); up.payTick = t; }
      } else if (m.k === 'refok') { up.refSet = m.c || s.refIn; up.refMsg = 'ok'; }
      else if (m.k === 'refbad') up.refMsg = m.why === 'own' ? 'own' : 'bad';
      else if (m.k === 'kbad') { up.keyMsg = 'used'; }
      else if (m.k === 'nick') {
        if (m.ok) { C.meName = m.n; LS.set('nick', m.n); up.nkSt = 'ok'; up.nkIn = null; if (C._nkCustom && !INFO.nkb) { try { NB.nickBonus(); } catch (e2) {} INFO.nkb = true; } } else up.nkSt = m.why === 'taken' ? 'taken' : 'bad';
      } else if (m.k === 'uban') { INFO.uban = !!m.on; if (m.on) C.say('⛔ ' + tx.ub_msg); }
      else if (m.k === 'quota') { qAdd(m.id, m.t, m.at); up.qTick = (s.qTick || 0) + 1; }
      else if (m.k === 'atk') { if (INFO.adm) { C.say((m.new ? tx.atk_new : '🎫') + ' #' + m.tid + (m.n ? ' · ' + m.n : '') + ': ' + String(m.t || '').slice(0, 70)); admAt = 0; } }
      else if (m.k === 'mute') { LS.set('muteUntil', (m.until || 0) * 1000); C.say('🔇 ' + tx.g_muteOn); }
      else if (m.k === 'gwarn') { C.say('⚠️ ' + tx.g_warn.replace('{n}', String(m.n || 1))); }
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
    if (s.zoom) { C.setState({ zoom: '' }); return true; }
    if (s.rkm) { C.setState({ rkm: null }); return true; }
    if (s.dmPeek) { C.setState({ dmPeek: null }); return true; }
    if (s.stOn) { C.setState({ stOn: false }); return true; }
    if (s.cf) { C.cfNo(); return true; }
    if (s.menu) { C.setState({ menu: false }); return true; }
    if (s.fan) { C.setState({ fan: false }); return true; }
    if (s.sharing) { C.setState({ sharing: false }); return true; }
    if (s.page !== 'main') { C.goBack(); return true; }
    return false;
  };

  let lpAt = 0;
  document.addEventListener('click', (e) => {
    const C = window.C; if (!C || !e.target || !e.target.closest) return; const tg = e.target;
    if (tg.closest('.rxbar')) return;
    const b = tg.closest('.tgc .gb[data-rp]');
    if (!b || tg.closest('button,a,img,.kchip,.kuse')) { if (C.state.rxFor && !tg.closest('.rxc')) C.setState({ rxFor: null }); return; }
    if (Date.now() - lpAt < 800) return;
    const k = b.getAttribute('data-rp'); C.setState({ rxFor: C.state.rxFor === k ? null : k });
  });
  document.addEventListener('dblclick', (e) => {
    const C = window.C, b = e.target && e.target.closest && e.target.closest('.tgc .gb[data-rp]'); if (!C || !b) return;
    const k = b.getAttribute('data-rp'); C.setState({ rxFor: null });
    if (C.state.page === 'dm' && C.state.dmPeer) C.dmReact(C.state.dmPeer, k, '❤️'); else C.gReact(k, '❤️');
  });
  // habaryň tekstini basyp saklap göçürmek (ady, alynty, surat, wagt goşulmaýar)
  function lpCopy(el) {
    const c = el.cloneNode(true);
    c.querySelectorAll('.gnm,.rpq,img,.gst,.bt,.ailbl,button:not(.kchip)').forEach((x) => x.remove());
    const t = (c.innerText || c.textContent || '').replace(/📋/g, '').trim();
    if (!t || !window.C) return;
    lpAt = Date.now(); NB.copy(t); try { NB.tap(); } catch (e) {}
    window.C.say('✓ ' + window.C.T()[window.C.state.lang].copied);
  }
  // 1.21: hususy habarlar sanawynda adyň üstüne basyp saklamak → açmazdan görmek
  let dmLp = null;
  document.addEventListener('touchstart', (e) => {
    const el = e.target && e.target.closest && e.target.closest('[data-dv]'); if (!el) { dmLp = null; return; }
    const t = e.touches[0], o = { x: t.clientX, y: t.clientY };
    o.tm = setTimeout(() => { if (dmLp !== o) return; dmLp = null; window.__lpDm = Date.now(); try { NB.tap(); } catch (e2) {} if (window.C) window.C.peekDm(el.getAttribute('data-dv')); }, 450);
    dmLp = o;
  }, { passive: true });
  document.addEventListener('touchmove', (e) => { if (!dmLp) return; const t = e.touches[0]; if (Math.abs(t.clientX - dmLp.x) > 10 || Math.abs(t.clientY - dmLp.y) > 10) { clearTimeout(dmLp.tm); dmLp = null; } }, { passive: true });
  const dmLpEnd = () => { if (dmLp) { clearTimeout(dmLp.tm); dmLp = null; } };
  document.addEventListener('touchend', dmLpEnd, { passive: true }); document.addEventListener('touchcancel', dmLpEnd, { passive: true });
  document.addEventListener('contextmenu', (e) => { const el = e.target && e.target.closest && e.target.closest('[data-dv]'); if (!el || !window.C) return; e.preventDefault();
    if (Date.now() - (window.__lpDm || 0) < 900) return; window.__lpDm = Date.now(); window.C.peekDm(el.getAttribute('data-dv')); });
  // 1.23: serweri basyp saklamak → 30 sekunt gizlemek (diňe eýesi)
  const svHide = (el) => { const C = window.C; if (!C || !window.__isOwn) return; const n = el.getAttribute('data-sn'); if (!n) return;
    window.__lpSv = Date.now(); const H = window.__svHide || (window.__svHide = {}); H[n] = Date.now() + 30000;
    try { NB.tap(); } catch (e) {} C.say('🙈 ' + n + ' · ' + C.T()[C.state.lang].sv_hid); C.setState({ svhTick: Date.now() });
    setTimeout(() => window.C && window.C.setState({ svhTick: Date.now() }), 30100); };
  let svLp = null;
  document.addEventListener('touchstart', (e) => { const el = e.target && e.target.closest && e.target.closest('[data-sn]'); if (!el || !window.__isOwn) { svLp = null; return; }
    const t = e.touches[0], o = { x: t.clientX, y: t.clientY }; o.tm = setTimeout(() => { if (svLp === o) { svLp = null; svHide(el); } }, 500); svLp = o; }, { passive: true });
  document.addEventListener('touchmove', (e) => { if (!svLp) return; const t = e.touches[0]; if (Math.abs(t.clientX - svLp.x) > 10 || Math.abs(t.clientY - svLp.y) > 10) { clearTimeout(svLp.tm); svLp = null; } }, { passive: true });
  const svEnd = () => { if (svLp) { clearTimeout(svLp.tm); svLp = null; } };
  document.addEventListener('touchend', svEnd, { passive: true }); document.addEventListener('touchcancel', svEnd, { passive: true });
  document.addEventListener('contextmenu', (e) => { const el = e.target && e.target.closest && e.target.closest('[data-sn]'); if (!el || !window.__isOwn) return; e.preventDefault(); if (Date.now() - (window.__lpSv || 0) > 900) svHide(el); });
  document.addEventListener('click', (e) => { if (Date.now() - (window.__lpSv || 0) < 900 && e.target && e.target.closest && e.target.closest('[data-sn]')) { e.stopPropagation(); e.preventDefault(); } }, true);
  // habary saga süýşürmek → jogap (Global chat, hususy habar)
  let sw = null;
  document.addEventListener('touchstart', (e) => {
    const el = e.target && e.target.closest && (e.target.closest('[data-rp]') || e.target.closest('.bub')); if (!el) { sw = null; return; }
    const t = e.touches[0]; sw = { el, x: t.clientX, y: t.clientY, dx: 0, on: false };
    const s1 = sw; sw.lp = setTimeout(() => { if (sw !== s1 || s1.on) return; sw = null; lpCopy(el); }, 550);   // basyp saklamak → göçür
  }, { passive: true });
  document.addEventListener('touchmove', (e) => {
    if (!sw) return; const t = e.touches[0], dx = t.clientX - sw.x, dy = t.clientY - sw.y;
    if (Math.abs(dx) > 8 || Math.abs(dy) > 8) clearTimeout(sw.lp);
    if (!sw.el.hasAttribute('data-rp')) return;   // admin/AI söhbeti: diňe göçürmek
    if (!sw.on) { if (Math.abs(dy) > 14 && Math.abs(dy) > Math.abs(dx)) { sw = null; return; } if (dx > 12) sw.on = true; else return; }
    sw.dx = Math.max(0, Math.min(90, dx)); sw.el.style.transform = 'translateX(' + sw.dx + 'px)';
  }, { passive: true });
  const swEnd = () => {
    if (!sw) return; const s0 = sw; sw = null; clearTimeout(s0.lp);
    s0.el.style.transition = 'transform .2s ease'; s0.el.style.transform = ''; setTimeout(() => { s0.el.style.transition = ''; }, 230);
    if (s0.on && s0.dx > 55 && window.C) { window.C.replyTo(s0.el.getAttribute('data-rp')); try { NB.tap(); } catch (e) {} }
  };
  document.addEventListener('touchend', swEnd, { passive: true }); document.addEventListener('touchcancel', swEnd, { passive: true });

  // hususy habar: täze habar gelende aşak süýşür
  DC.after.push(() => {
    const C = window.C; if (!C || !C.dmEl || !C.dmEl.isConnected) return;
    const el = C.dmEl, h = el.scrollHeight;
    if (el.__h !== h) { const near = !el.__h || el.scrollTop + el.clientHeight >= el.__h - 120; el.__h = h; if (near) el.scrollTop = h; }
  });
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
