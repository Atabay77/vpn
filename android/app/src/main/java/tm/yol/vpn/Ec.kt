package tm.yol.vpn

import java.math.BigInteger
import java.security.AlgorithmParameters
import java.security.KeyFactory
import java.security.KeyPair
import java.security.spec.ECFieldFp
import java.security.spec.ECGenParameterSpec
import java.security.spec.ECParameterSpec
import java.security.spec.ECPoint
import java.security.spec.ECPrivateKeySpec
import java.security.spec.ECPublicKeySpec

/** 1.47.31: P-256 açar jübüti berlen 32 baýtdan (her gezek şol bir açar) — DM açary programma gaýtadan gurnalanda üýtgemesin. */
object Ec {
    private val spec: ECParameterSpec by lazy {
        AlgorithmParameters.getInstance("EC").apply { init(ECGenParameterSpec("secp256r1")) }.getParameterSpec(ECParameterSpec::class.java)
    }

    fun keyPair(seed: ByteArray): KeyPair {
        val n = spec.order
        val d = BigInteger(1, seed).mod(n.subtract(BigInteger.ONE)).add(BigInteger.ONE)
        val q = mul(d, spec.generator)
        val kf = KeyFactory.getInstance("EC")
        return KeyPair(kf.generatePublic(ECPublicKeySpec(q, spec)), kf.generatePrivate(ECPrivateKeySpec(d, spec)))
    }

    private val P: BigInteger get() = (spec.curve.field as ECFieldFp).p

    private fun add(a: ECPoint, b: ECPoint): ECPoint {
        if (a == ECPoint.POINT_INFINITY) return b
        if (b == ECPoint.POINT_INFINITY) return a
        val p = P
        val lam = if (a.affineX == b.affineX) {
            if (a.affineY.add(b.affineY).mod(p) == BigInteger.ZERO) return ECPoint.POINT_INFINITY
            a.affineX.pow(2).multiply(BigInteger.valueOf(3)).add(spec.curve.a).multiply(a.affineY.shiftLeft(1).modInverse(p)).mod(p)
        } else b.affineY.subtract(a.affineY).multiply(b.affineX.subtract(a.affineX).modInverse(p)).mod(p)
        val x = lam.pow(2).subtract(a.affineX).subtract(b.affineX).mod(p)
        val y = lam.multiply(a.affineX.subtract(x)).subtract(a.affineY).mod(p)
        return ECPoint(x, y)
    }

    private fun mul(k: BigInteger, g: ECPoint): ECPoint {
        var r = ECPoint.POINT_INFINITY; var q = g
        for (i in 0 until k.bitLength()) {
            if (k.testBit(i)) r = add(r, q)
            q = add(q, q)
        }
        return r
    }
}
