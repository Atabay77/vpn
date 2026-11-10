package tm.yol.vpn

import android.app.Activity
import android.app.AlertDialog
import android.content.Intent
import android.graphics.Color
import android.graphics.Typeface
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
import android.view.MotionEvent
import android.view.View
import android.widget.EditText
import android.widget.FrameLayout
import android.widget.LinearLayout
import android.widget.ScrollView
import android.widget.TextView
import android.widget.Toast
import libv2ray.Libv2ray
import java.util.concurrent.Executors

class Main : Activity() {
    private lateinit var root: FrameLayout
    private lateinit var power: Power
    private lateinit var status: TextView
    private lateinit var hint: TextView
    private lateinit var card: LinearLayout
    private lateinit var info: LinearLayout
    private lateinit var timer: TextView
    private lateinit var timerLbl: TextView
    private lateinit var down: TextView
    private lateinit var up: TextView
    private lateinit var spark: Spark
    private lateinit var updBar: TextView
    private var onServers = false
    private val ms = HashMap<String, Long>()          // uri → ms (-1 = ulaşılamadı)
    private val msViews = HashMap<String, TextView>() // ölçüm satırları yerinde güncellenir (kaydırma kaymasın)
    private var testing = false
    private var fromApp = false                       // bağlantıyı bu ekrandan başlattık mı
    private var downloading = false
    private val h = Handler(Looper.getMainLooper())
    private val listener: () -> Unit = { renderState() }
    private val taps = ArrayList<Pair<Int, Long>>()

    override fun onCreate(b: Bundle?) {
        super.onCreate(b)
        State.app = applicationContext
        Libv2ray.initCoreEnv(filesDir.absolutePath, "")
        root = FrameLayout(this).apply { setBackgroundColor(C.BG) }
        setContentView(root)
        Sub.load(this)
        showMain()
        if (Build.VERSION.SDK_INT >= 33) requestPermissions(arrayOf("android.permission.POST_NOTIFICATIONS"), 2)
        bg { Sub.refresh(this); ui { if (onServers) showServers() else showMain() } }   // açılışta liste, key ve sürüm bilgisi
        handle(intent)
    }

    override fun onNewIntent(i: Intent) { super.onNewIntent(i); handle(i) }

    private fun handle(i: Intent?) {
        if (i == null) return
        if (Upd.onResult(this, i)) return
        if (i.action == GO && State.now != State.ON && State.now != State.WAIT) connect()   // bildirim panelinden
    }

    override fun onStart() {
        super.onStart(); State.subs += listener; renderState()
        h.removeCallbacks(tick); h.post(tick)
    }

    override fun onStop() {
        State.subs -= listener; h.removeCallbacks(tick)
        // bağlanırken ekrandan çıkılırsa bağlantı iptal
        if (fromApp && State.now == State.WAIT) startService(Intent(this, Svc::class.java).setAction(Svc.STOP))
        fromApp = false
        super.onStop()
    }

    @Deprecated("Activity API")
    override fun onBackPressed() { if (onServers) showMain() else super.onBackPressed() }

    // ---------- ana ekran ----------
    private fun showMain() {
        onServers = false
        msViews.clear()
        root.removeAllViews()
        root.addView(VideoBg(this, R.raw.bg), FrameLayout.LayoutParams(-1, -1))
        root.addView(View(this).apply { setBackgroundColor(0x550A1C14) }, FrameLayout.LayoutParams(-1, -1))
        val row = LinearLayout(this).apply { orientation = LinearLayout.HORIZONTAL }
        val carpet = Carpet(this, true, 5).apply { alpha = 0.92f }
        carpet.setOnTouchListener { v, e ->
            if (e.action == MotionEvent.ACTION_UP) secret(carpet.indexAt(e.y))
            v.performClick(); true
        }
        row.addView(carpet, LinearLayout.LayoutParams(dpi(30), -1))

        val col = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            setPadding(dpi(18), dpi(24), dpi(18), dpi(22))
        }
        updBar = text("", 14f, C.BG, true).apply {
            gravity = Gravity.CENTER; setPadding(dpi(12), dpi(10), dpi(12), dpi(10))
            background = box(C.GOLD, C.GOLD, 14f); visibility = View.GONE
            setOnClickListener { update() }
        }
        col.addView(updBar, LinearLayout.LayoutParams(-1, -2).apply { bottomMargin = dpi(12) })

        // logo + ad: cam kutu
        val head = LinearLayout(this).apply {
            orientation = LinearLayout.HORIZONTAL; gravity = Gravity.CENTER_VERTICAL
            setPadding(dpi(10), dpi(10), dpi(16), dpi(10))
            background = glass(18f)
        }
        head.addView(android.widget.ImageView(this).apply {
            setImageResource(R.drawable.logo); clipToOutline = true
            background = box(C.BG, Color.argb(140, 224, 176, 74), 12f)
            importantForAccessibility = View.IMPORTANT_FOR_ACCESSIBILITY_NO
        }, LinearLayout.LayoutParams(dpi(46), dpi(46)))
        val ht = LinearLayout(this).apply { orientation = LinearLayout.VERTICAL; setPadding(dpi(12), 0, 0, 0) }
        ht.addView(text(getString(R.string.app_name).uppercase(), 20f, C.TEXT, true).apply { letterSpacing = 0.12f })
        ht.addView(text("Türkmenistan üçin", 12f, C.MUTED).apply { letterSpacing = 0.06f })
        head.addView(ht)
        col.addView(head, LinearLayout.LayoutParams(-2, -2))

        val mid = LinearLayout(this).apply { orientation = LinearLayout.VERTICAL; gravity = Gravity.CENTER }
        power = Power(this).apply { isClickable = true; setOnClickListener { toggle() } }
        mid.addView(power)
        status = text("", 20f, C.TEXT, true).apply { gravity = Gravity.CENTER; setPadding(0, dpi(14), 0, dpi(2)); letterSpacing = 0.05f }
        hint = text("", 13f, C.MUTED).apply { gravity = Gravity.CENTER }
        mid.addView(status, LinearLayout.LayoutParams(-1, -2))
        mid.addView(hint, LinearLayout.LayoutParams(-1, -2))
        col.addView(mid, LinearLayout.LayoutParams(-1, 0, 1f))

        // sayaç + hız (bağlıyken)
        info = LinearLayout(this).apply { orientation = LinearLayout.HORIZONTAL; visibility = View.GONE }
        val tbox = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL; gravity = Gravity.CENTER
            setPadding(dpi(10), dpi(10), dpi(10), dpi(10)); background = glass(16f)
        }
        timerLbl = text("GALAN WAGT", 10f, C.MUTED, true).apply { letterSpacing = 0.15f }
        timer = text("02:00:00", 22f, C.GOLD, true).apply { typeface = Typeface.create(Typeface.MONOSPACE, Typeface.BOLD) }
        tbox.addView(timerLbl); tbox.addView(timer)
        info.addView(tbox, LinearLayout.LayoutParams(0, dpi(84), 1f).apply { rightMargin = dpi(10) })
        val sbox = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL; setPadding(dpi(12), dpi(8), dpi(12), dpi(8))
            background = glass(16f, Color.argb(110, 111, 219, 156))
        }
        val sv = LinearLayout(this).apply { orientation = LinearLayout.HORIZONTAL }
        down = text("↓ 0 B/s", 13f, C.GREEN, true).apply { typeface = Typeface.create(Typeface.MONOSPACE, Typeface.BOLD) }
        up = text("↑ 0 B/s", 13f, C.MUTED, true).apply { typeface = Typeface.create(Typeface.MONOSPACE, Typeface.BOLD); gravity = Gravity.END }
        sv.addView(down, LinearLayout.LayoutParams(0, -2, 1f)); sv.addView(up, LinearLayout.LayoutParams(0, -2, 1f))
        sbox.addView(sv)
        spark = Spark(this)
        sbox.addView(spark, LinearLayout.LayoutParams(-1, 0, 1f).apply { topMargin = dpi(4) })
        info.addView(sbox, LinearLayout.LayoutParams(0, dpi(84), 1.4f))
        col.addView(info, LinearLayout.LayoutParams(-1, -2).apply { bottomMargin = dpi(12) })

        card = LinearLayout(this).apply {
            orientation = LinearLayout.HORIZONTAL; gravity = Gravity.CENTER_VERTICAL
            setPadding(dpi(14), dpi(12), dpi(14), dpi(12))
            background = glass(18f, C.LINE)
            setOnClickListener { showServers() }
        }
        col.addView(card, LinearLayout.LayoutParams(-1, -2))

        row.addView(col, LinearLayout.LayoutParams(0, -1, 1f))
        root.addView(row)
        renderState()
    }

    private fun fillCard() {
        card.removeAllViews()
        val s = State.selected(this)
        val a = State.active.takeIf { State.now == State.ON }
        val t = LinearLayout(this).apply { orientation = LinearLayout.VERTICAL; setPadding(dpi(12), 0, dpi(8), 0) }
        if (Sub.list.isEmpty()) {
            card.addView(flag("🌐", C.GOLD))
            t.addView(text("Serwer ýok", 16f, C.TEXT, true))
            t.addView(text("Täzelemek üçin basyň", 13f, C.MUTED))
        } else if (s == null) {
            card.addView(flag(a?.flag ?: "⚡", C.GOLD))
            t.addView(text("Awtomatik", 16f, C.TEXT, true))
            t.addView(text(if (a != null) "${a.country} · ${sub(a)}" else "Iň çalt serwer", 13f, C.MUTED).apply { oneLine() })
        } else {
            card.addView(flag(s.flag, C.GOLD))
            t.addView(text(s.country, 16f, C.TEXT, true))
            t.addView(text(sub(s), 13f, C.MUTED).apply { oneLine() })
        }
        card.addView(t, LinearLayout.LayoutParams(0, -2, 1f))
        card.addView(Ico(this, "next", C.MUTED, 18f))
    }

    private fun renderState() {
        if (onServers || !::power.isInitialized) return
        val st = State.now
        power.on = st == State.ON
        power.busy = st == State.WAIT
        power.contentDescription = if (st == State.ON) "VPN-i öçür" else "VPN-e birik"
        when (st) {
            State.ON -> { status.text = "Birikdirildi"; status.setTextColor(C.GREEN); hint.text = "Öçürmek üçin düwmä basyň" }
            State.WAIT -> { status.text = "Birikdirilýär…"; status.setTextColor(C.GOLD); hint.text = "Garaşyň" }
            State.FAIL -> { status.text = "Birikmedi"; status.setTextColor(C.BAD); hint.text = "Başga serwer saýlaň ýa-da gaýtadan synanyşyň" }
            else -> { status.text = "Birikdirilmedik"; status.setTextColor(C.TEXT); hint.text = "Birikmek üçin düwmä basyň" }
        }
        info.visibility = if (st == State.ON) View.VISIBLE else View.GONE
        if (st != State.ON) { spark.clear(); lastRx = -1 }
        fillCard()
        renderUpd()
        tick.run()
    }

    // her saniye: sayaç + hız
    private var lastRx = -1L; private var lastTx = -1L
    private val tick = object : Runnable {
        override fun run() {
            h.removeCallbacks(this)
            if (onServers || !::timer.isInitialized) return
            if (State.now == State.ON) {
                val left = Lic.left(this@Main)
                if (left == null) {
                    timerLbl.text = "KEY"
                    val e = Lic.exp(this@Main) ?: 0L
                    timer.text = if (e == 0L) "ÇÄKSIZ" else {
                        val d = (e - System.currentTimeMillis()) / 1000
                        "%dg %02d:%02d".format(d / 86400, d % 86400 / 3600, d % 3600 / 60)
                    }
                } else {
                    timerLbl.text = "GALAN WAGT"
                    val sec = left / 1000
                    timer.text = "%02d:%02d:%02d".format(sec / 3600, sec % 3600 / 60, sec % 60)
                    timer.setTextColor(if (sec < 600) C.BAD else C.GOLD)
                }
                val uid = Process.myUid()
                val rx = TrafficStats.getUidRxBytes(uid); val tx = TrafficStats.getUidTxBytes(uid)
                if (lastRx >= 0 && rx >= lastRx) {
                    down.text = "↓ " + rate(rx - lastRx); up.text = "↑ " + rate(tx - lastTx)
                    spark.add((rx - lastRx).toFloat())
                }
                lastRx = rx; lastTx = tx
            }
            h.postDelayed(this, 1000)
        }
    }

    private fun rate(b: Long): String = when {
        b >= 1024 * 1024 -> "%.1f MB/s".format(b / 1048576f)
        b >= 1024 -> "%.0f KB/s".format(b / 1024f)
        else -> "$b B/s"
    }

    // ---------- güncelleme ----------
    private fun ver(): String = runCatching { packageManager.getPackageInfo(packageName, 0).versionName }.getOrNull() ?: "0"

    private fun renderUpd() {
        if (!::updBar.isInitialized || downloading) return
        val u = Upd.available(ver())
        updBar.visibility = if (u != null) View.VISIBLE else View.GONE
        if (u != null) updBar.text = "⬆  Täze wersiýa ${u.first} · Täzele"
    }

    private fun update() {
        val u = Upd.available(ver()) ?: return
        if (downloading) return
        downloading = true; updBar.text = "Ýüklenýär… 0%"
        bg {
            val ok = runCatching { Upd.install(this, u.second) { p -> ui { updBar.text = "Ýüklenýär… $p%" } } }.isSuccess
            ui {
                downloading = false
                if (!ok) Toast.makeText(this, "Ýüklenmedi, internedi barlaň", Toast.LENGTH_LONG).show()
                renderUpd()
            }
        }
    }

    // ---------- gizli key bölümü: ilk göl 1 kez → son göl 2 kez → ilk göl 1 kez ----------
    private fun secret(i: Int) {
        val now = System.currentTimeMillis()
        taps.add(i to now)
        taps.removeAll { now - it.second > 6000 }
        while (taps.size > 4) taps.removeAt(0)
        val want = listOf(0, 4, 4, 0)
        if (taps.size == 4 && taps.map { it.first } == want) { taps.clear(); keyDialog() }
    }

    private fun keyDialog() {
        val e = EditText(this).apply {
            hint = "XXXX-XXXX-XXXX"; setSingleLine(); setTextColor(C.TEXT); setHintTextColor(C.MUTED)
            inputType = InputType.TYPE_CLASS_TEXT or InputType.TYPE_TEXT_FLAG_CAP_CHARACTERS or InputType.TYPE_TEXT_FLAG_NO_SUGGESTIONS
            typeface = Typeface.MONOSPACE; letterSpacing = 0.1f
            Lic.saved(this@Main)?.let { setText(it) }
        }
        val cur = Lic.exp(this)
        val msg = when {
            cur == null -> "Key giriziň"
            cur == 0L -> "Häzirki key: çäksiz"
            else -> "Häzirki key: ${(cur - System.currentTimeMillis()) / 86400000} gün galdy"
        }
        val box = FrameLayout(this).apply { setPadding(dpi(20), dpi(8), dpi(20), 0); addView(e) }
        AlertDialog.Builder(this, android.R.style.Theme_Material_Dialog_Alert)
            .setTitle("🔑 Key").setMessage(msg).setView(box)
            .setPositiveButton("Barla") { _, _ -> checkKey(e.text.toString()) }
            .setNegativeButton("Ýap", null)
            .show()
    }

    private fun checkKey(raw: String) {
        val k = Lic.norm(raw)
        if (k.length != 14) { Toast.makeText(this, "Key nädogry", Toast.LENGTH_SHORT).show(); return }
        val old = Lic.saved(this)
        Lic.save(this, k)
        bg {
            if (Lic.exp(this) == null) Sub.refresh(this)   // yeni key: listeyi bir kez daha al
            val ok = Lic.exp(this) != null
            ui {
                if (!ok) Lic.save(this, old)
                Toast.makeText(this, if (ok) "✅ Key kabul edildi" else "Key nädogry ýa-da möhleti geçdi", Toast.LENGTH_LONG).show()
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
    private fun showServers() {
        onServers = true
        msViews.clear()
        root.removeAllViews()
        val col = LinearLayout(this).apply { orientation = LinearLayout.VERTICAL }
        col.addView(Carpet(this, false, 9), LinearLayout.LayoutParams(-1, dpi(22)))

        val head = LinearLayout(this).apply {
            orientation = LinearLayout.HORIZONTAL; gravity = Gravity.CENTER_VERTICAL
            setPadding(dpi(20), dpi(18), dpi(20), dpi(10))
        }
        head.addView(iconBtn("back", C.TEXT, "Yza") { showMain() })
        val tt = LinearLayout(this).apply { orientation = LinearLayout.VERTICAL; setPadding(dpi(10), 0, dpi(10), 0) }
        tt.addView(text("Serwerler", 20f, C.TEXT, true))
        tt.addView(text("${Sub.list.size} serwer", 13f, C.MUTED))
        head.addView(tt, LinearLayout.LayoutParams(0, -2, 1f))
        head.addView(iconBtn("refresh", C.GOLD, "Serwerleri täzele") { refresh() })
        head.addView(View(this), LinearLayout.LayoutParams(dpi(10), 1))
        val test = LinearLayout(this).apply {
            orientation = LinearLayout.HORIZONTAL; gravity = Gravity.CENTER
            setPadding(dpi(14), 0, dpi(14), 0)
            background = box(C.CARD, C.GOLD, 14f)
            contentDescription = "Tizligi barla"
            addView(Ico(this@Main, "gauge", C.GOLD, 18f))
            addView(text("Barla", 14f, C.GOLD, true).apply { setPadding(dpi(8), 0, 0, 0) })
            setOnClickListener { measure() }
        }
        head.addView(test, LinearLayout.LayoutParams(-2, dpi(44)))
        col.addView(head)

        val list = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            setPadding(dpi(20), dpi(8), dpi(20), dpi(20))
        }
        val sel = State.selected(this)
        if (Sub.list.isNotEmpty()) list.addView(autoRow(sel == null))
        for (s in Sub.list.filter { !it.game }) list.addView(row(s, s === sel))
        val games = Sub.list.filter { it.game }
        if (games.isNotEmpty()) {
            list.addView(text("Oýunlar üçin", 15f, C.GOLD, true).apply { setPadding(dpi(4), dpi(14), 0, dpi(10)) })
            for (s in games) list.addView(row(s, s === sel))
        }
        if (Sub.list.isEmpty()) list.addView(text("Serwer ýok. Täzelemek üçin ýokardaky düwmä basyň.", 14f, C.MUTED))
        val sv = ScrollView(this).apply { addView(list) }
        col.addView(sv, LinearLayout.LayoutParams(-1, 0, 1f))
        root.addView(col)
    }

    private fun msText(m: Long?): Pair<String, Int> = when {
        m == null -> (if (testing) "… ms" else "—") to C.MUTED
        m < 0 -> "×" to C.BAD
        m < 300 -> "$m ms" to C.GREEN
        m < 800 -> "$m ms" to C.GOLD
        else -> "$m ms" to C.BAD
    }

    private fun row(s: Server, sel: Boolean): View {
        val r = LinearLayout(this).apply {
            orientation = LinearLayout.HORIZONTAL; gravity = Gravity.CENTER_VERTICAL
            setPadding(dpi(14), dpi(12), dpi(14), dpi(12))
            minimumHeight = dpi(64)
            background = box(if (sel) C.CARD_SEL else C.CARD, if (sel) C.GREEN else C.LINE, 18f, 1.5f)
            setOnClickListener { pick(s) }
        }
        r.addView(flag(s.flag, if (sel) C.GREEN else C.GOLD))
        val t = LinearLayout(this).apply { orientation = LinearLayout.VERTICAL; setPadding(dpi(12), 0, dpi(8), 0) }
        t.addView(text(s.country, 16f, C.TEXT, true))
        t.addView(text(sub(s), 13f, C.MUTED).apply { oneLine() })
        r.addView(t, LinearLayout.LayoutParams(0, -2, 1f))
        val (mt, mc) = msText(ms[s.uri])
        val mv = text(mt, 14f, mc, true)
        msViews[s.uri] = mv
        r.addView(mv)
        if (sel) r.addView(Ico(this, "check", C.GREEN, 20f, 2.4f).apply {
            contentDescription = "Saýlanan"
        }, LinearLayout.LayoutParams(-2, -2).apply { leftMargin = dpi(10) })
        return r.also {
            it.layoutParams = LinearLayout.LayoutParams(-1, -2).apply { bottomMargin = dpi(10) }
        }
    }

    private fun autoRow(sel: Boolean): View {
        val r = LinearLayout(this).apply {
            orientation = LinearLayout.HORIZONTAL; gravity = Gravity.CENTER_VERTICAL
            setPadding(dpi(14), dpi(12), dpi(14), dpi(12))
            minimumHeight = dpi(64)
            background = box(if (sel) C.CARD_SEL else C.CARD, if (sel) C.GREEN else C.LINE, 18f, 1.5f)
            setOnClickListener { pick(null) }
        }
        r.addView(flag("⚡", if (sel) C.GREEN else C.GOLD))
        val t = LinearLayout(this).apply { orientation = LinearLayout.VERTICAL; setPadding(dpi(12), 0, dpi(8), 0) }
        t.addView(text("Awtomatik", 16f, C.TEXT, true))
        t.addView(text("Iň çalt serwere özi birigýär", 13f, C.MUTED).apply { oneLine() })
        r.addView(t, LinearLayout.LayoutParams(0, -2, 1f))
        if (sel) r.addView(Ico(this, "check", C.GREEN, 20f, 2.4f).apply { contentDescription = "Saýlanan" })
        r.layoutParams = LinearLayout.LayoutParams(-1, -2).apply { bottomMargin = dpi(10) }
        return r
    }

    private fun pick(s: Server?) {
        State.select(this, s)
        if (State.now == State.ON) startVpn()   // bağlıyken yeni serverle yeniden bağlan
        showMain()
    }

    private fun refresh() {
        Toast.makeText(this, "Täzelenýär…", Toast.LENGTH_SHORT).show()
        bg {
            val ok = Sub.refresh(this)
            ui {
                Toast.makeText(this, if (ok) "Täzelendi" else "Täzelenmedi", Toast.LENGTH_SHORT).show()
                ms.clear()
                if (onServers) showServers()
            }
        }
    }

    private fun paintMs() {
        for ((uri, v) in msViews) { val (t, c) = msText(ms[uri]); v.text = t; v.setTextColor(c) }
    }

    private fun measure() {
        if (testing) return
        val items = Sub.list.toList()
        if (items.isEmpty()) return
        testing = true; ms.clear(); paintMs()
        val pool = Executors.newFixedThreadPool(4)
        var left = items.size
        for (s in items) pool.execute {
            val v = runCatching {
                Libv2ray.measureOutboundDelay(Cfg.full(s.uri, false), State.PING)
            }.getOrDefault(-1L)
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

    private fun TextView.oneLine() { maxLines = 1; ellipsize = TextUtils.TruncateAt.END }

    private fun flag(f: String, border: Int) = TextView(this).apply {
        text = f; textSize = 22f; gravity = Gravity.CENTER
        background = box(C.BG, border, 22f, 2f)
        layoutParams = LinearLayout.LayoutParams(dpi(44), dpi(44))
        importantForAccessibility = View.IMPORTANT_FOR_ACCESSIBILITY_NO
    }

    private fun iconBtn(kind: String, color: Int, desc: String, on: () -> Unit) = FrameLayout(this).apply {
        background = box(C.CARD, C.LINE, 14f)
        contentDescription = desc
        layoutParams = LinearLayout.LayoutParams(dpi(44), dpi(44))
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
