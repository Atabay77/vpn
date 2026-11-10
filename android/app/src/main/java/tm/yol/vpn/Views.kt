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
        val s = context.dp(176f).toInt(); setMeasuredDimension(s, s)
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
        val s = context.dp(56f) / 24f
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

/** Yarı saydam «cam» kutu (cyber görünüm). */
fun Context.glass(radiusDp: Float = 18f, stroke: Int = Color.argb(110, 224, 176, 74)) =
    box(Color.argb(120, 10, 28, 20), stroke, radiusDp)

/** Ana ekranın canlı arka planı: sessiz, döngülü video, ekranı kaplayacak şekilde kırpılır. */
class VideoBg(ctx: Context, private val res: Int) : android.view.TextureView(ctx), android.view.TextureView.SurfaceTextureListener {
    private var mp: android.media.MediaPlayer? = null
    private var vw = 0; private var vh = 0

    init { surfaceTextureListener = this; isOpaque = false }

    override fun onSurfaceTextureAvailable(st: android.graphics.SurfaceTexture, w: Int, h: Int) {
        runCatching {
            val m = android.media.MediaPlayer.create(context, res) ?: return
            m.setSurface(android.view.Surface(st))
            m.isLooping = true
            m.setVolume(0f, 0f)
            m.setOnVideoSizeChangedListener { _, a, b -> vw = a; vh = b; crop() }
            m.start()
            mp = m
        }
    }

    private fun crop() {
        if (vw == 0 || vh == 0 || width == 0 || height == 0) return
        val s = maxOf(width.toFloat() / vw, height.toFloat() / vh)
        val m = android.graphics.Matrix()
        m.setScale(vw * s / width, vh * s / height, width / 2f, height / 2f)
        setTransform(m)
    }

    override fun onSurfaceTextureSizeChanged(st: android.graphics.SurfaceTexture, w: Int, h: Int) = crop()
    override fun onSurfaceTextureDestroyed(st: android.graphics.SurfaceTexture): Boolean {
        runCatching { mp?.release() }; mp = null; return true
    }
    override fun onSurfaceTextureUpdated(st: android.graphics.SurfaceTexture) {}
}
