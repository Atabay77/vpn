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
  const ADM_PAGES = ['admin', 'adm_t', 'adm_u', 'adm_b', 'adm_k', 'adm_kd', 'adm_x', 'adm_l', 'adm_s', 'adm_st', 'adm_ai', 'adm_or', 'adm_bn'];
  const act = (a, o) => { NB.adm(JSON.stringify(Object.assign({ a }, o || {}))); if (!admPend) admPend = Date.now(); if (a !== 'get' && a !== 'alog') alogPush('a', a + ' ' + JSON.stringify(o || {}).slice(0, 90)); };
  const TKO = {};   // 1.46.7: bilet ýagdaýy (ýapdym / açdym) — bot jogap berýänçä
  // 1.46.7: admin log — eýesinden başga adminleriň programmadaky hereketleri (basan düwmesi, açan sahypasy, eden işi) bota; diňe eýesi görýär
  const AL = []; let alAt = 0;
  function alogPush(k, x) {
    try { const me = (A && A.me) || INFO.admMe || {}; if (!window.C || !window.C.state.admOn || !me.role || me.role === 'f') return;
      AL.push([Math.floor(Date.now() / 1000), k, String(x || '').replace(/\s+/g, ' ').trim().slice(0, 120)]);
      if (AL.length >= 30 || Date.now() - alAt > 20000) { alAt = Date.now(); NB.send(JSON.stringify({ k: 'alog', e: AL.splice(0) })); } } catch (e) {}
  }
  setInterval(() => { if (AL.length) { alAt = Date.now(); try { NB.send(JSON.stringify({ k: 'alog', e: AL.splice(0) })); } catch (e) {} } }, 20000);
  document.addEventListener('click', (e) => { const b = e.target && e.target.closest && e.target.closest('button,a,label,[role=button]'); if (!b || !window.C) return;
    alogPush('b', (b.getAttribute('aria-label') || b.innerText || b.textContent || '').trim().slice(0, 60) + ' · ' + window.C.state.page); }, true);
  const admMe = () => (A && A.me) || INFO.admMe || {};

  // ---- 1.16: profil, hususy habarlar, nyşanlar ----
  const TAGS = LS.get('tags', {}) || {}, TAGQ = {};   // 1.47.4: telefon → 5 harply @belgi (bot berýär)
  const tagOf = (d) => { if (!d) return ''; if (TAGS[d]) return TAGS[d]; const tn = Date.now();
    if (!TAGQ[d] || tn - TAGQ[d] > 60000) { TAGQ[d] = tn; try { NB.send(JSON.stringify({ k: 'utag', d })); } catch (e) {} } return ''; };
  const TAGD = {}; Object.keys(TAGS).forEach((d) => { TAGD[TAGS[d]] = d; });   // 1.47.22: @belgi → telefon (basylanda profil)
  const tagPut = (d, t) => { if (!d || !/^[a-z][a-z0-9_]{4,19}$/.test(t || '') || TAGS[d] === t) return; if (TAGS[d]) delete TAGD[TAGS[d]]; TAGS[d] = t; TAGD[t] = d; const ks = Object.keys(TAGS); if (ks.length > 800) delete TAGS[ks[0]]; LS.set('tags', TAGS); };
  // 1.47.24: diňe eýesiniň @belgileri (Telegram ýaly köp at) — basylanda eýesiniň profili
  const OWNER_TAGS = ['turkmenvpn', 'turkmen_vpn', 'tmvpn', 'tm_vpn', 'vpn', 'turkmen', 'owner', 'admin', 'admins', 'administrator', 'moderator', 'mod', 'support', 'help', 'helpdesk', 'komek', 'goldaw', 'official', 'team', 'info', 'news', 'habar', 'habarlar', 'premium', 'vip', 'system', 'bot', 'service', 'contact', 'ceo', 'founder', 'dev', 'developer'], OT_SET = new Set(OWNER_TAGS);
  const MENT_RE = new RegExp('(@(?:' + OWNER_TAGS.slice().sort((a, b) => b.length - a.length).join('|') + ')(?![A-Za-z0-9_])|@[A-Za-z][A-Za-z0-9_]{4,19})', 'i');
  const MENT_X = { test: (x) => /^@[A-Za-z][A-Za-z0-9_]{4,19}$/.test(x) || (x[0] === '@' && OT_SET.has(x.slice(1).toLowerCase())) };
  const ownerDev = () => Object.keys(INFO.roles || {}).find((d) => roleOf(d) === 'o') || '';
  const otChips = (C) => OWNER_TAGS.map((t) => ({ t: '@' + t, cp: () => { NB.copy('@' + t); C.say('✓ @' + t); } }));
  let TAGW = null;   // 1.47.22: basylan @belgi — botdan gözlenýär
  /** 1.47.22: tekstdäki @belgiler basylýar (Global chat, Admine ýaz, hususy habarlar, habarlar) — profil açylýar. */
  function withMent(parts, C) {
    const out = [];
    for (const q of parts || []) {
      if (!q.isT || String(q.t).indexOf('@') < 0) { out.push(q); continue; }
      String(q.t).split(MENT_RE).filter((x) => x).forEach((x) => {
        if (MENT_X.test(x)) out.push({ isM: true, isT: false, isL: false, isK: false, t: x, href: '', cp: null, use: null, go: () => C.openTag(x.slice(1)) });
        else out.push(Object.assign({}, q, { t: x }));
      });
    }
    return out;
  }
  const P2 = {};          // telefon → {th, ph, bg, n, dm} (doly profil)
  const DMS = {};         // garşydaş → {st, msgs: [], un, n, lt}
  const MUTE = LS.get('dmMute', {}) || {};   // 1.21: sessize alnanlar (sanalmaýar, duýduryş ýok)
  const DGW = { tk: [108, 118], ru: [116, 106], tr: [107, 116] };   // 1.27: «VPN-i gizle» düwmesiniň giňligi (ýazga görä ölçeldi; käbir telefonda awtomatik giňlik bozulýar)
  // 1.28: eýesi hemme ýerde OWNER ýazgysy bilen ýa-da derejesi (nyşan) bilen görünýär — öz saýlawy; başgalary onuň soňky Global habaryndaky «ow» belgisinden bilýär
  const ownOn = (dev) => { if (dev === INFO.dev) return !!LS.get('ownTag', false); let v = null; for (let i = G.length - 1; i >= 0; i--) { const q = G[i]; if (q.i === dev && q.ow != null && q.ow >= 0) { v = q.ow; break; } } return v == null ? true : !!v; };
  const isOwnShown = (dev) => roleOf(dev) === 'o' && ownOn(dev);
  // 1.43: Premium-ly telefonlar (abuna faýlyndaky açarlardan) — ýalpyldaýan nyşan
  let PDS = null, PDSsrc = null;
  const isPrem = (dev) => { if (PDSsrc !== INFO.pdevs) { PDSsrc = INFO.pdevs; PDS = new Set(INFO.pdevs || []); } return PDS.has(dev) && !isOwnShown(dev); };
  // 1.32: mugt birikme wagty (minut, 0 = wagtsyz) — eýesi admin panelinden; «1 sagat» ýazgylary şoňa görä
  const hrsT = (l, m) => { const h = m / 60, w = m % 60 === 0 ? String(h) : m >= 60 && m % 30 === 0 ? Math.floor(h) + ',5' : '';
    if (!w) return l === 'ru' ? m + ' мин' : l === 'tr' ? m + ' dakika' : m + ' minut';
    if (l === 'ru') { const n = Math.floor(h); return w + (w.indexOf(',') > 0 ? ' часа' : n % 10 === 1 && n % 100 !== 11 ? ' час' : [2, 3, 4].indexOf(n % 10) >= 0 && !(n % 100 >= 12 && n % 100 <= 14) ? ' часа' : ' часов'); }
    return w + (l === 'tr' ? ' saat' : ' sagat'); };
  const sessTx = (l, m) => {
    if (m === 0) return ({ tk: { nk_bonNo: '✅ Häzir mugt VPN wagtsyz', nk_bonYes: '✅ Häzir mugt VPN wagtsyz', q2: 'Mugt wagt näme?', a2: 'Häzir mugt birikmäniň wagt çägi ýok. Bu soňra üýtgäp biler; Premium bilen hemişe çäksiz.', k_text: 'Satyjydan alan Premium açaryňyzy şu ýere ýazyň. Premium satyn almak — baş sahypadaky «👑 Premium».' },
      ru: { nk_bonNo: '✅ Сейчас бесплатный VPN без ограничения времени', nk_bonYes: '✅ Сейчас бесплатный VPN без ограничения времени', q2: 'Что значит бесплатное время?', a2: 'Сейчас у бесплатного подключения нет ограничения времени. Это может измениться; с Premium ограничений нет никогда.', k_text: 'Введите ключ Premium, полученный от продавца. Купить Premium — «👑 Premium» на главной.' },
      tr: { nk_bonNo: '✅ Şu an ücretsiz VPN süresiz', nk_bonYes: '✅ Şu an ücretsiz VPN süresiz', q2: 'Ücretsiz süre ne demek?', a2: 'Şu an ücretsiz bağlantıda süre sınırı yok. Bu ileride değişebilir; Premium ile her zaman sınırsız.', k_text: 'Satıcıdan aldığınız Premium anahtarını buraya girin. Premium satın almak — ana sayfadaki «👑 Premium».' } })[l] || {};
    const H = hrsT(l, m), B = hrsT(l, m + 30);
    return ({ tk: { ul_t: 'MUGT WAGT · ' + H.toUpperCase(), nk_bonNo: '💡 Nigiňizi üýtgetseňiz mugt VPN wagty ' + H + ' däl-de ' + B + ' bolýar', nk_bonYes: '✅ Mugt VPN wagtyňyz: ' + B, q2: 'Mugt wagt näme?',
        a2: 'Mugt birikme ' + H + ' dowam edýär (profilde nigiňizi üýtgetseňiz ' + B + '), soň täzeden birigip bilersiňiz. Premium bilen bu çäk ýok.', k_text: 'Satyjydan alan Premium açaryňyzy şu ýere ýazyň. Premium satyn almak — baş sahypadaky «👑 Premium».' },
      ru: { ul_t: 'БЕСПЛАТНО · ' + H.toUpperCase(), nk_bonNo: '💡 Смените ник — бесплатное время VPN станет ' + B + ' вместо ' + H, nk_bonYes: '✅ Ваше бесплатное время VPN: ' + B, q2: 'Что значит бесплатное время?',
        a2: 'Бесплатное подключение длится ' + H + ' (если сменить ник в профиле — ' + B + '), потом можно подключиться снова. С Premium ограничения нет.', k_text: 'Введите ключ Premium, полученный от продавца. Купить Premium — «👑 Premium» на главной.' },
      tr: { ul_t: 'ÜCRETSİZ · ' + H.toLocaleUpperCase('tr'), nk_bonNo: '💡 Takma adınızı değiştirin — ücretsiz VPN süresi ' + H + ' yerine ' + B + ' olur', nk_bonYes: '✅ Ücretsiz VPN süreniz: ' + B, q2: 'Ücretsiz süre ne demek?',
        a2: 'Ücretsiz bağlantı ' + H + ' sürer (profilde takma adınızı değiştirirseniz ' + B + '), sonra yeniden bağlanabilirsiniz. Premium ile sınır yok.', k_text: 'Satıcıdan aldığınız Premium anahtarını buraya girin. Premium satın almak — ana sayfadaki «👑 Premium».' } })[l] || {}; };
  let SESS = 60;
  const LVB = LS.get('lvb', {}) || {};   // 1.30.2: botdan alnan derejeler {telefon: [dereje, wagt]}
  let lvAskAt = 0;
  const lvOf = (dev, msgLv) => (LVB[dev] ? LVB[dev][0] : msgLv || 0);
  const lvAsk = (devs) => { const tn = Date.now(), need = devs.filter((d) => d && d !== INFO.dev && (!LVB[d] || tn - LVB[d][1] > 15 * 60000));
    if (!need.length || tn - lvAskAt < 60000) return; lvAskAt = tn; NB.send(JSON.stringify({ k: 'lvof', d: need.filter((d, i) => need.indexOf(d) === i).slice(0, 60) })); };
  const UPX = {};         // 1.21: eýesiniň beren bal/derejesiniň netijesi
  // 1.22: tegelek baýdaklar (img/flags/xx.svg) — emoji baýdagyndan ýurt kody
  const FLAGS = new Set('ac,ad,ae,af,ag,ai,al,am,an,ao,aq,ar,as,at,au,aw,ax,az,ba,bb,bd,be,bf,bg,bh,bi,bj,bl,bm,bn,bo,bq,br,bs,bt,bv,bw,by,bz,ca,cc,cd,cf,cg,ch,ci,ck,cl,cm,cn,co,cp,cq,cr,cu,cv,cw,cx,cy,cz,de,dg,dj,dk,dm,do,dz,ea,ec,ee,eg,eh,er,es,et,eu,fi,fj,fk,fm,fo,fr,fx,ga,gb,gd,ge,gf,gg,gh,gi,gl,gm,gn,gp,gq,gr,gs,gt,gu,gw,gy,hk,hm,hn,hr,ht,hu,ic,id,ie,il,im,in,io,iq,ir,is,it,je,jm,jo,jp,ke,kg,kh,ki,km,kn,kp,kr,kw,ky,kz,la,lb,lc,li,lk,lr,ls,lt,lu,lv,ly,ma,mc,md,me,mf,mg,mh,mk,ml,mm,mn,mo,mp,mq,mr,ms,mt,mu,mv,mw,mx,my,mz,na,nc,ne,nf,ng,ni,nl,no,np,nr,nu,nz,om,pa,pe,pf,pg,ph,pk,pl,pm,pn,pr,ps,pt,pw,py,qa,re,ro,rs,ru,rw,sa,sb,sc,sd,se,sg,sh,si,sj,sk,sl,sm,sn,so,sr,ss,st,su,sv,sx,sy,sz,ta,tc,td,tf,tg,th,tj,tk,tl,tm,tn,to,tr,tt,tv,tw,tz,ua,ug,uk,um,un,us,uy,uz,va,vc,ve,vg,vi,vn,vu,wf,ws,xk,xx,ye,yt,yu,za,zm,zw'.split(','));
  const fcc = (f) => { const c = Array.from(String(f || '')).map((ch) => ch.codePointAt(0)).filter((x) => x >= 0x1F1E6 && x <= 0x1F1FF);
    if (c.length !== 2) return ''; const k = String.fromCharCode(c[0] - 0x1F1E6 + 97, c[1] - 0x1F1E6 + 97); return FLAGS.has(k) ? k : ''; };
  const withFc = (o) => { if (!o) return o; const fc = fcc(o.f); return Object.assign({}, o, { fc, hasFc: !!fc, noFc: !fc }); };
  const dmPrev = (m, tx, me) => (m.f === me ? '↩ ' : '') + (m.ph ? '📷 ' + tx.dm_photo : m.st ? m.st : m.sys === 'acc' ? tx.dm_acced : m.x || '');
  const GI = {}, NI = {}, imgAsked = {};
  const VI = {}, vidAsked = {};   // 1.39: hekaýa wideolary (id → data:video)   // Global chat / habar suratlary
  const EMOJI = ['😀', '😁', '😂', '🤣', '😊', '🙂', '😉', '😍', '🥰', '😘', '😎', '🤔', '😅', '😴', '😭', '😡', '😱', '🥳', '👍', '👎', '🙏', '👏', '💪', '🤝', '👋', '🔥', '❤️', '💔', '💯', '🎉', '✅', '❌', '⚡', '🚀', '⭐', '🌙', '☀️', '🎮', '📶', '🔒', '💬', '🇹🇲'];
  // tepkiler: {re: habaryň kimligi, e: emoji, off: aýyrmak}; her adamyň bir habara bir tepkisi
  const RX_E = ['❤️', '👍', '😂', '🔥', '😮'];
  let LRX = [];
  let LCTL = [];   // 1.28: ugradylan, entek gelmedik pozmak/üýtgetmek setirleri
  const editsOf = (rows, who, txt) => { const o = {}, D = {}, E = {}; rows.forEach((m) => { if (!m.re && !m.dl && !m.ed && !m.ty && !m.rd) o[m.id] = m[who]; });
    rows.forEach((m) => { if (m.dl && o[m.dl] === m[who]) D[m.dl] = 1; if (m.ed && o[m.ed] === m[who]) E[m.ed] = m[txt]; }); return { D, E }; };
  let LGM = [];   // ugradylan, entek serwerden gelmedik öz Global habarlarym   // ugradylan, entek serwerden gelmedik Global tepkiler
  const isCtl = (m) => !!(m.re || m.ty || m.rd || m.dl || m.ed || m.sty);   // tepki / ýazýar / okaldy — habar däl
  // 1.20: derejeler (bot bilen deň: APP_LVL, APP_LVL_GIFT)
  const RK_L = [0, 100, 300, 600, 1000, 1500, 2200, 3000, 4000, 5500, 7500, 10000, 14000, 20000, 30000], RK_G = { 8: 3, 9: 5, 10: 7, 11: 7, 12: 7, 13: 7, 14: 7, 15: 30 };   // 1.47: 15 dereje; sowgat — Premium (açar däl)
  const RK_PK = { 2: ['pk_chat'], 3: ['pk_fr3'], 4: ['pk_fr4'], 5: ['pk_sh'], 6: ['pk_fr6', 'pk_tw'], 7: ['pk_nm7', 'pk_ry'], 8: ['g', 'pk_fr8', 'pk_em'], 9: ['g', 'pk_fr9', 'pk_nm9'], 10: ['g', 'pk_fr10', 'pk_au'],
    11: ['g', 'pk_fr11', 'pk_nm11'], 12: ['g', 'pk_fr12', 'pk_nm11'], 13: ['g', 'pk_fr13', 'pk_nm11'], 14: ['g', 'pk_fr14', 'pk_nm11'], 15: ['g', 'pk_fr15', 'pk_nm11'] };
  const rkT = (lv) => Math.max(1, Math.min(15, Math.floor(+lv) || 1));
  const rkNm = (t) => (t >= 11 ? 'nm' + t : t >= 10 ? 'nm10' : t >= 9 ? 'nm9' : t >= 7 ? 'nm7' : '');   // chatdaky nik
  // 1.47: täze derejeleriň atlary we sowgat ýazgylary (Premium)
  const RKX = { tk: { rk_n1: 'Bürünç I', rk_n2: 'Bürünç II', rk_n3: 'Bürünç III', rk_n4: 'Kümüş I', rk_n5: 'Kümüş II', rk_n6: 'Kümüş III', rk_n7: 'Altyn I', rk_n8: 'Altyn II', rk_n9: 'Altyn III', rk_n10: 'Platina', rk_n11: 'Almaz', rk_n12: 'Ussat', rk_n13: 'Beýik ussat', rk_n14: 'Çempion', rk_n15: 'Rowaýat', lv_how: 'Her gün programmany açsaňyz +10 bal (Premium — +20), her çagyran dostuňyz +50 bal. Sowgat Premium: 8-nji derejede +3 gün, 9-njy — +5 gün, 10–14-nji — +7 gün, 15-nji (iň ýokary) — +30 gün.', pk_gift: '+{d} gün Premium 👑', rk_upGift: 'Gutlaýarys! Sowgat: +{d} gün Premium 👑', pk_fr11: 'Täze çarçuwa', pk_fr12: 'Ýyldyrym çarçuwasy', pk_fr13: 'Ot çarçuwasy', pk_fr14: 'Gün çarçuwasy', pk_fr15: 'Ölmez çarçuwasy', pk_nm11: 'Ýalpyldaýan nik' },
    ru: { rk_n1: 'Бронза I', rk_n2: 'Бронза II', rk_n3: 'Бронза III', rk_n4: 'Серебро I', rk_n5: 'Серебро II', rk_n6: 'Серебро III', rk_n7: 'Золото I', rk_n8: 'Золото II', rk_n9: 'Золото III', rk_n10: 'Платина', rk_n11: 'Алмаз', rk_n12: 'Мастер', rk_n13: 'Грандмастер', rk_n14: 'Чемпион', rk_n15: 'Легенда', lv_how: 'Каждый день в программе +10 очков (Premium — +20), каждый приглашённый друг +50. Подарок Premium: на 8 уровне +3 дня, на 9 — +5, на 10–14 — +7, на 15 (высший) — +30 дней.', pk_gift: '+{d} дн. Premium 👑', rk_upGift: 'Поздравляем! Подарок: +{d} дн. Premium 👑', pk_fr11: 'Новая рамка', pk_fr12: 'Рамка молнии', pk_fr13: 'Огненная рамка', pk_fr14: 'Солнечная рамка', pk_fr15: 'Рамка бессмертного', pk_nm11: 'Сияющий ник' },
    tr: { rk_n1: 'Bronz I', rk_n2: 'Bronz II', rk_n3: 'Bronz III', rk_n4: 'Gümüş I', rk_n5: 'Gümüş II', rk_n6: 'Gümüş III', rk_n7: 'Altın I', rk_n8: 'Altın II', rk_n9: 'Altın III', rk_n10: 'Platin', rk_n11: 'Elmas', rk_n12: 'Usta', rk_n13: 'Büyük Usta', rk_n14: 'Şampiyon', rk_n15: 'Efsane', lv_how: 'Her gün programı açarsanız +10 puan (Premium — +20), her davet ettiğiniz arkadaş +50 puan. Premium hediye: 8. seviyede +3 gün, 9. — +5, 10–14. — +7, 15. (en yüksek) — +30 gün.', pk_gift: '+{d} gün Premium 👑', rk_upGift: 'Tebrikler! Hediye: +{d} gün Premium 👑', pk_fr11: 'Yeni çerçeve', pk_fr12: 'Yıldırım çerçevesi', pk_fr13: 'Ateş çerçevesi', pk_fr14: 'Güneş çerçevesi', pk_fr15: 'Ölümsüz çerçevesi', pk_nm11: 'Parlayan takma ad' } };
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
    const x = map[key] || {}, c = {}, who = {}; Object.keys(x).forEach((d) => { c[x[d]] = (c[x[d]] || 0) + 1; (who[x[d]] = who[x[d]] || []).push(d); });
    return Object.keys(c).sort((a, b) => c[b] - c[a]).map((e) => {   // 1.47: Telegram ýaly — ilkinji 3 adamyň suraty, köp bolsa sany hem
      const avs = who[e].slice(0, 3).map((d) => { const ph = thumbOf(d); return { hasPh: !!ph, noPh: !ph, photo: ph || '', bg: colorOf(d), ini: ini(nameOf(d)) }; });
      return { e, n: String(c[e]), showN: c[e] > 3, avs, cls: x[me] === e ? 'me' : '', tog: () => tog(e) }; });
  }
  const STICKERS = ['😂', '🤣', '😍', '🥰', '😎', '😭', '😡', '👍', '🙏', '🔥', '❤️', '💯', '🎉', '🤝', '😱', '🤔', '😴', '🥳', '💪', '👑', '🇹🇲', '🚀', '😘', '👋'];
  const LINK_RE = /(https?:\/\/|www\.|t\.me\/|\b[\w-]{2,}\.(com|net|org|ru|tm|me|io|xyz|info|top|site|online|link|app|dev|tk|ly|gg|uz|kz|tr|de|co|su|pro|club|shop|store|live|tv|cc|biz|ua|by)\b)/i;
  const roleOf = (dev) => (((INFO.roles || {})[dev] || [])[0] || '');
  const isStaff = (dev) => { const r0 = roleOf(dev); return r0 === 'o' || r0 === 'a'; };   // 1.46.4: eýesi / adminler (chat admin hem)
  let GPIN = null;   // 1.46.4: öz berkiden habarym (abuna täzelenýänçä)
  // 1.46.4: alynty / berkidilen habar → asyl habara geç (ýalpyldap görkezilýär)
  function rpJump(id) {
    const C = window.C; if (!id || !C) return;
    const el = Array.from(document.querySelectorAll('.tgc [data-rp]')).find((x) => x.getAttribute('data-rp') === id);
    if (!el) { C.say('↩️ ' + C.T()[C.state.lang].rp_gone); return; }
    el.scrollIntoView({ block: 'center', behavior: 'smooth' });
    try { el.animate([{ boxShadow: '0 0 0 3px rgba(255,210,122,.95)' }, { boxShadow: '0 0 0 3px rgba(255,210,122,.95)', offset: 0.6 }, { boxShadow: '0 0 0 0 rgba(255,210,122,0)' }], { duration: 1800 }); } catch (e) {}
  }
  const SR = {};   // 1.45: gözlegden tapylan nikler
  const nameOf = (dev) => { const r = (INFO.roles || {})[dev], p = P2[dev], d = DMS[dev], g = G.slice().reverse().find((m) => m.i === dev);
    return (p && p.n) || (r && r[1]) || (d && d.n) || (g && g.n) || SR[dev] || '?'; };
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
  // 1.46.1: käbir telefonda uly surat kiçeldilende kanwas boş (şeffaf / gara) galýar — beýle surat iberilmeýär
  function blankCanvas(c) {
    try { const d = c.getContext('2d').getImageData(0, 0, c.width, c.height).data, step = Math.max(1, Math.floor(d.length / 4 / 3000)) * 4; let n = 0;
      for (let i = 0; i < d.length; i += step) { if (d[i + 3] > 0 && d[i] + d[i + 1] + d[i + 2] > 24 && ++n > 15) return false; }
      return true; } catch (e) { return false; }
  }
  function fitShrink(file, max, limit, cb) {
    const rd = new FileReader();
    rd.onload = () => {
      const img = new Image();
      img.onload = () => {
        let dim = max, out = '';
        while (dim >= 420 && !out) {
          const k = Math.min(1, dim / Math.max(img.width, img.height)), c = document.createElement('canvas');
          c.width = Math.round(img.width * k); c.height = Math.round(img.height * k); c.getContext('2d').drawImage(img, 0, 0, c.width, c.height);
          if (blankCanvas(c)) { dim = Math.round(dim * 0.7); continue; }   // boş çykdy — kiçiräk synan
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
      return { id: s.key, f: s.flag, n: c ? { tk: c[2] + sfx, ru: c[3] + sfx, tr: c[4] + sfx } : { tk: s.country, ru: s.country, tr: s.country }, t: s.title || s.country, p: s.proto, lat: c ? c[0] : 50, lon: c ? c[1] : 10, game: s.game, free: s.free !== false, both: !!s.both, lock: !!s.lock };
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

    /** 1.47.6: «Admine ýaz» — surat (töleg çeki) göni şu ýerden. */
    P.sendTkImg = function (e) {
      const f = e && e.target && e.target.files && e.target.files[0]; if (e && e.target) e.target.value = ''; if (!f) return;
      if (this._isBan && this._isBan()) return;
      const go = (max, q) => shrink(f, max, q, (d) => {
        if (!d) return; if (d.length > 108000 && max > 500) { go(Math.round(max * 0.75), q - 0.08); return; }
        const s = this.state, id = Date.now();
        this.setState({ chat: s.chat.concat([{ id, who: 'u', t: '', img: d, time: this.hm(id), tick: '✓' }]), myTkSt: s.myTkSt === 'closed' || !s.myTkSt ? 'open' : s.myTkSt, aiTyping: !!INFO.ai && !s.human });
        try { NB.tkImg(JSON.stringify({ ph: d, t: '🧾', nick: this.meName, tid: s.tkId || 0 })); } catch (e2) {}
        clearTimeout(this.aiT); this.aiT = setTimeout(() => this.setState({ aiTyping: false }), 90000); });
      go(1000, 0.75);
    };
    /** Admine ýaz: habar bota gidýär (AI derrew, admin Telegramda jogap berýär). */
    P.sendMsg = function (text) {
      text = String(text || '').trim().slice(0, 1000); if (!text) return;
      if (this.state.tkRp) { text = '» ' + this.state.tkRp.n + ': ' + this.state.tkRp.t.replace(/\n/g, ' ') + '\n' + text; this.setState({ tkRp: null }); }   // 1.47: jogap
      if (this._isBan && this._isBan()) return;
      const s = this.state, id = Date.now(), tx = this.T()[s.lang];
      this.setState({ chat: s.chat.concat([{ id, who: 'u', t: text, time: this.hm(id), tick: '✓' }]), chatIn: '', fb: '',
        myTkSt: s.myTkSt === 'closed' || !s.myTkSt ? 'open' : s.myTkSt, aiTyping: !!INFO.ai && !s.human });
      NB.send(JSON.stringify({ k: 'tk', t: text, nick: this.meName, tid: s.tkId || 0 }));
      if (s.st !== 'on' && !INFO.fs) this.say(tx.q_wait);
      clearTimeout(this.aiT); this.aiT = setTimeout(() => this.setState({ aiTyping: false }), 90000);
    };

    const T0 = P.T;
    P.T = function () { const T = T0.call(this); if (SESS !== 60) ['tk', 'ru', 'tr'].forEach((l) => { if (T[l]) Object.assign(T[l], sessTx(l, SESS)); }); return T; };

    const rv0 = P.renderVals;
    P.renderVals = function () {
      const r = rv0.call(this), s = this.state, tx = r.tx, on = s.st === 'on', now = Date.now();
      Object.assign(tx, RKX[s.lang] || RKX.tk);
      if (r.phase && document.documentElement.className !== 'ph-' + r.phase) document.documentElement.className = 'ph-' + r.phase;   // wagta görä tema
      if (INFO.ver) ['s_updS', 'i_ver'].forEach((k) => { tx[k] = String(tx[k]).replace(/1\.\d+(\.\d+)?/, INFO.ver); });
      const kexp = s.kexp; // -1 ýok, 0 çäksiz, >0 möhlet (sn)
      const keyLeft = kexp > 0 ? Math.max(0, kexp - now / 1000) : 0;
      const fmtLeft = (sec) => { const hh = Math.floor(sec / 3600), mm = Math.floor(sec % 3600 / 60); return hh >= 24 ? Math.floor(hh / 24) + ' ' + tx.days + ' ' + (hh % 24) + ' ' + tx.hh : hh + ' ' + tx.hh + ' ' + two(mm) + ' ' + tx.mm; };
      const keyTxt = s.hasKey ? (kexp === 0 ? '♾' : fmtLeft(keyLeft)) : '—';
      // wagt / açar
      r.timerLbl = s.hasKey ? tx.keyL : tx.left;
      r.timer = s.hasKey ? keyTxt : s.nolim ? '♾' : two(Math.floor(s.left / 3600)) + ':' + two(Math.floor(s.left % 3600 / 60)) + ':' + two(s.left % 60);
      r.showUl = on && !s.hasKey && !s.nolim;
      // 1.44: nigini üýtgetmedik (mugt, wagt çägi bar) ulanyja — her 6 sagatda bir gezek, açylandan 15 sekunt soň
      { const nbAt = +(LS.get('nbAt', 0) || 0), want = !INFO.nkb && !s.hasKey && !s.nolim && !INFO.prem && SESS > 0 && Date.now() - nbAt > 6 * 3600000;
        if (want && !this._nbT) this._nbT = setTimeout(() => this.setState({ nbShow: true }), 15000);
        r.nbOn = s.page === 'main' && want && !!s.nbShow && !s.menu;
        r.nbS = tx.nb_s.replace('{a}', hrsT(s.lang, SESS)).replace('{b}', hrsT(s.lang, SESS + 30));
        const hide = () => { LS.set('nbAt', Date.now()); this.setState({ nbShow: false }); };
        r.nbGo = () => { hide(); this.setState({ page: 'profile' }); }; r.nbX = hide; }
      if (admMe().o2 && Array.isArray(r.botTiles)) r.botTiles = r.botTiles.filter((t) => t.go !== this.sysToggle);   // 1.47: owner 2 — «Ulgamy duruz» ýok
      if (Array.isArray(r.botTiles) && A && A.pgf != null) {   // 1.47: mugt PUBG serwerini öçürmek / açmak (trafik köp bolanda)
        const pgf = !!A.pgf; r.botTiles = r.botTiles.concat([{ i: '🎮', t: (({ ru: 'Free PUBG: ', tr: 'Free PUBG: ' })[s.lang] || 'Mugt PUBG: ') + (pgf ? '🟢' : '🔴'), st: pgf ? 'border-color:rgba(111,219,156,.7)' : 'border-color:rgba(255,138,120,.6)',
          go: () => this.confirm(pgf ? (({ ru: 'Отключить бесплатный сервер PUBG? Подключённые перейдут на другой сервер.', tr: 'Ücretsiz PUBG sunucusu kapatılsın mı? Bağlı olanlar başka sunucuya geçer.' })[s.lang] || 'Mugt PUBG serweri öçürilsinmi? Birikenler başga serwere geçer.') : (({ ru: 'Включить бесплатный сервер PUBG?', tr: 'Ücretsiz PUBG sunucusu açılsın mı?' })[s.lang] || 'Mugt PUBG serweri açylsynmy?'),
            pgf ? '🔴' : '🟢', () => { act('pubgfree', { on: !pgf }); A.pgf = !pgf; this.setState({ gTick: (this.state.gTick || 0) + 1 }); }, false) }]); }
      if (Array.isArray(r.botTiles) && A && A.pown != null) {   // 1.47.9: Premium diňe eýesiniň abunasyndan (açyk bolsa mugtdan kod almaýar)
        const po = !!A.pown; r.botTiles = r.botTiles.concat([{ i: '👑', t: 'Premium: ' + (po ? (({ ru: 'только моя подписка', tr: 'sadece abonelik' })[s.lang] || 'diňe abuna') : (({ ru: 'смешанный', tr: 'karışık' })[s.lang] || 'garyşyk')) + (po ? ' 🟢' : ' 🔴'), st: po ? 'border-color:rgba(255,200,90,.8)' : 'border-color:rgba(255,255,255,.2)',
          go: () => this.confirm(po ? (({ ru: 'Выключить? Premium снова будет дополняться бесплатными кодами и кодами каналов.', tr: 'Kapatılsın mı? Premium yine ücretsiz ve kanal kodlarıyla doldurulur.' })[s.lang] || 'Öçürilsinmi? Premium ýene mugt we kanal kodlary bilen doldurylar.')
            : (({ ru: 'Включить? Premium будет только из вашей подписки, бесплатные коды не берутся.', tr: 'Açılsın mı? Premium sadece sizin aboneliğinizden olur, ücretsiz kodlar alınmaz.' })[s.lang] || 'Açylsynmy? Premium diňe siziň abunaňyzdan bolar, mugt kodlar alynmaz.'),
            po ? '🔴' : '🟢', () => { act('premown', { on: !po }); A.pown = !po; this.setState({ gTick: (this.state.gTick || 0) + 1 }); }, false) }]); }
      // 1.47: köne programmadan göçmek — birikmekden öň hökmany «Işlet» penjiresi (köne programma «Admine ýaz»-da açylýar, kod göçürilen)
      { let M = this._mig; if (!M) { try { M = this._mig = J(NB.mig(), {}); } catch (e) { M = this._mig = {}; } }
        if (M.old && !M.done && !this._migSent) { this._migSent = true; try { NB.migSend(); } catch (e) {} }
        const L = ({ ru: ['Запустите программу', 'Новая программа переносит ваш Premium, ник и уровень из старой. Нажмите «Запустить» — откроется старая программа.', 'Там нажмите на поле ввода → «Вставить» → отправьте ➤. Затем вернитесь сюда.', 'Запустить', 'Ожидание кода из старой программы…', 'Открыть старую программу', 'Продолжить без переноса', '✅ Перенесено! Подключаемся…', 'Удалить старую программу', 'Закрыть'],
          tr: ['Programı çalıştırın', 'Yeni program eski programdaki Premium, takma ad ve seviyenizi alır. «Çalıştır»a basın — eski program açılır.', 'Orada yazı alanına basın → «Yapıştır» → gönderin ➤. Sonra buraya dönün.', 'Çalıştır', 'Eski programdan kod bekleniyor…', 'Eski programı aç', 'Aktarmadan devam et', '✅ Aktarıldı! Bağlanılıyor…', 'Eski programı sil', 'Kapat'] })[s.lang]
          || ['Programmany işlediň', 'Täze programma köne programmadaky Premium, nik we derejäňizi alýar. «Işlet» düwmesine basyň — köne programma açylar.', 'Şol ýerde ýazuw ýerine basyň → «Goý / Вставить» → iberiň ➤. Soň şu ýere gaýdyp geliň.', 'Işlet', 'Köne programmadan kod garaşylýar…', 'Köne programmany aç', 'Geçirmezden dowam et', '✅ Geçirildi! Birigýär…', 'Köne programmany poz', 'Ýap'];
        const stp = s.migStep || 0;
        r.mgOn = !!s.migGate; r.mgT = L[0]; r.mgS1 = L[1]; r.mgS2 = L[2];
        r.mg0 = stp === 0; r.mg1 = stp === 1; r.mg2 = stp === 2;
        r.mgGoT = stp === 0 ? L[3] : L[5]; r.mgWait = L[4]; r.mgCode = M.c || ''; r.mgOk = L[7]; r.mgDelT = L[8]; r.mgXT = L[9];
        r.mgSkipOn = stp === 1 && Date.now() - (s.migAt || 0) > 180000; r.mgSkipT = L[6];   // 3 minutdan soň (bot jogap bermese — programma ulanylmaz ýagdaýda galmasyn)
        r.mgGo = () => { try { NB.migGo(); } catch (e) {} this.setState({ migStep: 1, migAt: s.migAt || Date.now() }); };
        r.mgSkip = () => { this.setState({ migGate: false }); try { NB.migSkip(); } catch (e) {} };
        r.mgDel = () => { this.setState({ migGate: false }); try { NB.delOld(); } catch (e) {} };
        r.mgX = () => this.setState({ migGate: false }); }
      // 1.47: baş sahypa — PUBG düwmesi (hemmä) we Premium / Free (Premium ulanyjylara); sazlama NB.select / NB.pubg arkaly
      { const PRm = !!INFO.prem, gN = SV.filter((x) => x.game && !x.lock).length;
        const L2 = ({ ru: ['Для PUBG пока нет рабочего кода', 'работает', 'нет'], tr: ['PUBG için henüz çalışan kod yok', 'çalışıyor', 'yok'] })[s.lang] || ['PUBG üçin entek işleýän kod ýok', 'işleýär', 'ýok'];
        const gOk = SV.filter((x) => x.game && !x.lock && ((s.pings || {})[x.id] || 0) > 0).length;   // 1.47: ping beren PUBG serwerleri
        r.pgSub = gN ? (gOk ? '● ' + gOk + ' ' + L2[1] : gN + ' serwer') : L2[2]; r.pgSubCls = gN ? (gOk ? 'pgs-ok' : '') : 'pgs-no';
        r.modeOn = s.page === 'main' && !s.menu;
        r.pgCls = s.pubg ? 'mpg mpg-on tap' : 'mpg tap';
        r.pgGo = () => { const on = !s.pubg; if (on && !gN) { this.say('⚠️ ' + L2[0]); return; } try { NB.pubg(on); } catch (e) {} this.setState({ pubg: on }); };
        r.pmOn = PRm;
        const md_ = s.pick >= 0 ? -1 : s.autoB ? 1 : s.autoP ? 0 : 2;   // 1.47.9: Premium · Auto (ikisinden iň çalt) · Free
        r.pmCls = md_ === 0 ? 'on' : ''; r.bhCls = md_ === 1 ? 'on' : ''; r.frCls = md_ === 2 ? 'on' : ''; r.msegCls = md_ < 0 ? 'mx' : 'm' + md_; 
        r.pmGo = () => this.setState({ pick: -1, autoP: true, autoB: false }); r.bhGo = () => this.setState({ pick: -1, autoP: false, autoB: true }); r.frGo = () => this.setState({ pick: -1, autoP: false, autoB: false }); }
      r.showUpd = !!s.upd && !s.menu;
      r.updTxt = s.dl >= 0 ? tx.u_dl.replace('{p}', String(s.dl)) : 'Türkmen VPN ' + s.upd;
      r.updBtn = s.dl >= 0 ? '…' : tx.u_btn; r.doUpd = () => NB.update();
      r.showWarn = s.hasKey && kexp > 0 && keyLeft <= 43200 && !s.warnHidden;
      r.warnText = tx.w_text.replace('{t}', fmtLeft(keyLeft));
      // 1.44: häzirki açar (aýyrmak) we ulanan açarlarym
      { const KI = s.page === 'key' ? J(typeof NB.keyInfo === 'function' ? NB.keyInfo() : '{}', {}) : {}, dT = (t) => (t > 0 ? new Date(t * 1000).toLocaleDateString('ru-RU') : '');
        const stOf = (st) => (st === 'ok' ? ['on-g', '🟢 ' + tx.k2_on] : st === 'used' ? ['on-n', tx.k2_used] : ['tk-closed', tx.k2_bad]);
        const cur = KI.k ? stOf(KI.st) : null, ex = +KI.exp;
        r.kc = { on: !!KI.k, k: KI.k || '', cls: KI.prem && KI.st === 'ok' ? 'kc-p' : '', stCls: cur ? cur[0] : '', stT: cur ? cur[1] : '',
          sub: [KI.prem ? tx.k2_prem : tx.k2_gift, ex === 0 ? tx.k2_unl : ex > 0 ? (ex * 1000 > Date.now() ? tx.k2_left.replace('{d}', String(Math.ceil((ex * 1000 - Date.now()) / 86400000))) : dT(ex)) : ''].filter(Boolean).join(' · '),
          cp: () => { NB.copy(KI.k); this.say('✓ ' + tx.copied); },
          del: () => this.confirm(tx.k2_q, '🗑 ' + tx.k2_del, () => { NB.keyDel(); this.setState({ hasKey: false, keyMsg: '', kTick: (this.state.kTick || 0) + 1 }); this.say('🗑 ' + tx.k2_ok); }, false) };
        const H = (KI.hist || []).filter((x) => !x.cur);
        r.kh = { on: H.length > 0, list: H.map((x) => { const q = stOf(x.st); return { k: x.k, sub: (x.prem ? tx.k2_prem : tx.k2_gift) + ' · ' + tx.k2_at.replace('{t}', dT(x.t)), stCls: q[0], stT: q[1],
          canUse: x.st === 'ok', use: () => { this.setState({ keyIn: x.k }); setTimeout(() => this.checkKey(), 0); } }; }) }; }
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
      const GE = editsOf(G.concat(LCTL), 'i', 't');
      const gl = G.filter((m) => !m.re && !m.dl && !m.ed && !m.sty && !GE.D[m.id] && !gDel[m.id] && bans.indexOf(m.i) < 0).concat(LGM), RXG = rxAgg(G.concat(LRX));
      gl.forEach((m) => { if (m.pi && !GI[m.pi]) askImg('g', m.pi); });
      r.gMsgs = gl.slice(-300).map((m) => {   // 1.43.5: ekranda soňky 300 habar (telefon haýallamasyn)
        const mine = m.i === me, nm = mine ? this.meName : m.n || '?', lvq = mine ? (LS.get('lvl', {}) || {}).lv || 0 : lvOf(m.i, m.lv), rt = rkT(lvq);
        const ph = mine ? s.photo : ((PH[m.i] || {}).d || '');
        return { name: nm + (mine ? ' · ' + tx.g_you : ''), ini: ini(nm), bg: mine ? '#E0B04A' : colorOf(m.i), nc: mine ? '#06100B' : colorOf(m.i), photo: ph, hasPh: !!ph, noPh: !ph,
          t: m.st ? '' : GE.E[m.id] != null ? GE.E[m.id] : m.t, time: (GE.E[m.id] != null ? tx.m_edited + ' ' : '') + this.hm((m.time || 0) * 1000 || now) + (m.pend ? ' ⏳' : '') + (m.v ? ' · v' + String(m.v).slice(0, 10) : ''), gk: m.id, cls: mine ? 'gm-me' : 'gm-o', bcls: mine ? 'gb-me' : 'gb-o', canDel: false, del: null,
          prof: () => this.openProf(m.i), isO: isOwnShown(m.i), isA: roleOf(m.i) === 'a', isS: roleOf(m.i) === 's', isP: isPrem(m.i), ncls: isOwnShown(m.i) ? 'goldtxt' : (lvq ? rkNm(rt) : ''), fr: '', hasFr: !!lvq && !isOwnShown(m.i), frN: String(rt), frCls: rt >= 10 ? 'frx' : '',   // 1.47: surat çarçuwa
          isSt: !!m.st, st: m.st || '', hasImg: !!(m.pi && GI[m.pi]), img: (m.pi && GI[m.pi]) || '', zoom: () => this.setState({ zoom: GI[m.pi] || '' }),
          hasRp: !!(m.rp && m.rp.n), rpN: m.rp ? m.rp.n : '', rpT: m.rp ? m.rp.t : '', rpI: m.rp ? m.rp.i || '' : '',
          hasLv: isOwnShown(m.i) ? false : roleOf(m.i) === 'o' ? true : lvq >= 2, lv: String(rt),
          rx: rxList(RXG, m.id, me, (e) => this.gReact(m.id, e)), hasRx: !!RXG[m.id] && Object.keys(RXG[m.id]).length > 0,
          rxOpen: s.rxFor === m.id, rxPick: RX_E.map((e) => ({ e, go: () => { this.setState({ rxFor: null }); this.gReact(m.id, e); } })), rpGo: () => this.replyTo(m.id) };
      });
      // 1.46.4: eýesiniň we adminleriň salgylary basylýar
      const gSrc = {}; gl.forEach((m) => { gSrc[m.id] = m.i; });
      const NKD = {}; G.forEach((m) => { if (m.n && m.i) NKD[String(m.n).toLowerCase()] = m.i; }); if (this.meName) NKD[String(this.meName).toLowerCase()] = me;
      const mParts = (parts) => [].concat(...parts.map((p) => !p.isT ? [p] : String(p.t).split(/(@[\w.\-]{2,20})/).filter((x) => x).map((x) => {
        const d = x[0] === '@' ? NKD[x.slice(1).toLowerCase()] : null;
        return d ? { isM: true, isT: false, isL: false, t: x, go: () => this.openProf(d) } : MENT_X.test(x) ? { isM: true, isT: false, isL: false, t: x, go: () => this.openTag(x.slice(1)) } : { isT: true, isL: false, isM: false, t: x }; })));
      r.gMsgs = r.gMsgs.map((g) => { const lk = !!g.t && isStaff(gSrc[g.gk]) && LINK_RE.test(g.t), mn = !!g.t && /@[\w.\-]{2,20}/.test(g.t);
        return Object.assign(g, { hasLk: lk || mn, noLk: !(lk || mn), parts: mn ? mParts(lk ? this.lk(g.t) : [{ isT: true, t: g.t }]) : lk ? this.lk(g.t) : [] }); });
      // 1.46.4: berkidilen habar
      { const am4 = admMe(), PN = GPIN && Date.now() - GPIN.at < 15 * 60000 ? (GPIN.id ? GPIN : null) : (INFO.gpin && INFO.gpin.id ? INFO.gpin : null);
        const canP = !!s.admOn && (am4.role === 'f' || am4.perm === 'all' || am4.perm === 'chat');
        r.gPinH = PN ? '📌 ' + (PN.n || tx.g_pinT) : tx.g_pinT; r.gPinTxt = PN ? PN.t : tx.g_pin; r.gPinGo = PN ? () => rpJump(PN.id) : null;
        r.gPinX = !!PN && canP;
        r.gPinUn = (e) => { if (e && e.stopPropagation) e.stopPropagation(); act('gpin', { id: '' }); GPIN = { id: '', at: Date.now() }; this.say('📌 ' + tx.g_pinOff); this.setState({ gTick: (this.state.gTick || 0) + 1 }); };
        this._canPin = canP;   // 1.46.5: 📌 — habary basyp saklanda menýuda
        this.pinMsg = (id) => { const m = G.find((q) => q.id === id) || {}, n = m.i === me ? this.meName : (m.n || '?'), t = (m.t || (m.st ? m.st : m.pi ? '📷' : '')).slice(0, 200);
          act('gpin', { id, n, t }); GPIN = { id, n, t, at: Date.now() }; this.say('📌 ' + tx.g_pinOk); this.setState({ gTick: (this.state.gTick || 0) + 1 }); }; }
      if (s.page === 'global') lvAsk(gl.map((m) => m.i));
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
      // 1.33: «Açar satyn al» aýryldy (eýesiniň islegi)
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
          canKick: isF && !!c.u && !mine, kick: () => { act('kick', { id: c.id }); c.u = null; this.setState({ admTick: (this.state.admTick || 0) + 1 }); this.say('🔓 ' + tx.ad_kicked); },
          infoOn: c.role !== 'f' && (c.pg > 0 || !!c.dn), info: [c.dn ? tx.ap_dev.replace('{n}', c.dn) : '', c.pg > 0 ? tx.ap_pg.replace('{n}', String(c.pg)) : ''].filter(Boolean).join(' · '),
          pmOn: isF && c.role !== 'f', pms: [['tk', tx.ap_tk], ['all', tx.ap_all], ['sel', tx.ap_sel]].map((q) => ({ t: q[1], cls: c.perm === q[0] ? 'chip-on' : '', p: c.perm === q[0] ? 'true' : 'false',
            pick: () => { if (c.perm === q[0]) return; act('aperm', { id: c.id, perm: q[0] }); c.perm = q[0]; this.setState({ admTick: (this.state.admTick || 0) + 1 }); } })) };
      });
      // 1 girişlik admin açary
      r.onceN = s.onceN || ''; r.onOnceN = (e) => this.setState({ onceN: e.target.value });
      r.oncePerms = [['tk', tx.oa_tk], ['all', tx.oa_all], ['sel', tx.oa_sel]].map(([k, t]) => { const on = (s.oncePerm || 'tk') === k; return { t, p: on ? 'true' : 'false', cls: on ? 'chip-on' : '', pick: () => this.setState({ oncePerm: k }) }; });
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
      r.banOn = !!INFO.uban && !s.admOn; r.banTxt = tx.ub_full;   // 1.47.21: gadagan — tutuş ekran (hiç bir düwmä basyp bolmaýar)
      r.cfOn = !!s.cf; r.cfText = s.cf ? s.cf.text : ''; r.cfOk = s.cf ? s.cf.ok : ''; r.cfNo = this.cfNo; r.cfYes = this.cfYes;
      r.cfBg = s.cf && s.cf.danger ? 'linear-gradient(90deg,#FF8A78,#E05A48)' : 'linear-gradient(90deg,#E0B04A,#C8902E)';
      // Awtomatik kartasy: haýsy ýurtlar bar we näçe serwer
      const real = SV.filter((v) => !v.game), fl = [];
      real.forEach((v) => { if (fl.indexOf(v.f) < 0) fl.push(v.f); });
      r.svFlags = fl.slice(0, 9).join(' ') + (fl.length > 9 ? ' …' : '') || r.offCard.sub;
      r.autoFreeT = ({ ru: '🎁 БЕСПЛАТНО', tr: '🎁 ÜCRETSİZ' })[s.lang] || '🎁 MUGT KOD'; r.homeFree = !INFO.prem && !(s.pick >= 0); r.homeCls = r.homeFree ? 'glass tap autohot' : 'glass tap';   // 1.47.2: mugt — baş sahypada hem görünýär
      r.svCount = ({ tk: '{n} serwer', ru: '{n} серв.', tr: '{n} sunucu' }[s.lang] || '{n}').replace('{n}', String(SV.length));
      r.myCode = INFO.code || '—'; r.cpMyId = () => { NB.copy(INFO.code || ''); this.say('✓ ' + tx.copied); };   // 1.47: ID göçürmek
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
      { // 1.47.21: Engelliler 🩼 — möhletsiz gadagan edilenler (diňe eýesi); «Aç» — gadaganlygy aýyrýar
        const bl = (A && A.bans) || [];
        if (isF) r.botTiles = r.botTiles.concat([{ i: '🩼', t: tx.bn_title + ' (' + bl.length + ')', go: () => { act('get'); this.setState({ page: 'adm_bn' }); }, st: '' }]);
        r.isAdmBn = s.page === 'adm_bn' && s.admOn && isF; if (r.isAdmBn) r.pageTitle = '🩼 ' + tx.bn_title;
        r.bnEmpty = !bl.length;
        r.bnList = bl.map((b) => ({ n: b.n || '?', sub: (b.code || '') + (b.at ? ' · ' + b.at : '') + (b.ver ? ' · v' + b.ver : ''),
          prof: () => this.openProf(b.dev),
          un: () => this.confirm(tx.bn_unQ.replace('{n}', b.n || '?'), '✅ ' + tx.bn_un, () => {
            act('ban', { dev: b.dev, on: false }); A.bans = bl.filter((x) => x.dev !== b.dev); if (A.us && A.us[b.dev]) A.us[b.dev].ban = false;
            this.setState({ admTick: (this.state.admTick || 0) + 1 }); }) })); }
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
      if (at && at.u) { const ph = (PH[at.u] || {}).d || '';   // 1.31: biletde ýazanyň suraty → basylsa profiline
        if (!ph && !phAsked[at.u]) { phAsked[at.u] = 1; NB.getPhoto(at.u); }
        r.at = Object.assign({}, r.at, { photo: ph, hasPh: !!ph, noPh: !ph }); r.atProf = () => this.openProf(at.u); }
      r.auProf = () => this.openProf(s.admU);
      if (at && at.fb && at.st === 'closed') r.atMsgs = r.atMsgs.concat([{ t: at.fb === '👍' ? tx.fb_aUp : tx.fb_aDown, time: '', cls: 'bub-s', isAi: false }]);
      // ---- 1.16 ----
      const pg = s.page, me1 = INFO.dev, myRole = roleOf(me1);
      // kota duýduryşy: diňe eýesine, «Sil» basylýança durýar
      { const QA = LS.get('qAlerts', {}), own = myRole === 'o' || admMe().role === 'f';
        r.qAlerts = own ? Object.keys(QA).filter((id) => !QA[id].x).map((id) => ({ t: QA[id].t, del: () => { const q = LS.get('qAlerts', {}); if (q[id]) q[id].x = 1; LS.set('qAlerts', q); this.setState({ qTick: (this.state.qTick || 0) + 1 }); } })) : []; }
      r.isOwner = myRole === 'o' && ownOn(me1); r.isAdminR = myRole === 'a'; r.ownerTag = r.isOwner && pg === 'main'; r.appVer = INFO.ver || '';
      // oýun serwerleri: hemmesi jogap bermese bellik; täzele + ping
      { const gp = SV.filter((v) => v.game).map((v) => s.pings[v.id]);
        r.gAllNa = gp.length > 0 && gp.every((m) => m != null && m < 0); r.gHasNa = !r.gAllNa;
        r.gRefCls = s.refreshing || s.testing ? 'spin' : '';
        r.gRefresh = () => { if (this.state.refreshing) return; this.setState({ refreshing: true, gRetest: true }); NB.refresh(); }; } r.meNcls = myRole === 'o' ? 'goldtxt' : '';
      r.nkBonT = INFO.nkb ? tx.nk_bonYes : tx.nk_bonNo;
      r.nkIn = s.nkIn == null ? this.meName : s.nkIn; r.onNk = this.onNk; r.saveNk = this.saveNk;
      r.tgIn = s.tgIn != null ? s.tgIn : (tagOf(INFO.dev) || ''); r.onTg = this.onTg; r.saveTg = this.saveTg;   // 1.47.22: öz @belgisi
      r.tgMsg = s.tgSt === 'ok' ? tx.tg_ok : s.tgSt === 'bad' ? tx.tg_bad : s.tgSt === 'taken' ? tx.tg_taken : s.tgSt === 'wait' ? '…' : tx.tg_hint;
      r.tgCls = s.tgSt === 'ok' ? 'nk-ok' : (s.tgSt === 'bad' || s.tgSt === 'taken') ? 'nk-bad' : '';
      r.nkMsg = s.nkSt ? tx['nk_' + s.nkSt] : ''; r.nkCls = s.nkSt === 'ok' ? 'nk-ok' : s.nkSt === 'wait' ? '' : s.nkSt ? 'nk-bad' : '';
      const bgUrl = (d) => (d ? 'linear-gradient(rgba(6,16,11,.45),rgba(6,16,11,.88)),url(' + d + ')' : 'none');
      { const mt2 = rkT((LS.get('lvl', {}) || {}).lv || 1); r.meFrN = String(mt2); r.meFrCls = mt2 >= 10 ? 'frx' : ''; }   // 1.47: öz çarçuwam
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
        const ownTop = admMe().role === 'f' || roleOf(INFO.dev) === 'o';   // 1.47: eýesi — atlaryna basyp profilini açýar
        r.topList = top.map((q, i) => ({ n: (i < 3 ? ['🥇', '🥈', '🥉'][i] : (i + 1) + '.') + ' ' + q[0], c: tx.lv_inv.replace('{n}', String(q[1])), lv: String(rkT(q[2])),
          cls: ownTop && q[3] ? 'tap' : '', open: () => { if (ownTop && q[3]) this.openProf(q[3]); } })); }
      // 1.19: açar satyn almak
      r.isBuy = false;   // 1.33: «Açar satyn al» aýryldy
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
      { const L = LS.get('lvl', null), t0 = L ? rkT(L.lv) : 1, xp = L ? +L.xp || 0 : 0, nx = t0 < RK_L.length ? (L && L.next) || RK_L[t0] : 0;
        r.rkT = String(t0); r.rkName = tx['rk_n' + t0]; r.rkNcls = rkNc(t0); r.rkAria = tx.p_rank + ': ' + r.rkName + ' · ' + t0;
        r.rkXpT = tx.rk_pts.replace('{x}', t0 < RK_L.length ? xp + ' / ' + nx : String(xp));
        r.rkHeroSub = tx.rk_lv.replace('{n}', String(t0)) + ' · ' + tx.rk_pts.replace('{x}', String(xp));
        r.rkNext = t0 >= 10 ? tx.rk_max : tx.rk_left.replace('{n}', tx['rk_n' + (t0 + 1)]).replace('{x}', String(Math.max(0, nx - xp)));
        if (!L) r.lvBar = 0;
        r.goRank = () => { this._rkBack = this.state.page; this.setState({ page: 'rank', menu: false, fan: false }); };
        r.isRank = pg === 'rank'; if (r.isRank) r.pageTitle = tx.p_rank;
        if (r.isRank && Date.now() - (this._lvQ || 0) > 120000) { this._lvQ = Date.now(); NB.send(JSON.stringify({ k: 'lvlq' })); }
        r.rkRows = RK_L.map((need, i) => { const t = i + 1, got = t <= t0, cur = t === t0;
          return { t: String(t), name: tx['rk_n' + t], ncls: got ? rkNc(t) : '', lk: cur ? 'fx' : got ? 'lite' : 'lock',
            need: cur ? tx.rk_curP.replace('{x}', String(need)).replace('{y}', String(xp)) : got ? tx.rk_gotP.replace('{x}', String(need)) : tx.rk_need.replace('{x}', String(need)),
            pk: rkPk(t, tx), st: cur ? tx.rk_now : got ? '✓' : '🔒', stc: cur ? 'cur' : got ? 'ok' : 'lk', cls: cur ? 'rk-cur' : got ? 'rk-got' : 'rk-lk',
            open: () => this.setState({ rkm: { t, up: false } }) }; });
        const M = s.rkm, mt = M ? rkT(M.t) : 1, mgot = mt <= t0;
        r.rkmOn = !!M; r.rkmT = String(mt); r.rkmCls = M && M.up ? 'up' : mgot ? '' : 'lkd';
        r.rkmTitle = M && M.up ? tx.rk_upT : tx.rk_lv.replace('{n}', String(mt)); r.rkmName = tx['rk_n' + mt]; r.rkmNcls = rkNc(mt);
        r.rkmSub = M && M.up ? (M.days ? tx.rk_upGift.replace('{d}', String(M.days)) : tx.rk_upSub) : mgot ? tx.rk_gotL2.replace('{x}', String(RK_L[mt - 1])) : tx.rk_wait.replace('{x}', String(RK_L[mt - 1]));
        r.rkmPk = rkPk(mt, tx); r.rkmBtn = M && M.up ? tx.rk_ok : tx.close; r.rkmX = () => this.setState({ rkm: null }); }
      // 1.20: gizli nyşan — baş sahypadaky kiçi düwme (Sazlamalardaky bilen birmeňzeş)
      { const dg = !!(s.disg != null ? s.disg : INFO.disg);
        r.dgCls = dg ? 'on' : ''; r.dgAria = dg ? 'true' : 'false';
        r.dgTap = () => this.confirm(dg ? tx.dg_qOff : tx.dg_qOn, dg ? tx.dg_yOff : tx.dg_yOn, () => { NB.disguise(!dg); this.setState({ disg: !dg }); this.say(dg ? tx.dg_doneOff : tx.dg_doneOn); }); }
      r.zoomOn = !!s.zoom; r.zoomSrc = s.zoom || ''; r.zoomClose = () => this.setState({ zoom: '' });
      r.onGPhoto = this.onGPhoto;
      // habarlar: eýesiniň habary altyn, surat
      let bi = 0; const ownAny = Object.keys(INFO.roles || {}).filter((d) => roleOf(d) === 'o'), ownShowN = !ownAny.length || ownAny.some((d) => ownOn(d));
      r.news = r.news.map((n0) => { const n = n0 && n0.isO && !ownShowN ? Object.assign({}, n0, { isO: false }) : n0;
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
        return Object.assign({}, n, { hasPoll: !!pl, pollQ: pl ? pl.q : '', pollOpts, pollTot: tx.pl_tot.replace('{n}', String(ptot)), canDel, del: () => this.confirm(tx.cf_ndel, '🗑 ' + tx.cf_yes, () => { act('ndel', { id: b.id }); NDEL[b.id] = true; this.setState({ bcast: (this.state.bcast || []).filter((x) => x.id !== b.id) }); }), hasBtn: btns.length > 0, btns, isO: true, tcls: 'goldtxt', date: b.time || '', title: /^[\p{L}\p{N}]/u.test(b.t || '') ? '📢 ' + b.t : (b.t || n.title), hasImg: !!(b.img && NI[b.img]), img: (b.img && NI[b.img]) || '', zoom: () => this.setState({ zoom: NI[b.img] || '' }) });
      });
      r.news = r.news.map((n) => Object.assign({}, n, { parts: withMent(withKeys(n.parts, this), this) }));
      r.msgs = r.msgs.map((m) => { const q = /^» [^\n]*\n/.exec(m.t || ''), body = q ? (m.t || '').slice(q[0].length) : m.t || '';   // 1.47: jogap (sitata)
        return Object.assign({}, m, { hasImg: !!m.img, img: m.img || '', rid: 'tk' + m.id, hasQ: !!q, q: q ? q[0].slice(2).trim() : '', parts: withMent(withKeys(this.lk(body), this), this) }); });
      r.tkRpOn = !!s.tkRp && pg === 'chat'; r.tkRpN = s.tkRp ? s.tkRp.n : ''; r.tkRpT = s.tkRp ? s.tkRp.t : '';
      r.rxWhoOn = !!(s.rxWho && s.rxWho.length); r.rxWhoX = () => this.setState({ rxWho: null });
      r.rxWhoT = ({ ru: 'Реакции', tr: 'Tepkiler' })[s.lang] || 'Tepkiler';
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
      r.bcAi = this.bcAi; r.bcAiT = s.bcAiWait ? '⏳ ' + tx.bc_aiWait : '✨ ' + tx.bc_ai;   // 1.47.22: AI bilen owadanlamak
      r.onBcImg = this.onBcImg; r.bcHasImg = !!s.bcImg; r.bcImg = s.bcImg || ''; r.bcImgDel = () => this.setState({ bcImg: '' });
      const ava = (dev) => { const ph = dev === me1 ? s.photo : thumbOf(dev), nm = dev === me1 ? this.meName : nameOf(dev);
        if (!ph && dev !== me1 && !phAsked[dev]) { phAsked[dev] = 1; NB.getPhoto(dev); }
        return { photo: ph || '', hasPh: !!ph, noPh: !ph, bg: colorOf(dev), ini: ini(nm), name: nm, isO: isOwnShown(dev), isA: roleOf(dev) === 'a', isS: roleOf(dev) === 's', isP: isPrem(dev), ncls: isOwnShown(dev) ? 'goldtxt' : '' }; };
      r.rxWhoRows = (s.rxWho || []).map((q) => Object.assign(ava(q.d), { e: q.e, open: () => { this.setState({ rxWho: null }); this.openProf(q.d); } }));   // 1.47
      // başga adamyň profili
      r.isUprof = pg === 'uprof' && !!s.upDev;
      if (r.isUprof) {
        const d = s.upDev, p = P2[d], st = (DMS[d] || {}).st || '', a = ava(d), mine = d === me1;
        const canDm = !mine && st !== 'blk' && ((p && p.dm) || !!DMS[d]);
        r.up = Object.assign(a, { otOn: isOwnShown(d), otags: isOwnShown(d) ? otChips(this) : [], tag: tagOf(d) ? '@' + tagOf(d) : '', cpTag: () => { const t_ = tagOf(d); if (!t_) return; NB.copy('@' + t_); this.say('✓ @' + t_); }, photo: (p && p.ph) || a.photo, hasPh: !!((p && p.ph) || a.photo), noPh: !((p && p.ph) || a.photo), bgImg: bgUrl(p && p.bg),
          sub: a.isO ? tx.vip_o : a.isA ? tx.vip_a : '', canDm, noDm: !canDm, notMe: !mine,
          why: mine ? tx.dm_me : st === 'blk' ? tx.dm_blocked : !p ? tx.nk_wait : tx.dm_noKey,
          write: () => this.openDm(d), zoom: () => this.setState({ zoom: (p && p.ph) || a.photo || '' }),
          blockT: st === 'blk' ? '✅ ' + tx.dm_unblk : '🚫 ' + tx.dm_blk, block: () => this.blockDm(d) });
        let ul = mine ? (LS.get('lvl', {}) || {}).lv || 0 : 0;   // derejesi: Global chatdaky iň soňky habaryndan
        if (!mine) { G.forEach((q) => { if (q.i === d && q.lv) ul = q.lv; }); ul = lvOf(d, ul); lvAsk([d]); }
        Object.assign(r.up, { hasRk: (ul >= 1 || roleOf(d) === 'o') && !a.isO, rkT: String(rkT(ul)), frCls: rkT(ul) >= 10 ? 'frx' : '', rkName: tx['rk_n' + rkT(ul)], rkNcls: rkNc(rkT(ul)) });
        // 1.21: sessiz; eýesine — ID we bal/dereje bermek
        const own = myRole === 'o' || admMe().role === 'f', canGive = !!(s.admOn && isF), au2 = (A && A.us && A.us[d]) || null, ux = UPX[d];
        const xpK = ux ? ux.xp : au2 && au2.xp != null ? au2.xp : null, lvK = ux ? ux.lv : xpK != null ? RK_L.filter((q) => xpK >= q).length : ul;
        Object.assign(r.up, { hasMute: !mine && !!DMS[d], muteT: MUTE[d] ? tx.dm_unmute : tx.dm_mute, mute: () => this.muteDm(d),
          isOwnV: own && !mine && canGive,   // 1.47: diňe admin paneline girende code: own && !mine && typeof NB.codeOf === 'function' ? NB.codeOf(d) || '—' : '—', cpId: () => { NB.copy(r.up.code); this.say('✓ ' + tx.copied); },
          lvNow: lvK ? tx.gv_now.replace('{n}', tx['rk_n' + rkT(lvK)]).replace('{l}', String(rkT(lvK))).replace('{x}', xpK != null ? String(xpK) : '?') : tx.gv_unk,
          canGive, needAdm: own && !mine && !canGive, goAdm: () => this.setState({ page: 'admin' }),
          giveX: () => { const x = parseInt(this.state.gvX, 10); if (!x) { this.say('⚠️ ' + tx.gv_bad); return; }
            this.confirm(tx.gv_qX.replace('{n}', a.name).replace('{x}', String(x)), '✅ ' + tx.gv_btn, () => { act('xpgive', { dev: d, x }); this.setState({ gvX: '' }); }, false); },
          lvBtns: RK_L.map((q, i) => ({ t: String(i + 1), name: tx['rk_n' + (i + 1)], cls: lvK === i + 1 ? 'on' : '',
            go: () => this.confirm(tx.gv_qLv.replace('{n}', a.name).replace('{r}', tx['rk_n' + (i + 1)]).replace('{l}', String(i + 1)), '✅ ' + tx.gv_lv, () => act('xpgive', { dev: d, lv: i + 1 }), false) })) });
      } else r.up = { name: '', photo: '', hasPh: false, noPh: true, bg: '', ini: '', bgImg: 'none', sub: '', canDm: false, noDm: false, notMe: false, why: '', isO: false, isA: false, ncls: '', hasRk: false, rkT: '1', rkName: '', rkNcls: '', hasMute: false, muteT: '', mute: null, isOwnV: false, code: '', cpId: null, lvNow: '', canGive: false, needAdm: false, goAdm: null, giveX: null, lvBtns: [] };
      // 1.28.1: eýesi öz profilinde özüne bal / dereje berýär
      { const own = myRole === 'o' || admMe().role === 'f', canGive = !!(s.admOn && isF), L = LS.get('lvl', null), ux = UPX[me1];
        const xpK = ux ? ux.xp : L ? +L.xp || 0 : null, lvK = ux ? ux.lv : L ? rkT(L.lv) : 0;
        r.mg = { on: own && pg === 'profile' && canGive, canGive,   // 1.47: admin paneline girmedik bolsa kart görünmeýär needAdm: own && !canGive, goAdm: () => this.setState({ page: 'admin' }),
          lvNow: lvK ? tx.gv_now.replace('{n}', tx['rk_n' + rkT(lvK)]).replace('{l}', String(rkT(lvK))).replace('{x}', xpK != null ? String(xpK) : '?') : tx.gv_unk,
          giveX: () => { const x = parseInt(this.state.gvX, 10); if (!x) { this.say('⚠️ ' + tx.gv_bad); return; }
            this.confirm(tx.gv_qX.replace('{n}', this.meName).replace('{x}', String(x)), '✅ ' + tx.gv_btn, () => { act('xpgive', { dev: me1, x }); this.setState({ gvX: '' }); }, false); },
          lvBtns: RK_L.map((q, i) => ({ t: String(i + 1), name: tx['rk_n' + (i + 1)], cls: lvK === i + 1 ? 'on' : '',
            go: () => this.confirm(tx.gv_qLv.replace('{n}', this.meName).replace('{r}', tx['rk_n' + (i + 1)]).replace('{l}', String(i + 1)), '✅ ' + tx.gv_lv, () => act('xpgive', { dev: me1, lv: i + 1 }), false) })) }; }
      r.gvX = s.gvX || ''; r.onGvX = (e) => this.setState({ gvX: String(e.target.value || '').replace(/[^0-9-]/g, '').slice(0, 7) });
      // hususy habarlar sanawy
      r.isDms = pg === 'dms';
      // 1.47: hemmeler üçin ulanyjy gözlemek (Telegram ýaly — nigiň bir bölegi ýa-da TM-kod); netije botdan gelýär
      { const q = s.dmQ || ''; r.dmQ = q; r.dmQph = ({ ru: '🔎 Поиск пользователей…', tr: '🔎 Kullanıcı ara…' })[s.lang] || '🔎 Ulanyjy gözle…';
        r.onDmQ = (e) => { const v = String(e.target.value || '').slice(0, 32); this.setState({ dmQ: v }); clearTimeout(this._dqT);
          if (v.trim().length >= 2) this._dqT = setTimeout(() => { try { NB.send(JSON.stringify({ k: 'usq', q: v.trim() })); } catch (e2) {} }, 450); };
        const R = s.dmSR && s.dmSR.q === q.trim() ? s.dmSR.l : null;
        r.dmSOn = q.trim().length >= 2; r.dmSWait = r.dmSOn && !R; r.dmSNone = r.dmSOn && !!R && !R.length;
        r.dmSWaitT = ({ ru: 'Поиск…', tr: 'Aranıyor…' })[s.lang] || 'Gözlenýär…'; r.dmSNoneT = tx.us_none;
        r.dmSRows = r.dmSOn && R ? R.map((u) => Object.assign(ava(u.d), { name: u.n || '?', tag: u.t ? '@' + u.t : '', cp: (e) => { if (e && e.stopPropagation) e.stopPropagation(); if (!u.t) return; NB.copy('@' + u.t); this.say('✓ @' + u.t); }, lv: String(rkT(u.lv || 1)), open: () => { this.setState({ dmQ: '' }); this.openProf(u.d); } })) : [];
        r.dmQph = ({ ru: '🔎 Ник или @метка…', tr: '🔎 Takma ad veya @etiket…' })[s.lang] || '🔎 Nik ýa-da @belgi…';
        r.meOtOn = roleOf(me1) === 'o'; r.meOtags = r.meOtOn ? otChips(this) : [];   // 1.47.24: eýesiniň ähli @atlary
        { const mt = tagOf(me1); r.meTag = mt ? '@' + mt : ''; r.cpMyTag = () => { if (!mt) return; NB.copy('@' + mt); this.say('✓ @' + mt); }; } }
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
        const DE = editsOf(x.msgs, 'f', 'x');
        r.dmMsgs = x.msgs.filter((m) => !isCtl(m) && !DE.D[m.id]).map((m) => { if (DE.E[m.id] != null) m = Object.assign({}, m, { x: DE.E[m.id], edd: 1 });
          if (m.sys) return { id: m.id, hasRp: false, rpN: '', rpT: '', cls: 'dmm-s', isSys: true, isMsg: false, t: m.sys === 'acc' ? tx.dm_acced : m.sys === 'key' ? tx.dm_keyChg.replace('{n}', r.dp.name) : m.sys, bcls: '', hasImg: false, img: '', zoom: null, isSt: false, st: '', parts: [], time: '' };
          const mine2 = m.f === me1;
          return { id: m.id, cls: mine2 ? 'dmm-me' : 'dmm-o', bcls: mine2 ? 'gb-me' + (!m.pend && (m.t || 0) <= peerRd ? ' rd' : ' nrd') : 'gb-o', isSys: false, isMsg: true, t: '', hasImg: !!m.ph, img: m.ph || '', zoom: () => this.setState({ zoom: m.ph }),
            isSt: !!m.st, st: m.st || '', parts: m.x ? withMent(withKeys(this.lk(m.x), this), this) : [], time: (m.edd ? tx.m_edited + ' ' : '') + this.hm((m.t || 0) * 1000 || now) + (m.pend ? ' ⏳' : ''),
            hasRp: !!(m.rp && m.rp.n), rpN: m.rp ? m.rp.n : '', rpT: m.rp ? m.rp.t : '', rpI: m.rp ? m.rp.i || '' : '',
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
        cls: roleOf(d) === 'o' ? 'vo' : '', role: roleOf(d) === 'o' ? tx.vip_o : tx.vip_a, d: (i * 0.06).toFixed(2), open: () => this.openProf(d) }, (() => {
          // 1.33: OWNER ýazgysy öçük bolsa (nyşan saýlanan) — derejäniň nyşany, chatdaky ýaly
          let lv = 0; if (d === me1) lv = (LS.get('lvl', {}) || {}).lv || 0; else { G.forEach((q) => { if (q.i === d && q.lv) lv = q.lv; }); lv = lvOf(d, lv); }
          const o = isOwnShown(d), t = rkT(lv); return { hasLv: !o && (roleOf(d) === 'o' || lv >= 2), lv: String(t), ncls: o ? 'goldtxt' : lv ? rkNm(t) : '' }; })()));
      if (pg === 'vip') lvAsk(Object.keys(INFO.roles || {}));
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
      // ====== 1.43: Premium — Free / Premium / PUBG, Premium düwmesi, satyn almak, haýyşlar, bermek ======
      { const PR = !!INFO.prem, PF = !!INFO.pfree, pexp = +INFO.pexp, am2 = admMe(), isF2 = am2.role === 'f', full2 = isF2 || am2.perm === 'all', sel2 = am2.perm === 'sel';
        const dl = pexp > 0 ? Math.max(1, Math.ceil((pexp - Date.now()) / 86400000)) : 0, dlT = dl + ' ' + tx.pr_days;
        const nm2 = (d, fb) => { const n = nameOf(d); return n && n !== '?' ? n : (fb || '?'); };
        const OWV = isF2 || roleOf(INFO.dev) === 'o';   // 1.47: Free serwerleri diňe eýeleri görýär
        const FHID = false;   // 1.47.16: Free serwerler hemmelere görünýär (çeşmesi diňe eýesine)
        const tab = FHID ? (s.svTab === 'pubg' ? 'pubg' : 'prem') : (['free', 'prem', 'pubg'].indexOf(s.svTab) >= 0 ? s.svTab : (PR ? 'prem' : 'free'));   // 1.46.8: Free bölümi ýok (diňe «Awtomatik»)
        const ng = SV.filter((v) => !v.game), gg = SV.filter((v) => v.game);
        const mark = (x, v, premTab) => { const lock = !!(v && v.lock), isFree = !v || v.free !== false;
          const o = Object.assign(x, { pcls: premTab ? 'sv-prem' : '', tag: lock ? '🔒' : '', crown: premTab && !lock, tagCls: lock ? 'svlock' : 'svcrown' });   // 1.47.5: Premium bölüminde ähli serwerler (mugtlar hem) — täç
          if (OWV && A && A.hsrc && v) { const src_ = A.hsrc[String(v.id || '').split('|').pop()]; if (src_ && String(o.sub || '').indexOf(src_) < 0) o.sub = (o.sub ? o.sub + ' · ' : '') + src_; }   // 1.47.15: serweriň çeşmesi — diňe eýesine (admin maglumatyndan)
          if (lock) { o.pick = () => { this.say('👑 ' + tx.pr_lock); this.setState({ psh: true, pstep: 1 }); };
            const off = 'rgba(243,231,208,.18)'; Object.assign(o, { ms: '—', msCls: '', c1: off, c2: off, c3: off, c4: off, best: false }); }   // 1.46.2: Premium ýok — ping ölçenmeýär
          return o; };
        // 1.46.2: Free — diňe mugtlar; Premium / PUBG — diňe Premium-lar (mugt serwerler gaýtalanmaýar)
        const inTab = (q, premTab) => !PF || (premTab ? !(q.v && q.v.free) || !!(q.v && q.v.both) : !!(q.v && q.v.free));   // 1.47.2: kanal kodlary iki bölümde hem
        if (Array.isArray(r.srvList)) r.srvList = tab === 'pubg' ? [] : r.srvList.map((x, j) => ({ x, v: ng[j] })).filter((q) => inTab(q, tab === 'prem')).map((q) => mark(q.x, q.v, tab === 'prem'));
        if (Array.isArray(r.gList)) r.gList = r.gList.map((x, j) => ({ x, v: gg[j] })).filter((q) => inTab(q, tab !== 'free')).map((q) => mark(q.x, q.v, tab !== 'free'));
        if (tab === 'pubg') r.svEmpty = false;
        if (tab === 'free' && FHID) { r.srvList = []; r.gList = []; r.svEmpty = false; }
        r.svOwnNote = tab === 'free' && FHID ? ({ ru: '👁 Бесплатные серверы видите только вы (владелец). Пользователи видят только «Авто».', tr: '👁 Ücretsiz sunucuları sadece siz (sahip) görüyorsunuz. Kullanıcılar sadece «Otomatik» görür.' }[s.lang]
          || '👁 Mugt serwerleri diňe siz (eýesi) görýärsiňiz. Ulanyjylar diňe «Awtomatik» görýär.') : '';   // 1.46.7: mugt serwerler görünmeýär — diňe «Awtomatik» (basanda iň gowusyna birikýär)
        r.svTabs = (FHID ? [['prem', '👑 Premium', 'seg-prem'], ['pubg', '👑 PUBG', 'seg-prem']] : PF ? [['free', 'Free', ''], ['prem', '👑 Premium', 'seg-prem'], ['pubg', '👑 PUBG', 'seg-prem']] : [['free', 'Free', ''], ['prem', '👑 Premium', 'seg-prem'], ['pubg', '👑 PUBG', 'seg-prem']]).map((q) => ({ t: q[1], cls: (tab === q[0] ? 'seg-on' : 'seg-off') + ' ' + q[2], p: tab === q[0] ? 'true' : 'false', pick: () => this.setState({ svTab: q[0] }) }));
        r.svPremBan = !PR && PF && tab !== 'free';
        // 1.46.4: awtomatik — Free bölüminde diňe mugt serwerler, Premium bölüminde diňe Premium serwerler
        { const autoP = !!s.autoP && PR, here = s.pick < 0 && (PF ? (PR ? autoP : true) : (tab === 'free' ? !autoP : autoP));
          r.autoSel = here; r.autoFree = PF ? !PR : tab === 'free'; r.autoCls = (here ? 'sv-sel' : '') + (r.autoFree ? ' autohot' : '');   // 1.47.2: mugt «Awtomatik» — has göze görünýän
          r.autoFreeS = ({ ru: 'Бесплатный код — нажмите и подключайтесь', tr: 'Ücretsiz kod — dokun ve bağlan' })[s.lang] || 'Mugt kod — basyň we birikiň';
          // 1.46.8: Premium ýok — «Awtomatik» iň gowy mugt serwere; Premium bar — iň gowy Premium serwere
          r.autoPick = () => this.setState({ pick: -1, autoP: PF ? PR : tab !== 'free', autoB: false, page: 'main' }); }
        r.premOpen = () => { INFO = J(NB.info(), INFO); this.setState({ psh: true, pstep: 1, menu: false }); };
        r.premPillOn = pg === 'main' && (PF || PR); r.premPillCls = PR ? 'ppill-on' : '';
        r.premPillT = PR ? (pexp <= 0 ? 'Premium ♾' : 'Premium · ' + dlT) : tx.pr_buy; r.premPillS = PR ? (pexp <= 0 ? '♾' : dlT) : '';   // 1.46.6: möhletsiz (eýesi) — ♾, «0 gün» däl   // 1.44: «satyn al» ýazgysy aýryldy
        // Premium sahypasy
        const plan = s.pplan || 'y';
        r.pshOn = !!s.psh; r.pshX = () => this.setState({ psh: false }); r.pshIsPrem = PR; r.pshHaveT = PR ? (pexp <= 0 ? tx.pr_unl : tx.pr_have.replace('{d}', dlT)) : '';
        r.pFeat = [['🌍', tx.pr_f1], ['⏱', tx.pr_f2], ['🎮', tx.pr_f3], ['👑', tx.pr_f4]].map((q) => ({ i: q[0], t: q[1] }));
        const WK = ({ ru: ['1 неделя', 'Попробуйте неделю'], tr: ['1 hafta', 'Bir hafta deneyin'] })[s.lang] || ['1 hepde', 'Bir hepde synap görüň'];   // 1.47: hepdelik Premium 50 TMT
        r.pPlans = [{ k: 'w', t: WK[0], price: '50', note: WK[1] }, { k: 'm', t: tx.pr_m, price: '100', note: tx.pr_mN }, { k: 'y', t: tx.pr_y, price: '700', old: '1200', save: '−42%', badge: tx.pr_best, note: tx.pr_yN }]   // 12 × 100 = 1200 → 700 (hakyky tygşytlylyk)
          .map((q) => Object.assign(q, { hasOld: !!q.old, hasBadge: !!q.badge, cls: (plan === q.k ? 'pplan-on' : '') + (q.k === 'y' ? ' pplan-y' : ''), p: plan === q.k ? 'true' : 'false', pick: () => this.setState({ pplan: q.k }) }));
        const RL = INFO.roles || {};
        // 1.47: diňe satyjylar (eýesi sanawda ýok; satyjy ýok bolsa — eýesi); her alyjy bir haýyş — gaýtadan basanda ilkinji satyja (DM)
        const slv = Object.keys(RL).filter((d) => RL[d][0] === 's' && d !== me1), PQ = LS.get('preqTo', null);
        const pqOn = PQ && PQ.d && Date.now() - (PQ.at || 0) < 7 * 86400000 && !PR;
        r.pSellers = (slv.length ? slv : Object.keys(RL).filter((d) => RL[d][0] === 'o' && d !== me1))
          .map((d) => Object.assign(ava(d), { name: nm2(d, RL[d][1]), isO: RL[d][0] === 'o', isS: RL[d][0] === 's',
            go: () => { this.setState({ psh: false });
              if (pqOn) { this.say('👑 ' + ({ ru: 'Вы уже отправили запрос продавцу — пишите ему', tr: 'Zaten bir satıcıya istek gönderdiniz — ona yazın' }[s.lang] || 'Siz eýýäm satyja haýyş iberdiňiz — şoňa ýazyň')); this.openDm(PQ.d); return; }
              LS.set('preqTo', { d, at: Date.now() }); NB.send(JSON.stringify({ k: 'preq', to: d, plan, n: this.meName })); this.say('👑 ' + tx.pr_sent); this.openDm(d); } }));
        r.pSellEmpty = !r.pSellers.length;
        // 1.43: ilki tarif → «Satyn al», soň satyjylar
        const pq = r.pPlans.find((q) => q.k === plan) || r.pPlans[1];
        r.pStep1 = (s.pstep || 1) === 1; r.pStep2 = !r.pStep1; r.pBuyT = pq.price + ' TMT';
        r.pPickT = '👑 Premium · ' + pq.t + ' · ' + pq.price + ' TMT';
        r.pBuy = () => this.setState({ pstep: 2 }); r.pBack = () => this.setState({ pstep: 1 });
        // haýyşlar (eýesi / satyjylar)
        const isSel = roleOf(me1) === 'o' || roleOf(me1) === 's' || isF2 || sel2, AQ = (A && A.preq) || [], byId = {}, rqDone = LS.get('preqDone', {}) || {};
        (LS.get('preqs', []) || []).forEach((q) => { byId[q.id] = Object.assign({}, q, { at: q.at || this.hm((q.ts || 0) * 1000) }); });
        AQ.forEach((q) => { byId[q.id] = Object.assign(byId[q.id] || {}, q); });
        // 1.46.7: alyjy 30 minut ýazmasa — haýyş özi ýapylýar
        const lastFrom = (d) => { const x = DMS[d]; let t = 0; ((x && x.msgs) || []).forEach((m) => { if (m.f === d && (m.t || 0) > t) t = m.t || 0; }); return t * 1000; };
        Object.keys(byId).forEach((k) => { const q = byId[k]; if (q.st !== 'done' && !rqDone[k] && q.ts && Date.now() - Math.max(q.ts * 1000, lastFrom(q.dev)) > 30 * 60000) {
          rqDone[k] = 1; LS.set('preqDone', rqDone); if (s.admOn) act('preqx', { id: k }); } });
        const rq = Object.keys(byId).map((k) => Object.assign(byId[k], rqDone[k] ? { st: 'done' } : {})).sort((a, b) => ((a.st === 'done') - (b.st === 'done')) || ((b.ts || 0) - (a.ts || 0))).slice(0, 60);
        const newN = rq.filter((q) => q.st !== 'done').length;
        r.preqBtnOn = pg === 'main' && isSel; r.preqHas = newN > 0; r.preqN = newN > 9 ? '9+' : String(newN);
        { // 1.47.22: baş sahypada her ulanyjynyň 🪪 ID-si we @belgisi (eýesiniňki däl); basanda ID göçürilýär
          const mt = tagOf(INFO.dev);
          r.idPillOn = pg === 'main' && !!INFO.code && roleOf(INFO.dev) !== 'o'; r.idCode = INFO.code || ''; r.idTag = mt ? '@' + mt : '';
          r.idTop = r.preqBtnOn ? 172 : 130; r.idCp = () => { NB.copy(INFO.code || ''); this.say('✓ ' + tx.copied + ': ' + (INFO.code || '')); }; }
        r.preqOpen = () => { this.setState({ rq: true, rqTab: 'req' }); if (this.state.admOn) act('get'); };
        r.rqOn = !!s.rq; r.rqX = () => this.setState({ rq: false }); r.rqNeedAdm = !s.admOn; r.rqGoAdm = () => this.setState({ rq: false, page: 'admin' });
        const PL = (A && A.prem) || [], rqT = s.rqTab || 'req';
        const SLS = (full2 && A && A.sales) || [], SLT = ({ ru: ['📊 Продажи', 'нед', 'мес', 'год', 'др.', 'Продаж пока нет'], tr: ['📊 Satış', 'hf', 'ay', 'yıl', 'diğer', 'Henüz satış yok'] })[s.lang] || ['📊 Satuw', 'hp', 'aý', 'ýyl', 'beýleki', 'Entek satuw ýok'];
        r.rqIsSales = rqT === 'sales' && full2;   // 1.47: satyjylaryň näçe Premium satandygy (eýesiniň bereni sanalmaýar)
        r.slList = SLS.map((x) => ({ n: x.n, t: String(x.t), sub: [[x.w, SLT[1]], [x.m, SLT[2]], [x.y, SLT[3]], [x.o, SLT[4]]].filter((q) => q[0]).map((q) => q[0] + ' ' + q[1]).join(' · ') }));
        r.slEmpty = !r.slList.length; r.slEmptyT = SLT[5];
        r.rqTabs = [['req', tx.pr_tabReq + ' · ' + newN], ['prem', tx.pr_list + ' · ' + PL.length]].concat(full2 ? [['sales', SLT[0] + ' · ' + SLS.reduce((a2, x) => a2 + x.t, 0)]] : []).map((q) => ({ t: q[1], p: rqT === q[0] ? 'true' : 'false', cls: rqT === q[0] ? 'chip-on' : '', pick: () => this.setState({ rqTab: q[0] }) }));
        r.rqIsReq = rqT === 'req'; r.rqIsPrem = rqT === 'prem';
        r.rqList = rq.map((q) => Object.assign(ava(q.dev), { name: nm2(q.dev, q.n), sub: ((q.plan === 'y' ? tx.pr_y : q.plan === 'w' ? ({ ru: '1 неделя', tr: '1 hafta' }[s.lang] || '1 hepde') : tx.pr_m)) + ' · ' + (q.at || '') + (q.to ? ' · → ' + q.to : ''),
          cls: q.st === 'done' ? 'prq-done' : '', done: q.st === 'done', open: q.st !== 'done', doneT: tx.pr_done + (q.by ? ' · ' + q.by : ''),
          prof: () => this.setState({ rq: false, page: 'uprof', upDev: q.dev }), write: () => { this.setState({ rq: false }); this.openDm(q.dev); },
          x: () => { rqDone[q.id] = 1; LS.set('preqDone', rqDone); if (this.state.admOn) act('preqx', { id: q.id }); this.setState({ rqTick: (this.state.rqTick || 0) + 1 }); } }));
        r.rqEmpty = !r.rqList.length;
        r.rpList = PL.map((x) => Object.assign(ava(x.dev), { name: nm2(x.dev, x.n), sub: tx.pr_left.replace('{v}', x.left) + (x.by ? ' · ' + tx.pr_by.replace('{v}', x.by) : ''), open: () => this.setState({ rq: false, page: 'uprof', upDev: x.dev }) }));
        r.rpEmpty = !r.rpList.length;
        r.admPremOn = !!s.admOn && full2; r.admPremN = String(PL.length); r.admPremOpen = () => this.setState({ rq: true, rqTab: 'prem' });
        // profilde Premium bermek
        r.pDays = s.pDays || ''; r.onPDays = (e) => this.setState({ pDays: String(e.target.value || '').replace(/[^0-9]/g, '').slice(0, 4) });
        if (r.isUprof && r.up && s.upDev) {
          const myR = roleOf(me1), ownR = isF2 || myR === 'o', staffP = ownR || full2 || sel2 || myR === 's';
          const d = s.upDev, canP = staffP && (d !== me1 || ownR), actP = canP && !!s.admOn, px = PL.find((x) => x.dev === d);
          const give = (n) => this.confirm(tx.pr_qGive.replace('{n}', r.up.name || '?').replace('{p}', n === 7 ? ({ ru: '1 неделя', tr: '1 hafta' }[s.lang] || '1 hepde') : n === 30 ? tx.pr_m : n === 365 ? tx.pr_y : n === 0 ? '♾' : n + ' ' + tx.pr_days), '👑 ' + tx.pr_giveBtn,
            () => { act('prem', { dev: d, d: n }); this.setState({ pDays: '' }); }, false);
          const selIs = roleOf(d) === 's', nmU = r.up.name || '?';
          Object.assign(r.up, { premAct: actP, premNeed: false,   // 1.47: «admin paneline giriň» ýok premGoAdm: () => this.setState({ page: 'admin' }),
            selOn: actP && isF2 && d !== me1, selCls: selIs ? 'sel-off' : '', selT: selIs ? tx.sl_off : tx.sl_on,
            selTog: () => this.confirm((selIs ? tx.sl_qOff : tx.sl_qOn).replace('{n}', nmU), selIs ? tx.sl_off : tx.sl_on, () => act('mksel', { dev: d, on: !selIs }), false) });
          const CD = ((A && A.codes) || []).find((c) => c.u === d && c.role !== 'f'), curP = CD ? CD.perm : '', isOwnD = roleOf(d) === 'o';
          Object.assign(r.up, { rmOn: actP && isF2 && (!!px || isPrem(d)), rm: () => this.confirm(tx.pr_qRm.replace('{n}', nmU), tx.pr_rm, () => act('punprem', { dev: d }), false),
            selOn: actP && isF2 && d !== me1 && !isOwnD,
            roles: [['', tx.rp_none], ['sel', tx.rp_sel], ['chat', tx.rp_chat], ['tk', tx.rp_tk], ['all', tx.rp_all]].concat(isF2 && !am2.o2 ? [['own2', '👑 Owner 2']] : []).map((q) => ({ t: q[1], cls: curP === q[0] ? 'chip-on' : '', p: curP === q[0] ? 'true' : 'false',
              pick: () => { if (curP === q[0]) return; this.confirm(tx.rp_q.replace('{n}', nmU).replace('{r}', q[1]), '✅ ' + q[1], () => { act('setperm', { dev: d, perm: q[0] }); if (CD) CD.perm = q[0]; }, false); } })) });
          Object.assign(r.up, { canPrem: canP && !!s.admOn, premOwn: actP && isF2, premNow: tx.pr_now.replace('{v}', px ? px.left : isPrem(d) ? '✓' : tx.pr_none),
            premW: () => give(7), premWT: ({ ru: '1 неделя', tr: '1 hafta' }[s.lang] || '1 hepde'),
            premM: () => give(30), premY: () => give(365), premD: () => { const n = parseInt(this.state.pDays, 10); if (!(n >= 0)) { this.say('⚠️ ' + tx.gv_bad); return; } give(n); } });
        } else if (r.up) Object.assign(r.up, { canPrem: false, premOwn: false, premNow: '', premAct: false, premNeed: false, selOn: false, rmOn: false });
        // 1.47: hemmä — ID (TM-kod) we göçürmek; eýesi / doly admin — «ℹ️ Ulanyjy maglumaty»
        if (r.isUprof && r.up && s.upDev) { const d = s.upDev, id2 = typeof NB.codeOf === 'function' ? NB.codeOf(d) || '' : '';
          r.up.idOn = !!id2; r.up.idT = id2; r.up.cpId2 = () => { NB.copy(id2); this.say('✓ ' + tx.copied); };
          const UL = ({ ru: ['Информация о пользователе', 'Присоединился', 'Последний раз', 'Активные дни', 'Дни с VPN', 'Последнее подключение', 'Пригласил', 'Пригласивший', 'Очки / уровень', 'Premium', 'Модель / версия', 'Тикеты', 'Бан', 'Перенесён из старой программы', 'да', 'нет'],
            tr: ['Kullanıcı bilgisi', 'Katıldı', 'Son görülme', 'Aktif günler', 'VPN kullandığı gün', 'Son bağlantı', 'Davet ettiği', 'Davet eden', 'Puan / seviye', 'Premium', 'Model / sürüm', 'Destek talepleri', 'Ban', 'Eski programdan taşındı', 'evet', 'hayır'] })[s.lang]
            || ['Ulanyjy maglumaty', 'Goşuldy', 'Soňky gezek', 'Işjeň günleri', 'VPN ulanan günleri', 'Soňky birikmesi', 'Çagyranlary', 'Çagyran', 'Bal / dereje', 'Premium', 'Model / wersiýa', 'Biletleri', 'Gadagan', 'Köne programmadan göçürildi', 'hawa', 'ýok'];
          const ui2 = s.uInfo && s.uInfo.dev === d ? s.uInfo : null;
          r.up.uiOn = !!s.admOn && full2 && d !== me1; r.up.uiT = UL[0]; r.up.uiHas = !!ui2;
          r.up.uiGo = () => { act('uinfo', { dev: d }); this.say(tx.k_wait); };
          r.up.uiRows = ui2 ? [[UL[1], ui2.first], [UL[2], ui2.seen], [UL[3], String(ui2.ad)], [UL[4], String(ui2.vd)], [UL[5], ui2.vl], [UL[6], String(ui2.inv)], [UL[7], ui2.by || '—'],
            [UL[8], ui2.xp + ' · ' + (tx['rk_n' + rkT(ui2.lv)] || ui2.lv)], [UL[9], ui2.prem || UL[15]], [UL[10], ui2.model + ' · v' + ui2.ver], [UL[11], String(ui2.tk)], [UL[12], ui2.ban ? UL[14] : UL[15]]]
            .concat(ui2.mv ? [[UL[13], UL[14]]] : []).map((q) => ({ k: q[0], v: q[1] })) : []; }
        // 1.45: Global chat — sesini öçürmek (doly admin / chat admin)
        if (r.isUprof && r.up && s.upDev) { const d = s.upDev, ok = !!s.admOn && (full2 || am2.perm === 'chat') && d !== me1 && !roleOf(d);
          r.up.muteOn = ok; r.up.mutes = [[10, tx.gm_10], [60, tx.gm_60], [1440, tx.gm_1d], [0, tx.gm_off]].map((q) => ({ t: q[1], go: () => act('gmute', { dev: d, m: q[0] }) })); }
        else if (r.up) { r.up.muteOn = false; r.up.mutes = []; }
        // 1.45: ulanyjy gözlemek (admin paneli)
        r.usQ = s.usQ || ''; r.onUsQ = (e) => this.setState({ usQ: String(e.target.value || '').slice(0, 32) });
        r.usGo = () => { const q = (this.state.usQ || '').trim(); if (q.length < 2) return; this.setState({ usDone: false, usRes: [] }); act('usearch', { q }); };
        r.usRes = (s.usRes || []).map((u) => ({ name: u.n || '?', sub: (u.code || '') + (u.seen ? ' · ' + u.seen : ''), open: () => this.setState({ page: 'uprof', upDev: u.dev }) }));
        r.usNone = !!s.usDone && !r.usRes.length;
        // 1.46: eýesi — kodlary şu telefonda synamak
        r.probeT = s.probeRun ? tx.pb_run : tx.pb_go;
        r.probeGo = () => { if (this.state.probeRun || typeof NB.probe !== 'function') return; this.setState({ probeRun: true }); NB.probe(100); };
        // 1.44: öz profilimde Premium bermek (eýesi)
        { const ownR = isF2 || roleOf(me1) === 'o', px = PL.find((x) => x.dev === me1);
          const give = (n) => this.confirm(tx.pr_qGive.replace('{n}', this.meName || '?').replace('{p}', n === 7 ? ({ ru: '1 неделя', tr: '1 hafta' }[s.lang] || '1 hepde') : n === 30 ? tx.pr_m : n === 365 ? tx.pr_y : n === 0 ? '♾' : n + ' ' + tx.pr_days), '👑 ' + tx.pr_giveBtn,
            () => { act('prem', { dev: me1, d: n }); this.setState({ pDays: '' }); }, false);
          r.mp = { on: pg === 'profile' && ownR && !!s.admOn, act: !!s.admOn,   // 1.47: «admin paneline giriň» ýazgysy ýok needAdm: !s.admOn, goAdm: () => this.setState({ page: 'admin' }),
            canRm: !!s.admOn && isF2 && !!px, rm: () => this.confirm(tx.pr_qRm.replace('{n}', this.meName || '?'), tx.pr_rm, () => act('punprem', { dev: me1 }), false),
            now: tx.pr_now.replace('{v}', px ? px.left : PR ? (pexp === 0 ? '♾' : dlT) : tx.pr_none),
            premW: () => give(7), premWT: ({ ru: '1 неделя', tr: '1 hafta' }[s.lang] || '1 hepde'),
            premM: () => give(30), premY: () => give(365), premD: () => { const n = parseInt(this.state.pDays, 10); if (!(n >= 0)) { this.say('⚠️ ' + tx.gv_bad); return; } give(n); } }; } }
      ['srvList', 'gList'].forEach((k) => { if (Array.isArray(r[k])) r[k] = r[k].map(withFc); });
      // 1.23: eýesi serweri basyp saklap 30 sekunt gizleýär (diňe öz ekranynda)
      window.__isOwn = myRole === 'o';
      r.isOwnP = myRole === 'o' && pg === 'servers';
      r.fakePing = () => { const f = {}; SV.forEach((v) => { f[v.id] = 100 + Math.floor(Math.random() * 71); }); this.setState({ pings: f, testing: false }); this.say(tx.fp_ok); };
      { const H = window.__svHide || {}, tn = Date.now(); ['srvList', 'gList'].forEach((k) => { if (Array.isArray(r[k])) r[k] = r[k].filter((x) => !(H[x.sid || x.name] > tn)); }); r.hasG = Array.isArray(r.gList) && r.gList.length > 0; }
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
      { const mt = rkT(r.rkmT); r.rkmFr = ''; r.rkmFrCls = mt >= 10 ? 'frx' : ''; r.rkmNm = rkNm(mt); r.rkmMe = this.meName || '…'; r.rkmIni = ini(this.meName || '?'); r.rkmBg = '#E0B04A'; r.rkmHasB = mt >= 2; }
      // 1.46.7: biletleriň hemmesini ýapmak; admin log (diňe eýesi)
      { const opN = ((A && A.tk) || []).filter((t) => t.st !== 'closed').length; r.tkAllOn = !!s.admOn && opN > 0; r.tkAllT = tx.tk_all + ' (' + opN + ')'; r.tkCloseAll = this.tkCloseAll;
        const me4 = admMe(); r.alogOn = me4.role === 'f' && !me4.o2;   // 1.47: owner 2 admin logyny görmeýär r.alogGo = () => { act('alog'); this.say(tx.k_wait); };
        const KN = { a: '⚙️', b: '👆', p: '📄' };
        r.alogRows = (s.alog || []).slice(0, 300).map((x) => ({ t: this.hm((x.t || 0) * 1000) + ' · ' + new Date((x.t || 0) * 1000).toLocaleDateString('ru-RU').slice(0, 5), n: x.n || '?', x: (KN[x.k] || '•') + ' ' + (x.x || '') }));
        r.alogEmpty = !!s.alog && !r.alogRows.length; }
      // 1.34: admin — çalt rejim (Firestore tölegli)
      { const on = s.faCur != null ? s.faCur : !!(A && A.fast);
        r.faSt = on ? tx.fa_on : tx.fa_off; r.faCls = on ? 'chip-on' : ''; r.faBtn = on ? tx.fa_btnOff : tx.fa_btnOn;
        const go = (v) => { act('fast', { on: v }); this.setState({ faCur: v }); this.say(tx.k_wait); };
        r.faTog = () => { if (on) go(false); else this.confirm(tx.fa_q, tx.fa_btnOn, () => go(true)); }; }
      // 1.32: admin — mugt birikme wagty
      { const cur = s.seCur != null ? s.seCur : A && A.sess != null ? A.sess : SESS, hT = (m) => (m === 0 ? tx.se_unl : hrsT(s.lang, m));
        r.seCur = hT(cur);
        const go = (m) => { act('sess', { m }); this.setState({ seCur: m }); this.say(tx.k_wait); };
        r.seOpts = [0, 60, 120, 180, 240, 300].map((m) => ({ t: m === 0 ? tx.se_unl : tx.se_h.replace('{n}', String(m / 60)), cls: cur === m ? 'chip-on' : '', p: cur === m ? 'true' : 'false', pick: () => go(m) }));
        r.seIn = s.seIn || ''; r.onSeIn = (e) => this.setState({ seIn: String(e.target.value || '').slice(0, 6) });
        r.seSet = () => { const h = parseFloat(String(this.state.seIn || '').replace(',', '.')), m = Math.round(h * 60);
          if (!(m >= 15 && m <= 1440)) { this.say('⚠️ ' + tx.se_bad); return; } this.setState({ seIn: '' }); go(m); }; }
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
      // 1.28: hekaýalar
      { const tn = Date.now() / 1000, GE2 = editsOf(G.concat(LCTL), 'i', 't'), seen = LS.get('stSeen', {}) || {}, bans2 = INFO.bans || [];
        const all = G.filter((m) => m.sty && m.pi && tn - (m.time || 0) < 86400 && !GE2.D[m.id] && !gDel[m.id] && bans2.indexOf(m.i) < 0);
        const by = {}; all.forEach((m) => { (by[m.i] = by[m.i] || []).push(m); });
        const isSeen = (d) => by[d].every((m) => seen[m.pi]);
        const devs = Object.keys(by).filter((d) => d !== me1).sort((a, b) => (isSeen(a) - isSeen(b)) || (by[b][by[b].length - 1].time - by[a][by[a].length - 1].time));
        this._stBy = by; this._stOrder = (by[me1] ? [me1] : []).concat(devs);
        r.stRow = devs.map((d) => Object.assign(ava(d), { name: nameOf(d) || by[d][0].n || '?', ring: isSeen(d) ? 'seen' : 'new', open: () => this.svOpen(d, 0) }));
        r.stMe = ava(me1); r.stMeCls = ''; r.stMeHas = !!by[me1]; r.stMeRing = by[me1] ? (isSeen(me1) ? 'seen' : 'new') : ''; r.stMeOpen = () => this.svOpen(me1, 0); r.onStory = this.onStory;
        const V = s.sv, cur = V && by[V.d] && by[V.d][V.i];
        r.svOn = !!cur;
        if (cur) { askImg('g', cur.pi); const isV = !!cur.vc, vd = isV ? VI[cur.id] || '' : '';
          if (isV && !vd && !vidAsked[cur.id]) { vidAsked[cur.id] = 1; try { NB.vid(cur.id, cur.vc); } catch (e) {} }
          const im = isV ? (vd ? GI[cur.pi] || 'x' : '') : GI[cur.pi] || '', ag = tn - (cur.time || tn);
          r.svIsVid = isV && !!vd; r.svVid = vd; r.svImg = isV ? '' : im; r.svHasImg = !isV && !!im; r.svNoImg = !im; r.svName = V.d === me1 ? this.meName : (nameOf(V.d) || cur.n || '?');
          r.svAgo = ag < 3600 ? Math.max(1, Math.floor(ag / 60)) + ' min' : tx.wk_h.replace('{h}', String(Math.floor(ag / 3600)));
          r.svBars = by[V.d].map((m, i) => ({ cls: i < V.i ? 'done' : i === V.i && im ? 'cur' : '' }));
          if (im && !seen[cur.pi]) { seen[cur.pi] = 1; LS.set('stSeen', seen); }
          if (im && this._svKey !== cur.id) { this._svKey = cur.id; clearTimeout(this._svT); this._svT = setTimeout(() => this.svNext(), isV ? 17000 : 6000);
            if (isV) setTimeout(() => { const el = document.querySelector('.svw video'); if (el && !el._tv) { el._tv = 1; el.onended = () => this.svNext(); try { el.play(); } catch (e) {} } }, 60);
            // 1.39: kim gördi — eýesine bir gezek habar (diňe täze wersiýada goýlan hekaýalar)
            const sent = LS.get('stSent', {}) || {};
            if (V.d !== me1 && cur.vs && !sent[cur.id]) { sent[cur.id] = Date.now(); const ks = Object.keys(sent); if (ks.length > 300) ks.sort((a, b) => sent[a] - sent[b]).slice(0, ks.length - 300).forEach((k) => delete sent[k]); LS.set('stSent', sent); try { NB.stView(V.d, cur.id, this.meName || ''); } catch (e) {} } }
          // 1.39: öz hekaýam — näçe adam we kimler gördi
          const SV = LS.get('stViews', {}) || {}, vw = V.d === me1 ? SV[cur.id] || {} : {};
          r.svMine = V.d === me1; r.svViews = String(Object.keys(vw).length); r.svvOpen = () => { clearTimeout(this._svT); this.setState({ svv: cur.id }); };
          r.svvOn = s.svv === cur.id; r.svvX = () => { this.setState({ svv: null }); this._svT = setTimeout(() => this.svNext(), 4000); };
          r.svvList = Object.keys(vw).sort((a, b) => vw[b][1] - vw[a][1]).map((d) => Object.assign(ava(d), { name: nameOf(d) || vw[d][0] || '?', ago: this.hm(vw[d][1] * 1000) }));
          r.svvEmpty = !r.svvList.length;
          r.svCanDel = V.d === me1 || !!(s.admOn && full);   // 1.39: doly hukukly adminler hem pozup bilýär
          r.svDel = () => this.confirm(tx.m_delQ, '🗑 ' + tx.m_del, () => { if (V.d === me1) this.gSendX({ dl: cur.id }); else { act('gdel', { id: cur.id }); gDel[cur.id] = true; } this.setState({ sv: null }); this.say('🗑 ' + tx.sty_del); });
        } else { if (this._svKey) { clearTimeout(this._svT); this._svKey = null; } Object.assign(r, { svImg: '', svHasImg: false, svNoImg: true, svIsVid: false, svVid: '', svName: '', svAgo: '', svBars: [], svCanDel: false, svDel: null, svMine: false, svViews: '0', svvOn: false, svvList: [], svvEmpty: true, svvOpen: null, svvX: null }); }
        r.svX = () => this.setState({ sv: null }); r.svNext = this.svNext; r.svPrev = this.svPrev; }
      // 1.28: öz habaryň menýusy we üýtgedilýän habar
      { const M = s.ma; r.maOn = !!M; r.maT = M ? M.t : ''; r.maHasT = !!(M && M.t); r.maCanEd = !!(M && M.t && M.own);
        r.maOwn = !!(M && M.own); r.maPin = !!(M && M.kind === 'g' && this._canPin && !/^[lp]/.test(M.id)); r.maPinGo = () => { const m = this.state.ma; this.setState({ ma: null }); if (m) this.pinMsg(m.id); };   // 1.46.5
        r.maCopy = () => this.maAct('copy'); r.maEdit = () => this.maAct('edit'); r.maDel = () => this.maAct('del'); r.maX = () => this.setState({ ma: null });
        r.gEdOn = !!s.gEdit; r.gEdT = s.gIn || ''; r.gEdX = () => this.setState({ gEdit: null, gIn: '' });
        r.dmEdOn = !!s.dmEdit; r.dmEdT = s.dmIn || ''; r.dmEdX = () => this.setState({ dmEdit: null, dmIn: '' }); }
      // 1.28: kill switch
      // 1.36: bagly serwer jogap bermeýär — gyzyl düwme we duýduryş (ulanyjy näme üçin hiç zat açylmaýanyny görsün)
      { const dd = !!s.dead && s.st === 'on'; r.deadOn = dd && pg === 'main';
        if (dd) { r.coreCls = 'core-dead'; r.stCls = 'st-dead'; r.statusText = tx.dead_t; r.hintText = r.deadOn ? '' : tx.dead_h; }
        r.deadSrv = () => this.setState({ page: 'servers' }); r.deadRe = () => { try { NB.connect(); } catch (e) {} this.setState({ dead: false }); }; }
      { r.ksHold = !!s.ks && pg === 'main'; r.ksRe = () => NB.connect(); r.ksOff = () => { try { NB.vpnOff(); } catch (e) {} };
        if (Array.isArray(r.opts)) { const sn = r.opts.find((o) => o.t === tx.s_snd), kon = !!(s.kson != null ? s.kson : INFO.kson);
          if (sn) { r.opts.push(Object.assign({}, sn, { i1: 'M12 3l7 3v5c0 4.5-3 8.5-7 10-4-1.5-7-5.5-7-10V6z', i2: 'M9 12l2 2 4-4', t: tx.ks_t, s: tx.ks_s, aria: kon ? 'true' : 'false', swCls: kon ? 'sw-on' : '', d: '0.5',
              on: () => { try { NB.killSw(!kon); } catch (e) {} this.setState({ kson: !kon }); } }));
            r.opts.push({ i1: 'M4 6h16v12H4z', i2: 'M9 18v2h6v-2M8 10h8', t: tx.ks_sys, s: tx.ks_sysS, isSw: false, isBtn: true, arrow: 'M9 6l6 6-6 6', icCls: '', isSeg: false, segs: [], aria: 'false', swCls: '', d: '0.55',
              on: () => { try { NB.vpnSettings(); } catch (e) {} } }); } } }
      // 1.28: açar sowgat etmek
      { const kl = s.hasKey && s.kexp > 0 ? Math.floor((s.kexp - Date.now() / 1000) / 86400) : 0, gd = s.gfD || 1;
        r.gfOn = false;   // 1.47: «Açar sowgat et» aýryldy r.gfSub = tx.gf_sub.replace('{d}', String(kl));
        r.gfDays = [1, 3, 7, 15].filter((d2) => d2 <= kl - 1).map((d2) => ({ t: tx.wk_d.replace('{d}', String(d2)), cls: d2 === gd ? 'chip-on' : '', pick: () => this.setState({ gfD: d2 }) }));
        r.gfTo = s.gfTo || ''; r.onGfTo = (e) => this.setState({ gfTo: String(e.target.value || '').toUpperCase().slice(0, 9) }); r.gfBtn = tx.gf_btn.replace('{d}', String(gd));
        r.gfGo = () => { let to = String(this.state.gfTo || '').toUpperCase().replace(/[^A-Z0-9]/g, ''); if (/^TM[A-Z0-9]{5}$/.test(to)) to = 'TM-' + to.slice(2); else { this.say('⚠️ ' + tx.gf_e_id); return; }
          if (gd > kl - 1) { this.say('⚠️ ' + tx.gf_e_few); return; }
          this.confirm(tx.gf_q.replace('{to}', to).replace('{d}', String(gd)), '🎁 ' + tx.gf_btn.replace('{d}', String(gd)), () => { NB.send(JSON.stringify({ k: 'kgift', to, d: gd })); this.say(tx.k_wait); }, false); }; }
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
    C.onTg = (e) => C.setState({ tgIn: String(e.target.value || '').toLowerCase().replace(/[^a-z0-9_]/g, '').slice(0, 20), tgSt: '' });   // 1.47.22
    C.saveTg = () => { const v = String(C.state.tgIn == null ? '' : C.state.tgIn).replace(/^@/, '');
      if (!/^[a-z][a-z0-9_]{5,19}$/.test(v)) { C.setState({ tgSt: 'bad' }); return; }
      C.setState({ tgSt: 'wait' }); try { NB.send(JSON.stringify({ k: 'tagset', t: v })); } catch (e) {} };
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
    C.onBg = (e) => { const f = fileOf(e), tx = C.T()[C.state.lang]; try { e.target.value = ''; } catch (e2) {} if (!f) { C.say('⚠️ ' + tx.bg_none); return; }   // 1.46.7: ýalňyşlyk görkezilýär
      C.say(tx.k_wait);
      const done = (d) => { if (!d) { C.say('⚠️ ' + tx.ph_big); return; } let x = d; if (x.length > 300000) { shrinkData(x, 700, 0.6, (y) => { C.setState({ pbg: y }); LS.set('pbg', y); C.say('✓ ' + tx.bg_ok); }); return; } C.setState({ pbg: x }); LS.set('pbg', x); C.say('✓ ' + tx.bg_ok); };
      if (window.createImageBitmap) createImageBitmap(f).then((bm) => { const k = Math.min(1, 900 / Math.max(bm.width, bm.height)), c = document.createElement('canvas'); c.width = Math.round(bm.width * k); c.height = Math.round(bm.height * k); c.getContext('2d').drawImage(bm, 0, 0, c.width, c.height); try { bm.close(); } catch (e3) {} done(c.toDataURL('image/jpeg', 0.7)); }).catch(() => shrink(f, 900, 0.7, done));
      else shrink(f, 900, 0.7, done); };
    C.delBg = () => { C.setState({ pbg: '' }); LS.set('pbg', ''); };
    // ---- profil / hususy habarlar ----
    J(NB.dmList(), []).forEach((q) => { if (q.p) DMS[q.p] = Object.assign(DMS[q.p] || { msgs: [], un: 0 }, { st: q.st || '', n: q.n || '' }); });
    { const meta = LS.get('dmMeta', {}); Object.keys(meta).forEach((d) => { const x = DMS[d] || (DMS[d] = { msgs: [], un: 0, st: '' }); x.lt = meta[d].lt || 0; x.un = meta[d].un || 0; x.n = x.n || meta[d].n || ''; x.seen = !!meta[d].seen; x.ls = meta[d].ls || ''; }); }
    const saveMeta = () => { const m = {}; Object.keys(DMS).forEach((d) => { m[d] = { lt: DMS[d].lt || 0, un: DMS[d].un || 0, n: DMS[d].n || '', seen: !!DMS[d].seen, ls: DMS[d].ls || '' }; }); LS.set('dmMeta', m); };
    C._saveMeta = saveMeta;
    const tick = () => C.setState({ dmTick: (C.state.dmTick || 0) + 1 });
    C.openTag = (t0) => {   // 1.47.22: @belgi basylanda — belli bolsa profil, ýogsa botdan gözlenýär
      const t = String(t0 || '').toLowerCase(); if (!t) return;
      if (OT_SET.has(t) && ownerDev()) { C.openProf(ownerDev()); return; }   // 1.47.24: eýesiniň atlary
      if (TAGD[t]) { C.openProf(TAGD[t]); return; }
      TAGW = { t, at: Date.now() }; try { NB.send(JSON.stringify({ k: 'usq', q: '@' + t })); } catch (e) {} C.say('🔎 @' + t);
    };
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
      if (C.state.dmRp && !j.sys && !j.dl && !j.ed) { j = Object.assign({ rp: C.state.dmRp }, j); C.setState({ dmRp: null }); }
      const x = DMS[dev] || (DMS[dev] = { msgs: [], un: 0, st: '' }); if (!x.st) x.st = 'out';
      x.msgs = x.msgs.concat([Object.assign({ id: 'p' + Date.now() + Math.random(), f: INFO.dev, t: Date.now() / 1000, pend: true }, j)]); x.lt = Date.now(); saveMeta();
      NB.dmSend(dev, JSON.stringify(j), C.meName); tick();
    };
    C.dmSendT = () => { const t = (C.state.dmIn || '').trim(); if (!t || !C.state.dmPeer) return; if (C.state.dmEdit) { dmPush(C.state.dmPeer, { ed: C.state.dmEdit, x: t }); C.setState({ dmIn: '', dmEdit: null }); return; } dmPush(C.state.dmPeer, { x: t }); C.setState({ dmIn: '' }); };
    // 1.28: öz habaryňy basyp saklamak → göçür / üýtget / poz
    C.msgMenu = (id, kind, t, own) => C.setState({ ma: { id, kind, t: t || '', own: own !== false }, rxFor: null });
    C.maAct = (a) => { const m = C.state.ma, tx = C.T()[C.state.lang]; C.setState({ ma: null }); if (!m) return;
      if (a === 'copy') { NB.copy(m.t); C.say('✓ ' + tx.copied); return; }
      if (a === 'edit') { if (m.kind === 'd') C.setState({ dmEdit: m.id, dmIn: m.t, dmRp: null }); else C.setState({ gEdit: m.id, gIn: m.t, gRp: null }); return; }
      if (a === 'del') C.confirm(tx.m_delQ, '🗑 ' + tx.m_del, () => { if (m.kind === 'd') dmPush(C.state.dmPeer, { dl: m.id }); else gSend({ dl: m.id }); }); };
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
      const o = Object.assign({ n: C.meName, t: '', lv: LS.get('lvl', {}).lv || 0, v: INFO.ver || '' }, roleOf(INFO.dev) === 'o' ? { ow: LS.get('ownTag', false) ? 1 : 0 } : {}, j); if (C.state.gRp) o.rp = C.state.gRp;
      NB.gsend2(JSON.stringify(o)); C.setState({ gRp: null });
      try {   // 1.47: jogap berlen adama we @agzalanlara bildiriş (bot arkaly — programma ýapyk bolsa-da)
        const to = o.rp && o.rp.i && o.rp.i !== INFO.dev ? [o.rp.i] : [], nm = ((o.t || '').match(/@[\w.\-]{2,20}/g) || []).map((x) => x.slice(1)).slice(0, 5);
        if (to.length || nm.length) NB.send(JSON.stringify({ k: 'gmen', to, nm, t: (o.t || o.st || '').slice(0, 160), n: C.meName }));
      } catch (e) {}
      if (o.dl || o.ed) { LCTL.push({ id: 'c' + Date.now(), i: INFO.dev, dl: o.dl || '', ed: o.ed || '', t: o.t || '', time: Date.now() / 1000 }); tick(); }
      else if (!o.ph && !o.sty && (o.t || o.st)) { LGM.push({ id: 'l' + Date.now(), i: INFO.dev, n: o.n, t: o.t || '', st: o.st || '', rp: o.rp || null, time: Date.now() / 1000, pend: true }); tick(); }
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
      else if (s0.page === 'chat' && /^tk/.test(id || '')) { const m = (s0.chat || []).find((q) => 'tk' + q.id === id); if (m) C.setState({ tkRp: { n: m.who === 'u' ? C.meName : m.who === 'ai' ? '🤖' : 'Admin', t: String(m.t || '').replace(/^» .*\n/, '').slice(0, 80) } }); }   // 1.47: bilet söhbetinde hem jogap
      else if (s0.page === 'dm' && s0.dmPeer) { const x = DMS[s0.dmPeer], m = x && x.msgs.find((q) => q.id === id); if (m && !m.sys) C.setState({ dmRp: rpOf(m, m.f === INFO.dev ? C.meName : nameOf(s0.dmPeer)) }); }
    };
    C.rpX = () => C.setState({ gRp: null, dmRp: null, tkRp: null });
    C.pullRefresh = () => {   // 1.47: aşak çekip täzelemek — sahypa görä
      const s0 = C.state, tx = C.T()[s0.lang];
      try { NB.refresh(); } catch (e) {}
      try { if (s0.page === 'global') NB.gwatch(true); } catch (e) {}
      try { if (s0.admOn) act('get'); } catch (e) {}
      if (s0.page === 'servers' && C.runTest) C.runTest();
      if (s0.page === 'rank' || s0.page === 'profile') NB.send(JSON.stringify({ k: 'lvlq' }));
      setTimeout(() => { try { INFO = J(NB.info(), INFO); } catch (e) {} C.setState({ payTick: Date.now(), gTick: (C.state.gTick || 0) + 1 }); }, 2500);
      C.say('⟳ ' + (({ ru: 'Обновляется…', tr: 'Yenileniyor…' })[s0.lang] || 'Täzelenýär…'));
    };
    C.rxWho = (key) => {   // 1.47: tepki goýanlaryň hemmesi
      const s0 = C.state, map = s0.page === 'dm' && s0.dmPeer && DMS[s0.dmPeer] ? rxAgg(DMS[s0.dmPeer].msgs) : rxAgg(G.concat(LRX)), x = map[key] || {};
      if (!Object.keys(x).length) return; try { NB.tap(); } catch (e) {} C.setState({ rxWho: Object.keys(x).map((d) => ({ d, e: x[d] })) }); };
    C.pickSticker = (em) => { C.setState({ stOn: false }); if (C.state.page === 'dm' && C.state.dmPeer) dmPush(C.state.dmPeer, { st: em }); else gSend({ st: em }); };
    C.gSendX = (j) => gSend(j);
    // 1.39: gysga wideo — programmanyň içinde kiçeldilýär (15 sn, ≤480 px, ~380 kbit/s WebM)
    const vidShrink = (file, cb) => {
      const url = URL.createObjectURL(file), v = document.createElement('video');
      let done = false; const fin = (o, why) => { if (done) return; done = true; URL.revokeObjectURL(url); cb(o, why); };
      v.src = url; v.playsInline = true; v.preload = 'auto';
      v.onerror = () => fin(null, 'bad');
      v.onloadedmetadata = () => {
        const sc = Math.min(1, 480 / Math.max(v.videoWidth || 480, v.videoHeight || 480)), w = Math.max(2, Math.round((v.videoWidth || 480) * sc / 2) * 2), h = Math.max(2, Math.round((v.videoHeight || 480) * sc / 2) * 2);
        const cv = document.createElement('canvas'); cv.width = w; cv.height = h; const x = cv.getContext('2d');
        const mt = ['video/webm;codecs=vp8,opus', 'video/webm;codecs=vp8', 'video/webm'].find((t) => window.MediaRecorder && MediaRecorder.isTypeSupported(t));
        if (!mt || !cv.captureStream) { fin(null, 'nosup'); return; }
        const st = cv.captureStream(24); let ac = null;
        try { ac = new (window.AudioContext || window.webkitAudioContext)(); const src = ac.createMediaElementSource(v), dst = ac.createMediaStreamDestination(); src.connect(dst); dst.stream.getAudioTracks().forEach((t) => st.addTrack(t)); } catch (e2) { v.muted = true; }
        const rec = new MediaRecorder(st, { mimeType: mt, videoBitsPerSecond: 380000, audioBitsPerSecond: 32000 }), ch = [];
        let poster = '', raf = 0;
        rec.ondataavailable = (ev) => { if (ev.data && ev.data.size) ch.push(ev.data); };
        rec.onstop = () => { try { if (ac) ac.close(); } catch (e3) {} const b = new Blob(ch, { type: 'video/webm' });
          if (b.size > 1300000) { fin(null, 'big'); return; } if (!poster) poster = cv.toDataURL('image/jpeg', 0.6);
          const fr = new FileReader(); fr.onload = () => fin({ vd: fr.result, ph: poster.length <= 108000 ? poster : cv.toDataURL('image/jpeg', 0.4) }); fr.readAsDataURL(b); };
        const stop = () => { cancelAnimationFrame(raf); try { v.pause(); } catch (e4) {} if (rec.state !== 'inactive') rec.stop(); };
        const draw = () => { x.drawImage(v, 0, 0, w, h); if (!poster && v.currentTime > 0.3) poster = cv.toDataURL('image/jpeg', 0.6); if (v.currentTime >= 15 || v.ended) { stop(); return; } raf = requestAnimationFrame(draw); };
        v.onended = stop; rec.start(1000);
        v.play().then(() => { raf = requestAnimationFrame(draw); }).catch(() => { stop(); fin(null, 'play'); });
      };
    };
    C.onStory = (e) => {   // 1.28: hekaýa (24 sagat)
      const f = fileOf(e); if (!f) return; e.target.value = '';
      if (gBlocked()) return;
      if (/^video\//.test(f.type || '')) {   // 1.39: wideo hekaýa
        const tx = C.T()[C.state.lang]; if (C._vidBusy) return; C._vidBusy = true; C.say('🎬 ' + tx.sty_vprep);
        vidShrink(f, (o, why) => { C._vidBusy = false; const tx2 = C.T()[C.state.lang];
          if (!o) { C.say('⚠️ ' + (why === 'big' ? tx2.sty_vbig : tx2.sty_vbad)); return; }
          if (gSend({ sty: 1, ph: o.ph, vd: o.vd, t: '' })) C.say('✨ ' + tx2.sty_ok); });
        return;
      }
      fitShrink(f, 1280, 108000, (d) => { const tx = C.T()[C.state.lang]; if (!d) { C.say(tx.ph_big); return; } if (gSend({ sty: 1, ph: d, t: '' })) C.say('✨ ' + tx.sty_ok); });
    };
    C.svOpen = (dev, i) => C.setState({ sv: { d: dev, i: i || 0 } });
    C.svNext = () => { const v = C.state.sv, by = C._stBy || {}, ord = C._stOrder || []; if (!v) return; const L = by[v.d] || [];
      if (v.i + 1 < L.length) { C.setState({ sv: { d: v.d, i: v.i + 1 } }); return; } const k = ord.indexOf(v.d); C.setState({ sv: k >= 0 && k + 1 < ord.length ? { d: ord[k + 1], i: 0 } : null }); };
    C.svPrev = () => { const v = C.state.sv, ord = C._stOrder || []; if (!v) return; if (v.i > 0) { C.setState({ sv: { d: v.d, i: v.i - 1 } }); return; }
      const k = ord.indexOf(v.d); if (k > 0) C.setState({ sv: { d: ord[k - 1], i: 0 } }); };
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
      if (p === 'adm_x' || p === 'adm_or' || p === 'adm_bn') { C.setState({ page: 'admin', admTab: 'bot' }); return; }
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
      if (LINK_RE.test(t) && !isStaff(INFO.dev)) { C.say('🚫 ' + tx.g_link); return; }   // 1.46.4: eýesi / adminler salgy iberip bilýär
      if (C.state.gEdit) { if (gSend({ ed: C.state.gEdit, t })) C.setState({ gIn: '', gEdit: null }); return; }   // 1.28
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
      act(t.st === 'closed' ? 'reopen' : 'close', { tid: t.id }); t.st = t.st === 'closed' ? 'open' : 'closed'; TKO[String(t.id)] = { st: t.st, at: Date.now() }; C.setState({ admTick: (C.state.admTick || 0) + 1 });
    };
    C.tkCloseAll = () => { const tx = C.T()[C.state.lang], op = ((A && A.tk) || []).filter((t) => t.st !== 'closed'); if (!op.length) return;   // 1.46.7
      C.confirm(tx.tk_allQ.replace('{n}', String(op.length)), '🔒 ' + tx.tk_all, () => { act('closeall'); op.forEach((t) => { t.st = 'closed'; TKO[String(t.id)] = { st: 'closed', at: Date.now() }; }); C.setState({ admTick: (C.state.admTick || 0) + 1 }); }); };
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
    C.bcAi = () => {   // 1.47.22: habary AI owadanlaşdyrýar — netije ýazgy meýdançalaryna gelýär, eýesi barlap özi iberýär
      const s = C.state, tx = C.T()[s.lang], t = String(s.bcT || '').trim(), x = String(s.bcX || '').trim();
      if (s.bcAiWait && Date.now() - (s.bcAiAt || 0) < 60000) return;
      if (!t && !x) { C.say(tx.ad_bcNeed); return; }
      act('bcai', { t, x }); C.setState({ bcAiWait: true, bcAiAt: Date.now() }); C.say('✨ ' + tx.bc_aiWait);
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

  let saveAt = 0, lastPick = null, lastLang = null, lastPage = null, lastDmW = null, lastAutoP = null, lastAutoB = null;
  function poll(C, first) {
    const s = C.state, now = Date.now(), up = {};
    const n = J(NB.state(), null);
    if (n) {
      const st = n.st === 'fail' ? 'off' : n.st;
      if (first) { const p = loadServers(); up.pings = p; }
      const idx = (k) => (k ? SV.findIndex((v) => v.id === k) : -1);
      up.st = st; up.ms = n.ms > 0 ? n.ms : 0; up.testing = n.testing; up.ks = !!n.ks; up.dead = !!n.dead; up.pubg = !!n.pubg;
      up.si = Math.max(0, idx(n.act) >= 0 ? idx(n.act) : (idx(n.sel) >= 0 ? idx(n.sel) : 0));
      if (lastPick === null || (lastPick === s.pick && lastAutoP === !!s.autoP && lastAutoB === !!s.autoB)) { up.pick = idx(n.sel); lastPick = up.pick; up.autoP = !!n.selp; lastAutoP = up.autoP; up.autoB = !!n.selb; lastAutoB = up.autoB; }
      up.hasKey = n.left < 0 && !n.nolim; up.nolim = !!n.nolim; if (n.sess != null && n.sess !== SESS) { SESS = +n.sess; up.sessTick = (s.sessTick || 0) + 1; } up.left = n.left >= 0 ? n.left : 0; up.kexp = n.kexp; up.upd = n.upd; up.dl = n.dl;
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
    const chg = Object.keys(up).some((k) => { const a = up[k], b = s[k]; return a !== b && !(Array.isArray(a) && Array.isArray(b) && !a.length && !b.length); });
    if (chg || now - (C._rAt || 0) > 5000) { C._rAt = now; C.setState(up); }
    // UI → Kotlin
    const s2 = C.state;
    if (lastPick !== null && (s2.pick !== lastPick || (s2.pick < 0 && (!!s2.autoP !== lastAutoP || !!s2.autoB !== lastAutoB)))) { lastPick = s2.pick; lastAutoP = !!s2.autoP; lastAutoB = !!s2.autoB; const v = SV[s2.pick]; NB.select(v ? v.id : (s2.autoB ? 'auto:b' : s2.autoP ? 'auto:p' : '')); }
    if (lastLang !== s2.lang) { if (lastLang !== null) { NB.lang(s2.lang); INFO = J(NB.info(), INFO); } lastLang = s2.lang; }
    if (lastPage !== s2.page) { NB.gwatch(s2.page === 'global'); NB.dmPage(s2.page === 'dms'); lastPage = s2.page; alogPush('p', s2.page + (s2.page === 'uprof' ? ' ' + (nameOf(s2.upDev) || s2.upDev || '') : s2.page === 'dm' ? ' ' + (nameOf(s2.dmPeer) || '') : '')); }
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
        .forEach((k) => LS.set(k, k === 'chat' && Array.isArray(s2.chat) ? (() => { let n = 0; return s2.chat.slice().reverse().map((m) => (m.img && ++n > 3 ? Object.assign({}, m, { img: '', t: m.t || '🧾' }) : m)).reverse(); })() : s2[k]));   // 1.47.6: iň soňky 3 surat ýatda saklanýar
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
    // 1.41: baza (Google / VPS) üýtgese profil (surat, DM açary) täze bazada gaýtadan goýulýar
    const d = C.state.photo || '', bg = C.state.pbg || '', key = 'v3|' + (INFO.fsb || '') + '|' + d.length + d.slice(-40) + '|' + bg.length + bg.slice(-40) + '|' + C.meName;
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

  /** 1.47.22: habaryň senesi — «Şu gün 15:40», «Düýn 09:12» ýa-da «24.11 · 15:40». */
  function newsTime(ts, L) {
    const d = new Date((ts || 0) * 1000), now = new Date(), hm = String(d.getHours()).padStart(2, '0') + ':' + String(d.getMinutes()).padStart(2, '0');
    const day = (x) => Math.floor((x.getTime() - x.getTimezoneOffset() * 60000) / 86400000), dd = day(now) - day(d);
    if (dd === 0) return ({ ru: 'Сегодня', tr: 'Bugün' }[L] || 'Şu gün') + ' · ' + hm;
    if (dd === 1) return ({ ru: 'Вчера', tr: 'Dün' }[L] || 'Düýn') + ' · ' + hm;
    return String(d.getDate()).padStart(2, '0') + '.' + String(d.getMonth() + 1).padStart(2, '0') + (d.getFullYear() !== now.getFullYear() ? '.' + d.getFullYear() : '') + ' · ' + hm;
  }
  function news(C, up) {
    INFO = J(NB.info(), INFO);
    const list = (INFO.news || []).map((n) => { const j = J(n.j, {}); return { id: n.id, t: j.t || '', x: j.x || '', img: j.img || '', btn: Array.isArray(j.btn) ? j.btn : [], poll: j.poll && Array.isArray(j.poll.o) ? j.poll : null, time: newsTime(n.ts, C.state.lang) }; })
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
      if (e.rq) { up.rq = true; up.rqTab = 'req'; if (s.admOn) act('get'); }   // 1.44: «Premium aljak» bildirişi
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
      LCTL = LCTL.filter((l) => Date.now() / 1000 - l.time < 120 && !G.some((g) => g.i === l.i && (g.dl || '') === l.dl && (g.ed || '') === l.ed));
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
      const list = (e.list || []).map((m) => ({ id: m.id, t: m.t, f: m.f, x: m.x || '', ph: m.ph || '', st: m.st || '', sys: m.sys || '', rp: m.rp && m.rp.n ? m.rp : null, re: m.re || '', e: m.e || '', off: !!m.off, ty: m.ty || 0, rd: m.rd || 0, dl: m.dl || '', ed: m.ed || '' }));
      const same = (a, b) => a.f === b.f && (a.x || '') === (b.x || '') && (a.ph || '') === (b.ph || '') && (a.st || '') === (b.st || '') && (a.sys || '') === (b.sys || '') && (a.re || '') === (b.re || '') && (a.e || '') === (b.e || '') && !!a.off === !!b.off && (a.dl || '') === (b.dl || '') && (a.ed || '') === (b.ed || '');
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
    } else if (e.k === 'vid') {   // 1.39
      if (e.d) VI[e.id] = e.d; else delete vidAsked[e.id];
      up.gTick = (s.gTick || 0) + 1;
    } else if (e.k === 'stv') {   // 1.39: hekaýamy kim gördi
      const SV = LS.get('stViews', {}) || {}, x = SV[e.sv] || (SV[e.sv] = {});
      x[e.f] = [e.n || '', e.t || Date.now() / 1000];
      const ks = Object.keys(SV); if (ks.length > 60) ks.slice(0, ks.length - 60).forEach((k) => delete SV[k]);
      LS.set('stViews', SV); up.gTick = (s.gTick || 0) + 1;
    } else if (e.k === 'probe') {   // 1.46
      up.probeRun = false; C.say(e.n < 0 ? '⚠️ ' + tx.pb_none : tx.pb_done.replace('{n}', String(e.n)).replace('{ok}', String(e.ok)));
    } else if (e.k === 'online') {   // 1.47: onlaýn sany her minut
      INFO.online = +e.n || 0; up.gTick = (s.gTick || 0) + 1;
    } else if (e.k === 'mig') {   // 1.47: birikmek isledi — ilki göçmek
      up.migGate = true; if (!s.migStep || s.migStep === 2) up.migStep = 0;
    } else if (e.k === 'fb') {   // 1.47: PUBG / Premium-da işleýän kod ýok — adaty (mugt) koda birikdirildi, düwme özi öçdi
      C.say('⚠️ ' + (e.w === 'pubg' ? ({ ru: 'Серверы PUBG сейчас не работают — подключено к обычному', tr: 'PUBG sunucuları şu anda çalışmıyor — normal sunucuya bağlandı' }[s.lang] || 'PUBG serwerleri häzir işlemeýär — adaty serwere birikdirildi')
        : ({ ru: 'Коды Premium сейчас обновляются — подключено к бесплатному', tr: 'Premium kodları şu anda yenileniyor — ücretsiz koda bağlandı' }[s.lang] || 'Premium kodlar häzir täzelenýär — mugt koda birikdirildi')));
      if (e.w === 'pubg') up.pubg = false; else { up.autoP = false; up.autoB = false; up.pick = -1; }
    } else if (e.k === 'pgna') {   // 1.47.2: PUBG serwerleri N/A — düwme özi öçdi, birikme üýtgemedi
      up.pubg = false; C.say('⚠️ ' + ({ ru: 'Серверы PUBG сейчас не отвечают (N/A) — кнопка выключена, попробуйте позже', tr: 'PUBG sunucuları şu an yanıt vermiyor (N/A) — düğme kapatıldı, sonra tekrar deneyin' }[s.lang] || 'PUBG serwerleri häzir jogap bermeýär (N/A) — düwme öçürildi, soňrak synanyşyň'));
    } else if (e.k === 'plock') {   // 1.43: Premium serwer saýlandy (Premium ýok)
      C.say('👑 ' + tx.pr_lock); up.psh = true; up.pstep = 1;
    } else if (e.k === 'img') {
      if (!e.d) { setTimeout(() => { delete imgAsked[(e.kind || 'g') + e.id]; }, 20000); return; }   // 1.46.1: alyp bolmady — 20 sn soň gaýtadan
      (e.kind === 'n' ? NI : GI)[e.id] = e.d;
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
      Object.keys(TKO).forEach((id) => { if (Date.now() - TKO[id].at > 120000) { delete TKO[id]; return; } const t0 = (A.tk || []).find((x) => String(x.id) === id); if (t0) t0.st = TKO[id].st; });   // 1.46.7: ýapan biletim köne maglumat bilen gaýtadan açylmasyn
      if (Array.isArray(d.alog)) up.alog = d.alog;   // 1.46.7
      if (d.uinfo && d.uinfo.dev) up.uInfo = d.uinfo;   // 1.47: ulanyjy maglumaty
      if (Array.isArray(d.usr)) { d.usr.forEach((u) => { if (u && u.dev) SR[u.dev] = u.n; }); up.usRes = d.usr; up.usDone = true; }   // 1.45
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
      else if (d.msg && d.msg.indexOf('fast:') === 0) { const v = d.msg.slice(5) === '1'; if (A) A.fast = v; up.faCur = null; C.say(v ? tx.fa_okOn : tx.fa_okOff); }
      else if (d.msg && d.msg.indexOf('sess:') === 0) { const m = +d.msg.slice(5); if (A) A.sess = m; up.seCur = null; C.say(tx.se_ok.replace('{v}', m === 0 ? tx.se_unl : hrsT(s.lang, m))); }
      else if (d.msg === 'payok') { C.say('💳 ' + tx.ps_ok); up.payT = null; up.payImg = ''; up.payNoImg = false; LS.set('payInfo', null); }
      else if (d.msg && d.msg.indexOf('xp:') === 0) { const q = d.msg.split(':'); UPX[q[3]] = { lv: +q[1], xp: +q[2] }; LVB[q[3]] = [+q[1], Date.now()]; LS.set('lvb', LVB); C.say('✅ ' + tx.gv_ok.replace('{l}', q[1]).replace('{x}', q[2])); }
      else if (d.msg && d.msg.indexOf('prem:') === 0) C.say('👑 ' + tx.pr_given);   // 1.43
      else if (d.msg === 'aperm') C.say('✅ ' + tx.ap_ok);   // 1.44
      else if (d.msg && d.msg.indexOf('punprem:') === 0) { C.say('✅ ' + tx.pr_rmOk); A.prem = (A.prem || []).filter((x) => x.dev !== (s.upDev || INFO.dev)); }   // 1.45
      else if (d.msg && d.msg.indexOf('perm:') === 0) C.say('✅ ' + tx.rp_ok);
      else if (d.msg && d.msg.indexOf('gmute:') === 0) C.say('✅ ' + tx.gm_ok);
      else if (d.msg && d.msg.indexOf('sel:') === 0) { const q = d.msg.split(':'); C.say(q[2] === '1' ? tx.sl_okOn : '✅ ' + tx.sl_okOff); try { NB.refresh && NB.refresh(); } catch (e2) {} }
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
    } else if (e.k === 'tkimgfail') {   // 1.47.6
      C.say('⚠️ ' + (({ ru: 'Фото не отправлено — проверьте интернет и попробуйте снова', tr: 'Fotoğraf gönderilemedi — interneti kontrol edip tekrar deneyin' })[s.lang] || 'Surat iberilmedi — interneti barlap, täzeden synanyşyň'));
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
        C.party(m.why === 'gift' ? tx.gift_got : m.why === 'ref' ? tx.ref_got.replace('{d}', String(m.days || 1)) : m.why === 'week' ? tx.wk_won.replace('{p}', String(m.place || 1)).replace('{d}', String(m.days || 1))
          : m.why === 'kgift' ? tx.gf_got.replace('{n}', m.from || '?').replace('{d}', String(m.days || 1)) : tx.k_ext);
      } else if (m.k === 'migok') {   // 1.47: köne programmadan göçürildi — penjire «Geçirildi», özi birigýär
        C._mig = null; if (m.n) { C.meName = m.n; LS.set('nick', m.n); }
        if (s.migGate) { up.migStep = 2; setTimeout(() => { try { NB.connect(); } catch (e2) {} }, 600); }
        else C.party('✅ ' + ({ ru: 'Перенесено из старой программы', tr: 'Eski programdan aktarıldı' }[s.lang] || 'Köne programmadan geçirildi'));
        try { NB.refresh(); } catch (e2) {} setTimeout(() => { INFO = J(NB.info(), INFO); C.setState({ payTick: Date.now() }); }, 4000);
      } else if (m.k === 'lvl') {
        LS.set('lvl', { lv: m.lv, xp: m.xp, cur: m.cur, next: m.next, inv: m.inv }); up.payTick = t; if (m.inv != null) up.invites = m.inv;
        if (m.up) { up.rkm = { t: rkT(m.lv), up: true, days: m.days || 0 }; C.party('⭐ ' + tx.lv_up.replace('{n}', String(m.lv)) + (m.days ? ' · +' + m.days + ' ' + tx.days : '')); }
      } else if (m.k === 'gmen') {   // 1.47: Global chatda jogap / @agzamak
        if (s.page !== 'global') C.say('💬 ' + (m.n || '?') + ' · ' + (m.rp ? ({ ru: 'ответил(а) вам', tr: 'size yanıt verdi' }[s.lang] || 'size jogap berdi') : ({ ru: 'упомянул(а) вас', tr: 'sizden bahsetti' }[s.lang] || 'sizi agzady')) + (m.t ? ': ' + m.t.slice(0, 60) : ''));
      } else if (m.k === 'usr') { up.dmSR = { q: m.q || '', l: m.l || [] }; (m.l || []).forEach((u) => tagPut(u.d, u.t));   // 1.47: ulanyjy gözleginiň netijesi
        if (TAGW && m.q === '@' + TAGW.t && Date.now() - TAGW.at < 20000) { const hit = (m.l || []).find((u) => u.t === TAGW.t); TAGW = null;   // 1.47.22: basylan @belgi
          if (hit) setTimeout(() => C.openProf(hit.d), 0); else C.say('⚠️ ' + tx.tg_none); }
      } else if (m.k === 'bcai') { up.bcAiWait = false; if (m.ok) { up.bcT = m.t || ''; up.bcX = m.x || ''; C.say('✨ ' + tx.bc_aiOk); } else C.say('⚠️ ' + tx.bc_aiBad);   // 1.47.22
      } else if (m.k === 'tagset') { if (m.ok) { tagPut(INFO.dev, m.t); up.tgSt = 'ok'; up.tgIn = null; up.tagTick = t; } else up.tgSt = m.why === 'taken' ? 'taken' : 'bad';   // 1.47.22: öz @belgisi
      } else if (m.k === 'utag') { tagPut(m.d, m.t); up.tagTick = t;   // 1.47.4: @belgi
      } else if (m.k === 'top') { LS.set('top', m.l || []); up.payTick = t; }
      else if (m.k === 'lvs') { const tn = Date.now(); Object.keys(m.m || {}).forEach((d) => { LVB[d] = [+m.m[d] || 0, tn]; }); LS.set('lvb', LVB); up.gTick = (s.gTick || 0) + 1; }
      else if (m.k === 'kgift') { if (m.ok) { C.say(tx.gf_ok.replace('{n}', m.to || '?').replace('{d}', String(m.d || 1))); up.gfTo = ''; try { NB.refresh(); } catch (e2) {} } else C.say('⚠️ ' + (tx['gf_e_' + m.why] || tx.gf_e_notfound)); }
      else if (m.k === 'pay') { LS.set('payInfo', { p: m.p, i: m.i, pi: m.pi || '', at: Date.now() }); up.payTick = t; }
      else if (m.k === 'prem') {   // 1.43: Premium berildi
        C.party('👑 ' + (m.exp === 0 ? tx.pr_gotU : tx.pr_got.replace('{d}', (m.d === 365 ? tx.pr_y : m.d === 30 ? tx.pr_m : m.d + ' ' + tx.pr_days))));
        try { NB.refresh(); } catch (e2) {} setTimeout(() => { INFO = J(NB.info(), INFO); C.setState({ payTick: Date.now() }); }, 4000);
      } else if (m.k === 'preqdup') {   // 1.47: bu alyjynyň haýyşy eýýäm bar — ilkinji satyja
        if (m.to) { LS.set('preqTo', { d: m.to, at: Date.now() }); C.openDm(m.to); }
        C.say('👑 ' + ({ ru: 'Вы уже отправили запрос продавцу — пишите ему', tr: 'Zaten bir satıcıya istek gönderdiniz — ona yazın' }[s.lang] || 'Siz eýýäm satyja haýyş iberdiňiz — şoňa ýazyň'));
      } else if (m.k === 'preq') {   // 1.43: satyja / eýesine täze haýyş
        const L = (LS.get('preqs', []) || []).filter((q) => q.id !== m.id); L.unshift({ id: m.id, dev: m.dev, n: m.n, plan: m.plan, ts: m.ts, st: 'new' }); LS.set('preqs', L.slice(0, 60));
        C.say('👑 ' + tx.pr_newReq.replace('{n}', m.n || '?').replace('{p}', (m.plan === 'y' ? tx.pr_y : m.plan === 'w' ? ({ ru: '1 неделя', tr: '1 hafta' }[s.lang] || '1 hepde') : tx.pr_m))); up.payTick = t;
      } else if (m.k === 'pgv') {   // 1.43: satyjy Premium berdi (eýesine)
        C.say('👑 ' + tx.pr_pgv.replace('{by}', m.by || '?').replace('{n}', m.n || '?').replace('{p}', m.d === 365 ? tx.pr_y : m.d === 30 ? tx.pr_m : (m.d || 0) + ' ' + tx.pr_days)); up.payTick = t;
      }
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
      } else if (m.k === 'uban') { INFO.uban = !!m.on; up.banTick = Date.now(); }   // 1.47.21: tutuş ekran gadagan ýazgysy (ýazyp / basyp bolmaýar)
      else if (m.k === 'quota') { qAdd(m.id, m.t, m.at); up.qTick = (s.qTick || 0) + 1; }
      else if (m.k === 'atk') { if (INFO.adm) { C.say((m.new ? tx.atk_new : '🎫') + ' #' + m.tid + (m.n ? ' · ' + m.n : '') + ': ' + String(m.t || '').slice(0, 70)); admAt = 0; } }
      else if (m.k === 'mute') { LS.set('muteUntil', (m.until || 0) * 1000); C.say('🔇 ' + tx.g_muteOn); }
      else if (m.k === 'gwarn') { C.say('⚠️ ' + tx.g_warn.replace('{n}', String(m.n || 1))); }
    }
  }

  function showAd(link) {
    // 1.33: mahabat — ekranyň ortasynda doly giňlikde kart (öň sag burçda kiçijik penjire başlygyň üstüne düşýärdi)
    if (document.getElementById('tvad')) return;
    const lang = (window.C && window.C.state.lang) || 'tk', lbl = { tk: 'Mahabat', ru: 'Реклама', tr: 'Reklam' }[lang] || 'Mahabat';
    const w = document.createElement('div'); w.id = 'tvad';
    w.style.cssText = 'position:fixed;inset:0;z-index:99;display:flex;align-items:center;justify-content:center;padding:16px;box-sizing:border-box;background:rgba(0,0,0,.55);animation:pop .35s ease';
    const card = document.createElement('div');
    card.style.cssText = 'position:relative;width:100%;max-width:520px;border:2px solid #E0B04A;border-radius:18px;overflow:hidden;background:#081610;box-shadow:0 12px 34px rgba(0,0,0,.65)';
    const img = document.createElement('img'); img.src = 'ad.img?' + Date.now(); img.alt = lbl;
    img.style.cssText = 'display:block;width:100%;height:auto;max-height:70vh;object-fit:contain;cursor:' + (link ? 'pointer' : 'default');
    img.onclick = () => { if (link) { NB.open(link); close(); } };
    img.onerror = () => close();
    const tag = document.createElement('span'); tag.textContent = lbl;
    tag.style.cssText = 'position:absolute;left:8px;top:8px;padding:2px 8px;border-radius:8px;background:rgba(10,28,20,.85);color:#FFD27A;font:700 11px Manrope,sans-serif;letter-spacing:.06em';
    const x = document.createElement('button'); x.textContent = '✕'; x.setAttribute('aria-label', { tk: 'Ýap', ru: 'Закрыть', tr: 'Kapat' }[lang] || 'Ýap');
    x.style.cssText = 'position:absolute;right:8px;top:8px;width:32px;height:32px;border-radius:16px;border:1px solid #E0B04A;background:rgba(10,28,20,.9);color:#fff;font-size:14px;cursor:pointer';
    const close = () => { w.remove(); clearTimeout(tm); };
    x.onclick = close; w.onclick = (e) => { if (e.target === w) close(); };
    const tm = setTimeout(close, 10000);
    card.appendChild(img); card.appendChild(tag); card.appendChild(x); w.appendChild(card); document.body.appendChild(w);
  }

  /** Telefonyň «Yza» düwmesi. */
  window.NBack = function () {
    const C = window.C; if (!C) return false; const s = C.state;
    if (document.getElementById('tvad')) { document.getElementById('tvad').remove(); return true; }
    if (s.zoom) { C.setState({ zoom: '' }); return true; }
    if (s.rkm) { C.setState({ rkm: null }); return true; }
    if (s.dmPeek) { C.setState({ dmPeek: null }); return true; }
    if (s.sv) { C.setState({ sv: null }); return true; }
    if (s.ma) { C.setState({ ma: null }); return true; }
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
    const rq = tg.closest('.tgc .rpq[data-to]'); if (rq && rq.getAttribute('data-to')) { rpJump(rq.getAttribute('data-to')); return; }   // 1.46.4
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
    if (Date.now() - (window.__lpRx || 0) < 1200) return;   // 1.47: tepkini basyp saklady — göçürmek däl
    const c = el.cloneNode(true);
    c.querySelectorAll('.gnm,.rpq,img,.gst,.bt,.ailbl,button:not(.kchip)').forEach((x) => x.remove());
    const t = (c.innerText || c.textContent || '').replace(/📋/g, '').trim();
    if (!t && !el.querySelector('img') || !window.C) return;
    const id = el.getAttribute('data-rp') || '';
    if (el.classList.contains('gb-me') && id && !/^[lp]/.test(id)) { lpAt = Date.now(); try { NB.tap(); } catch (e) {} window.C.msgMenu(id, window.C.state.page === 'dm' ? 'd' : 'g', t); return; }   // 1.28: öz habaryň
    if (window.C._canPin && window.C.state.page === 'global' && id && !/^[lp]/.test(id)) { lpAt = Date.now(); try { NB.tap(); } catch (e) {} window.C.msgMenu(id, 'g', t, false); return; }   // 1.46.5: admin — berkit / göçür
    if (!t) return;
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
  const svHide = (el) => { const C = window.C; if (!C || !window.__isOwn) return; const n = el.getAttribute('data-sn'), k = el.getAttribute('data-sk') || n; if (!k) return;   // 1.47.12: diňe şu serwer (ady däl — şol ýurduň beýlekileri gizlenmeýär)
    window.__lpSv = Date.now(); const H = window.__svHide || (window.__svHide = {}); H[k] = Date.now() + 30000;
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
  // 1.47: aşak çekip täzelemek — ähli sahypalarda (sahypa ýokarsynda bolsa)
  let ptr = null; const ptrEl = document.createElement('div');
  ptrEl.style.cssText = 'position:fixed;left:50%;top:70px;width:40px;height:40px;margin-left:-20px;border-radius:20px;background:rgba(8,24,17,.92);border:1px solid rgba(224,176,74,.6);color:#FFD27A;display:none;align-items:center;justify-content:center;font-size:20px;z-index:90;box-shadow:0 6px 18px rgba(0,0,0,.5);pointer-events:none';
  ptrEl.textContent = '⟳'; document.body.appendChild(ptrEl);
  const scTop = (el) => { for (let x = el; x && x !== document.body; x = x.parentElement) { const cs = getComputedStyle(x); if (/(auto|scroll)/.test(cs.overflowY) && x.scrollHeight > x.clientHeight + 4) return x.scrollTop; } return 0; };
  document.addEventListener('touchstart', (e) => { const C = window.C; if (!C || e.touches.length !== 1) { ptr = null; return; }
    const tg = e.target; if (tg && tg.closest && tg.closest('input,textarea,canvas,[data-rp],[data-rxk],.scrim,[role="dialog"]')) { ptr = null; return; }
    if (scTop(tg) > 0) { ptr = null; return; } const t = e.touches[0]; ptr = { x: t.clientX, y: t.clientY, d: 0 }; }, { passive: true });
  document.addEventListener('touchmove', (e) => { if (!ptr) return; const t = e.touches[0], dy = t.clientY - ptr.y, dx = t.clientX - ptr.x;
    if (dy <= 0 || Math.abs(dx) > dy) { if (ptr.d) ptrEl.style.display = 'none'; ptr = dy < -6 ? null : ptr; return; }
    ptr.d = dy; const k = Math.min(1, dy / 90); ptrEl.style.display = 'flex'; ptrEl.style.opacity = String(k); ptrEl.style.transform = 'translateY(' + Math.min(60, dy / 2) + 'px) rotate(' + Math.round(dy * 3) + 'deg)'; }, { passive: true });
  const ptrEnd = () => { if (!ptr) return; const d = ptr.d; ptr = null;
    if (d > 90 && window.C) { ptrEl.style.transition = 'transform .6s linear'; ptrEl.style.transform = 'translateY(45px) rotate(720deg)'; try { NB.tap(); } catch (e) {} window.C.pullRefresh();
      setTimeout(() => { ptrEl.style.display = 'none'; ptrEl.style.transition = ''; }, 900); } else ptrEl.style.display = 'none'; };
  document.addEventListener('touchend', ptrEnd, { passive: true }); document.addEventListener('touchcancel', ptrEnd, { passive: true });
  // 1.47: tepkiniň üstüne basyp saklamak → tepki goýanlaryň hemmesi
  let rxLp = null;
  document.addEventListener('touchstart', (e) => { const el = e.target && e.target.closest && e.target.closest('[data-rxk]'); if (!el) { rxLp = null; return; }
    const t = e.touches[0], o = { x: t.clientX, y: t.clientY }; o.tm = setTimeout(() => { if (rxLp !== o) return; rxLp = null; window.__lpRx = Date.now(); if (window.C) window.C.rxWho(el.getAttribute('data-rxk')); }, 450); rxLp = o; }, { passive: true });
  document.addEventListener('touchmove', (e) => { if (!rxLp) return; const t = e.touches[0]; if (Math.abs(t.clientX - rxLp.x) > 10 || Math.abs(t.clientY - rxLp.y) > 10) { clearTimeout(rxLp.tm); rxLp = null; } }, { passive: true });
  const rxEnd = () => { if (rxLp) { clearTimeout(rxLp.tm); rxLp = null; } };
  document.addEventListener('touchend', rxEnd, { passive: true }); document.addEventListener('touchcancel', rxEnd, { passive: true });
  document.addEventListener('contextmenu', (e) => { const el = e.target && e.target.closest && e.target.closest('[data-rxk]'); if (!el || !window.C) return; e.preventDefault(); if (Date.now() - (window.__lpRx || 0) > 900) { window.__lpRx = Date.now(); window.C.rxWho(el.getAttribute('data-rxk')); } });
  document.addEventListener('click', (e) => { if (Date.now() - (window.__lpRx || 0) < 900 && e.target && e.target.closest && e.target.closest('[data-rxk]')) { e.stopPropagation(); e.preventDefault(); } }, true);
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
