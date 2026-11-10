package tm.yol.vpn

import android.app.Activity
import android.app.AlertDialog
import android.app.DownloadManager
import android.app.StatusBarManager
import android.content.ComponentName
import android.content.Intent
import android.graphics.BitmapFactory
import android.graphics.Color
import android.graphics.PorterDuff
import android.graphics.Typeface
import android.graphics.drawable.GradientDrawable
import android.graphics.drawable.Icon
import android.net.TrafficStats
import android.net.Uri
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
import android.view.animation.DecelerateInterpolator
import android.view.animation.OvershootInterpolator
import android.widget.EditText
import android.widget.FrameLayout
import android.widget.ImageView
import android.widget.LinearLayout
import android.widget.ScrollView
import android.widget.TextView
import android.widget.Toast
import libv2ray.Libv2ray
import java.io.File
import java.net.HttpURLConnection
import java.net.URL
import java.util.concurrent.Executors

class Main : Activity() {
    private enum class Page { MAIN, SERVERS, SPEED, SETTINGS, INFO }

    private lateinit var root: FrameLayout
    private lateinit var bgv: AnimBg
    private lateinit var page: FrameLayout          // değişen sayfa (arka plan sabit)
    private var menu: FrameLayout? = null           // ☰ ile açılan menü
    private var cur = Page.MAIN
    private var ready = false                       // açılış güncellemesi bitti mi
    private var lastState = -1

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
    private var updBar: NeonBar? = null
    private var updTxt: TextView? = null
    private var adBox: FrameLayout? = null
    // serverler
    private var testBtn: TextView? = null
    // hız sayfası
    private var bigDown: TextView? = null
    private var bigUp: TextView? = null
    private var bigSpark: Spark? = null
    private var totals: TextView? = null
    private var pingTv: TextView? = null
    private var offHint: TextView? = null

    private val ms = HashMap<String, Long>()          // uri → ms (-1 = ulaşılamadı)
    private val msViews = HashMap<String, TextView>() // ölçüm yerinde güncellenir (kaydırma kaymasın)
    private var testing = false
    private var fromApp = false
    private var slowShown = false
    private val h = Handler(Looper.getMainLooper())
    private val listener: () -> Unit = { renderState() }
    private val taps = ArrayList<Pair<Int, Long>>()
    private var lastRx = -1L; private var lastTx = -1L
    private var rx0 = -1L; private var tx0 = -1L
    private var pingAt = 0L

    override fun onCreate(b: Bundle?) {
        super.onCreate(b)
        State.app = applicationContext
        Lang.init(this)
        runCatching { Libv2ray.initCoreEnv(filesDir.absolutePath, "") }
        runCatching { Snd.init(this) }
        window.statusBarColor = Color.TRANSPARENT
        root = FrameLayout(this).apply { setBackgroundColor(C.BG) }
        setContentView(root)
        bgv = AnimBg(this, R.drawable.bg_tm)
        root.addView(bgv, FrameLayout.LayoutParams(-1, -1))
        root.addView(View(this).apply { setBackgroundColor(0x260A1C14) }, FrameLayout.LayoutParams(-1, -1))
        page = FrameLayout(this)
        root.addView(page, FrameLayout.LayoutParams(-1, -1))
        Sub.load(this)
        // her açılışta sunucu seçimi otomatik (bağlıyken dokunulmaz)
        if (b == null && State.now != State.ON && State.now != State.WAIT) State.select(this, null)
        if (Build.VERSION.SDK_INT >= 33) requestPermissions(arrayOf("android.permission.POST_NOTIFICATIONS"), 2)
        if (b == null && State.now != State.ON) splash() else { ready = true; show(Page.MAIN) }
        handle(intent)
    }

    /** Açılış: önce sunucular güncellenir, sonra ana menü açılır. */
    private fun splash() {
        val v = LinearLayout(this).apply { orientation = LinearLayout.VERTICAL; gravity = Gravity.CENTER }
        val logo = ImageView(this).apply { setImageResource(R.drawable.logo); clipToOutline = true; background = box(C.CREAM, C.GOLD, 26f) }
        v.addView(logo, LinearLayout.LayoutParams(dpi(104), dpi(104)))
        v.addView(text(getString(R.string.app_name).uppercase(), 20f, C.TEXT, true).apply {
            letterSpacing = 0.18f; gravity = Gravity.CENTER; setPadding(0, dpi(16), 0, dpi(4)) }, LinearLayout.LayoutParams(-1, -2))
        v.addView(text(t("Serwerler täzelenýär…", "Обновление серверов…", "Sunucular güncelleniyor…"), 13f, C.MUTED).apply {
            gravity = Gravity.CENTER }, LinearLayout.LayoutParams(-1, -2))
        v.addView(Spinner(this), LinearLayout.LayoutParams(dpi(30), dpi(30)).apply { topMargin = dpi(16) })
        page.addView(v, FrameLayout.LayoutParams(-1, -1))
        logo.scaleX = 0.85f; logo.scaleY = 0.85f; logo.alpha = 0f
        logo.animate().scaleX(1f).scaleY(1f).alpha(1f).setDuration(600).setInterpolator(OvershootInterpolator(1.4f)).start()
        val t0 = System.currentTimeMillis()
        bg {
            Sub.refresh(this, 7000)
            val wait = 900 - (System.currentTimeMillis() - t0)   // logo en az bir an görünsün
            if (wait > 0) Thread.sleep(wait)
            ui {
                ready = true
                v.animate().alpha(0f).setDuration(260).withEndAction { show(Page.MAIN) }.start()
            }
            Stats.beat(this, false)
            State.warm()   // otomatik bağlanma beklemesin diye sunucular arka planda ölçülür
        }
    }

    override fun onNewIntent(i: Intent) { super.onNewIntent(i); handle(i) }

    private fun handle(i: Intent?) {
        if (i == null) return
        when (i.action) {
            INSTALL -> Upd.install(this)
            GO -> if (State.now != State.ON && State.now != State.WAIT) connect()
        }
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
    override fun onBackPressed() {
        when {
            menu != null -> closeMenu()
            cur != Page.MAIN -> show(Page.MAIN)
            else -> super.onBackPressed()
        }
    }

    // ---------- ☰ menü ----------
    private val items = listOf(R.drawable.nav_home to Page.MAIN, R.drawable.nav_globe to Page.SERVERS,
        R.drawable.nav_gauge to Page.SPEED, R.drawable.nav_gear to Page.SETTINGS, R.drawable.nav_info to Page.INFO)

    private fun pageName(p: Page) = when (p) {
        Page.MAIN -> t("Baş sahypa", "Главная", "Ana sayfa"); Page.SERVERS -> t("Serwerler", "Серверы", "Sunucular")
        Page.SPEED -> t("Tizlik", "Скорость", "Hız"); Page.SETTINGS -> t("Sazlamalar", "Настройки", "Ayarlar")
        Page.INFO -> t("Maglumat", "О программе", "Hakkında")
    }

    private fun burger() = FrameLayout(this).apply {
        background = box(Color.argb(140, 10, 28, 20), Color.argb(170, 224, 176, 74), 12f)
        contentDescription = t("Menýu", "Меню", "Menü")
        addView(Ico(this@Main, "menu", C.GOLD, 20f, 2f), FrameLayout.LayoutParams(-2, -2, Gravity.CENTER))
        setOnClickListener { if (ready) openMenu() }
        pressFx()
    }

    private fun openMenu() {
        if (menu != null) return
        val m = FrameLayout(this)
        val scrim = View(this).apply { setBackgroundColor(Color.argb(140, 0, 0, 0)); setOnClickListener { closeMenu() } }
        m.addView(scrim, FrameLayout.LayoutParams(-1, -1))
        val panel = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL; setPadding(dpi(10), dpi(10), dpi(10), dpi(10))
            background = glass(20f, Color.argb(190, 224, 176, 74)); isClickable = true
        }
        items.forEachIndexed { i, (icon, pg) ->
            if (i > 0) panel.addView(GulSep(this), LinearLayout.LayoutParams(dpi(34), dpi(10)))
            val on = pg == cur
            val row = LinearLayout(this).apply {
                orientation = LinearLayout.HORIZONTAL; gravity = Gravity.CENTER_VERTICAL
                setPadding(dpi(10), dpi(8), dpi(14), dpi(8))
                background = if (on) box(Color.argb(170, 18, 120, 74), C.GREEN, 12f) else null
                val ib = FrameLayout(this@Main).apply {
                    background = GradientDrawable().apply { shape = GradientDrawable.OVAL; setColor(Color.argb(120, 10, 28, 20)); setStroke(dpi(1), if (on) C.GREEN else C.GOLD) }
                    addView(ImageView(this@Main).apply { setImageResource(icon); setColorFilter(if (on) Color.WHITE else C.GOLD, PorterDuff.Mode.SRC_IN) },
                        FrameLayout.LayoutParams(dpi(16), dpi(16), Gravity.CENTER))
                }
                addView(ib, LinearLayout.LayoutParams(dpi(30), dpi(30)))
                addView(text(pageName(pg), 14f, if (on) Color.WHITE else C.TEXT, true).apply { setPadding(dpi(12), 0, 0, 0) })
                setOnClickListener { secret(i); closeMenu(); if (pg != cur) show(pg) }
                pressFx()
            }
            panel.addView(row, LinearLayout.LayoutParams(-1, -2))
        }
        m.addView(panel, FrameLayout.LayoutParams(dpi(210), -2).apply { leftMargin = dpi(16); topMargin = dpi(104) })
        root.addView(m, FrameLayout.LayoutParams(-1, -1))
        menu = m
        scrim.alpha = 0f; scrim.animate().alpha(1f).setDuration(200).start()
        panel.alpha = 0f; panel.translationX = -dp(40f)
        panel.animate().alpha(1f).translationX(0f).setDuration(260).setInterpolator(DecelerateInterpolator(1.8f)).start()
    }

    private fun closeMenu() {
        val m = menu ?: return
        menu = null
        m.animate().alpha(0f).setDuration(160).withEndAction { root.removeView(m) }.start()
    }

    // gizli key bölümü: menüde ilk satır 1 kez → son satır 2 kez → ilk satır 1 kez (8 sn içinde)
    private fun secret(i: Int) {
        val now = System.currentTimeMillis()
        taps.add(i to now); taps.removeAll { now - it.second > 8000 }
        while (taps.size > 4) taps.removeAt(0)
        if (taps.map { it.first } == listOf(0, 4, 4, 0)) { taps.clear(); h.postDelayed({ keyDialog() }, 250) }
    }

    // ---------- sayfalar ----------
    private fun show(p: Page) {
        cur = p
        page.removeAllViews(); msViews.clear()
        power = null; status = null; hint = null; card = null; timer = null; timerLbl = null; down = null; up = null; spark = null
        updBar = null; updTxt = null; adBox = null; testBtn = null
        bigDown = null; bigUp = null; bigSpark = null; totals = null; pingTv = null; offHint = null
        val v = when (p) {
            Page.MAIN -> mainPage(); Page.SERVERS -> serversPage(); Page.SPEED -> speedPage()
            Page.SETTINGS -> settingsPage(); Page.INFO -> infoPage()
        }
        page.addView(v, FrameLayout.LayoutParams(-1, -1))
        enter(v)
        renderState()
    }

    /** Sayfa açılınca öğeler sırayla, hafifçe yukarı kayarak belirir. */
    private fun enter(v: View) {
        val list = if (v is LinearLayout) (0 until v.childCount).map { v.getChildAt(it) } else listOf(v)
        list.forEachIndexed { i, c ->
            c.alpha = 0f; c.translationY = dp(14f)
            c.animate().alpha(1f).translationY(0f).setStartDelay(40L * i).setDuration(320)
                .setInterpolator(DecelerateInterpolator(1.6f)).start()
        }
    }

    /** Basınca hafif küçülüp yaylanarak geri gelir. */
    private fun View.pressFx(): View {
        setOnTouchListener { vw, e ->
            when (e.actionMasked) {
                MotionEvent.ACTION_DOWN -> vw.animate().scaleX(0.96f).scaleY(0.96f).setDuration(90).start()
                MotionEvent.ACTION_UP, MotionEvent.ACTION_CANCEL ->
                    vw.animate().scaleX(1f).scaleY(1f).setDuration(220).setInterpolator(OvershootInterpolator(2.5f)).start()
            }
            false
        }
        return this
    }

    private fun content() = LinearLayout(this).apply {
        orientation = LinearLayout.VERTICAL
        setPadding(dpi(14), dpi(30), dpi(14), dpi(16))
    }

    private fun mainPage(): View {
        val col = content()
        col.addView(header(), LinearLayout.LayoutParams(-1, dpi(60)))

        // yeni sürüm: neon ışıklı şerit
        val nb = NeonBar(this).apply { visibility = View.GONE; setOnClickListener { askUpdate(false) }; pressFx() }
        updTxt = text("", 13f, C.GOLD, true).apply { gravity = Gravity.CENTER }
        nb.addView(updTxt, FrameLayout.LayoutParams(-1, -1))
        updBar = nb
        col.addView(nb, LinearLayout.LayoutParams(-1, dpi(46)).apply { topMargin = dpi(10) })

        val mid = LinearLayout(this).apply { orientation = LinearLayout.VERTICAL; gravity = Gravity.CENTER }
        power = Power(this).apply { isClickable = true; setOnClickListener { Snd.play(this@Main, R.raw.tap, 0.5f); toggle() }; pressFx() }
        mid.addView(power)
        status = text("", 18f, C.TEXT, true).apply { gravity = Gravity.CENTER; setPadding(0, dpi(4), 0, dpi(1)); setShadowLayer(dp(6f), 0f, dp(1f), Color.BLACK) }
        hint = text("", 12f, C.MUTED).apply { gravity = Gravity.CENTER; setShadowLayer(dp(5f), 0f, dp(1f), Color.BLACK) }
        mid.addView(status, LinearLayout.LayoutParams(-1, -2)); mid.addView(hint, LinearLayout.LayoutParams(-1, -2))
        col.addView(mid, LinearLayout.LayoutParams(-1, 0, 1f))

        // reklam (bot üzerinden eklenir)
        adBox = FrameLayout(this).apply { visibility = View.GONE; background = glass(16f); clipToOutline = true }
        col.addView(adBox, LinearLayout.LayoutParams(-1, dpi(70)).apply { bottomMargin = dpi(10) })
        loadAd()

        val row = LinearLayout(this).apply { orientation = LinearLayout.HORIZONTAL }
        val tbox = LinearLayout(this).apply { orientation = LinearLayout.VERTICAL; gravity = Gravity.CENTER; background = glass(16f) }
        timerLbl = text("", 9f, C.MUTED, true).apply { letterSpacing = 0.2f; gravity = Gravity.CENTER }
        timer = mono("--:--:--", 19f, C.GOLD).apply { gravity = Gravity.CENTER; setPadding(0, dpi(2), 0, 0) }
        tbox.addView(timerLbl, LinearLayout.LayoutParams(-1, -2)); tbox.addView(timer, LinearLayout.LayoutParams(-1, -2))
        row.addView(tbox, LinearLayout.LayoutParams(0, dpi(68), 1f).apply { rightMargin = dpi(10) })
        val sbox = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL; setPadding(dpi(12), dpi(8), dpi(12), dpi(6))
            background = glass(16f, Color.argb(140, 111, 219, 156))
        }
        val sv = LinearLayout(this).apply { orientation = LinearLayout.HORIZONTAL; gravity = Gravity.CENTER_VERTICAL }
        down = mono("↓ 0 B/s", 11f, C.GREEN); up = mono("↑ 0 B/s", 11f, C.GOLD).apply { gravity = Gravity.END }
        sv.addView(down, LinearLayout.LayoutParams(0, -2, 1f)); sv.addView(up, LinearLayout.LayoutParams(0, -2, 1f))
        sbox.addView(sv)
        spark = Spark(this)
        sbox.addView(spark, LinearLayout.LayoutParams(-1, 0, 1f).apply { topMargin = dpi(4) })
        row.addView(sbox, LinearLayout.LayoutParams(0, dpi(68), 1.3f))
        col.addView(row, LinearLayout.LayoutParams(-1, -2).apply { bottomMargin = dpi(10) })

        card = LinearLayout(this).apply {
            orientation = LinearLayout.HORIZONTAL; gravity = Gravity.CENTER_VERTICAL
            setPadding(dpi(12), 0, dpi(12), 0)
            background = glass(16f)
            setOnClickListener { show(Page.SERVERS) }
            pressFx()
        }
        col.addView(card, LinearLayout.LayoutParams(-1, dpi(60)))
        return col
    }

    /** Üst şerit: ☰ · logo · ad · dil. Soldan sağa tam genişlik. */
    private fun header() = LinearLayout(this).apply {
        orientation = LinearLayout.HORIZONTAL; gravity = Gravity.CENTER_VERTICAL
        setPadding(dpi(8), 0, dpi(8), 0)
        background = glass(18f, Color.argb(190, 224, 176, 74))
        addView(burger(), LinearLayout.LayoutParams(dpi(40), dpi(40)))
        addView(ImageView(this@Main).apply {
            setImageResource(R.drawable.logo); clipToOutline = true; background = box(C.CREAM, C.GOLD, 10f)
            importantForAccessibility = View.IMPORTANT_FOR_ACCESSIBILITY_NO
        }, LinearLayout.LayoutParams(dpi(38), dpi(38)).apply { leftMargin = dpi(10) })
        val tv = LinearLayout(this@Main).apply { orientation = LinearLayout.VERTICAL; setPadding(dpi(10), 0, dpi(6), 0) }
        tv.addView(text(getString(R.string.app_name).uppercase(), 14f, C.TEXT, true).apply { letterSpacing = 0.1f; oneLine() })
        tv.addView(text(t("Türkmenistan üçin", "для Туркменистана", "Türkmenistan için"), 10f, C.MUTED).apply { oneLine() })
        addView(tv, LinearLayout.LayoutParams(0, -2, 1f))
        addView(langBtn())
    }

    /** «Dil» yazısı + bayrak/kod düğmesi. */
    private fun langBtn() = LinearLayout(this).apply {
        orientation = LinearLayout.VERTICAL; gravity = Gravity.CENTER_HORIZONTAL
        addView(text(t("Dil", "Язык", "Dil"), 9f, C.MUTED, true).apply { letterSpacing = 0.1f })
        addView(text("${Lang.flags[Lang.cur]} ${if (Lang.cur == "tk") "TM" else Lang.cur.uppercase()}", 11f, C.GOLD, true).apply {
            gravity = Gravity.CENTER; setPadding(dpi(7), dpi(3), dpi(7), dpi(3))
            background = box(Color.argb(120, 10, 28, 20), Color.argb(170, 224, 176, 74), 10f)
        })
        contentDescription = t("Dil", "Язык", "Dil")
        setOnClickListener { langDialog() }
        pressFx()
    }

    /** Diğer sayfaların üst şeridi: ☰ · başlık · sağ düğmeler. */
    private fun topBar(tt: String, sub: String?, vararg right: View): View {
        val r = LinearLayout(this).apply {
            orientation = LinearLayout.HORIZONTAL; gravity = Gravity.CENTER_VERTICAL
            setPadding(dpi(8), 0, dpi(8), 0); background = glass(18f, Color.argb(190, 224, 176, 74))
        }
        r.addView(burger(), LinearLayout.LayoutParams(dpi(40), dpi(40)))
        val c = LinearLayout(this).apply { orientation = LinearLayout.VERTICAL; setPadding(dpi(12), 0, dpi(6), 0) }
        c.addView(text(tt.uppercase(), 15f, C.TEXT, true).apply { letterSpacing = 0.12f; oneLine() })
        if (sub != null) c.addView(text(sub, 10f, C.MUTED).apply { oneLine() })
        r.addView(c, LinearLayout.LayoutParams(0, -2, 1f))
        right.forEach { r.addView(it, LinearLayout.LayoutParams(-2, dpi(36)).apply { leftMargin = dpi(6) }) }
        return r
    }

    private fun langDialog() {
        val v = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL; setPadding(dpi(14), dpi(14), dpi(14), dpi(8))
            background = box(Color.argb(245, 8, 22, 16), C.GOLD, 20f)
        }
        v.addView(text(t("Dil saýlaň", "Выберите язык", "Dil seçin"), 15f, C.TEXT, true).apply { gravity = Gravity.CENTER; setPadding(0, 0, 0, dpi(10)) }, LinearLayout.LayoutParams(-1, -2))
        val d = AlertDialog.Builder(this).setView(v).create()
        d.window?.setBackgroundDrawableResource(android.R.color.transparent)
        for (l in Lang.codes) {
            val on = l == Lang.cur
            v.addView(text("${Lang.flags[l]}   ${Lang.names[l]}", 15f, if (on) C.GREEN else C.TEXT, on).apply {
                setPadding(dpi(14), dpi(12), dpi(14), dpi(12))
                background = if (on) box(Color.argb(140, 18, 120, 74), C.GREEN, 12f) else null
                setOnClickListener { d.dismiss(); Lang.set(this@Main, l); show(cur); State.app?.let { Tile.refresh(it) } }
            }, LinearLayout.LayoutParams(-1, -2).apply { bottomMargin = dpi(6) })
        }
        d.show()
    }

    private fun serversPage(): View {
        val col = content()
        testBtn = text(t("Barla", "Тест", "Test"), 12f, C.GOLD, true).apply {
            gravity = Gravity.CENTER; setPadding(dpi(12), 0, dpi(12), 0)
            background = box(Color.argb(120, 10, 28, 20), C.GOLD, 10f)
            setOnClickListener { measure() }
            pressFx()
        }
        col.addView(topBar(t("Serwerler", "Серверы", "Sunucular"), t("${Sub.list.size} serwer", "${Sub.list.size} серв.", "${Sub.list.size} sunucu"),
            iconBtn("refresh") { refresh() }, testBtn!!), LinearLayout.LayoutParams(-1, dpi(60)))
        paintTest()
        val list = LinearLayout(this).apply { orientation = LinearLayout.VERTICAL; setPadding(0, dpi(12), 0, dpi(24)) }
        val sel = State.selected(this)
        if (Sub.list.isNotEmpty()) list.addView(autoRow(sel == null))
        for (s in Sub.list.filter { !it.game }) list.addView(row(s, s === sel))
        val games = Sub.list.filter { it.game }
        if (games.isNotEmpty()) {
            list.addView(text(t("OÝUNLAR ÜÇIN", "ДЛЯ ИГР", "OYUNLAR İÇİN"), 12f, C.GOLD, true).apply { letterSpacing = 0.15f; setPadding(dpi(4), dpi(10), 0, dpi(8)) })
            for (s in games) list.addView(row(s, s === sel))
        }
        if (Sub.list.isEmpty()) list.addView(text(t("Serwer ýok. Täzelemek üçin ýokardaky düwmä basyň.", "Нет серверов. Нажмите кнопку обновления вверху.", "Sunucu yok. Yenilemek için üstteki düğmeye basın."), 13f, C.MUTED))
        col.addView(ScrollView(this).apply { addView(list); isVerticalScrollBarEnabled = false }, LinearLayout.LayoutParams(-1, 0, 1f))
        return col
    }

    private fun paintTest() {
        val b = testBtn ?: return
        b.text = if (testing) t("Barlanýar… garaşyň", "Проверка… подождите", "Test ediliyor… bekleyin") else t("Barla", "Тест", "Test")
        b.alpha = if (testing) 0.75f else 1f
    }

    private fun speedPage(): View {
        val col = content()
        col.addView(topBar(t("Tizlik", "Скорость", "Hız"), t("Häzirki internet akymy", "Текущий трафик", "Anlık internet akışı")), LinearLayout.LayoutParams(-1, dpi(60)))
        val b = LinearLayout(this).apply { orientation = LinearLayout.VERTICAL; setPadding(dpi(12), dpi(12), dpi(12), dpi(12)); background = glass(18f, Color.argb(140, 111, 219, 156)) }
        val r = LinearLayout(this).apply { orientation = LinearLayout.HORIZONTAL }
        fun cell(arrow: String, lbl: String, tv: TextView, col_: Int) = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL; gravity = Gravity.CENTER
            setPadding(0, dpi(8), 0, dpi(8)); background = box(Color.argb(90, 6, 18, 12), Color.argb(80, Color.red(col_), Color.green(col_), Color.blue(col_)), 12f)
            addView(text("$arrow  $lbl", 10f, C.MUTED, true).apply { letterSpacing = 0.15f; gravity = Gravity.CENTER }, LinearLayout.LayoutParams(-1, -2))
            tv.gravity = Gravity.CENTER
            addView(tv, LinearLayout.LayoutParams(-1, -2).apply { topMargin = dpi(4) })
        }
        bigDown = mono("0 B/s", 16f, C.GREEN); bigUp = mono("0 B/s", 16f, C.GOLD)
        r.addView(cell("↓", t("ÝÜKLEME", "ЗАГРУЗКА", "İNDİRME"), bigDown!!, C.GREEN), LinearLayout.LayoutParams(0, -2, 1f).apply { rightMargin = dpi(8) })
        r.addView(cell("↑", t("IBERME", "ОТДАЧА", "GÖNDERME"), bigUp!!, C.GOLD), LinearLayout.LayoutParams(0, -2, 1f))
        b.addView(r)
        bigSpark = Spark(this)
        val sf = FrameLayout(this)
        sf.addView(bigSpark, FrameLayout.LayoutParams(-1, -1))
        offHint = text(t("VPN-e birikiň", "Подключите VPN", "VPN'e bağlanın"), 12f, C.MUTED).apply { gravity = Gravity.CENTER }
        sf.addView(offHint, FrameLayout.LayoutParams(-1, -1))
        b.addView(sf, LinearLayout.LayoutParams(-1, dpi(90)).apply { topMargin = dpi(10) })
        col.addView(b, LinearLayout.LayoutParams(-1, -2).apply { topMargin = dpi(12) })
        val g = LinearLayout(this).apply { orientation = LinearLayout.HORIZONTAL }
        val pb = LinearLayout(this).apply { orientation = LinearLayout.VERTICAL; gravity = Gravity.CENTER; background = glass(16f) }
        pb.addView(text("PING", 9f, C.MUTED, true).apply { letterSpacing = 0.2f; gravity = Gravity.CENTER }, LinearLayout.LayoutParams(-1, -2))
        pingTv = mono("—", 17f, C.GOLD).apply { gravity = Gravity.CENTER }; pb.addView(pingTv, LinearLayout.LayoutParams(-1, -2))
        g.addView(pb, LinearLayout.LayoutParams(0, dpi(68), 1f).apply { rightMargin = dpi(10) })
        val tb = LinearLayout(this).apply { orientation = LinearLayout.VERTICAL; gravity = Gravity.CENTER; background = glass(16f) }
        tb.addView(text(t("JEMI", "ВСЕГО", "TOPLAM"), 9f, C.MUTED, true).apply { letterSpacing = 0.2f; gravity = Gravity.CENTER }, LinearLayout.LayoutParams(-1, -2))
        totals = mono("—", 12f, C.TEXT).apply { gravity = Gravity.CENTER }; tb.addView(totals, LinearLayout.LayoutParams(-1, -2))
        g.addView(tb, LinearLayout.LayoutParams(0, dpi(68), 1.3f))
        col.addView(g, LinearLayout.LayoutParams(-1, -2).apply { topMargin = dpi(10) })
        return col
    }

    private fun settingsPage(): View {
        val col = content()
        col.addView(topBar(t("Sazlamalar", "Настройки", "Ayarlar"), null), LinearLayout.LayoutParams(-1, dpi(60)))
        col.addView(View(this), LinearLayout.LayoutParams(1, dpi(12)))
        col.addView(option(R.drawable.nav_globe, t("Dil", "Язык", "Dil"), "${Lang.flags[Lang.cur]} ${Lang.names[Lang.cur]}") { langDialog() })
        col.addView(option(R.drawable.nav_gauge, t("Sesler", "Звуки", "Sesler"),
            if (Snd.on(this)) t("Açyk", "Включены", "Açık") else t("Öçük", "Выключены", "Kapalı")) { Snd.setOn(this, !Snd.on(this)); show(Page.SETTINGS) })
        col.addView(option(R.drawable.nav_home, t("Serwerleri täzele", "Обновить серверы", "Sunucuları yenile"),
            t("Abunany häzir täzeden al", "Получить подписку заново", "Aboneliği şimdi yeniden al")) { refresh() })
        col.addView(option(R.drawable.nav_info, t("Täze wersiýa", "Новая версия", "Yeni sürüm"),
            t("Häzirki wersiýa ${ver()}", "Текущая версия ${ver()}", "Mevcut sürüm ${ver()}")) {
            bg { Sub.refresh(this); ui { if (Upd.available(ver()) != null) askUpdate(false) else toast(t("Iň täze wersiýa gurnalan", "Установлена последняя версия", "En yeni sürüm yüklü")) } }
        })
        if (Build.VERSION.SDK_INT >= 33) col.addView(option(R.drawable.nav_gear, t("Bildiriş paneline goş", "Добавить в шторку", "Bildirim paneline ekle"),
            t("Ýokarky panelde Aç/Ýap düwmesi", "Кнопка Вкл/Выкл в шторке", "Üst panelde Aç/Kapat düğmesi")) {
            runCatching {
                getSystemService(StatusBarManager::class.java).requestAddTileService(
                    ComponentName(this, Tile::class.java), getString(R.string.app_name),
                    Icon.createWithResource(this, R.drawable.ic_tile), mainExecutor) { }
            }
        })
        return col
    }

    private fun infoPage(): View {
        val col = content()
        col.addView(topBar(t("Maglumat", "О программе", "Hakkında"), null), LinearLayout.LayoutParams(-1, dpi(60)))
        val b = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL; gravity = Gravity.CENTER_HORIZONTAL
            setPadding(dpi(18), dpi(18), dpi(18), dpi(20)); background = glass(18f)
        }
        b.addView(ImageView(this).apply { setImageResource(R.drawable.logo_full); adjustViewBounds = true; clipToOutline = true; background = box(C.CREAM, C.GOLD, 16f) },
            LinearLayout.LayoutParams(dpi(220), -2))
        b.addView(text(t("Wersiýa ${ver()}", "Версия ${ver()}", "Sürüm ${ver()}"), 12f, C.MUTED).apply { gravity = Gravity.CENTER; setPadding(0, dpi(12), 0, 0) }, LinearLayout.LayoutParams(-1, -2))
        b.addView(text(t("Türkmenistan üçin çalt we howpsuz VPN.", "Быстрый и безопасный VPN для Туркменистана.", "Türkmenistan için hızlı ve güvenli VPN.") +
            "\nHysteria2 · Shadowsocks · VLESS", 12f, C.MUTED).apply { gravity = Gravity.CENTER; setPadding(0, dpi(8), 0, 0) }, LinearLayout.LayoutParams(-1, -2))
        col.addView(b, LinearLayout.LayoutParams(-1, -2).apply { topMargin = dpi(12) })
        return col
    }

    private fun option(icon: Int, tt: String, sub: String, on: () -> Unit) = LinearLayout(this).apply {
        orientation = LinearLayout.HORIZONTAL; gravity = Gravity.CENTER_VERTICAL
        setPadding(dpi(14), dpi(10), dpi(14), dpi(10)); minimumHeight = dpi(56); background = glass(16f)
        addView(ImageView(this@Main).apply { setImageResource(icon); setColorFilter(C.GOLD, PorterDuff.Mode.SRC_IN) }, LinearLayout.LayoutParams(dpi(20), dpi(20)))
        val c = LinearLayout(this@Main).apply { orientation = LinearLayout.VERTICAL; setPadding(dpi(12), 0, 0, 0) }
        c.addView(text(tt, 14f, C.TEXT, true)); c.addView(text(sub, 11f, C.MUTED))
        addView(c, LinearLayout.LayoutParams(0, -2, 1f))
        addView(Ico(this@Main, "next", C.MUTED, 16f))
        setOnClickListener { on() }
        pressFx()
        layoutParams = LinearLayout.LayoutParams(-1, -2).apply { bottomMargin = dpi(8) }
    }

    // ---------- durum ----------
    private fun fillCard() {
        val card = card ?: return
        card.removeAllViews()
        val s = State.selected(this)
        val a = State.active.takeIf { State.now == State.ON }
        val c = LinearLayout(this).apply { orientation = LinearLayout.VERTICAL }
        val (f, c1, c2) = when {
            Sub.list.isEmpty() -> Triple("🌐", t("Serwer ýok", "Нет серверов", "Sunucu yok"), t("Täzelemek üçin basyň", "Нажмите для обновления", "Yenilemek için basın"))
            s == null -> Triple(a?.flag ?: "⚡", t("Awtomatik", "Авто", "Otomatik"), if (a != null) "${a.country} · ${sub(a)}" else t("Iň çalt serwer", "Самый быстрый сервер", "En hızlı sunucu"))
            else -> Triple(s.flag, s.country, sub(s))
        }
        card.addView(flag(f, C.GOLD, 38))
        card.addView(View(this).apply { setBackgroundColor(Color.argb(150, 224, 176, 74)) },
            LinearLayout.LayoutParams(dpi(1), dpi(26)).apply { leftMargin = dpi(10); rightMargin = dpi(10) })
        c.addView(text(c1, 14f, C.TEXT, true).apply { oneLine() }); c.addView(text(c2, 11f, C.MUTED).apply { oneLine() })
        card.addView(c, LinearLayout.LayoutParams(0, -2, 1f))
        card.addView(Ico(this, "next", C.GOLD, 16f))
    }

    private fun renderState() {
        val st = State.now
        if (lastState == State.WAIT && st == State.ON) Snd.play(this, R.raw.on)
        if (lastState == State.ON && st == State.OFF) Snd.play(this, R.raw.off)
        lastState = st
        power?.let { it.on = st == State.ON; it.busy = st == State.WAIT; it.contentDescription = if (st == State.ON) t("VPN-i öçür", "Выключить VPN", "VPN'i kapat") else t("VPN-e birik", "Подключить VPN", "VPN'e bağlan") }
        status?.let { s ->
            val (a, col, b) = when (st) {
                State.ON -> Triple(t("Birikdirildi", "Подключено", "Bağlandı"), C.GREEN, t("Öçürmek üçin düwmä basyň", "Нажмите, чтобы отключить", "Kapatmak için düğmeye basın"))
                State.WAIT -> Triple(t("Birikdirilýär…", "Подключение…", "Bağlanıyor…"), C.GOLD, t("Garaşyň", "Подождите", "Bekleyin"))
                State.FAIL -> Triple(t("Birikmedi", "Не подключилось", "Bağlanamadı"), C.BAD, t("Başga serwer saýlaň ýa-da gaýtadan synanyşyň", "Выберите другой сервер или повторите", "Başka sunucu seçin ya da tekrar deneyin"))
                else -> Triple(t("Birikdirilmedik", "Не подключено", "Bağlı değil"), C.TEXT, t("Birikmek üçin düwmä basyň", "Нажмите, чтобы подключиться", "Bağlanmak için düğmeye basın"))
            }
            if (s.text != a) { s.alpha = 0f; s.animate().alpha(1f).setDuration(260).start() }
            s.text = a; s.setTextColor(col); hint?.text = b
        }
        if (st != State.ON) { spark?.clear(); bigSpark?.clear(); lastRx = -1; rx0 = -1 }
        offHint?.visibility = if (st == State.ON) View.GONE else View.VISIBLE
        fillCard(); renderUpd(); paintBg(); tick.run()
    }

    // bütün ekranın manzarası: bağlı (ya da seçili) sunucunun ülkesi; yoksa Aşgabat
    private val bgs = mapOf("FR" to R.drawable.bg_fr, "GB" to R.drawable.bg_gb, "DE" to R.drawable.bg_de, "NL" to R.drawable.bg_nl,
        "FI" to R.drawable.bg_fi, "RU" to R.drawable.bg_ru, "CH" to R.drawable.bg_ch, "PL" to R.drawable.bg_pl,
        "TR" to R.drawable.bg_tr, "SE" to R.drawable.bg_se, "US" to R.drawable.bg_us)

    private fun cc(flag: String): String = flag.codePoints().toArray().filter { it in 0x1F1E6..0x1F1FF }
        .joinToString("") { (it - 0x1F1E6 + 'A'.code).toChar().toString() }

    private fun paintBg() {
        if (!::bgv.isInitialized) return
        val s = State.active.takeIf { State.now == State.ON } ?: State.selected(this)
        bgv.change(s?.let { bgs[cc(it.flag)] } ?: R.drawable.bg_tm)
    }

    private val tick = object : Runnable {
        override fun run() {
            h.removeCallbacks(this)
            val on = State.now == State.ON
            timer?.let { tv ->
                if (!on) { timerLbl?.text = t("GALAN WAGT", "ОСТАЛОСЬ", "KALAN SÜRE"); tv.text = "--:--:--"; tv.setTextColor(C.GOLD) }
                else {
                    val left = Lic.left(this@Main)
                    if (left == null) {
                        timerLbl?.text = t("AÇAR", "КЛЮЧ", "ANAHTAR")
                        val e = Lic.exp(this@Main) ?: 0L
                        tv.text = if (e == 0L) t("ÇÄKSIZ", "БЕЗЛИМИТ", "SINIRSIZ") else ((e - System.currentTimeMillis()) / 1000).let { d -> "%dg %02d:%02d".format(d / 86400, d % 86400 / 3600, d % 3600 / 60) }
                        tv.setTextColor(C.GOLD)
                    } else {
                        timerLbl?.text = t("GALAN WAGT", "ОСТАЛОСЬ", "KALAN SÜRE")
                        val sec = left / 1000
                        tv.text = "%02d:%02d:%02d".format(sec / 3600, sec % 3600 / 60, sec % 60)
                        tv.setTextColor(if (sec < 600) C.BAD else C.GOLD)
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
                totals?.text = t("VPN öçük", "VPN выкл.", "VPN kapalı")
            }
            watchDownload()
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
        val u = Upd.available(ver())
        bar.visibility = if (u != null) View.VISIBLE else View.GONE
        if (u == null) return
        val q = Upd.query(this)
        updTxt?.text = when (q?.status) {
            DownloadManager.STATUS_RUNNING, DownloadManager.STATUS_PENDING, DownloadManager.STATUS_PAUSED ->
                t("Ýüklenýär… ${q.pct}%", "Загрузка… ${q.pct}%", "İndiriliyor… %${q.pct}")
            DownloadManager.STATUS_SUCCESSFUL -> "⬇  " + t("Ýüklendi · Gurnamak üçin basyň", "Загружено · Нажмите для установки", "İndirildi · Kurmak için dokunun")
            else -> "⬆  " + t("Täze wersiýa ${u.first} · Täzele", "Новая версия ${u.first} · Обновить", "Yeni sürüm ${u.first} · Güncelle")
        }
    }

    /** Zorunlu güncelleme sorusu. vpn=true: bağlanmaya çalışırken çıktı. */
    private fun askUpdate(vpn: Boolean) {
        val u = Upd.available(ver()) ?: return
        val q = Upd.query(this)
        if (q?.status == DownloadManager.STATUS_SUCCESSFUL) { installHint(); Upd.install(this); return }
        if (Upd.busy(this)) { toast(t("Täze wersiýa ýüklenýär, garaşyň", "Новая версия загружается, подождите", "Yeni sürüm iniyor, bekleyin")); return }
        val msg = if (vpn) t("VPN-i işletmek üçin VPN-iň täze wersiýasyny ýüklemeli! Size täze wersiýany ýükläýinmi?",
            "Чтобы пользоваться VPN, нужно загрузить новую версию! Загрузить новую версию?",
            "VPN'i kullanmak için yeni sürümü indirmelisiniz! Yeni sürüm indirilsin mi?")
        else t("Täze wersiýa ${u.first} bar. Ýükläýinmi?", "Доступна версия ${u.first}. Загрузить?", "Yeni sürüm ${u.first} var. İndirilsin mi?")
        ask(msg, t("Hawa", "Да", "Evet"), t("Ýok", "Нет", "Hayır")) { startUpdate(u) }
    }

    private fun startUpdate(u: Pair<String, String>) {
        if (State.now == State.ON || State.now == State.WAIT) startService(Intent(this, Svc::class.java).setAction(Svc.STOP))   // güncellemede VPN kapalı
        slowShown = false
        if (!Upd.start(this, u.first, u.second))
            toast(t("Ýüklenýär. Programmadan çyksaňyz hem dowam eder", "Загрузка продолжится даже если закрыть программу", "İndiriliyor. Uygulamadan çıksanız da devam eder"))
        renderUpd()
    }

    private var lastDl = -1
    private fun watchDownload() {
        val q = Upd.query(this) ?: return
        if (q.status != lastDl) {
            val was = lastDl; lastDl = q.status
            if (was != -1 && q.status == DownloadManager.STATUS_SUCCESSFUL) { installHint(); Upd.install(this) }
            if (q.status == DownloadManager.STATUS_FAILED) {
                getSharedPreferences("p", 0).edit().remove("dl").apply()
                info(Upd.errText(this, q.reason))
            }
        }
        if (q.status == DownloadManager.STATUS_PAUSED && !slowShown &&
            System.currentTimeMillis() - getSharedPreferences("p", 0).getLong("dlAt", 0) > 40_000) {
            slowShown = true; info(Upd.errText(this, 0))
        }
        renderUpd()
    }

    /** Kurulum olmazsa: dosya «Download» klasöründe, dosya yöneticisinden açılabilir. */
    private fun installHint() {
        if (Build.VERSION.SDK_INT >= 29) toast(t("Gurnalmasa: faýl dolandyryjyda «Download» bukjasyndaky TurkmenVPN faýlyny açyň",
            "Если не установится: откройте файл TurkmenVPN в папке «Download» через файловый менеджер",
            "Kurulmazsa: dosya yöneticisinde «Download» klasöründeki TurkmenVPN dosyasını açın"))
    }

    // ---------- reklam ----------
    private fun loadAd() {
        val box = adBox ?: return
        val ad = Sub.ad ?: return
        bg {
            val f = File(cacheDir, "ad_${ad.first}")
            if (!f.exists()) runCatching {
                val c = URL(Sub.fileUrl(ad.first)).openConnection() as HttpURLConnection
                c.connectTimeout = 8000; c.readTimeout = 15000
                if (c.responseCode == 200) c.inputStream.use { i -> f.outputStream().use { i.copyTo(it) } }
                c.disconnect()
            }
            val bmp = runCatching { BitmapFactory.decodeFile(f.path) }.getOrNull() ?: return@bg
            ui {
                if (adBox !== box) return@ui
                box.removeAllViews()
                box.addView(ImageView(this).apply { setImageBitmap(bmp); scaleType = ImageView.ScaleType.CENTER_CROP }, FrameLayout.LayoutParams(-1, -1))
                box.visibility = View.VISIBLE
                box.setOnClickListener { if (ad.second.isNotBlank()) runCatching { startActivity(Intent(Intent.ACTION_VIEW, Uri.parse(ad.second))) } }
                box.alpha = 0f; box.animate().alpha(1f).setDuration(300).start()
            }
        }
    }

    // ---------- key ----------
    private fun keyDialog() {
        val e = EditText(this).apply {
            hint = "XXXX-XXXX-XXXX"; setSingleLine(); setTextColor(C.GOLD); setHintTextColor(C.MUTED)
            inputType = InputType.TYPE_CLASS_TEXT or InputType.TYPE_TEXT_FLAG_CAP_CHARACTERS or InputType.TYPE_TEXT_FLAG_NO_SUGGESTIONS
            typeface = Typeface.create(Typeface.MONOSPACE, Typeface.BOLD); textSize = 18f; letterSpacing = 0.1f
            gravity = Gravity.CENTER; background = glass(12f, C.GOLD); setPadding(dpi(10), dpi(10), dpi(10), dpi(10))
            Lic.saved(this@Main)?.let { setText(it) }
        }
        val cur = Lic.exp(this)
        val info = when {
            cur == null -> t("Açar giriziň", "Введите ключ", "Anahtarı girin")
            cur == 0L -> t("Häzirki açar: çäksiz", "Текущий ключ: безлимит", "Mevcut anahtar: sınırsız")
            else -> ((cur - System.currentTimeMillis()) / 86400000).let { d -> t("Häzirki açar: $d gün galdy", "Текущий ключ: осталось $d дн.", "Mevcut anahtar: $d gün kaldı") }
        }
        val v = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL; gravity = Gravity.CENTER_HORIZONTAL
            setPadding(dpi(20), dpi(20), dpi(20), dpi(16)); background = box(Color.argb(245, 8, 22, 16), C.GOLD, 20f)
        }
        v.addView(ImageView(this).apply { setImageResource(R.drawable.logo); clipToOutline = true; background = box(C.CREAM, C.GOLD, 12f) },
            LinearLayout.LayoutParams(dpi(48), dpi(48)))
        v.addView(text(t("AÇAR", "КЛЮЧ", "ANAHTAR"), 16f, C.TEXT, true).apply { letterSpacing = 0.25f; gravity = Gravity.CENTER; setPadding(0, dpi(8), 0, dpi(2)) }, LinearLayout.LayoutParams(-1, -2))
        v.addView(text(info, 12f, C.MUTED).apply { gravity = Gravity.CENTER; setPadding(0, 0, 0, dpi(12)) }, LinearLayout.LayoutParams(-1, -2))
        v.addView(e, LinearLayout.LayoutParams(-1, -2))
        val btn = text(t("BARLA", "ПРОВЕРИТЬ", "KONTROL ET"), 14f, C.BG, true).apply {
            gravity = Gravity.CENTER; letterSpacing = 0.15f; background = box(C.GOLD, C.GOLD, 12f)
        }
        v.addView(btn, LinearLayout.LayoutParams(-1, dpi(44)).apply { topMargin = dpi(12) })
        val d = AlertDialog.Builder(this).setView(v).create()
        d.window?.setBackgroundDrawableResource(android.R.color.transparent)
        btn.setOnClickListener { d.dismiss(); checkKey(e.text.toString()) }
        d.show()
    }

    private fun checkKey(raw: String) {
        val k = Lic.norm(raw)
        val bad = t("Açar nädogry ýa-da möhleti geçdi", "Неверный или истёкший ключ", "Anahtar geçersiz ya da süresi dolmuş")
        if (k.length != 14) { toast(bad); return }
        val old = Lic.saved(this)
        Lic.save(this, k)
        bg {
            if (Lic.exp(this) == null) Sub.refresh(this)
            val ok = Lic.exp(this) != null
            ui {
                if (!ok) Lic.save(this, old)
                toast(if (ok) "✅ " + t("Açar kabul edildi", "Ключ принят", "Anahtar kabul edildi") else bad)
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
        if (Upd.busy(this)) { toast(t("Täze wersiýa ýüklenýär, gutarýança garaşyň", "Идёт загрузка новой версии, подождите", "Yeni sürüm iniyor, bitene kadar bekleyin")); return }
        if (Upd.available(ver()) != null) { askUpdate(true); return }   // zorunlu güncelleme
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
        m == null -> (if (testing) "…" else "—") to C.MUTED
        m < 0 -> "n/a" to C.BAD
        m < 300 -> "$m ms" to C.GREEN
        m < 800 -> "$m ms" to C.GOLD
        else -> "$m ms" to C.BAD
    }

    private fun rowBase(sel: Boolean, on: () -> Unit) = LinearLayout(this).apply {
        orientation = LinearLayout.HORIZONTAL; gravity = Gravity.CENTER_VERTICAL
        setPadding(dpi(12), dpi(8), dpi(12), dpi(8)); minimumHeight = dpi(56)
        background = if (sel) glass(14f, C.GREEN) else glass(14f, Color.argb(100, 224, 176, 74))
        setOnClickListener { on() }
        pressFx()
        layoutParams = LinearLayout.LayoutParams(-1, -2).apply { bottomMargin = dpi(8) }
    }

    private fun row(s: Server, sel: Boolean): View {
        val r = rowBase(sel) { pick(s) }
        r.addView(flag(s.flag, if (sel) C.GREEN else C.GOLD, 36))
        val c = LinearLayout(this).apply { orientation = LinearLayout.VERTICAL; setPadding(dpi(12), 0, dpi(8), 0) }
        c.addView(text(s.country, 14f, C.TEXT, true).apply { oneLine() }); c.addView(text(sub(s), 11f, C.MUTED).apply { oneLine() })
        r.addView(c, LinearLayout.LayoutParams(0, -2, 1f))
        val (mt, mc) = msText(ms[s.uri])
        val mv = mono(mt, 12f, mc); msViews[s.uri] = mv; r.addView(mv)
        if (sel) r.addView(Ico(this, "check", C.GREEN, 18f, 2.4f), LinearLayout.LayoutParams(-2, -2).apply { leftMargin = dpi(8) })
        return r
    }

    private fun autoRow(sel: Boolean): View {
        val r = rowBase(sel) { pick(null) }
        r.addView(flag("⚡", if (sel) C.GREEN else C.GOLD, 36))
        val c = LinearLayout(this).apply { orientation = LinearLayout.VERTICAL; setPadding(dpi(12), 0, dpi(8), 0) }
        c.addView(text(t("Awtomatik", "Авто", "Otomatik"), 14f, C.TEXT, true))
        c.addView(text(t("Iň çalt serwere özi birigýär", "Сам выбирает самый быстрый", "En hızlı sunucuya kendisi bağlanır"), 11f, C.MUTED).apply { oneLine() })
        r.addView(c, LinearLayout.LayoutParams(0, -2, 1f))
        if (sel) r.addView(Ico(this, "check", C.GREEN, 18f, 2.4f))
        return r
    }

    private fun pick(s: Server?) {
        State.select(this, s)
        if (State.now == State.ON) startVpn()
        show(Page.MAIN)
    }

    private fun refresh() {
        toast(t("Täzelenýär…", "Обновление…", "Yenileniyor…"))
        bg {
            val ok = Sub.refresh(this)
            ui {
                toast(if (ok) t("Täzelendi", "Обновлено", "Yenilendi") else t("Täzelenmedi", "Не обновилось", "Yenilenemedi"))
                ms.clear(); if (cur == Page.SERVERS) show(Page.SERVERS) else renderState()
            }
        }
    }

    private fun paintMs() { for ((uri, v) in msViews) { val (tt, c) = msText(ms[uri]); v.text = tt; v.setTextColor(c) } }

    private fun measure() {
        if (testing) return
        val list = Sub.list.toList()
        if (list.isEmpty()) return
        testing = true; ms.clear(); paintMs(); paintTest()
        val pool = Executors.newFixedThreadPool(4)
        var left = list.size
        for (s in list) pool.execute {
            val v = State.ping(s)
            ui {
                ms[s.uri] = v
                left--
                if (left == 0) {
                    testing = false; pool.shutdown(); State.pingAt = System.currentTimeMillis(); paintTest()
                    // hiçbiri yanıt vermediyse: kodlar yenileniyor
                    if (ms.values.all { it < 0 }) info(t("Kodlar täzelenýär, takmynan 3-5 minut aralygynda işlär. VPN-den çykyň we 3-5 minutdan giriň.",
                        "Коды обновляются, заработают примерно через 3-5 минут. Выйдите из VPN и зайдите через 3-5 минут.",
                        "Kodlar yenileniyor, yaklaşık 3-5 dakika içinde çalışır. VPN'den çıkın ve 3-5 dakika sonra girin."))
                }
                paintMs()   // liste yeniden kurulmaz: kaydırma yerinde kalır
            }
        }
    }

    // ---------- yardımcılar ----------
    private fun sub(s: Server) = if (s.title.isEmpty()) s.proto else "${s.title} · ${s.proto}"

    private fun toast(s: String) = Toast.makeText(this, s, Toast.LENGTH_LONG).show()

    /** Bilgi penceresi (tek düğme). */
    private fun info(msg: String) = ask(msg, "OK", null) {}

    /** Kendi tasarımımızda soru penceresi. */
    private fun ask(msg: String, yes: String, no: String?, onYes: () -> Unit) {
        val v = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL; gravity = Gravity.CENTER_HORIZONTAL
            setPadding(dpi(20), dpi(20), dpi(20), dpi(16)); background = box(Color.argb(245, 8, 22, 16), C.GOLD, 20f)
        }
        v.addView(ImageView(this).apply { setImageResource(R.drawable.logo); clipToOutline = true; background = box(C.CREAM, C.GOLD, 12f) },
            LinearLayout.LayoutParams(dpi(44), dpi(44)))
        v.addView(text(msg, 14f, C.TEXT).apply { gravity = Gravity.CENTER; setPadding(0, dpi(12), 0, dpi(14)); setLineSpacing(0f, 1.15f) }, LinearLayout.LayoutParams(-1, -2))
        val d = AlertDialog.Builder(this).setView(v).create()
        d.window?.setBackgroundDrawableResource(android.R.color.transparent)
        val r = LinearLayout(this).apply { orientation = LinearLayout.HORIZONTAL }
        if (no != null) r.addView(text(no, 14f, C.TEXT, true).apply {
            gravity = Gravity.CENTER; background = box(Color.argb(120, 10, 28, 20), C.LINE, 12f)
            setOnClickListener { d.dismiss() }
        }, LinearLayout.LayoutParams(0, dpi(44), 1f).apply { rightMargin = dpi(10) })
        r.addView(text(yes, 14f, C.BG, true).apply {
            gravity = Gravity.CENTER; background = box(C.GOLD, C.GOLD, 12f)
            setOnClickListener { d.dismiss(); onYes() }
        }, LinearLayout.LayoutParams(0, dpi(44), 1f))
        v.addView(r, LinearLayout.LayoutParams(-1, -2))
        d.show()
    }

    private fun text(tx: String, sp: Float, color: Int, bold: Boolean = false) = TextView(this).apply {
        text = tx; textSize = sp; setTextColor(color)
        if (bold) typeface = Typeface.create(Typeface.DEFAULT, Typeface.BOLD)
    }
    private fun mono(tx: String, sp: Float, color: Int) = text(tx, sp, color).apply { typeface = Typeface.create(Typeface.MONOSPACE, Typeface.BOLD) }

    private fun TextView.oneLine() { maxLines = 1; ellipsize = TextUtils.TruncateAt.END }

    private fun flag(f: String, border: Int, sz: Int = 40) = TextView(this).apply {
        text = f; textSize = sz * 0.45f; gravity = Gravity.CENTER
        background = GradientDrawable().apply { shape = GradientDrawable.OVAL; setColor(C.BG); setStroke(dpi(2), border) }
        layoutParams = LinearLayout.LayoutParams(dpi(sz), dpi(sz))
        importantForAccessibility = View.IMPORTANT_FOR_ACCESSIBILITY_NO
    }

    private fun iconBtn(kind: String, on: () -> Unit) = FrameLayout(this).apply {
        background = box(Color.argb(120, 10, 28, 20), C.GOLD, 10f)
        contentDescription = t("Täzele", "Обновить", "Yenile")
        minimumWidth = dpi(36)
        addView(Ico(this@Main, kind, C.GOLD, 18f), FrameLayout.LayoutParams(-2, -2, Gravity.CENTER))
        setOnClickListener { on() }
        pressFx()
    }

    private fun bg(f: () -> Unit) = Thread(f).start()
    private fun ui(f: () -> Unit) = runOnUiThread { if (!isDestroyed) f() }

    companion object {
        const val GO = "tm.yol.vpn.GO"
        const val INSTALL = "tm.yol.vpn.INSTALL"
    }
}
