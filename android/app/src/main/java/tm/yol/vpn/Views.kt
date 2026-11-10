package tm.yol.vpn

import android.content.Context
import android.graphics.Canvas
import android.graphics.Color
import android.graphics.Paint
import android.graphics.Path
import android.graphics.RectF
import android.graphics.drawable.GradientDrawable
import android.view.View

object C {
    val BG = Color.parseColor("#0A1C14")
    val CARD = Color.parseColor("#12281D")
    val CARD_SEL = Color.parseColor("#143524")
    val LINE = Color.parseColor("#24483A")
    val TEXT = Color.parseColor("#F2EFE6")
    val MUTED = Color.parseColor("#9DB3A6")
    val GOLD = Color.parseColor("#E0B04A")
    val RED = Color.parseColor("#A61E2B")
    val CREAM = Color.parseColor("#F3E7D0")
    val GREEN = Color.parseColor("#6FDB9C")
    val GREEN_BG = Color.parseColor("#12784A")
    val BAD = Color.parseColor("#E06A5A")
}

fun Context.dp(v: Float) = v * resources.displayMetrics.density
fun Context.dpi(v: Int) = (v * resources.displayMetrics.density).toInt()

fun Context.box(fill: Int, stroke: Int, radiusDp: Float, strokeDp: Float = 1f) = GradientDrawable().apply {
    setColor(fill); cornerRadius = dp(radiusDp); setStroke(dp(strokeDp).toInt().coerceAtLeast(1), stroke)
}

/** Kırmızı halı şeridi, göl motifleriyle. vertical=true: ana ekrandaki sol şerit. */
class Carpet(ctx: Context, private val vertical: Boolean, private val count: Int) : View(ctx) {
    fun count() = count
    fun len() = if (vertical) height.toFloat() else width.toFloat()
    fun pad() = if (vertical) context.dp(28f) else context.dp(12f)
    private val p = Paint(Paint.ANTI_ALIAS_FLAG)
    private val path = Path()

    private fun diamond(c: Canvas, cx: Float, cy: Float, hw: Float, hh: Float, color: Int) {
        p.color = color
        path.reset()
        path.moveTo(cx, cy - hh); path.lineTo(cx + hw, cy); path.lineTo(cx, cy + hh); path.lineTo(cx - hw, cy); path.close()
        c.drawPath(path, p)
    }

    override fun onDraw(c: Canvas) {
        c.drawColor(C.RED)
        p.color = C.GOLD
        val line = context.dp(2f)
        if (vertical) c.drawRect(width - line, 0f, width.toFloat(), height.toFloat(), p)
        else c.drawRect(0f, height - line, width.toFloat(), height.toFloat(), p)

        val step = (len() - 2 * pad()) / count
        for (i in 0 until count) {
            val along = pad() + step * (i + 0.5f)
            if (vertical) {
                val cx = (width - line) / 2f; val cy = along
                val s = (width - line) / 44f   // şerit daraldıkça motif de küçülür
                diamond(c, cx, cy, 16 * s, 22 * s, C.CREAM)
                diamond(c, cx, cy, 11 * s, 16 * s, C.RED)
                // iki koyu üçgen
                p.color = C.BG
                path.reset(); path.moveTo(cx, cy - 16 * s); path.lineTo(cx + 11 * s, cy); path.lineTo(cx, cy); path.close(); c.drawPath(path, p)
                path.reset(); path.moveTo(cx, cy + 16 * s); path.lineTo(cx - 11 * s, cy); path.lineTo(cx, cy); path.close(); c.drawPath(path, p)
                diamond(c, cx, cy, 5 * s, 7 * s, C.GOLD)
                p.color = C.RED; c.drawCircle(cx, cy, 2 * s, p)
            } else {
                val cx = along; val cy = (height - line) / 2f
                val s = context.dp(1f)
                diamond(c, cx, cy, 12 * s, 9 * s, C.CREAM)
                diamond(c, cx, cy, 8 * s, 6 * s, C.BG)
                diamond(c, cx, cy, 4 * s, 3 * s, C.GOLD)
            }
        }
    }
}

/** Dokunulan göl motifinin sırası (0 = ilk). */
fun Carpet.indexAt(pos: Float): Int = ((pos - pad()) / ((len() - 2 * pad()) / count())).toInt().coerceIn(0, count() - 1)

/** 24 birimlik kutuda çizgi ikonlar. */
class Ico(ctx: Context, private val kind: String, var color: Int, private val sizeDp: Float, private val strokeW: Float = 2f) : View(ctx) {
    private val p = Paint(Paint.ANTI_ALIAS_FLAG).apply {
        style = Paint.Style.STROKE; strokeCap = Paint.Cap.ROUND; strokeJoin = Paint.Join.ROUND
    }

    override fun onMeasure(w: Int, h: Int) {
        val s = context.dp(sizeDp).toInt(); setMeasuredDimension(s, s)
    }

    override fun onDraw(c: Canvas) {
        val k = width / 24f
        p.color = color; p.strokeWidth = strokeW
        c.save(); c.scale(k, k)
        val path = Path()
        when (kind) {
            "back" -> { path.moveTo(15f, 6f); path.lineTo(9f, 12f); path.lineTo(15f, 18f) }
            "next" -> { path.moveTo(9f, 6f); path.lineTo(15f, 12f); path.lineTo(9f, 18f) }
            "check" -> { path.moveTo(5f, 12.5f); path.lineTo(9.5f, 17f); path.lineTo(19f, 7.5f) }
            "refresh" -> {
                path.addArc(RectF(4f, 4f, 20f, 20f), 200f, 130f)
                path.moveTo(4f, 4f); path.lineTo(4f, 8f); path.lineTo(8f, 8f)
                path.addArc(RectF(4f, 4f, 20f, 20f), 20f, 130f)
                path.moveTo(20f, 20f); path.lineTo(20f, 16f); path.lineTo(16f, 16f)
            }
            "menu" -> {
                path.moveTo(5f, 7f); path.lineTo(19f, 7f)
                path.moveTo(5f, 12f); path.lineTo(19f, 12f)
                path.moveTo(5f, 17f); path.lineTo(19f, 17f)
            }
            "home" -> {
                path.moveTo(4f, 11f); path.lineTo(12f, 4f); path.lineTo(20f, 11f)
                path.moveTo(6f, 9.5f); path.lineTo(6f, 20f); path.lineTo(18f, 20f); path.lineTo(18f, 9.5f)
                path.moveTo(10f, 20f); path.lineTo(10f, 14f); path.lineTo(14f, 14f); path.lineTo(14f, 20f)
            }
            "globe" -> {
                path.addCircle(12f, 12f, 8.5f, Path.Direction.CW)
                path.addOval(RectF(8f, 3.5f, 16f, 20.5f), Path.Direction.CW)
                path.moveTo(3.5f, 12f); path.lineTo(20.5f, 12f)
                path.moveTo(5f, 7.5f); path.lineTo(19f, 7.5f); path.moveTo(5f, 16.5f); path.lineTo(19f, 16.5f)
            }
            "gear" -> {
                path.addCircle(12f, 12f, 3f, Path.Direction.CW)
                for (i in 0 until 8) {
                    val an = Math.toRadians(i * 45.0)
                    path.moveTo(12f + 5.5f * Math.cos(an).toFloat(), 12f + 5.5f * Math.sin(an).toFloat())
                    path.lineTo(12f + 8.5f * Math.cos(an).toFloat(), 12f + 8.5f * Math.sin(an).toFloat())
                }
                path.addCircle(12f, 12f, 5.5f, Path.Direction.CW)
            }
            "info" -> {
                path.addCircle(12f, 12f, 8.5f, Path.Direction.CW)
                path.moveTo(12f, 11f); path.lineTo(12f, 16.5f); path.moveTo(12f, 7.6f); path.lineTo(12f, 7.7f)
            }
            "gauge" -> {
                path.addArc(RectF(4f, 10f, 20f, 26f), 180f, 180f)
                path.moveTo(12f, 18f); path.lineTo(16f, 12f)
            }
        }
        c.drawPath(path, p)
        c.restore()
    }
}

/** Yuvarlak bağlan düğmesi: bağlanırken dönen ışık, bağlıyken nabız gibi parlama. */
class Power(ctx: Context) : View(ctx) {
    private val p = Paint(Paint.ANTI_ALIAS_FLAG)
    private val icon = Path()
    private val arc = RectF()
    var on = false; set(v) { field = v; invalidate() }
    var busy = false; set(v) { field = v; invalidate() }
    private val t0 = System.currentTimeMillis()

    override fun onMeasure(w: Int, h: Int) {
        val s = context.dp(140f).toInt(); setMeasuredDimension(s, s)
    }

    override fun onDraw(c: Canvas) {
        val cx = width / 2f; val cy = height / 2f
        val r = width / 2f
        val t = (System.currentTimeMillis() - t0) / 1000f
        val accent = if (on) C.GREEN else C.GOLD
        // dış parlama halkaları
        val pulse = if (on) (0.5f + 0.5f * kotlin.math.sin(t * 2.4f)) else 0.35f
        p.style = Paint.Style.STROKE
        for (i in 0..2) {
            p.strokeWidth = context.dp(1f)
            p.color = Color.argb((60 * pulse / (i + 1)).toInt() + 10, Color.red(accent), Color.green(accent), Color.blue(accent))
            c.drawCircle(cx, cy, r - context.dp(2f + i * 5f), p)
        }
        // cam gövde
        p.style = Paint.Style.FILL
        p.color = if (on) Color.argb(200, 18, 120, 74) else Color.argb(170, 10, 28, 20)
        val body = r - context.dp(18f)
        c.drawCircle(cx, cy, body, p)
        // kenar çizgisi
        p.style = Paint.Style.STROKE; p.strokeWidth = context.dp(3f); p.color = accent
        c.drawCircle(cx, cy, body, p)
        // bağlanırken dönen yay
        if (busy) {
            arc.set(cx - body - context.dp(8f), cy - body - context.dp(8f), cx + body + context.dp(8f), cy + body + context.dp(8f))
            p.strokeWidth = context.dp(3f); p.strokeCap = Paint.Cap.ROUND; p.color = C.GOLD
            val a0 = (t * 300f) % 360f
            c.drawArc(arc, a0, 70f, false, p)
            p.color = Color.argb(120, 224, 176, 74); c.drawArc(arc, a0 + 180f, 40f, false, p)
        }
        // güç simgesi
        val s = context.dp(44f) / 24f
        c.save(); c.translate(cx - 12 * s, cy - 12 * s); c.scale(s, s)
        p.strokeCap = Paint.Cap.ROUND; p.strokeWidth = 1.8f
        p.color = if (on) Color.WHITE else if (busy) C.GOLD else C.CREAM
        icon.reset()
        icon.moveTo(12f, 3f); icon.lineTo(12f, 12f)
        icon.addArc(RectF(4f, 5f, 20f, 21f), -47.4f, 274.8f)
        c.drawPath(icon, p)
        c.restore()
        if (on || busy) postInvalidateOnAnimation()
    }
}

/** Son 60 saniyenin hız çizgisi (indirme). */
class Spark(ctx: Context) : View(ctx) {
    private val v = ArrayDeque<Float>()
    private val p = Paint(Paint.ANTI_ALIAS_FLAG)
    private val path = Path()
    fun add(x: Float) { v.addLast(x); while (v.size > 60) v.removeFirst(); invalidate() }
    fun clear() { v.clear(); invalidate() }
    override fun onDraw(c: Canvas) {
        p.style = Paint.Style.STROKE; p.strokeWidth = context.dp(1f); p.color = Color.argb(60, 111, 219, 156)
        c.drawLine(0f, height - context.dp(1f), width.toFloat(), height - context.dp(1f), p)   // taban çizgisi
        if (v.size < 2) return
        val mx = maxOf(v.max(), 1f)
        val dx = width / 59f
        path.reset()
        v.forEachIndexed { i, y ->
            val px = width - (v.size - 1 - i) * dx; val py = height - (y / mx) * (height - context.dp(4f)) - context.dp(2f)
            if (i == 0) path.moveTo(px, py) else path.lineTo(px, py)
        }
        p.style = Paint.Style.STROKE; p.strokeWidth = context.dp(1.6f); p.color = C.GREEN
        c.drawPath(path, p)
        path.lineTo(width.toFloat(), height.toFloat()); path.lineTo(width - (v.size - 1) * dx, height.toFloat()); path.close()
        p.style = Paint.Style.FILL; p.color = Color.argb(40, 111, 219, 156)
        c.drawPath(path, p)
    }
}

/** Dolgun cam kutu: koyu degrade gövde, üstte hafif parlama, ince renkli kenar. */
fun Context.glass(radiusDp: Float = 18f, stroke: Int = Color.argb(130, 224, 176, 74)): android.graphics.drawable.Drawable {
    val r = dp(radiusDp)
    val body = GradientDrawable(GradientDrawable.Orientation.TOP_BOTTOM,
        intArrayOf(Color.argb(215, 20, 48, 35), Color.argb(225, 8, 22, 16))).apply {
        cornerRadius = r; setStroke(dp(1.3f).toInt().coerceAtLeast(2), stroke)
    }
    val sheen = GradientDrawable(GradientDrawable.Orientation.TOP_BOTTOM,
        intArrayOf(Color.argb(34, 255, 255, 255), Color.argb(0, 255, 255, 255))).apply {
        cornerRadii = floatArrayOf(r, r, r, r, 0f, 0f, 0f, 0f)
    }
    return android.graphics.drawable.LayerDrawable(arrayOf(body, sheen)).apply {
        val i = dp(1.5f).toInt()
        setLayerInset(1, i, i, i, 0)
        setLayerGravity(1, android.view.Gravity.TOP or android.view.Gravity.FILL_HORIZONTAL)
        setLayerHeight(1, dp(26f).toInt())
    }
}

/** Arka plan: Higgsfield görseli çok yavaş kayar + parıldayan altın noktalar (saniyede ~30 kare, hafif). */
class AnimBg(ctx: Context, res: Int) : View(ctx) {
    private var bmp: android.graphics.Bitmap? = load(res)
    private var old: android.graphics.Bitmap? = null
    private var fadeAt = 0L
    var res = res; private set

    private fun load(r: Int): android.graphics.Bitmap? = runCatching {
        val o = android.graphics.BitmapFactory.Options().apply { inJustDecodeBounds = true }
        android.graphics.BitmapFactory.decodeResource(context.resources, r, o)
        val sw = context.resources.displayMetrics.widthPixels.coerceAtLeast(720)
        var ss = 1; while (o.outWidth / (ss * 2) >= sw) ss *= 2
        android.graphics.BitmapFactory.decodeResource(context.resources, r, android.graphics.BitmapFactory.Options().apply { inSampleSize = ss })
    }.getOrNull()

    /** Bütün ekran yeni ülkeye yumuşakça geçer. */
    fun change(r: Int) {
        if (r == res) return
        res = r; old = bmp; bmp = load(r); fadeAt = System.currentTimeMillis()
    }

    private fun drawBmp(c: Canvas, b: android.graphics.Bitmap, t: Float, alpha: Int) {
        val s = maxOf(width.toFloat() / b.width, height.toFloat() * 1.18f / b.height) * 1.04f
        val dx = (width - b.width * s) / 2 + kotlin.math.sin(t / 9f) * context.dp(8f)
        val dy = (height - b.height * s) / 2 - height * 0.085f + kotlin.math.cos(t / 11f) * context.dp(6f)   // manzara kutuların üstünde kalsın
        m.setScale(s, s); m.postTranslate(dx, dy); bp.alpha = alpha
        c.drawBitmap(b, m, bp)
    }
    private val m = android.graphics.Matrix()
    private val bp = Paint(Paint.FILTER_BITMAP_FLAG)
    private val dot = Paint(Paint.ANTI_ALIAS_FLAG)
    private val t0 = System.currentTimeMillis()
    private val rnd = java.util.Random(7)
    private val stars = Array(34) { floatArrayOf(rnd.nextFloat(), rnd.nextFloat(), 0.6f + rnd.nextFloat() * 1.6f, rnd.nextFloat() * 6.28f, 0.4f + rnd.nextFloat()) }

    override fun onDraw(c: Canvas) {
        val t = (System.currentTimeMillis() - t0) / 1000f
        val f = ((System.currentTimeMillis() - fadeAt) / 700f).coerceIn(0f, 1f)
        old?.let { if (f < 1f) drawBmp(c, it, t, 255) else old = null }
        bmp?.let { drawBmp(c, it, t, (255 * f).toInt().coerceAtLeast(if (old == null) 255 else 0)) }
        for (st in stars) {
            val a = (0.5f + 0.5f * kotlin.math.sin(t * st[4] * 1.6f + st[3]))
            dot.color = Color.argb((40 + 180 * a).toInt(), 224, 176, 74)
            val y = (st[1] * height - t * context.dp(3f) * st[4]) % height
            c.drawCircle(st[0] * width, if (y < 0) y + height else y, context.dp(st[2]) * (0.7f + 0.3f * a), dot)
        }
        postInvalidateDelayed(33)
    }
}

/** Sol menüdeki iki buton arasındaki küçük halı motifi (göl) ve ince kırmızı çizgi. */
class GulSep(ctx: Context) : View(ctx) {
    private val p = Paint(Paint.ANTI_ALIAS_FLAG)
    private val path = Path()
    override fun onDraw(c: Canvas) {
        val cx = width / 2f; val cy = height / 2f; val s = context.dp(1f)
        p.color = Color.argb(160, 166, 30, 43); p.strokeWidth = s
        c.drawLine(cx, 0f, cx, height.toFloat(), p)
        fun d(hw: Float, col: Int) {
            p.color = col; path.reset()
            path.moveTo(cx, cy - hw); path.lineTo(cx + hw, cy); path.lineTo(cx, cy + hw); path.lineTo(cx - hw, cy); path.close()
            c.drawPath(path, p)
        }
        d(3.5f * s, C.GOLD); d(2.3f * s, C.RED); d(1.1f * s, C.CREAM)
    }
}

/** Açılıştaki dönen altın halka. */
class Spinner(ctx: Context) : View(ctx) {
    private val p = Paint(Paint.ANTI_ALIAS_FLAG).apply { style = Paint.Style.STROKE; strokeCap = Paint.Cap.ROUND }
    private val r = RectF()
    override fun onDraw(c: Canvas) {
        val w = context.dp(3f); p.strokeWidth = w
        r.set(w, w, width - w, height - w)
        p.color = Color.argb(50, 224, 176, 74); c.drawArc(r, 0f, 360f, false, p)
        p.color = C.GOLD; c.drawArc(r, (System.currentTimeMillis() % 1000) * 0.36f, 90f, false, p)
        postInvalidateOnAnimation()
    }
}

/** Kenarında neon ışık dönen hap şeklinde düğme zemini (yeni sürüm bildirimi). */
class NeonBar(ctx: Context) : android.widget.FrameLayout(ctx) {
    private val p = Paint(Paint.ANTI_ALIAS_FLAG).apply { style = Paint.Style.STROKE; strokeCap = Paint.Cap.ROUND }
    private val fill = Paint(Paint.ANTI_ALIAS_FLAG)
    private val path = Path(); private val seg = Path()
    private val pm = android.graphics.PathMeasure()
    private val rf = RectF()
    private val t0 = System.currentTimeMillis()
    init { setWillNotDraw(false) }

    override fun onSizeChanged(w: Int, h: Int, ow: Int, oh: Int) {
        val i = context.dp(3f)
        rf.set(i, i, w - i, h - i)
        path.reset(); path.addRoundRect(rf, (h - 2 * i) / 2f, (h - 2 * i) / 2f, Path.Direction.CW)
        pm.setPath(path, true)
    }

    override fun onDraw(c: Canvas) {
        val r = (height - context.dp(6f)) / 2f
        fill.color = Color.argb(235, 12, 30, 22); c.drawRoundRect(rf, r, r, fill)
        p.strokeWidth = context.dp(1f); p.color = Color.argb(70, 224, 176, 74); c.drawRoundRect(rf, r, r, p)
        val len = pm.length; if (len <= 0f) return
        val head = ((System.currentTimeMillis() - t0) % 2600) / 2600f * len
        val tail = len * 0.45f
        // iz: arkaya doğru solan parçalar, önde parlak baş
        val steps = 18
        for (k in 0 until steps) {
            val a = 1f - k / steps.toFloat()
            var e = head - tail * k / steps
            if (e < 0) e += len
            val s = e - tail / steps
            seg.reset()
            if (s >= 0) pm.getSegment(s, e, seg, true)
            else { pm.getSegment(len + s, len, seg, true); pm.getSegment(0f, e, seg, true) }
            val col = if (k < steps / 2) C.GOLD else C.GREEN
            p.color = Color.argb((220 * a * a).toInt(), Color.red(col), Color.green(col), Color.blue(col))
            p.strokeWidth = context.dp(1.2f + 2.4f * a)
            c.drawPath(seg, p)
            p.color = Color.argb((60 * a).toInt(), Color.red(col), Color.green(col), Color.blue(col))
            p.strokeWidth = context.dp(6f * a + 2f)
            c.drawPath(seg, p)
        }
        postInvalidateOnAnimation()
    }
}
