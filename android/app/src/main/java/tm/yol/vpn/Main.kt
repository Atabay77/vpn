package tm.yol.vpn

import android.annotation.SuppressLint
import android.app.Activity
import android.app.AlertDialog
import android.app.DownloadManager
import android.app.StatusBarManager
import android.content.ClipData
import android.content.ClipboardManager
import android.content.ComponentName
import android.content.Intent
import android.graphics.Color
import android.graphics.drawable.Icon
import android.net.TrafficStats
import android.net.Uri
import android.net.VpnService
import android.os.Build
import android.os.Bundle
import android.os.Handler
import android.os.Looper
import android.os.Process
import android.view.View
import android.view.WindowInsets
import android.webkit.ConsoleMessage
import android.webkit.JavascriptInterface
import android.webkit.ValueCallback
import android.webkit.WebChromeClient
import android.webkit.WebResourceRequest
import android.webkit.WebResourceResponse
import android.webkit.WebView
import android.webkit.WebViewClient
import android.widget.FrameLayout
import android.widget.Toast
import libv2ray.Libv2ray
import org.json.JSONArray
import org.json.JSONObject
import java.io.File
import java.net.HttpURLConnection
import java.net.URL
import java.util.concurrent.Executors

/**
 * 1.14: ekranlar tasarymyň özi (assets/ui, WebView içinde). VPN, serwerler, açar, täzelenme we habarlaşma şu ýerde (Kotlin).
 * Sahypa https://tvpn.local/ salgysyndan açylýar — faýllar programmanyň içinden berilýär (internet gerek däl).
 */
class Main : Activity() {
    private lateinit var web: WebView
    private val h = Handler(Looper.getMainLooper())
    private var fromApp = false
    private var lastState = -1
    private var testing = false
    private var slowShown = false
    private var fileCb: ValueCallback<Array<Uri>>? = null
    private val listener: () -> Unit = { onState() }
    // tizlik
    private var lastRx = -1L; private var lastTx = -1L; private var lastT = 0L; private var rx0 = -1L; private var tx0 = -1L
    @Volatile private var dRate = 0L; @Volatile private var uRate = 0L; @Volatile private var rxSum = 0L; @Volatile private var txSum = 0L
    private var msAt = 0L; private var msFails = 0

    @SuppressLint("SetJavaScriptEnabled")
    override fun onCreate(b: Bundle?) {
        super.onCreate(b)
        State.app = applicationContext
        Lang.init(this)
        runCatching { Libv2ray.initCoreEnv(filesDir.absolutePath, "") }
        runCatching { Snd.init(this) }
        Msg.start(this)
        window.statusBarColor = Color.parseColor("#06100B"); window.navigationBarColor = Color.parseColor("#06100B")
        val root = FrameLayout(this).apply { setBackgroundColor(Color.parseColor("#06100B")) }
        web = WebView(this).apply { setBackgroundColor(Color.parseColor("#06100B")) }
        root.addView(web, FrameLayout.LayoutParams(-1, -1))
        // Android 15: ekranyň ýokarky/aşaky zolagy tasarymyň üstüne düşmesin
        // Android 11+: zolaklary we klawiaturany özümiz hasaplaýarys (her wersiýada birmeňzeş); köne wersiýalarda ulgam özi edýär
        if (Build.VERSION.SDK_INT >= 30) {
            window.setDecorFitsSystemWindows(false)
            root.setOnApplyWindowInsetsListener { v, ins ->
                val s = ins.getInsets(WindowInsets.Type.systemBars() or WindowInsets.Type.ime()); v.setPadding(s.left, s.top, s.right, s.bottom); ins
            }
        }
        setContentView(root)
        with(web.settings) {
            javaScriptEnabled = true; domStorageEnabled = true; allowFileAccess = false; allowContentAccess = false
            mediaPlaybackRequiresUserGesture = true; textZoom = 100; setSupportZoom(false)
        }
        web.addJavascriptInterface(Bridge(), "NB")
        web.webViewClient = object : WebViewClient() {
            override fun shouldInterceptRequest(v: WebView, r: WebResourceRequest): WebResourceResponse? = asset(r.url)
            override fun shouldOverrideUrlLoading(v: WebView, r: WebResourceRequest): Boolean {
                if (r.url.host == HOST) return false
                runCatching { startActivity(Intent(Intent.ACTION_VIEW, r.url)) }; return true
            }
        }
        web.webChromeClient = object : WebChromeClient() {
            override fun onShowFileChooser(v: WebView, cb: ValueCallback<Array<Uri>>, p: FileChooserParams): Boolean {
                fileCb?.onReceiveValue(null); fileCb = cb
                return runCatching { startActivityForResult(Intent(Intent.ACTION_GET_CONTENT).setType("image/*").addCategory(Intent.CATEGORY_OPENABLE), 7); true }
                    .getOrElse { fileCb = null; false }
            }
            override fun onConsoleMessage(m: ConsoleMessage): Boolean { android.util.Log.d("ui", m.message() + " @" + m.lineNumber()); return true }
        }
        Sub.load(this)
        runCatching { Upd.clean(this, Msg.ver(this)) }   // gurnalan wersiýanyň (ýa-da könäniň) ýüklemesi galmasyn
        if (b == null && State.now != State.ON && State.now != State.WAIT) State.select(this, null)
        if (Build.VERSION.SDK_INT >= 33) requestPermissions(arrayOf("android.permission.POST_NOTIFICATIONS"), 2)
        web.loadUrl("https://$HOST/index.html" + (if (intent?.action == CHAT) "#chat" else ""))
        Thread {
            val ok = Sub.refresh(this, 7000)
            push(JSONObject().put("k", "srv").put("ok", ok))
            // 1.13-den täzelenenler: ýatda saklanan açar heniz telefona baglanmadyk bolsa bota habar (1 açar = 1 telefon)
            Lic.saved(this)?.let { k -> val h = Lic.hash(k); if (ok && Sub.keys.containsKey(h) && Msg.dev(this) !in Lic.devs(h) && Lic.exp(this) != null) Msg.send(this, JSONObject().put("k", "ka").put("h", h)) }
            Stats.beat(this, false)
            loadAd()
            if (State.pings.isEmpty()) { State.warm(); push(JSONObject().put("k", "srv")) }
        }.start()
        if (b == null) handle(intent)
    }

    /** Programmanyň içindäki faýllar (assets/ui) we mahabat suraty. */
    private fun asset(u: Uri): WebResourceResponse? {
        if (u.host != HOST) return null
        val path = (u.path ?: "/").trimStart('/').ifEmpty { "index.html" }
        if (path == "ad.img") {
            val f = File(cacheDir, "ad_" + (Sub.ad?.first ?: "x"))
            return if (f.exists()) WebResourceResponse("image/jpeg", null, f.inputStream()) else WebResourceResponse("text/plain", null, 404, "yok", null, null)
        }
        if (path.contains("..")) return null
        val mime = when (path.substringAfterLast('.')) {
            "html" -> "text/html"; "js" -> "application/javascript"; "css" -> "text/css"; "png" -> "image/png"
            "jpg" -> "image/jpeg"; "woff2" -> "font/woff2"; "json" -> "application/json"; else -> "application/octet-stream"
        }
        return runCatching { WebResourceResponse(mime, "utf-8", assets.open("ui/$path")) }.getOrNull()
    }

    override fun onNewIntent(i: Intent) { super.onNewIntent(i); handle(i) }

    private fun handle(i: Intent?) {
        when (i?.action) {
            INSTALL -> Upd.install(this)
            GO -> if (State.now != State.ON && State.now != State.WAIT) connect()
            CHAT -> push(JSONObject().put("k", "go").put("page", "chat"))
            ADMT -> push(JSONObject().put("k", "go").put("page", "adm_t").put("tid", i.getIntExtra("tid", 0)))
        }
    }

    override fun onStart() {
        super.onStart(); State.subs += listener; Msg.visible = true; Msg.kick(); onState()
        h.removeCallbacks(tick); h.post(tick)
    }

    override fun onStop() {
        State.subs -= listener; h.removeCallbacks(tick); Msg.visible = false; Msg.watchG = false
        if (fromApp && State.now == State.WAIT) startService(Intent(this, Svc::class.java).setAction(Svc.STOP))   // bağlanırken çıkılırsa iptal
        fromApp = false
        super.onStop()
    }

    @Deprecated("Activity API")
    override fun onBackPressed() {
        web.evaluateJavascript("window.NBack&&window.NBack()") { r -> if (r != "true") ui { @Suppress("DEPRECATION") super.onBackPressed() } }
    }

    @Deprecated("Activity API")
    override fun onActivityResult(req: Int, res: Int, data: Intent?) {
        super.onActivityResult(req, res, data)
        if (req == 1 && res == RESULT_OK) startVpn()
        if (req == 7) { fileCb?.onReceiveValue(if (res == RESULT_OK && data?.data != null) arrayOf(data.data!!) else null); fileCb = null }
    }

    // ---------- ýagdaý ----------
    private fun onState() {
        val st = State.now
        if (lastState == State.WAIT && st == State.ON) { Snd.play(this, R.raw.on); msAt = System.currentTimeMillis() - 8000; msFails = 0 }
        if (lastState == State.WAIT && st == State.FAIL && State.noNet) { State.noNet = false; info(noNet()) }
        if (lastState == State.WAIT && st == State.FAIL && State.noPing) { State.noPing = false; info(noCodes()) }
        if (lastState == State.ON && st == State.OFF) Snd.play(this, R.raw.off)
        if (st != State.ON) { lastRx = -1; rx0 = -1; dRate = 0; uRate = 0 }
        lastState = st
    }

    private val tick = object : Runnable {
        override fun run() {
            h.removeCallbacks(this)
            if (State.now == State.ON) {
                val uid = Process.myUid()
                val rx = TrafficStats.getUidRxBytes(uid); val tx = TrafficStats.getUidTxBytes(uid)
                if (rx0 < 0) { rx0 = rx; tx0 = tx }
                val now = android.os.SystemClock.elapsedRealtime()
                if (lastRx < 0 || rx < lastRx || tx < lastTx) { lastRx = rx; lastTx = tx; lastT = now }
                else if (now - lastT >= 800) {
                    val dt = now - lastT
                    dRate = (rx - lastRx) * 1000 / dt; uRate = (tx - lastTx) * 1000 / dt
                    rxSum = rx - rx0; txSum = tx - tx0
                    lastRx = rx; lastTx = tx; lastT = now
                }
                measureLive()
            }
            watchDownload()
            h.postDelayed(this, 1000)
        }
    }

    /** Bağlıyken tünel içinden ms (10 sn'de bir). */
    private fun measureLive() {
        val now = System.currentTimeMillis()
        if (now - msAt < 10_000) return
        msAt = now
        Thread {
            val v = runCatching { State.core?.measureDelay(State.PING) ?: -1L }.getOrDefault(-1L)
            if (v > 0) { State.ms = v; msFails = 0 } else if (++msFails >= 2 || State.ms <= 0) State.ms = -1
        }.start()
    }

    private fun push(o: JSONObject) { Msg.events.add(o) }

    // ---------- JS köprüsi ----------
    inner class Bridge {
        @JavascriptInterface fun state(): String {
            val c = this@Main
            val left = Lic.left(c); val exp = Lic.exp(c)
            val upd = Upd.available(Msg.ver(c))
            val q = Upd.query(c)
            return JSONObject()
                .put("st", when (State.now) { State.ON -> "on"; State.WAIT -> "wait"; State.FAIL -> "fail"; else -> "off" })
                .put("act", State.active?.key ?: "").put("sel", State.selected(c)?.key ?: "")
                .put("ms", State.ms).put("left", if (left == null) -1 else left / 1000).put("kexp", if (exp == null) -1 else exp / 1000)
                .put("dn", dRate).put("up", uRate).put("rxT", rxSum).put("txT", txSum).put("onAt", State.onAt)
                .put("testing", testing).put("upd", upd?.first ?: "")
                .put("dl", if (q != null && q.status != DownloadManager.STATUS_SUCCESSFUL && q.status != DownloadManager.STATUS_FAILED) q.pct else -1)
                .toString()
        }

        @JavascriptInterface fun info(): String {
            val c = this@Main
            val nw = JSONArray(); Sub.news.forEach { (id, ts, j) -> nw.put(JSONObject().put("id", id).put("ts", ts).put("j", j)) }
            return JSONObject().put("dev", Msg.dev(c)).put("code", Msg.code(c)).put("ver", Msg.ver(c)).put("lang", Lang.cur)
                .put("snd", Snd.on(c)).put("news", nw).put("ai", Sub.ai).put("online", Sub.online).put("bans", JSONArray(Sub.bans.toList()))
                .put("key", Lic.saved(c) ?: "").put("model", Build.MANUFACTURER + " " + Build.MODEL).put("relay", Sub.relay.isNotEmpty() || Fs.on()).put("fs", Fs.on())
                .put("dl", (Sub.upd["all"] ?: Sub.upd["64"] ?: Sub.upd["32"])?.let { runCatching { Sub.fileUrl(it.second) }.getOrNull() } ?: "")
                .put("roles", JSONObject().apply { Sub.roles.forEach { (d, rn) -> put(d, JSONArray().put(rn.first).put(rn.second)) } })
                .put("uban", Lic.banned(c))
                .put("adm", Msg.admPw(c) != null).put("admMe", Msg.admMe(c) ?: JSONObject()).toString()
        }

        @JavascriptInterface fun servers(): String {
            val a = JSONArray()
            Sub.list.forEach { s -> a.put(JSONObject().put("key", s.key).put("flag", s.flag).put("country", s.country).put("title", s.title).put("proto", s.proto).put("game", s.game)) }
            val p = JSONObject(); State.pings.forEach { (k, v) -> p.put(k, v) }
            return JSONObject().put("list", a).put("pings", p).toString()
        }

        @JavascriptInterface fun take(): String = Msg.take(this@Main).toString()
        @JavascriptInterface fun toggle() = ui { when (State.now) { State.ON, State.WAIT -> startService(Intent(this@Main, Svc::class.java).setAction(Svc.STOP)); else -> connect() } }
        @JavascriptInterface fun connect() = ui { if (State.now == State.ON || State.now == State.WAIT) startVpn() else this@Main.connect() }
        @JavascriptInterface fun select(key: String) {
            val s = Sub.list.firstOrNull { it.key == key }
            if (State.selected(this@Main)?.key == s?.key) return
            State.select(this@Main, s)
            ui { if (State.now == State.ON || State.now == State.WAIT) startVpn() }
        }
        @JavascriptInterface fun test() = measure()
        @JavascriptInterface fun lang(l: String) { if (l in Lang.codes) Lang.set(this@Main, l) }
        @JavascriptInterface fun snd(on: Boolean) = Snd.setOn(this@Main, on)
        @JavascriptInterface fun tap() = Snd.play(this@Main, R.raw.tap, 0.4f)
        @JavascriptInterface fun refresh() = Thread {
            val ok = Sub.refresh(this@Main)
            State.pings.clear(); push(JSONObject().put("k", "srv").put("ok", ok).put("manual", true))
        }.start()
        @JavascriptInterface fun update() = ui { if (Upd.available(Msg.ver(this@Main)) != null) askUpdate(false) else toast(t("Iň täze wersiýa gurnalan", "Установлена последняя версия", "En yeni sürüm kurulu")) }
        @JavascriptInterface fun tile() = ui { addTile() }
        @JavascriptInterface fun key(raw: String) = Thread { push(JSONObject().put("k", "key").put("r", checkKey(raw))) }.start()
        @JavascriptInterface fun send(json: String) { runCatching { Msg.send(this@Main, JSONObject(json)) } }
        // 1.16: profil, hususy habarlar, Global chat suraty
        @JavascriptInterface fun profile(json: String) { runCatching { Chat.profile(this@Main, JSONObject(json)) } }
        @JavascriptInterface fun prof(dev: String) = Chat.prof(dev)
        @JavascriptInterface fun dmSend(peer: String, json: String, nick: String) { runCatching { Chat.send(this@Main, peer, JSONObject(json), nick) } }
        @JavascriptInterface fun dmOpen(peer: String) = Chat.open(this@Main, peer)
        @JavascriptInterface fun dmWatch(peer: String) { Chat.watch = peer.ifEmpty { null }; Msg.kick() }
        @JavascriptInterface fun dmPage(on: Boolean) { Msg.dmPage = on; if (on) Msg.kick() }
        @JavascriptInterface fun dmSt(peer: String, st: String) = Chat.setSt(this@Main, peer, st)
        @JavascriptInterface fun dmList(): String = Chat.list(this@Main).toString()
        @JavascriptInterface fun gsend2(json: String) { runCatching { Chat.gsend(this@Main, JSONObject(json)) } }
        @JavascriptInterface fun img(kind: String, id: String) = Chat.img(kind, id)
        @JavascriptInterface fun adm(json: String) { runCatching { Msg.adm(this@Main, JSONObject(json)) } }
        @JavascriptInterface fun gsend(nick: String, text: String) = Msg.gsend(this@Main, nick, text)
        @JavascriptInterface fun gwatch(on: Boolean) { Msg.watchG = on; if (on) Msg.kick() }
        @JavascriptInterface fun photo(d: String) = Msg.photo(this@Main, d)
        @JavascriptInterface fun getPhoto(dev: String) = Msg.getPhoto(dev)
        @JavascriptInterface fun diag() = Thread { push(JSONObject().put("k", "diag").put("r", Msg.diag())) }.start()
        @JavascriptInterface fun copy(t: String) = ui { runCatching { getSystemService(ClipboardManager::class.java).setPrimaryClip(ClipData.newPlainText("Türkmen VPN", t)) } }
        @JavascriptInterface fun share(t: String) = ui { runCatching { startActivity(Intent.createChooser(Intent(Intent.ACTION_SEND).setType("text/plain").putExtra(Intent.EXTRA_TEXT, t), null)) } }
        @JavascriptInterface fun open(url: String) = ui { if (url.startsWith("https://") || url.startsWith("http://")) runCatching { startActivity(Intent(Intent.ACTION_VIEW, Uri.parse(url))) } }
        @JavascriptInterface fun mail(to: String) = ui { runCatching { startActivity(Intent(Intent.ACTION_SENDTO, Uri.parse("mailto:$to"))) } }
        @JavascriptInterface fun toast(t: String) = ui { Toast.makeText(this@Main, t, Toast.LENGTH_SHORT).show() }
    }

    // ---------- açar ----------
    /** "ok" / "used" / "bad". Täze açar kabul edilse bot hem habarly bolýar (1 açar = 1 telefon). */
    private fun checkKey(raw: String): String {
        val k = Lic.norm(raw)
        if (k.length != 14) return "bad"
        var st = Lic.status(this, k)
        if (st == "bad") { Sub.refresh(this); st = Lic.status(this, k) }
        if (st == "ok") {
            val first = Lic.saved(this) != k
            Lic.save(this, k)
            if (first || Msg.dev(this) !in Lic.devs(Lic.hash(k))) Msg.send(this, JSONObject().put("k", "ka").put("h", Lic.hash(k)))
        }
        return st
    }

    // ---------- bağlan ----------
    private fun connect() {
        if (Upd.busy(this)) { toast(t("Täze wersiýa ýüklenýär, gutarýança garaşyň", "Идёт загрузка новой версии, подождите", "Yeni sürüm iniyor, bitene kadar bekleyin")); return }
        if (Upd.available(Msg.ver(this)) != null) { askUpdate(true); return }   // zorunlu güncelleme
        val i = VpnService.prepare(this)
        if (i != null) startActivityForResult(i, 1) else startVpn()
    }

    private fun startVpn() {
        fromApp = true
        val i = Intent(this, Svc::class.java)
        if (Build.VERSION.SDK_INT >= 26) startForegroundService(i) else startService(i)
    }

    private fun measure() {
        if (testing) return
        val list = Sub.list.toList()
        if (list.isEmpty()) return
        testing = true; State.pings.clear(); push(JSONObject().put("k", "srv"))
        val pool = Executors.newFixedThreadPool(4)
        var left = list.size
        for (s in list) pool.execute {
            State.ping(s)
            synchronized(this) {
                left--
                if (left == 0) {
                    testing = false; pool.shutdown(); State.pingAt = System.currentTimeMillis()
                    if (State.pings.values.none { it > 0 }) Thread { val on = State.online(this); ui { info(if (on) noCodes() else noNet()) } }.start()
                }
            }
            push(JSONObject().put("k", "srv"))
        }
    }

    private fun addTile() {
        if (Build.VERSION.SDK_INT >= 33) {
            val sbm = getSystemService(StatusBarManager::class.java)
            sbm.requestAddTileService(ComponentName(this, Tile::class.java), getString(R.string.app_name), Icon.createWithResource(this, R.drawable.ic_tile), mainExecutor) { r ->
                toast(if (r == StatusBarManager.TILE_ADD_REQUEST_RESULT_TILE_ADDED || r == StatusBarManager.TILE_ADD_REQUEST_RESULT_TILE_ALREADY_ADDED)
                    t("Bildiriş paneline goşuldy", "Добавлено в шторку", "Bildirim paneline eklendi") else t("Goşulmady", "Не добавлено", "Eklenmedi"))
            }
        } else info(t("Bildiriş panelini aşak çekiň → ✏️ → «Türkmen VPN» düwmesini ýokaryk süýşüriň.", "Опустите шторку → ✏️ → перетащите «Türkmen VPN» наверх.", "Bildirim panelini aşağı çekin → ✏️ → «Türkmen VPN» düğmesini yukarı taşıyın."))
    }

    // ---------- täzelenme ----------
    private fun askUpdate(vpn: Boolean) {
        val u = Upd.available(Msg.ver(this)) ?: return
        Upd.clean(this, Msg.ver(this), u.first)
        if (Upd.ready(this, u.first)) { installHint(); Upd.install(this, u.first); return }
        if (Upd.busy(this)) { toast(t("Täze wersiýa ýüklenýär, garaşyň", "Новая версия загружается, подождите", "Yeni sürüm iniyor, bekleyin")); return }
        val msg = if (vpn) t("VPN-i işletmek üçin VPN-iň täze wersiýasyny ýüklemeli! Size täze wersiýany ýükläýinmi?",
            "Чтобы пользоваться VPN, нужно загрузить новую версию! Загрузить новую версию?",
            "VPN'i kullanmak için yeni sürümü indirmelisiniz! Yeni sürüm indirilsin mi?")
        else t("Täze wersiýa ${u.first} bar. Ýükläýinmi?", "Доступна версия ${u.first}. Загрузить?", "Yeni sürüm ${u.first} var. İndirilsin mi?")
        ask(msg, t("Hawa", "Да", "Evet"), t("Ýok", "Нет", "Hayır")) { startUpdate(u) }
    }

    private fun startUpdate(u: Pair<String, String>) {
        if (State.now == State.ON || State.now == State.WAIT) startService(Intent(this, Svc::class.java).setAction(Svc.STOP))
        slowShown = false
        if (!Upd.start(this, u.first, u.second))
            toast(t("Ýüklenýär. Programmadan çyksaňyz hem dowam eder", "Загрузка продолжится даже если закрыть программу", "İndiriliyor. Uygulamadan çıksanız da devam eder"))
    }

    private var lastDl = -1
    private fun watchDownload() {
        val q = Upd.query(this) ?: return
        if (q.status != lastDl) {
            val was = lastDl; lastDl = q.status
            if (was != -1 && q.status == DownloadManager.STATUS_SUCCESSFUL) { installHint(); Upd.install(this) }
            push(JSONObject().put("k", "dl").put("st", q.status))
            if (q.status == DownloadManager.STATUS_FAILED) { getSharedPreferences("p", 0).edit().remove("dl").apply(); info(Upd.errText(this, q.reason)) }
        }
        if (q.status == DownloadManager.STATUS_PAUSED && !slowShown && System.currentTimeMillis() - getSharedPreferences("p", 0).getLong("dlAt", 0) > 40_000) {
            slowShown = true; info(Upd.errText(this, 0))
        }
    }

    private fun installHint() {
        if (Build.VERSION.SDK_INT >= 29) toast(t("Gurnalmasa: faýl dolandyryjyda «Download» bukjasyndaky TurkmenVPN faýlyny açyň",
            "Если не установится: откройте файл TurkmenVPN в папке «Download» через файловый менеджер",
            "Kurulmazsa: dosya yöneticisinde «Download» klasöründeki TurkmenVPN dosyasını açın"))
    }

    // ---------- mahabat ----------
    private fun loadAd() {
        val ad = Sub.ad ?: return
        val f = File(cacheDir, "ad_${ad.first}")
        if (!f.exists()) runCatching {
            val c = URL(Sub.fileUrl(ad.first)).openConnection() as HttpURLConnection
            c.connectTimeout = 8000; c.readTimeout = 15000
            val tmp = File(cacheDir, "ad_tmp")
            if (c.responseCode == 200) { c.inputStream.use { i -> tmp.outputStream().use { i.copyTo(it) } }; tmp.renameTo(f) }
            c.disconnect()
        }
        if (f.exists() && f.length() > 0) push(JSONObject().put("k", "ad").put("link", ad.second).put("id", ad.first))
    }

    // ---------- kömekçiler ----------
    private fun noCodes() = t("Kodlar täzelenýär, takmynan 3-5 minut aralygynda işlär.",
        "Коды обновляются, заработают примерно через 3-5 минут.",
        "Kodlar yenileniyor, yaklaşık 3-5 dakika içinde çalışır.")
    private fun noNet() = t("Internetiňiz ýok. Telefonyň internetini (Wi-Fi ýa-da mobil internet) barlaň.",
        "Нет интернета. Проверьте Wi-Fi или мобильный интернет.", "İnternetiniz yok. Wi-Fi'yi ya da mobil veriyi kontrol edin.")
    private fun toast(s: String) = Toast.makeText(this, s, Toast.LENGTH_LONG).show()
    private fun info(msg: String) = ask(msg, "OK", null) {}
    private fun ask(msg: String, yes: String, no: String?, onYes: () -> Unit) {
        if (isFinishing || isDestroyed) return
        val b = AlertDialog.Builder(this).setMessage(msg).setPositiveButton(yes) { _, _ -> onYes() }
        if (no != null) b.setNegativeButton(no, null)
        b.show()
    }
    private fun ui(f: () -> Unit) = runOnUiThread { if (!isDestroyed) f() }

    companion object {
        const val GO = "tm.yol.vpn.GO"
        const val INSTALL = "tm.yol.vpn.INSTALL"
        const val CHAT = "tm.yol.vpn.CHAT"
        const val ADMT = "tm.yol.vpn.ADMT"
        const val HOST = "tvpn.local"
    }
}
