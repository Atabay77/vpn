package tm.yol.vpn

import android.app.Activity
import android.app.AlertDialog
import android.app.StatusBarManager
import android.content.ComponentName
import android.content.Intent
import android.graphics.Color
import android.graphics.PorterDuff
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
import java.util.concurrent.Executors

class Main : Activity() {
    private enum class Page { MAIN, SERVERS, SPEED, SETTINGS, INFO }

    private lateinit var root: FrameLayout
    private lateinit var bgv: AnimBg
    private lateinit var page: FrameLayout          // değişen sayfa (arka plan ve sol menü sabit)
    private lateinit var rail: LinearLayout
    private var cur = Page.MAIN
    private var ready = false                       // açılış güncellemesi bitti mi

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
    private var offHint: TextView? = null

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
        Lang.init(this)
        Libv2ray.initCoreEnv(filesDir.absolutePath, "")
        window.statusBarColor = Color.TRANSPARENT
        root = FrameLayout(this).apply { setBackgroundColor(C.BG) }
        setContentView(root)
        bgv = AnimBg(this, R.drawable.bg_tm)
        root.addView(bgv, FrameLayout.LayoutParams(-1, -1))
        root.addView(View(this).apply { setBackgroundColor(0x260A1C14) }, FrameLayout.LayoutParams(-1, -1))
        page = FrameLayout(this)
        root.addView(page, FrameLayout.LayoutParams(-1, -1))
        rail = buildRail()
        root.addView(rail, FrameLayout.LayoutParams(dpi(50), -2).apply { leftMargin = dpi(10); topMargin = dpi(122) })
        Sub.load(this)
        // her açılışta sunucu seçimi otomatik (bağlıyken dokunulmaz)
        if (b == null && State.now != State.ON && State.now != State.WAIT) State.select(this, null)
        if (Build.VERSION.SDK_INT >= 33) requestPermissions(arrayOf("android.permission.POST_NOTIFICATIONS"), 2)
        if (b == null && State.now != State.ON) splash() else { ready = true; show(Page.MAIN) }
        handle(intent)
    }

    /** Açılış: önce sunucular güncellenir, sonra ana menü açılır. */
    private fun splash() {
        rail.visibility = View.INVISIBLE
        val v = LinearLayout(this).apply { orientation = LinearLayout.VERTICAL; gravity = Gravity.CENTER }
        val logo = ImageView(this).apply { setImageResource(R.drawable.logo); clipToOutline = true; background = box(C.CREAM, C.GOLD, 28f) }
        v.addView(logo, LinearLayout.LayoutParams(dpi(120), dpi(120)))
        v.addView(text(getString(R.string.app_name).uppercase(), 22f, C.TEXT, true).apply { letterSpacing = 0.18f; setPadding(0, dpi(18), 0, dpi(6)) })
        v.addView(text(t("Serwerler täzelenýär…", "Обновление серверов…", "Sunucular güncelleniyor…"), 13f, C.MUTED))
        v.addView(Spinner(this), LinearLayout.LayoutParams(dpi(36), dpi(36)).apply { topMargin = dpi(18) })
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
                v.animate().alpha(0f).setDuration(260).withEndAction {
                    rail.visibility = View.VISIBLE; rail.alpha = 0f; rail.translationX = -dp(20f)
                    rail.animate().alpha(1f).translationX(0f).setDuration(380).start()
                    show(Page.MAIN)
                }.start()
            }
        }
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
    private val railItems = listOf(R.drawable.nav_home to Page.MAIN, R.drawable.nav_globe to Page.SERVERS,
        R.drawable.nav_gauge to Page.SPEED, R.drawable.nav_gear to Page.SETTINGS, R.drawable.nav_info to Page.INFO)
    private val railBtns = ArrayList<Pair<FrameLayout, ImageView>>()

    private fun buildRail(): LinearLayout {
        val r = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL; gravity = Gravity.CENTER_HORIZONTAL
            setPadding(0, dpi(9), 0, dpi(9))
            background = glass(25f, Color.argb(150, 224, 176, 74))
        }
        railItems.forEachIndexed { i, (icon, pg) ->
            if (i > 0) r.addView(GulSep(this), LinearLayout.LayoutParams(dpi(20), dpi(20)))
            val ic = ImageView(this).apply { setImageResource(icon); setColorFilter(C.GOLD, PorterDuff.Mode.SRC_IN) }
            val b = FrameLayout(this).apply {
                background = GradientDrawable().apply { shape = GradientDrawable.OVAL; setColor(Color.argb(110, 10, 28, 20)); setStroke(dpi(1), C.GOLD) }
                addView(ic, FrameLayout.LayoutParams(dpi(22), dpi(22), Gravity.CENTER))
                setOnClickListener { secret(i); if (pg != cur && ready) show(pg) }
                pressFx()
            }
            railBtns += b to ic
            r.addView(b, LinearLayout.LayoutParams(dpi(40), dpi(40)))
        }
        return r
    }

    private fun paintRail() {
        railBtns.forEachIndexed { i, (b, ic) ->
            val on = railItems[i].second == cur
            (b.background as GradientDrawable).apply {
                setColor(if (on) Color.argb(200, 18, 120, 74) else Color.argb(110, 10, 28, 20))
                setStroke(dpi(if (on) 2 else 1), if (on) C.GREEN else C.GOLD)
            }
            ic.setColorFilter(if (on) Color.WHITE else C.GOLD, PorterDuff.Mode.SRC_IN)
            b.contentDescription = when (railItems[i].second) {
                Page.MAIN -> t("Baş sahypa", "Главная", "Ana sayfa"); Page.SERVERS -> t("Serwerler", "Серверы", "Sunucular")
                Page.SPEED -> t("Tizlik", "Скорость", "Hız"); Page.SETTINGS -> t("Sazlamalar", "Настройки", "Ayarlar")
                Page.INFO -> t("Maglumat", "О программе", "Hakkında")
            }
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
        power = null; status = null; hint = null; card = null; timer = null; timerLbl = null; down = null; up = null; spark = null; updBar = null
        bigDown = null; bigUp = null; bigSpark = null; totals = null; pingTv = null; offHint = null
        val v = when (p) {
            Page.MAIN -> mainPage(); Page.SERVERS -> serversPage(); Page.SPEED -> speedPage()
            Page.SETTINGS -> settingsPage(); Page.INFO -> infoPage()
        }
        page.addView(v, FrameLayout.LayoutParams(-1, -1))
        enter(v)
        paintRail(); renderState()
    }

    /** Sayfa açılınca öğeler sırayla, hafifçe yukarı kayarak belirir. */
    private fun enter(v: View) {
        val items = if (v is LinearLayout) (0 until v.childCount).map { v.getChildAt(it) } else listOf(v)
        items.forEachIndexed { i, c ->
            c.alpha = 0f; c.translationY = dp(18f)
            c.animate().alpha(1f).translationY(0f).setStartDelay(45L * i).setDuration(340)
                .setInterpolator(DecelerateInterpolator(1.6f)).start()
        }
    }

    /** Basınca hafif küçülüp yaylanarak geri gelir. */
    private fun View.pressFx(): View {
        setOnTouchListener { vw, e ->
            when (e.actionMasked) {
                MotionEvent.ACTION_DOWN -> vw.animate().scaleX(0.95f).scaleY(0.95f).setDuration(90).start()
                MotionEvent.ACTION_UP, MotionEvent.ACTION_CANCEL ->
                    vw.animate().scaleX(1f).scaleY(1f).setDuration(240).setInterpolator(OvershootInterpolator(3f)).start()
            }
            false
        }
        return this
    }

    /** Sağ taraf: sol menü kadar boşluk bırakılır. */
    private fun content() = LinearLayout(this).apply {
        orientation = LinearLayout.VERTICAL
        setPadding(dpi(72), dpi(34), dpi(16), dpi(20))
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
        power = Power(this).apply { isClickable = true; setOnClickListener { toggle() }; pressFx() }
        mid.addView(power)
        status = text("", 21f, C.TEXT, true).apply { gravity = Gravity.CENTER; setPadding(0, dpi(6), 0, dpi(2)) }
        hint = text("", 13f, C.MUTED).apply { gravity = Gravity.CENTER }
        mid.addView(status, LinearLayout.LayoutParams(-1, -2)); mid.addView(hint, LinearLayout.LayoutParams(-1, -2))
        col.addView(mid, LinearLayout.LayoutParams(-1, -2).apply { topMargin = dpi(14) })

        val row = LinearLayout(this).apply { orientation = LinearLayout.HORIZONTAL }
        val tbox = LinearLayout(this).apply { orientation = LinearLayout.VERTICAL; gravity = Gravity.CENTER; background = glass(18f) }
        timerLbl = text("", 10f, C.MUTED, true).apply { letterSpacing = 0.2f; gravity = Gravity.CENTER }
        timer = mono("--:--:--", 24f, C.GOLD).apply { gravity = Gravity.CENTER }
        tbox.addView(timerLbl, LinearLayout.LayoutParams(-1, -2)); tbox.addView(timer, LinearLayout.LayoutParams(-1, -2))
        row.addView(tbox, LinearLayout.LayoutParams(0, dpi(88), 1f).apply { rightMargin = dpi(10) })
        val sbox = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL; setPadding(dpi(12), dpi(10), dpi(12), dpi(10))
            background = glass(18f, Color.argb(140, 111, 219, 156))
        }
        val sv = LinearLayout(this).apply { orientation = LinearLayout.HORIZONTAL; gravity = Gravity.CENTER_VERTICAL }
        down = mono("↓ 0 B/s", 12f, C.GREEN); up = mono("↑ 0 B/s", 12f, C.GOLD).apply { gravity = Gravity.END }
        sv.addView(down, LinearLayout.LayoutParams(0, -2, 1f)); sv.addView(up, LinearLayout.LayoutParams(0, -2, 1f))
        sbox.addView(sv)
        spark = Spark(this)
        sbox.addView(spark, LinearLayout.LayoutParams(-1, 0, 1f).apply { topMargin = dpi(6) })
        row.addView(sbox, LinearLayout.LayoutParams(0, dpi(88), 1.25f))
        col.addView(row, LinearLayout.LayoutParams(-1, -2).apply { topMargin = dpi(18) })

        col.addView(View(this), LinearLayout.LayoutParams(-1, 0, 1f))   // ülke manzarası burada görünür

        card = LinearLayout(this).apply {
            orientation = LinearLayout.HORIZONTAL; gravity = Gravity.CENTER_VERTICAL
            setPadding(dpi(14), dpi(12), dpi(14), dpi(12))
            background = glass(20f)
            setOnClickListener { show(Page.SERVERS) }
            pressFx()
        }
        col.addView(card, LinearLayout.LayoutParams(-1, dpi(74)))
        return col
    }

    private fun header() = LinearLayout(this).apply {
        orientation = LinearLayout.HORIZONTAL; gravity = Gravity.CENTER_VERTICAL
        setPadding(dpi(10), 0, dpi(10), 0)
        background = glass(20f, Color.argb(190, 224, 176, 74))
        addView(ImageView(this@Main).apply {
            setImageResource(R.drawable.logo); clipToOutline = true; background = box(C.CREAM, C.GOLD, 12f)
            importantForAccessibility = View.IMPORTANT_FOR_ACCESSIBILITY_NO
        }, LinearLayout.LayoutParams(dpi(48), dpi(48)))
        addView(View(this@Main).apply { setBackgroundColor(Color.argb(150, 224, 176, 74)) },
            LinearLayout.LayoutParams(dpi(1), dpi(36)).apply { leftMargin = dpi(10); rightMargin = dpi(10) })
        val tv = LinearLayout(this@Main).apply { orientation = LinearLayout.VERTICAL }
        tv.addView(text(getString(R.string.app_name).uppercase(), 17f, C.TEXT, true).apply { letterSpacing = 0.12f; oneLine() })
        tv.addView(text(t("Türkmenistan üçin", "для Туркменистана", "Türkmenistan için"), 11f, C.MUTED).apply { oneLine() })
        addView(tv, LinearLayout.LayoutParams(0, -2, 1f))
        // dil düğmesi
        addView(text("${Lang.flags[Lang.cur]} ${if (Lang.cur == "tk") "TM" else Lang.cur.uppercase()}", 12f, C.GOLD, true).apply {
            gravity = Gravity.CENTER; setPadding(dpi(8), dpi(5), dpi(8), dpi(5))
            background = box(Color.argb(120, 10, 28, 20), Color.argb(170, 224, 176, 74), 12f)
            contentDescription = t("Dil", "Язык", "Dil")
            setOnClickListener { langDialog() }
            pressFx()
        })
    }

    private fun langDialog() {
        val v = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL; setPadding(dpi(16), dpi(16), dpi(16), dpi(10))
            background = box(Color.argb(245, 8, 22, 16), C.GOLD, 22f)
        }
        val d = AlertDialog.Builder(this).setView(v).create()
        d.window?.setBackgroundDrawableResource(android.R.color.transparent)
        for (l in Lang.codes) {
            val on = l == Lang.cur
            v.addView(text("${Lang.flags[l]}   ${Lang.names[l]}", 16f, if (on) C.GREEN else C.TEXT, on).apply {
                setPadding(dpi(14), dpi(14), dpi(14), dpi(14))
                background = if (on) box(Color.argb(140, 18, 120, 74), C.GREEN, 14f) else null
                setOnClickListener { d.dismiss(); Lang.set(this@Main, l); show(cur); State.app?.let { Tile.refresh(it) } }
            }, LinearLayout.LayoutParams(-1, -2).apply { bottomMargin = dpi(6) })
        }
        d.show()
    }

    private fun title(tt: String, sub: String?, vararg right: View): View {
        val r = LinearLayout(this).apply { orientation = LinearLayout.HORIZONTAL; gravity = Gravity.CENTER_VERTICAL; setPadding(dpi(4), 0, 0, dpi(12)) }
        val c = LinearLayout(this).apply { orientation = LinearLayout.VERTICAL }
        c.addView(text(tt.uppercase(), 18f, C.TEXT, true).apply { letterSpacing = 0.14f })
        if (sub != null) c.addView(text(sub, 12f, C.MUTED))
        r.addView(c, LinearLayout.LayoutParams(0, -2, 1f))
        right.forEach { r.addView(it, LinearLayout.LayoutParams(-2, dpi(42)).apply { leftMargin = dpi(8) }) }
        return r
    }

    private fun serversPage(): View {
        val col = content()
        val test = LinearLayout(this).apply {
            orientation = LinearLayout.HORIZONTAL; gravity = Gravity.CENTER
            setPadding(dpi(12), 0, dpi(14), 0); background = glass(14f, C.GOLD)
            addView(ImageView(this@Main).apply { setImageResource(R.drawable.nav_gauge); setColorFilter(C.GOLD, PorterDuff.Mode.SRC_IN) },
                LinearLayout.LayoutParams(dpi(18), dpi(18)))
            addView(text(t("Barla", "Тест", "Test"), 14f, C.GOLD, true).apply { setPadding(dpi(6), 0, 0, 0) })
            setOnClickListener { measure() }
            pressFx()
        }
        col.addView(title(t("Serwerler", "Серверы", "Sunucular"), t("${Sub.list.size} serwer", "${Sub.list.size} серв.", "${Sub.list.size} sunucu"),
            iconBtn("refresh", C.GOLD) { refresh() }, test))
        val list = LinearLayout(this).apply { orientation = LinearLayout.VERTICAL; setPadding(0, 0, 0, dpi(24)) }
        val sel = State.selected(this)
        if (Sub.list.isNotEmpty()) list.addView(autoRow(sel == null))
        for (s in Sub.list.filter { !it.game }) list.addView(row(s, s === sel))
        val games = Sub.list.filter { it.game }
        if (games.isNotEmpty()) {
            list.addView(text(t("OÝUNLAR ÜÇIN", "ДЛЯ ИГР", "OYUNLAR İÇİN"), 13f, C.GOLD, true).apply { letterSpacing = 0.15f; setPadding(dpi(4), dpi(12), 0, dpi(10)) })
            for (s in games) list.addView(row(s, s === sel))
        }
        if (Sub.list.isEmpty()) list.addView(text(t("Serwer ýok. Täzelemek üçin ýokardaky düwmä basyň.", "Нет серверов. Нажмите кнопку обновления вверху.", "Sunucu yok. Yenilemek için üstteki düğmeye basın."), 14f, C.MUTED))
        col.addView(ScrollView(this).apply { addView(list); isVerticalScrollBarEnabled = false }, LinearLayout.LayoutParams(-1, 0, 1f))
        return col
    }

    private fun speedPage(): View {
        val col = content()
        col.addView(title(t("Tizlik", "Скорость", "Hız"), t("Häzirki internet akymy", "Текущий трафик", "Anlık internet akışı")))
        val b = LinearLayout(this).apply { orientation = LinearLayout.VERTICAL; setPadding(dpi(14), dpi(14), dpi(14), dpi(14)); background = glass(20f, Color.argb(140, 111, 219, 156)) }
        val r = LinearLayout(this).apply { orientation = LinearLayout.HORIZONTAL }
        fun cell(arrow: String, lbl: String, tv: TextView, col_: Int) = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL; gravity = Gravity.CENTER
            setPadding(0, dpi(10), 0, dpi(10)); background = box(Color.argb(90, 6, 18, 12), Color.argb(70, Color.red(col_), Color.green(col_), Color.blue(col_)), 14f)
            addView(text(arrow, 18f, col_, true).apply { gravity = Gravity.CENTER }, LinearLayout.LayoutParams(-1, -2))
            addView(text(lbl, 10f, C.MUTED, true).apply { letterSpacing = 0.18f; gravity = Gravity.CENTER }, LinearLayout.LayoutParams(-1, -2))
            tv.gravity = Gravity.CENTER
            addView(tv, LinearLayout.LayoutParams(-1, -2).apply { topMargin = dpi(4) })
        }
        bigDown = mono("0 B/s", 20f, C.GREEN); bigUp = mono("0 B/s", 20f, C.GOLD)
        r.addView(cell("↓", t("ÝÜKLEME", "ЗАГРУЗКА", "İNDİRME"), bigDown!!, C.GREEN), LinearLayout.LayoutParams(0, -2, 1f).apply { rightMargin = dpi(8) })
        r.addView(cell("↑", t("IBERME", "ОТДАЧА", "GÖNDERME"), bigUp!!, C.GOLD), LinearLayout.LayoutParams(0, -2, 1f))
        b.addView(r)
        bigSpark = Spark(this)
        val sf = FrameLayout(this)
        sf.addView(bigSpark, FrameLayout.LayoutParams(-1, -1))
        offHint = text(t("VPN-e birikiň", "Подключите VPN", "VPN'e bağlanın"), 13f, C.MUTED).apply { gravity = Gravity.CENTER }
        sf.addView(offHint, FrameLayout.LayoutParams(-1, -1))
        b.addView(sf, LinearLayout.LayoutParams(-1, dpi(110)).apply { topMargin = dpi(12) })
        col.addView(b)
        val g = LinearLayout(this).apply { orientation = LinearLayout.HORIZONTAL }
        val pb = LinearLayout(this).apply { orientation = LinearLayout.VERTICAL; gravity = Gravity.CENTER; background = glass(18f) }
        pb.addView(text("PING", 10f, C.MUTED, true).apply { letterSpacing = 0.2f; gravity = Gravity.CENTER }, LinearLayout.LayoutParams(-1, -2))
        pingTv = mono("—", 22f, C.GOLD).apply { gravity = Gravity.CENTER }; pb.addView(pingTv, LinearLayout.LayoutParams(-1, -2))
        g.addView(pb, LinearLayout.LayoutParams(0, dpi(86), 1f).apply { rightMargin = dpi(10) })
        val tb = LinearLayout(this).apply { orientation = LinearLayout.VERTICAL; gravity = Gravity.CENTER; background = glass(18f) }
        tb.addView(text(t("JEMI", "ВСЕГО", "TOPLAM"), 10f, C.MUTED, true).apply { letterSpacing = 0.2f; gravity = Gravity.CENTER }, LinearLayout.LayoutParams(-1, -2))
        totals = mono("—", 14f, C.TEXT).apply { gravity = Gravity.CENTER }; tb.addView(totals, LinearLayout.LayoutParams(-1, -2))
        g.addView(tb, LinearLayout.LayoutParams(0, dpi(86), 1.3f))
        col.addView(g, LinearLayout.LayoutParams(-1, -2).apply { topMargin = dpi(12) })
        return col
    }

    private fun settingsPage(): View {
        val col = content()
        col.addView(title(t("Sazlamalar", "Настройки", "Ayarlar"), null))
        col.addView(option(R.drawable.nav_globe, t("Dil", "Язык", "Dil"), "${Lang.flags[Lang.cur]} ${Lang.names[Lang.cur]}") { langDialog() })
        col.addView(option(R.drawable.nav_home, t("Serwerleri täzele", "Обновить серверы", "Sunucuları yenile"),
            t("Abunany häzir täzeden al", "Получить подписку заново", "Aboneliği şimdi yeniden al")) { refresh() })
        col.addView(option(R.drawable.nav_info, t("Täze wersiýa", "Новая версия", "Yeni sürüm"),
            t("Häzirki wersiýa ${ver()}", "Текущая версия ${ver()}", "Mevcut sürüm ${ver()}")) {
            bg { Sub.refresh(this); ui { if (Upd.available(ver()) != null) update() else Toast.makeText(this, t("Iň täze wersiýa gurnalan", "Установлена последняя версия", "En yeni sürüm yüklü"), Toast.LENGTH_SHORT).show() } }
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
        col.addView(title(t("Maglumat", "О программе", "Hakkında"), null), LinearLayout.LayoutParams(-1, -2))
        val b = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL; gravity = Gravity.CENTER_HORIZONTAL
            setPadding(dpi(18), dpi(18), dpi(18), dpi(22)); background = glass(22f)
        }
        b.addView(ImageView(this).apply { setImageResource(R.drawable.logo_full); adjustViewBounds = true; clipToOutline = true; background = box(C.CREAM, C.GOLD, 18f) },
            LinearLayout.LayoutParams(-1, -2))
        b.addView(text(t("Wersiýa ${ver()}", "Версия ${ver()}", "Sürüm ${ver()}"), 13f, C.MUTED).apply { setPadding(0, dpi(14), 0, 0) })
        b.addView(text(t("Türkmenistan üçin çalt we howpsuz VPN.", "Быстрый и безопасный VPN для Туркменистана.", "Türkmenistan için hızlı ve güvenli VPN.") +
            "\nHysteria2 · Shadowsocks · VLESS", 13f, C.MUTED).apply { gravity = Gravity.CENTER; setPadding(0, dpi(10), 0, 0) })
        col.addView(b, LinearLayout.LayoutParams(-1, -2))
        return col
    }

    private fun option(icon: Int, tt: String, sub: String, on: () -> Unit) = LinearLayout(this).apply {
        orientation = LinearLayout.HORIZONTAL; gravity = Gravity.CENTER_VERTICAL
        setPadding(dpi(14), dpi(12), dpi(14), dpi(12)); minimumHeight = dpi(66); background = glass(18f)
        addView(ImageView(this@Main).apply { setImageResource(icon); setColorFilter(C.GOLD, PorterDuff.Mode.SRC_IN) }, LinearLayout.LayoutParams(dpi(24), dpi(24)))
        val c = LinearLayout(this@Main).apply { orientation = LinearLayout.VERTICAL; setPadding(dpi(12), 0, 0, 0) }
        c.addView(text(tt, 15f, C.TEXT, true)); c.addView(text(sub, 12f, C.MUTED))
        addView(c, LinearLayout.LayoutParams(0, -2, 1f))
        addView(Ico(this@Main, "next", C.MUTED, 18f))
        setOnClickListener { on() }
        pressFx()
        layoutParams = LinearLayout.LayoutParams(-1, -2).apply { bottomMargin = dpi(10) }
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
        card.addView(flag(f, C.GOLD))
        card.addView(View(this).apply { setBackgroundColor(Color.argb(150, 224, 176, 74)) },
            LinearLayout.LayoutParams(dpi(1), dpi(34)).apply { leftMargin = dpi(12); rightMargin = dpi(12) })
        c.addView(text(c1, 16f, C.TEXT, true)); c.addView(text(c2, 12f, C.MUTED).apply { oneLine() })
        card.addView(c, LinearLayout.LayoutParams(0, -2, 1f))
        card.addView(Ico(this, "next", C.GOLD, 18f))
    }

    private fun renderState() {
        val st = State.now
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
        if (u != null) bar.text = "⬆  " + t("Täze wersiýa ${u.first} · Täzele", "Новая версия ${u.first} · Обновить", "Yeni sürüm ${u.first} · Güncelle")
    }

    private fun update() {
        val u = Upd.available(ver()) ?: return
        if (downloading) return
        downloading = true
        val lbl = t("Ýüklenýär…", "Загрузка…", "İndiriliyor…")
        updBar?.text = "$lbl 0%"
        Toast.makeText(this, lbl, Toast.LENGTH_SHORT).show()
        bg {
            val ok = runCatching { Upd.install(this, u.second) { p -> ui { updBar?.text = "$lbl $p%" } } }.isSuccess
            ui {
                downloading = false
                if (!ok) Toast.makeText(this, t("Ýüklenmedi, internedi barlaň", "Не загрузилось, проверьте интернет", "İndirilemedi, interneti kontrol edin"), Toast.LENGTH_LONG).show()
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
            cur == null -> t("Açar giriziň", "Введите ключ", "Anahtarı girin")
            cur == 0L -> t("Häzirki açar: çäksiz", "Текущий ключ: безлимит", "Mevcut anahtar: sınırsız")
            else -> ((cur - System.currentTimeMillis()) / 86400000).let { d -> t("Häzirki açar: $d gün galdy", "Текущий ключ: осталось $d дн.", "Mevcut anahtar: $d gün kaldı") }
        }
        val v = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL; gravity = Gravity.CENTER_HORIZONTAL
            setPadding(dpi(22), dpi(22), dpi(22), dpi(18)); background = box(Color.argb(245, 8, 22, 16), C.GOLD, 22f)
        }
        v.addView(ImageView(this).apply { setImageResource(R.drawable.logo); clipToOutline = true; background = box(C.CREAM, C.GOLD, 14f) },
            LinearLayout.LayoutParams(dpi(56), dpi(56)))
        v.addView(text(t("AÇAR", "КЛЮЧ", "ANAHTAR"), 18f, C.TEXT, true).apply { letterSpacing = 0.25f; setPadding(0, dpi(10), 0, dpi(2)) })
        v.addView(text(info, 12f, C.MUTED).apply { setPadding(0, 0, 0, dpi(14)) })
        v.addView(e, LinearLayout.LayoutParams(-1, -2))
        val btn = text(t("BARLA", "ПРОВЕРИТЬ", "KONTROL ET"), 15f, C.BG, true).apply {
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
        val bad = t("Açar nädogry ýa-da möhleti geçdi", "Неверный или истёкший ключ", "Anahtar geçersiz ya da süresi dolmuş")
        if (k.length != 14) { Toast.makeText(this, bad, Toast.LENGTH_SHORT).show(); return }
        val old = Lic.saved(this)
        Lic.save(this, k)
        bg {
            if (Lic.exp(this) == null) Sub.refresh(this)
            val ok = Lic.exp(this) != null
            ui {
                if (!ok) Lic.save(this, old)
                Toast.makeText(this, if (ok) "✅ " + t("Açar kabul edildi", "Ключ принят", "Anahtar kabul edildi") else bad, Toast.LENGTH_LONG).show()
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
        setPadding(dpi(12), dpi(10), dpi(12), dpi(10)); minimumHeight = dpi(66)
        background = if (sel) glass(18f, C.GREEN) else glass(18f, Color.argb(100, 224, 176, 74))
        setOnClickListener { on() }
        pressFx()
        layoutParams = LinearLayout.LayoutParams(-1, -2).apply { bottomMargin = dpi(9) }
    }

    private fun row(s: Server, sel: Boolean): View {
        val r = rowBase(sel) { pick(s) }
        r.addView(flag(s.flag, if (sel) C.GREEN else C.GOLD))
        val c = LinearLayout(this).apply { orientation = LinearLayout.VERTICAL; setPadding(dpi(12), 0, dpi(8), 0) }
        c.addView(text(s.country, 15f, C.TEXT, true)); c.addView(text(sub(s), 12f, C.MUTED).apply { oneLine() })
        r.addView(c, LinearLayout.LayoutParams(0, -2, 1f))
        val (mt, mc) = msText(ms[s.uri])
        val mv = mono(mt, 13f, mc); msViews[s.uri] = mv; r.addView(mv)
        if (sel) r.addView(Ico(this, "check", C.GREEN, 20f, 2.4f), LinearLayout.LayoutParams(-2, -2).apply { leftMargin = dpi(8) })
        return r
    }

    private fun autoRow(sel: Boolean): View {
        val r = rowBase(sel) { pick(null) }
        r.addView(flag("⚡", if (sel) C.GREEN else C.GOLD))
        val c = LinearLayout(this).apply { orientation = LinearLayout.VERTICAL; setPadding(dpi(12), 0, dpi(8), 0) }
        c.addView(text(t("Awtomatik", "Авто", "Otomatik"), 15f, C.TEXT, true))
        c.addView(text(t("Iň çalt serwere özi birigýär", "Сам выбирает самый быстрый", "En hızlı sunucuya kendisi bağlanır"), 12f, C.MUTED).apply { oneLine() })
        r.addView(c, LinearLayout.LayoutParams(0, -2, 1f))
        if (sel) r.addView(Ico(this, "check", C.GREEN, 20f, 2.4f))
        return r
    }

    private fun pick(s: Server?) {
        State.select(this, s)
        if (State.now == State.ON) startVpn()
        show(Page.MAIN)
    }

    private fun refresh() {
        Toast.makeText(this, t("Täzelenýär…", "Обновление…", "Yenileniyor…"), Toast.LENGTH_SHORT).show()
        bg {
            val ok = Sub.refresh(this)
            ui {
                Toast.makeText(this, if (ok) t("Täzelendi", "Обновлено", "Yenilendi") else t("Täzelenmedi", "Не обновилось", "Yenilenemedi"), Toast.LENGTH_SHORT).show()
                ms.clear(); if (cur == Page.SERVERS) show(Page.SERVERS) else renderState()
            }
        }
    }

    private fun paintMs() { for ((uri, v) in msViews) { val (tt, c) = msText(ms[uri]); v.text = tt; v.setTextColor(c) } }

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

    private fun text(tx: String, sp: Float, color: Int, bold: Boolean = false) = TextView(this).apply {
        text = tx; textSize = sp; setTextColor(color)
        if (bold) typeface = Typeface.create(Typeface.DEFAULT, Typeface.BOLD)
    }
    private fun mono(tx: String, sp: Float, color: Int) = text(tx, sp, color).apply { typeface = Typeface.create(Typeface.MONOSPACE, Typeface.BOLD) }

    private fun TextView.oneLine() { maxLines = 1; ellipsize = TextUtils.TruncateAt.END }

    private fun flag(f: String, border: Int) = TextView(this).apply {
        text = f; textSize = 22f; gravity = Gravity.CENTER
        background = GradientDrawable().apply { shape = GradientDrawable.OVAL; setColor(C.BG); setStroke(dpi(2), border) }
        layoutParams = LinearLayout.LayoutParams(dpi(46), dpi(46))
        importantForAccessibility = View.IMPORTANT_FOR_ACCESSIBILITY_NO
    }

    private fun iconBtn(kind: String, color: Int, on: () -> Unit) = FrameLayout(this).apply {
        background = glass(14f, Color.argb(160, 224, 176, 74))
        contentDescription = t("Täzele", "Обновить", "Yenile")
        minimumWidth = dpi(42)
        addView(Ico(this@Main, kind, color, 20f), FrameLayout.LayoutParams(-2, -2, Gravity.CENTER))
        setOnClickListener { on() }
        pressFx()
    }

    private fun bg(f: () -> Unit) = Thread(f).start()
    private fun ui(f: () -> Unit) = runOnUiThread { if (!isDestroyed) f() }

    companion object {
        const val GO = "tm.yol.vpn.GO"
        const val INSTALLED = "tm.yol.vpn.INSTALLED"
    }
}
