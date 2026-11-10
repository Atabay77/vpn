package tm.yol.vpn

import android.app.Activity
import android.app.AlertDialog
import android.app.StatusBarManager
import android.content.ComponentName
import android.content.Intent
import android.graphics.Color
import android.graphics.Typeface
import android.graphics.drawable.GradientDrawable
import android.graphics.drawable.Icon
import android.net.TrafficStats
import android.net.VpnService
import android.os.Build
import android.os.Bundle
import android.os.Handler
import android.os.Looper
import android.os.Process
import android.text.InputType
import android.text.TextUtils
import android.view.Gravity
import android.view.View
import android.widget.EditText
import android.widget.FrameLayout
import android.widget.ImageView
import android.widget.LinearLayout
import android.widget.ScrollView
import android.widget.TextView
import android.widget.Toast
import libv2ray.Libv2ray
import java.util.concurrent.Executors

class Main : Activity() {
    private enum class Page { MAIN, SERVERS, SPEED, SETTINGS, INFO }

    private lateinit var root: FrameLayout
    private lateinit var page: FrameLayout          // değişen sayfa (arka plan ve sol menü sabit)
    private lateinit var rail: LinearLayout
    private lateinit var sky: ImageView
    private var skyRes = R.drawable.skyline
    private var cur = Page.MAIN

    // ana sayfa
    private var power: Power? = null
    private var status: TextView? = null
    private var hint: TextView? = null
    private var card: LinearLayout? = null
    private var timer: TextView? = null
    private var timerLbl: TextView? = null
    private var down: TextView? = null
    private var up: TextView? = null
    private var spark: Spark? = null
    private var updBar: TextView? = null
    // hız sayfası
    private var bigDown: TextView? = null
    private var bigUp: TextView? = null
    private var bigSpark: Spark? = null
    private var totals: TextView? = null
    private var pingTv: TextView? = null

    private val ms = HashMap<String, Long>()          // uri → ms (-1 = ulaşılamadı)
    private val msViews = HashMap<String, TextView>() // ölçüm yerinde güncellenir (kaydırma kaymasın)
    private var testing = false
    private var fromApp = false
    private var downloading = false
    private val h = Handler(Looper.getMainLooper())
    private val listener: () -> Unit = { renderState() }
    private val taps = ArrayList<Pair<Int, Long>>()
    private var lastRx = -1L; private var lastTx = -1L
    private var rx0 = -1L; private var tx0 = -1L
    private var pingAt = 0L

    override fun onCreate(b: Bundle?) {
        super.onCreate(b)
        State.app = applicationContext
        Libv2ray.initCoreEnv(filesDir.absolutePath, "")
        window.statusBarColor = Color.TRANSPARENT
        root = FrameLayout(this).apply { setBackgroundColor(C.BG) }
        setContentView(root)
        // sabit katmanlar: canlı video, koyulaştırma, Aşgabat silueti
        root.addView(VideoBg(this, R.raw.bg), FrameLayout.LayoutParams(-1, -1))
        root.addView(View(this).apply { setBackgroundColor(0x660A1C14) }, FrameLayout.LayoutParams(-1, -1))
        sky = ImageView(this).apply {
            setImageResource(R.drawable.skyline); scaleType = ImageView.ScaleType.CENTER_CROP; alpha = 0.95f
            importantForAccessibility = View.IMPORTANT_FOR_ACCESSIBILITY_NO
        }
        root.addView(sky, FrameLayout.LayoutParams(-1, dpi(175), Gravity.BOTTOM))
        page = FrameLayout(this)
        root.addView(page, FrameLayout.LayoutParams(-1, -1))
        rail = buildRail()
        root.addView(rail, FrameLayout.LayoutParams(dpi(46), -2).apply { leftMargin = dpi(10); topMargin = dpi(112) })
        Sub.load(this)
        show(Page.MAIN)
        if (Build.VERSION.SDK_INT >= 33) requestPermissions(arrayOf("android.permission.POST_NOTIFICATIONS"), 2)
        bg { Sub.refresh(this); ui { show(cur) } }   // açılışta liste, key ve sürüm bilgisi
        handle(intent)
    }

    override fun onNewIntent(i: Intent) { super.onNewIntent(i); handle(i) }

    private fun handle(i: Intent?) {
        if (i == null) return
        if (Upd.onResult(this, i)) return
        if (i.action == GO && State.now != State.ON && State.now != State.WAIT) connect()
    }

    override fun onStart() {
        super.onStart(); State.subs += listener; renderState()
        h.removeCallbacks(tick); h.post(tick)
    }

    override fun onStop() {
        State.subs -= listener; h.removeCallbacks(tick)
        if (fromApp && State.now == State.WAIT) startService(Intent(this, Svc::class.java).setAction(Svc.STOP))   // bağlanırken çıkılırsa iptal
        fromApp = false
        super.onStop()
    }

    @Deprecated("Activity API")
    override fun onBackPressed() { if (cur != Page.MAIN) show(Page.MAIN) else super.onBackPressed() }

    // ---------- sol menü ----------
    private val railItems = listOf("home" to Page.MAIN, "globe" to Page.SERVERS, "gauge" to Page.SPEED, "gear" to Page.SETTINGS, "info" to Page.INFO)
    private val railBtns = ArrayList<Pair<FrameLayout, Ico>>()

    private fun buildRail(): LinearLayout {
        val r = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL; gravity = Gravity.CENTER_HORIZONTAL
            setPadding(0, dpi(8), 0, dpi(8))
            background = glass(23f, Color.argb(120, 224, 176, 74))
        }
        railItems.forEachIndexed { i, (icon, pg) ->
            if (i > 0) r.addView(GulSep(this), LinearLayout.LayoutParams(dpi(20), dpi(22)))
            val ic = Ico(this, icon, C.GOLD, 20f, 1.7f)
            val b = FrameLayout(this).apply {
                background = GradientDrawable().apply { shape = GradientDrawable.OVAL; setColor(Color.argb(90, 10, 28, 20)); setStroke(dpi(1), C.GOLD) }
                contentDescription = when (pg) { Page.MAIN -> "Baş sahypa"; Page.SERVERS -> "Serwerler"; Page.SPEED -> "Tizlik"; Page.SETTINGS -> "Sazlamalar"; Page.INFO -> "Maglumat" }
                addView(ic, FrameLayout.LayoutParams(-2, -2, Gravity.CENTER))
                setOnClickListener { secret(i); show(pg) }
            }
            railBtns += b to ic
            r.addView(b, LinearLayout.LayoutParams(dpi(36), dpi(36)))
        }
        return r
    }

    private fun paintRail() {
        railBtns.forEachIndexed { i, (b, ic) ->
            val on = railItems[i].second == cur
            (b.background as GradientDrawable).apply {
                setColor(if (on) Color.argb(160, 18, 120, 74) else Color.argb(90, 10, 28, 20))
                setStroke(dpi(1), if (on) C.GREEN else C.GOLD)
            }
            ic.color = if (on) C.GREEN else C.GOLD; ic.invalidate()
        }
    }

    // gizli key bölümü: ilk buton 1 kez → son buton 2 kez → ilk buton 1 kez (6 sn içinde)
    private fun secret(i: Int) {
        val now = System.currentTimeMillis()
        taps.add(i to now); taps.removeAll { now - it.second > 6000 }
        while (taps.size > 4) taps.removeAt(0)
        if (taps.map { it.first } == listOf(0, 4, 4, 0)) { taps.clear(); h.post { keyDialog() } }
    }

    // ---------- sayfalar ----------
    private fun show(p: Page) {
        cur = p
        page.removeAllViews(); msViews.clear()
        power = null; status = null; hint = null; card = null; timer = null; down = null; up = null; spark = null; updBar = null
        bigDown = null; bigUp = null; bigSpark = null; totals = null; pingTv = null
        val v = when (p) {
            Page.MAIN -> mainPage(); Page.SERVERS -> serversPage(); Page.SPEED -> speedPage()
            Page.SETTINGS -> settingsPage(); Page.INFO -> infoPage()
        }
        page.addView(v, FrameLayout.LayoutParams(-1, -1))
        paintRail(); renderState()
    }

    /** Sağ taraf: sol menü kadar boşluk bırakılır. */
    private fun content() = LinearLayout(this).apply {
        orientation = LinearLayout.VERTICAL
        setPadding(dpi(66), dpi(34), dpi(16), dpi(18))
    }

    private fun mainPage(): View {
        val col = content()
        updBar = text("", 14f, C.BG, true).apply {
            gravity = Gravity.CENTER; setPadding(dpi(12), dpi(9), dpi(12), dpi(9))
            background = box(C.GOLD, C.GOLD, 14f); visibility = View.GONE
            setOnClickListener { update() }
        }
        col.addView(updBar, LinearLayout.LayoutParams(-1, -2).apply { bottomMargin = dpi(10) })
        col.addView(header(), LinearLayout.LayoutParams(-1, dpi(72)))

        val mid = LinearLayout(this).apply { orientation = LinearLayout.VERTICAL; gravity = Gravity.CENTER }
        power = Power(this).apply { isClickable = true; setOnClickListener { toggle() } }
        mid.addView(power)
        status = text("", 21f, C.TEXT, true).apply { gravity = Gravity.CENTER; setPadding(0, dpi(10), 0, dpi(2)) }
        hint = text("", 13f, C.MUTED).apply { gravity = Gravity.CENTER }
        mid.addView(status, LinearLayout.LayoutParams(-1, -2)); mid.addView(hint, LinearLayout.LayoutParams(-1, -2))
        col.addView(mid, LinearLayout.LayoutParams(-1, 0, 1f))

        val row = LinearLayout(this).apply { orientation = LinearLayout.HORIZONTAL }
        val tbox = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL; gravity = Gravity.CENTER
            background = glass(16f)
        }
        timerLbl = text("GALAN WAGT", 10f, C.MUTED, true).apply { letterSpacing = 0.2f }
        timer = text("--:--:--", 26f, C.GOLD, true).apply { typeface = Typeface.create(Typeface.MONOSPACE, Typeface.BOLD) }
        tbox.addView(timerLbl); tbox.addView(timer)
        row.addView(tbox, LinearLayout.LayoutParams(0, dpi(92), 1f).apply { rightMargin = dpi(10) })
        val sbox = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL; setPadding(dpi(12), dpi(10), dpi(12), dpi(10))
            background = glass(16f, Color.argb(120, 111, 219, 156))
        }
        val sv = LinearLayout(this).apply { orientation = LinearLayout.HORIZONTAL; gravity = Gravity.CENTER_VERTICAL }
        down = mono("↓ 0 B/s", 12f, C.GREEN); up = mono("↑ 0 B/s", 12f, C.GREEN).apply { gravity = Gravity.END }
        sv.addView(down, LinearLayout.LayoutParams(0, -2, 1f)); sv.addView(up, LinearLayout.LayoutParams(0, -2, 1f))
        sbox.addView(sv)
        spark = Spark(this)
        sbox.addView(spark, LinearLayout.LayoutParams(-1, 0, 1f).apply { topMargin = dpi(6) })
        row.addView(sbox, LinearLayout.LayoutParams(0, dpi(92), 1.25f))
        col.addView(row, LinearLayout.LayoutParams(-1, -2).apply { bottomMargin = dpi(12) })

        card = LinearLayout(this).apply {
            orientation = LinearLayout.HORIZONTAL; gravity = Gravity.CENTER_VERTICAL
            setPadding(dpi(14), dpi(12), dpi(14), dpi(12))
            background = glass(18f)
            setOnClickListener { show(Page.SERVERS) }
        }
        col.addView(card, LinearLayout.LayoutParams(-1, dpi(76)).apply { bottomMargin = dpi(120) })   // altında Aşgabat silueti
        return col
    }

    private fun header() = LinearLayout(this).apply {
        orientation = LinearLayout.HORIZONTAL; gravity = Gravity.CENTER_VERTICAL
        setPadding(dpi(10), 0, dpi(16), 0)
        background = glass(18f, Color.argb(170, 224, 176, 74))
        addView(ImageView(this@Main).apply {
            setImageResource(R.drawable.logo); clipToOutline = true; background = box(C.BG, C.GOLD, 12f)
            importantForAccessibility = View.IMPORTANT_FOR_ACCESSIBILITY_NO
        }, LinearLayout.LayoutParams(dpi(50), dpi(50)))
        addView(View(this@Main).apply { setBackgroundColor(Color.argb(150, 224, 176, 74)) },
            LinearLayout.LayoutParams(dpi(1), dpi(38)).apply { leftMargin = dpi(12); rightMargin = dpi(12) })
        val t = LinearLayout(this@Main).apply { orientation = LinearLayout.VERTICAL }
        t.addView(text(getString(R.string.app_name).uppercase(), 19f, C.TEXT, true).apply { letterSpacing = 0.16f; oneLine() })
        t.addView(text("Türkmenistan üçin", 12f, C.MUTED).apply { letterSpacing = 0.05f })
        addView(t, LinearLayout.LayoutParams(0, -2, 1f))
    }

    private fun title(t: String, sub: String?, vararg right: View): View {
        val r = LinearLayout(this).apply { orientation = LinearLayout.HORIZONTAL; gravity = Gravity.CENTER_VERTICAL; setPadding(dpi(4), 0, 0, dpi(12)) }
        val tt = LinearLayout(this).apply { orientation = LinearLayout.VERTICAL }
        tt.addView(text(t.uppercase(), 18f, C.TEXT, true).apply { letterSpacing = 0.14f })
        if (sub != null) tt.addView(text(sub, 12f, C.MUTED))
        r.addView(tt, LinearLayout.LayoutParams(0, -2, 1f))
        right.forEach { r.addView(it, LinearLayout.LayoutParams(-2, dpi(42)).apply { leftMargin = dpi(8) }) }
        return r
    }

    private fun serversPage(): View {
        val col = content()
        val test = LinearLayout(this).apply {
            orientation = LinearLayout.HORIZONTAL; gravity = Gravity.CENTER
            setPadding(dpi(12), 0, dpi(14), 0); background = glass(14f, C.GOLD)
            contentDescription = "Tizligi barla"
            addView(Ico(this@Main, "gauge", C.GOLD, 18f))
            addView(text("Barla", 14f, C.GOLD, true).apply { setPadding(dpi(6), 0, 0, 0) })
            setOnClickListener { measure() }
        }
        col.addView(title("Serwerler", "${Sub.list.size} serwer", iconBtn("refresh", C.GOLD, "Serwerleri täzele") { refresh() }, test))
        val list = LinearLayout(this).apply { orientation = LinearLayout.VERTICAL; setPadding(0, 0, 0, dpi(140)) }
        val sel = State.selected(this)
        if (Sub.list.isNotEmpty()) list.addView(autoRow(sel == null))
        for (s in Sub.list.filter { !it.game }) list.addView(row(s, s === sel))
        val games = Sub.list.filter { it.game }
        if (games.isNotEmpty()) {
            list.addView(text("OÝUNLAR ÜÇIN", 13f, C.GOLD, true).apply { letterSpacing = 0.15f; setPadding(dpi(4), dpi(12), 0, dpi(10)) })
            for (s in games) list.addView(row(s, s === sel))
        }
        if (Sub.list.isEmpty()) list.addView(text("Serwer ýok. Täzelemek üçin ýokardaky düwmä basyň.", 14f, C.MUTED))
        col.addView(ScrollView(this).apply { addView(list); isVerticalScrollBarEnabled = false }, LinearLayout.LayoutParams(-1, 0, 1f))
        return col
    }

    private fun speedPage(): View {
        val col = content()
        col.addView(title("Tizlik", "Häzirki internet akymy"))
        val b = LinearLayout(this).apply { orientation = LinearLayout.VERTICAL; setPadding(dpi(16), dpi(16), dpi(16), dpi(16)); background = glass(18f, Color.argb(130, 111, 219, 156)) }
        val r = LinearLayout(this).apply { orientation = LinearLayout.HORIZONTAL }
        fun cell(lbl: String, tv: TextView) = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            addView(text(lbl, 10f, C.MUTED, true).apply { letterSpacing = 0.2f }); addView(tv)
        }
        bigDown = mono("0 B/s", 22f, C.GREEN); bigUp = mono("0 B/s", 22f, C.GOLD)
        r.addView(cell("↓ ÝÜKLEME", bigDown!!), LinearLayout.LayoutParams(0, -2, 1f))
        r.addView(cell("↑ IBERME", bigUp!!), LinearLayout.LayoutParams(0, -2, 1f))
        b.addView(r)
        bigSpark = Spark(this)
        b.addView(bigSpark, LinearLayout.LayoutParams(-1, dpi(140)).apply { topMargin = dpi(12) })
        col.addView(b)
        val g = LinearLayout(this).apply { orientation = LinearLayout.HORIZONTAL }
        val pb = LinearLayout(this).apply { orientation = LinearLayout.VERTICAL; gravity = Gravity.CENTER; background = glass(16f) }
        pb.addView(text("PING", 10f, C.MUTED, true).apply { letterSpacing = 0.2f })
        pingTv = mono("—", 22f, C.GOLD); pb.addView(pingTv)
        g.addView(pb, LinearLayout.LayoutParams(0, dpi(84), 1f).apply { rightMargin = dpi(10) })
        val tb = LinearLayout(this).apply { orientation = LinearLayout.VERTICAL; gravity = Gravity.CENTER; background = glass(16f) }
        tb.addView(text("JEMI", 10f, C.MUTED, true).apply { letterSpacing = 0.2f })
        totals = mono("—", 15f, C.TEXT); tb.addView(totals)
        g.addView(tb, LinearLayout.LayoutParams(0, dpi(84), 1.3f))
        col.addView(g, LinearLayout.LayoutParams(-1, -2).apply { topMargin = dpi(12) })
        return col
    }

    private fun settingsPage(): View {
        val col = content()
        col.addView(title("Sazlamalar", null))
        col.addView(option("refresh", "Serwerleri täzele", "Abunany häzir täzeden al") { refresh() })
        col.addView(option("info", "Täze wersiýa", "Häzirki wersiýa ${ver()}") {
            bg { Sub.refresh(this); ui { if (Upd.available(ver()) != null) update() else Toast.makeText(this, "Iň täze wersiýa gurnalan", Toast.LENGTH_SHORT).show() } }
        })
        if (Build.VERSION.SDK_INT >= 33) col.addView(option("home", "Bildiriş paneline goş", "Ýokarky panelde Aç/Ýap düwmesi") {
            runCatching {
                getSystemService(StatusBarManager::class.java).requestAddTileService(
                    ComponentName(this, Tile::class.java), getString(R.string.app_name),
                    Icon.createWithResource(this, R.drawable.ic_tile), mainExecutor) { }
            }
        })
        return col
    }

    private fun infoPage(): View {
        val col = content().apply { gravity = Gravity.CENTER_HORIZONTAL }
        col.addView(title("Maglumat", null), LinearLayout.LayoutParams(-1, -2))
        val b = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL; gravity = Gravity.CENTER_HORIZONTAL
            setPadding(dpi(20), dpi(24), dpi(20), dpi(24)); background = glass(20f)
        }
        b.addView(ImageView(this).apply { setImageResource(R.drawable.logo); clipToOutline = true; background = box(C.BG, C.GOLD, 22f) },
            LinearLayout.LayoutParams(dpi(110), dpi(110)))
        b.addView(text(getString(R.string.app_name).uppercase(), 20f, C.TEXT, true).apply { letterSpacing = 0.16f; setPadding(0, dpi(14), 0, dpi(2)) })
        b.addView(text("Wersiýa ${ver()}", 13f, C.MUTED))
        b.addView(text("Türkmenistan üçin çalt we howpsuz VPN.\nHysteria2 · Shadowsocks · VLESS", 13f, C.MUTED).apply { gravity = Gravity.CENTER; setPadding(0, dpi(14), 0, 0) })
        col.addView(b, LinearLayout.LayoutParams(-1, -2))
        return col
    }

    private fun option(icon: String, t: String, sub: String, on: () -> Unit) = LinearLayout(this).apply {
        orientation = LinearLayout.HORIZONTAL; gravity = Gravity.CENTER_VERTICAL
        setPadding(dpi(14), dpi(12), dpi(14), dpi(12)); minimumHeight = dpi(64); background = glass(16f)
        addView(Ico(this@Main, icon, C.GOLD, 22f, 1.7f))
        val tt = LinearLayout(this@Main).apply { orientation = LinearLayout.VERTICAL; setPadding(dpi(12), 0, 0, 0) }
        tt.addView(text(t, 15f, C.TEXT, true)); tt.addView(text(sub, 12f, C.MUTED))
        addView(tt, LinearLayout.LayoutParams(0, -2, 1f))
        addView(Ico(this@Main, "next", C.MUTED, 18f))
        setOnClickListener { on() }
        layoutParams = LinearLayout.LayoutParams(-1, -2).apply { bottomMargin = dpi(10) }
    }

    // ---------- durum ----------
    private fun fillCard() {
        val card = card ?: return
        card.removeAllViews()
        val s = State.selected(this)
        val a = State.active.takeIf { State.now == State.ON }
        val t = LinearLayout(this).apply { orientation = LinearLayout.VERTICAL }
        val (f, c1, c2) = when {
            Sub.list.isEmpty() -> Triple("🌐", "Serwer ýok", "Täzelemek üçin basyň")
            s == null -> Triple(a?.flag ?: "⚡", "Awtomatik", if (a != null) "${a.country} · ${sub(a)}" else "Iň çalt serwer")
            else -> Triple(s.flag, s.country, sub(s))
        }
        card.addView(flag(f, C.GOLD))
        card.addView(View(this).apply { setBackgroundColor(Color.argb(150, 224, 176, 74)) },
            LinearLayout.LayoutParams(dpi(1), dpi(34)).apply { leftMargin = dpi(12); rightMargin = dpi(12) })
        t.addView(text(c1, 16f, C.TEXT, true)); t.addView(text(c2, 12f, C.MUTED).apply { oneLine() })
        card.addView(t, LinearLayout.LayoutParams(0, -2, 1f))
        card.addView(Ico(this, "next", C.GOLD, 18f))
    }

    private fun renderState() {
        val st = State.now
        power?.let { it.on = st == State.ON; it.busy = st == State.WAIT; it.contentDescription = if (st == State.ON) "VPN-i öçür" else "VPN-e birik" }
        status?.let { s ->
            val (a, col, b) = when (st) {
                State.ON -> Triple("Birikdirildi", C.GREEN, "Öçürmek üçin düwmä basyň")
                State.WAIT -> Triple("Birikdirilýär…", C.GOLD, "Garaşyň")
                State.FAIL -> Triple("Birikmedi", C.BAD, "Başga serwer saýlaň ýa-da gaýtadan synanyşyň")
                else -> Triple("Birikdirilmedik", C.TEXT, "Birikmek üçin düwmä basyň")
            }
            s.text = a; s.setTextColor(col); hint?.text = b
        }
        if (st != State.ON) { spark?.clear(); bigSpark?.clear(); lastRx = -1; rx0 = -1 }
        fillCard(); renderUpd(); paintSky(); tick.run()
    }

    // alttaki manzara: bağlı (ya da seçili) sunucunun ülkesi; yoksa Aşgabat
    private val skies = mapOf("FR" to R.drawable.sky_fr, "GB" to R.drawable.sky_gb, "DE" to R.drawable.sky_de, "NL" to R.drawable.sky_nl,
        "FI" to R.drawable.sky_fi, "RU" to R.drawable.sky_ru, "CH" to R.drawable.sky_ch, "PL" to R.drawable.sky_pl,
        "TR" to R.drawable.sky_tr, "SE" to R.drawable.sky_se, "US" to R.drawable.sky_us)

    private fun cc(flag: String): String = flag.codePoints().toArray().filter { it in 0x1F1E6..0x1F1FF }
        .joinToString("") { (it - 0x1F1E6 + 'A'.code).toChar().toString() }

    private fun paintSky() {
        if (!::sky.isInitialized) return
        val s = State.active.takeIf { State.now == State.ON } ?: State.selected(this)
        val res = s?.let { skies[cc(it.flag)] } ?: R.drawable.skyline
        if (res == skyRes) return
        skyRes = res
        sky.animate().alpha(0f).setDuration(220).withEndAction {
            sky.setImageResource(res); sky.animate().alpha(0.95f).setDuration(380).start()
        }.start()
    }

    private val tick = object : Runnable {
        override fun run() {
            h.removeCallbacks(this)
            val on = State.now == State.ON
            timer?.let { t ->
                if (!on) { timerLbl?.text = "GALAN WAGT"; t.text = "--:--:--"; t.setTextColor(C.GOLD) }
                else {
                    val left = Lic.left(this@Main)
                    if (left == null) {
                        timerLbl?.text = "KEY"
                        val e = Lic.exp(this@Main) ?: 0L
                        t.text = if (e == 0L) "ÇÄKSIZ" else ((e - System.currentTimeMillis()) / 1000).let { d -> "%dg %02d:%02d".format(d / 86400, d % 86400 / 3600, d % 3600 / 60) }
                        t.setTextColor(C.GOLD)
                    } else {
                        timerLbl?.text = "GALAN WAGT"
                        val sec = left / 1000
                        t.text = "%02d:%02d:%02d".format(sec / 3600, sec % 3600 / 60, sec % 60)
                        t.setTextColor(if (sec < 600) C.BAD else C.GOLD)
                    }
                }
            }
            if (on) {
                val uid = Process.myUid()
                val rx = TrafficStats.getUidRxBytes(uid); val tx = TrafficStats.getUidTxBytes(uid)
                if (rx0 < 0) { rx0 = rx; tx0 = tx }
                if (lastRx >= 0 && rx >= lastRx) {
                    val d = rx - lastRx; val u = tx - lastTx
                    down?.text = "↓ " + rate(d); up?.text = "↑ " + rate(u)
                    bigDown?.text = rate(d); bigUp?.text = rate(u)
                    spark?.add(d.toFloat()); bigSpark?.add(d.toFloat())
                    totals?.text = "↓ ${size(rx - rx0)}\n↑ ${size(tx - tx0)}"
                }
                lastRx = rx; lastTx = tx
                if (pingTv != null && System.currentTimeMillis() - pingAt > 5000) {
                    pingAt = System.currentTimeMillis()
                    bg { val v = runCatching { State.core?.measureDelay(State.PING) ?: -1L }.getOrDefault(-1L); ui { pingTv?.text = if (v > 0) "$v ms" else "—" } }
                }
            } else {
                down?.text = "↓ 0 B/s"; up?.text = "↑ 0 B/s"
                bigDown?.text = "0 B/s"; bigUp?.text = "0 B/s"; pingTv?.text = "—"
                totals?.text = "VPN öçük"
            }
            h.postDelayed(this, 1000)
        }
    }

    private fun rate(b: Long) = when {
        b >= 1024 * 1024 -> "%.1f MB/s".format(b / 1048576f)
        b >= 1024 -> "%.0f KB/s".format(b / 1024f)
        else -> "$b B/s"
    }
    private fun size(b: Long) = when {
        b >= 1024L * 1024 * 1024 -> "%.2f GB".format(b / 1073741824f)
        b >= 1024 * 1024 -> "%.1f MB".format(b / 1048576f)
        else -> "%.0f KB".format(b / 1024f)
    }

    // ---------- güncelleme ----------
    private fun ver(): String = runCatching { packageManager.getPackageInfo(packageName, 0).versionName }.getOrNull() ?: "0"

    private fun renderUpd() {
        val bar = updBar ?: return
        if (downloading) return
        val u = Upd.available(ver())
        bar.visibility = if (u != null) View.VISIBLE else View.GONE
        if (u != null) bar.text = "⬆  Täze wersiýa ${u.first} · Täzele"
    }

    private fun update() {
        val u = Upd.available(ver()) ?: return
        if (downloading) return
        downloading = true; updBar?.text = "Ýüklenýär… 0%"
        Toast.makeText(this, "Täze wersiýa ýüklenýär…", Toast.LENGTH_SHORT).show()
        bg {
            val ok = runCatching { Upd.install(this, u.second) { p -> ui { updBar?.text = "Ýüklenýär… $p%" } } }.isSuccess
            ui {
                downloading = false
                if (!ok) Toast.makeText(this, "Ýüklenmedi, internedi barlaň", Toast.LENGTH_LONG).show()
                renderUpd()
            }
        }
    }

    // ---------- key ----------
    private fun keyDialog() {
        val e = EditText(this).apply {
            hint = "XXXX-XXXX-XXXX"; setSingleLine(); setTextColor(C.GOLD); setHintTextColor(C.MUTED)
            inputType = InputType.TYPE_CLASS_TEXT or InputType.TYPE_TEXT_FLAG_CAP_CHARACTERS or InputType.TYPE_TEXT_FLAG_NO_SUGGESTIONS
            typeface = Typeface.create(Typeface.MONOSPACE, Typeface.BOLD); textSize = 20f; letterSpacing = 0.12f
            gravity = Gravity.CENTER; background = glass(14f, C.GOLD); setPadding(dpi(12), dpi(12), dpi(12), dpi(12))
            Lic.saved(this@Main)?.let { setText(it) }
        }
        val cur = Lic.exp(this)
        val info = when {
            cur == null -> "Açar giriziň"
            cur == 0L -> "Häzirki açar: çäksiz"
            else -> "Häzirki açar: ${(cur - System.currentTimeMillis()) / 86400000} gün galdy"
        }
        val v = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL; gravity = Gravity.CENTER_HORIZONTAL
            setPadding(dpi(22), dpi(22), dpi(22), dpi(18)); background = box(Color.argb(245, 8, 22, 16), C.GOLD, 22f)
        }
        v.addView(Ico(this, "gear", C.GOLD, 30f, 1.6f))
        v.addView(text("AÇAR", 18f, C.TEXT, true).apply { letterSpacing = 0.25f; setPadding(0, dpi(8), 0, dpi(2)) })
        v.addView(text(info, 12f, C.MUTED).apply { setPadding(0, 0, 0, dpi(14)) })
        v.addView(e, LinearLayout.LayoutParams(-1, -2))
        val btn = text("BARLA", 15f, C.BG, true).apply {
            gravity = Gravity.CENTER; letterSpacing = 0.2f; background = box(C.GOLD, C.GOLD, 14f)
        }
        v.addView(btn, LinearLayout.LayoutParams(-1, dpi(48)).apply { topMargin = dpi(14) })
        val d = AlertDialog.Builder(this).setView(v).create()
        d.window?.setBackgroundDrawableResource(android.R.color.transparent)
        btn.setOnClickListener { d.dismiss(); checkKey(e.text.toString()) }
        d.show()
    }

    private fun checkKey(raw: String) {
        val k = Lic.norm(raw)
        if (k.length != 14) { Toast.makeText(this, "Açar nädogry", Toast.LENGTH_SHORT).show(); return }
        val old = Lic.saved(this)
        Lic.save(this, k)
        bg {
            if (Lic.exp(this) == null) Sub.refresh(this)
            val ok = Lic.exp(this) != null
            ui {
                if (!ok) Lic.save(this, old)
                Toast.makeText(this, if (ok) "✅ Açar kabul edildi" else "Açar nädogry ýa-da möhleti geçdi", Toast.LENGTH_LONG).show()
                tick.run()
            }
        }
    }

    // ---------- bağlan ----------
    private fun toggle() {
        when (State.now) {
            State.ON, State.WAIT -> startService(Intent(this, Svc::class.java).setAction(Svc.STOP))
            else -> connect()
        }
    }

    private fun connect() {
        val i = VpnService.prepare(this)
        if (i != null) startActivityForResult(i, 1) else startVpn()
    }

    @Deprecated("Activity API")
    override fun onActivityResult(req: Int, res: Int, data: Intent?) {
        super.onActivityResult(req, res, data)
        if (req == 1 && res == RESULT_OK) startVpn()
    }

    private fun startVpn() {
        fromApp = true
        val i = Intent(this, Svc::class.java)
        if (Build.VERSION.SDK_INT >= 26) startForegroundService(i) else startService(i)
    }

    // ---------- serverler ----------
    private fun msText(m: Long?): Pair<String, Int> = when {
        m == null -> (if (testing) "… ms" else "—") to C.MUTED
        m < 0 -> "×" to C.BAD
        m < 300 -> "$m ms" to C.GREEN
        m < 800 -> "$m ms" to C.GOLD
        else -> "$m ms" to C.BAD
    }

    private fun rowBase(sel: Boolean, on: () -> Unit) = LinearLayout(this).apply {
        orientation = LinearLayout.HORIZONTAL; gravity = Gravity.CENTER_VERTICAL
        setPadding(dpi(12), dpi(10), dpi(12), dpi(10)); minimumHeight = dpi(64)
        background = if (sel) box(Color.argb(170, 18, 70, 44), C.GREEN, 16f, 1.5f) else glass(16f, Color.argb(90, 224, 176, 74))
        setOnClickListener { on() }
        layoutParams = LinearLayout.LayoutParams(-1, -2).apply { bottomMargin = dpi(9) }
    }

    private fun row(s: Server, sel: Boolean): View {
        val r = rowBase(sel) { pick(s) }
        r.addView(flag(s.flag, if (sel) C.GREEN else C.GOLD))
        val t = LinearLayout(this).apply { orientation = LinearLayout.VERTICAL; setPadding(dpi(12), 0, dpi(8), 0) }
        t.addView(text(s.country, 15f, C.TEXT, true)); t.addView(text(sub(s), 12f, C.MUTED).apply { oneLine() })
        r.addView(t, LinearLayout.LayoutParams(0, -2, 1f))
        val (mt, mc) = msText(ms[s.uri])
        val mv = mono(mt, 13f, mc); msViews[s.uri] = mv; r.addView(mv)
        if (sel) r.addView(Ico(this, "check", C.GREEN, 20f, 2.4f).apply { contentDescription = "Saýlanan" },
            LinearLayout.LayoutParams(-2, -2).apply { leftMargin = dpi(8) })
        return r
    }

    private fun autoRow(sel: Boolean): View {
        val r = rowBase(sel) { pick(null) }
        r.addView(flag("⚡", if (sel) C.GREEN else C.GOLD))
        val t = LinearLayout(this).apply { orientation = LinearLayout.VERTICAL; setPadding(dpi(12), 0, dpi(8), 0) }
        t.addView(text("Awtomatik", 15f, C.TEXT, true)); t.addView(text("Iň çalt serwere özi birigýär", 12f, C.MUTED).apply { oneLine() })
        r.addView(t, LinearLayout.LayoutParams(0, -2, 1f))
        if (sel) r.addView(Ico(this, "check", C.GREEN, 20f, 2.4f).apply { contentDescription = "Saýlanan" })
        return r
    }

    private fun pick(s: Server?) {
        State.select(this, s)
        if (State.now == State.ON) startVpn()
        show(Page.MAIN)
    }

    private fun refresh() {
        Toast.makeText(this, "Täzelenýär…", Toast.LENGTH_SHORT).show()
        bg {
            val ok = Sub.refresh(this)
            ui {
                Toast.makeText(this, if (ok) "Täzelendi" else "Täzelenmedi", Toast.LENGTH_SHORT).show()
                ms.clear(); if (cur == Page.SERVERS) show(Page.SERVERS) else renderState()
            }
        }
    }

    private fun paintMs() { for ((uri, v) in msViews) { val (t, c) = msText(ms[uri]); v.text = t; v.setTextColor(c) } }

    private fun measure() {
        if (testing) return
        val items = Sub.list.toList()
        if (items.isEmpty()) return
        testing = true; ms.clear(); paintMs()
        val pool = Executors.newFixedThreadPool(4)
        var left = items.size
        for (s in items) pool.execute {
            val v = runCatching { Libv2ray.measureOutboundDelay(Cfg.full(s.uri, false), State.PING) }.getOrDefault(-1L)
            ui {
                ms[s.uri] = if (v <= 0) -1 else v
                left--
                if (left == 0) { testing = false; pool.shutdown() }
                paintMs()   // liste yeniden kurulmaz: kaydırma yerinde kalır
            }
        }
    }

    // ---------- yardımcılar ----------
    private fun sub(s: Server) = if (s.title.isEmpty()) s.proto else "${s.title} · ${s.proto}"

    private fun text(t: String, sp: Float, color: Int, bold: Boolean = false) = TextView(this).apply {
        text = t; textSize = sp; setTextColor(color)
        if (bold) typeface = Typeface.create(Typeface.DEFAULT, Typeface.BOLD)
    }
    private fun mono(t: String, sp: Float, color: Int) = text(t, sp, color).apply { typeface = Typeface.create(Typeface.MONOSPACE, Typeface.BOLD) }

    private fun TextView.oneLine() { maxLines = 1; ellipsize = TextUtils.TruncateAt.END }

    private fun flag(f: String, border: Int) = TextView(this).apply {
        text = f; textSize = 22f; gravity = Gravity.CENTER
        background = GradientDrawable().apply { shape = GradientDrawable.OVAL; setColor(C.BG); setStroke(dpi(2), border) }
        layoutParams = LinearLayout.LayoutParams(dpi(46), dpi(46))
        importantForAccessibility = View.IMPORTANT_FOR_ACCESSIBILITY_NO
    }

    private fun iconBtn(kind: String, color: Int, desc: String, on: () -> Unit) = FrameLayout(this).apply {
        background = glass(14f, Color.argb(140, 224, 176, 74))
        contentDescription = desc
        minimumWidth = dpi(42)
        addView(Ico(this@Main, kind, color, 20f), FrameLayout.LayoutParams(-2, -2, Gravity.CENTER))
        setOnClickListener { on() }
    }

    private fun bg(f: () -> Unit) = Thread(f).start()
    private fun ui(f: () -> Unit) = runOnUiThread { if (!isDestroyed) f() }


    companion object {
        const val GO = "tm.yol.vpn.GO"
        const val INSTALLED = "tm.yol.vpn.INSTALLED"
    }
}
