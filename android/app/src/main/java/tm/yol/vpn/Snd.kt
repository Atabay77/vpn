package tm.yol.vpn

import android.content.Context
import android.media.AudioAttributes
import android.media.SoundPool

/** ElevenLabs ile üretilmiş kısa arayüz sesleri. Ayarlardan kapatılabilir. */
object Snd {
    private var pool: SoundPool? = null
    private val ids = HashMap<Int, Int>()
    fun on(ctx: Context) = ctx.getSharedPreferences("p", 0).getBoolean("snd", true)
    fun setOn(ctx: Context, v: Boolean) = ctx.getSharedPreferences("p", 0).edit().putBoolean("snd", v).apply()

    fun init(ctx: Context) {
        if (pool != null) return
        val p = SoundPool.Builder().setMaxStreams(2).setAudioAttributes(
            AudioAttributes.Builder().setUsage(AudioAttributes.USAGE_ASSISTANCE_SONIFICATION)
                .setContentType(AudioAttributes.CONTENT_TYPE_SONIFICATION).build()).build()
        for (r in listOf(R.raw.on, R.raw.off, R.raw.tap)) ids[r] = p.load(ctx, r, 1)
        pool = p
    }

    fun play(ctx: Context, res: Int, vol: Float = 0.7f) {
        if (!on(ctx)) return
        ids[res]?.let { pool?.play(it, vol, vol, 1, 0, 1f) }
    }
}
