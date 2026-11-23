/* Türkmen VPN — ýerli gorag (native).
 * 1) Abuna salgysy (SUB_URL) diňe şu ýerde XOR-ly durýar.
 * 2) 1.47.16: «#tvy» kod sanawy programmanyň gol şahadatnamasyna bagly açar bilen açylýar:
 *    açar = SHA-256("tvy1|" fid "|" salt "|" mask "|" şahadatnama_SHA-256). Şahadatnama APK faýlynyň
 *    v2/v3 gol blogyndan göni okalýar (libc däl — ulgam çagyryşy). Gaýtadan gollanan (üýtgedilen) APK
 *    başga şahadatnama berýär → açar nädogry → sanaw açylmaýar. Dogry şahadatnama programmada ýok
 *    (deňeşdirme ýok) — ony diňe bot bilýär.
 * 3) Barlaglar (bot «mask» bilen haýsylarynyň zäherleýändigini saýlaýar): TracerPid, Frida, inode,
 *    öz kodunyň möhüri (seal), paket ady, APK ýoly, birnäçe gol blogy deň däl.
 * Setirler we SHA-256 hemişelikleri her derlemede başga açar bilen XOR-ly (sec_str.h). */
#define _GNU_SOURCE
#include <stdint.h>
#include <stddef.h>
#include <string.h>
#include <stdlib.h>
#include <stdio.h>
#include <errno.h>
#include <fcntl.h>
#include <unistd.h>
#include <pthread.h>
#include <dlfcn.h>
#include <elf.h>
#include <sys/stat.h>
#include <sys/syscall.h>
#include "sec_data.h"
#include "sec_str.h"
#ifndef YTEST
#include <jni.h>
#endif

#define F_NOCERT 0x001u
#define F_TRACER 0x002u
#define F_FRIDA  0x004u
#define F_INODE  0x008u
#define F_SEAL   0x010u
#define F_MULTI  0x020u
#define F_PATH   0x040u
#define F_PMFB   0x080u   /* diňe mask: faýldan okap bolmasa PackageManager şahadatnamasy */
#define F_PKG    0x100u
#define F_SEALNA 0x200u
#define F_NOMAPS 0x400u
#define F_POISON (F_TRACER | F_FRIDA | F_INODE | F_SEAL | F_MULTI | F_PATH | F_PKG | F_SEALNA | F_NOMAPS)

/* ---------- ulgam çagyryşlary (libc-den geçmeýär: IO gönükdirijiler tutup bilmeýär) ---------- */
#if defined(__aarch64__)
static inline long rs(long n, long a, long b, long c, long d) {
    register long x8 __asm__("x8") = n;
    register long x0 __asm__("x0") = a;
    register long x1 __asm__("x1") = b;
    register long x2 __asm__("x2") = c;
    register long x3 __asm__("x3") = d;
    __asm__ volatile("svc #0" : "+r"(x0) : "r"(x8), "r"(x1), "r"(x2), "r"(x3) : "memory", "cc");
    return x0;
}
#elif defined(__x86_64__)
static inline long rs(long n, long a, long b, long c, long d) {
    long ret;
    register long r10 __asm__("r10") = d;
    __asm__ volatile("syscall" : "=a"(ret) : "a"(n), "D"(a), "S"(b), "d"(c), "r"(r10) : "rcx", "r11", "memory");
    return ret;
}
#else
static long rs(long n, long a, long b, long c, long d) {
    long r = syscall(n, a, b, c, d);
    return r == -1 ? -errno : r;
}
#endif

static int r_open(const char *p, int fl) { long r = rs(__NR_openat, AT_FDCWD, (long) p, fl | O_RDONLY | O_CLOEXEC, 0); return r < 0 ? -1 : (int) r; }
static long r_read(int fd, void *b, size_t n) { return rs(__NR_read, fd, (long) b, (long) n, 0); }
static void r_close(int fd) { rs(__NR_close, fd, 0, 0, 0); }
static long r_lseek(int fd, long off, int wh) { return rs(__NR_lseek, fd, off, wh, 0); }
static long r_getdents(int fd, void *b, size_t n) { return rs(__NR_getdents64, fd, (long) b, (long) n, 0); }
static int r_fstat(int fd, struct stat *st) {
#if defined(__LP64__)
    return (int) rs(__NR_fstat, fd, (long) st, 0, 0);
#else
    return (int) rs(__NR_fstat64, fd, (long) st, 0, 0);
#endif
}

static void wipe(void *p, size_t n) { volatile unsigned char *q = (volatile unsigned char *) p; while (n--) *q++ = 0; }

/* gizlin setir: i belgili setir o-a açylýar (ulanylandan soň wipe) */
static size_t ds(int i, char *o, size_t cap) {
    if (i < 0 || i >= SCOUNT) { o[0] = 0; return 0; }
    size_t off = SO[i], len = SL[i];
    if (len + 1 > cap) len = cap - 1;
    for (size_t k = 0; k < len; k++) o[k] = (char) (SS[off + k] ^ SX[off + k]);
    o[len] = 0;
    return len;
}

/* ---------- SHA-256 / HMAC (hemişelikler maskaly) ---------- */
typedef struct { uint32_t h[8]; uint64_t n; uint8_t b[64]; uint32_t bl; } Sh;
#define ROR(x, k) (((x) >> (k)) | ((x) << (32 - (k))))
static void sh_blk(Sh *c, const uint8_t *p) {
    uint32_t w[64], a, b, cc, d, e, f, g, h;
    for (int i = 0; i < 16; i++) w[i] = (uint32_t) p[4 * i] << 24 | (uint32_t) p[4 * i + 1] << 16 | (uint32_t) p[4 * i + 2] << 8 | p[4 * i + 3];
    for (int i = 16; i < 64; i++) {
        uint32_t s0 = ROR(w[i - 15], 7) ^ ROR(w[i - 15], 18) ^ (w[i - 15] >> 3);
        uint32_t s1 = ROR(w[i - 2], 17) ^ ROR(w[i - 2], 19) ^ (w[i - 2] >> 10);
        w[i] = w[i - 16] + s0 + w[i - 7] + s1;
    }
    a = c->h[0]; b = c->h[1]; cc = c->h[2]; d = c->h[3]; e = c->h[4]; f = c->h[5]; g = c->h[6]; h = c->h[7];
    for (int i = 0; i < 64; i++) {
        uint32_t S1 = ROR(e, 6) ^ ROR(e, 11) ^ ROR(e, 25), ch = (e & f) ^ (~e & g);
        uint32_t t1 = h + S1 + ch + (KX[i] ^ KM[i]) + w[i];
        uint32_t S0 = ROR(a, 2) ^ ROR(a, 13) ^ ROR(a, 22), mj = (a & b) ^ (a & cc) ^ (b & cc);
        uint32_t t2 = S0 + mj;
        h = g; g = f; f = e; e = d + t1; d = cc; cc = b; b = a; a = t1 + t2;
    }
    c->h[0] += a; c->h[1] += b; c->h[2] += cc; c->h[3] += d; c->h[4] += e; c->h[5] += f; c->h[6] += g; c->h[7] += h;
    wipe(w, sizeof w);
}
static void sh_init(Sh *c) { for (int i = 0; i < 8; i++) c->h[i] = HX[i] ^ HM[i]; c->n = 0; c->bl = 0; }
static void sh_up(Sh *c, const void *d, size_t len) {
    const uint8_t *p = (const uint8_t *) d;
    c->n += len;
    while (len) {
        uint32_t k = 64 - c->bl;
        if (k > len) k = (uint32_t) len;
        memcpy(c->b + c->bl, p, k); c->bl += k; p += k; len -= k;
        if (c->bl == 64) { sh_blk(c, c->b); c->bl = 0; }
    }
}
static void sh_fin(Sh *c, uint8_t o[32]) {
    uint64_t bits = c->n * 8; uint8_t pad = 0x80, z = 0, L[8];
    sh_up(c, &pad, 1);
    while (c->bl != 56) sh_up(c, &z, 1);
    for (int i = 0; i < 8; i++) L[i] = (uint8_t) (bits >> (56 - 8 * i));
    sh_up(c, L, 8);
    for (int i = 0; i < 8; i++) { o[4 * i] = (uint8_t) (c->h[i] >> 24); o[4 * i + 1] = (uint8_t) (c->h[i] >> 16); o[4 * i + 2] = (uint8_t) (c->h[i] >> 8); o[4 * i + 3] = (uint8_t) c->h[i]; }
    wipe(c, sizeof *c);
}
static void sha(const void *d, size_t n, uint8_t o[32]) { Sh c; sh_init(&c); sh_up(&c, d, n); sh_fin(&c, o); }
static void hmac2(const uint8_t *k, size_t kl, const void *d1, size_t l1, const void *d2, size_t l2, uint8_t o[32]) {
    uint8_t kb[64], ip[64], op[64], ih[32]; Sh c;
    memset(kb, 0, sizeof kb);
    if (kl > 64) sha(k, kl, kb); else memcpy(kb, k, kl);
    for (int i = 0; i < 64; i++) { ip[i] = kb[i] ^ 0x36; op[i] = kb[i] ^ 0x5c; }
    sh_init(&c); sh_up(&c, ip, 64); if (l1) sh_up(&c, d1, l1); if (l2) sh_up(&c, d2, l2); sh_fin(&c, ih);
    sh_init(&c); sh_up(&c, op, 64); sh_up(&c, ih, 32); sh_fin(&c, o);
    wipe(kb, 64); wipe(ip, 64); wipe(op, 64); wipe(ih, 32);
}
static void tohex(const uint8_t *b, size_t n, char *o) {
    static const char hx[] = "0123456789abcdef";
    for (size_t i = 0; i < n; i++) { o[2 * i] = hx[b[i] >> 4]; o[2 * i + 1] = hx[b[i] & 15]; }
    o[2 * n] = 0;
}
static int ct_eq(const uint8_t *a, const uint8_t *b, size_t n) { uint8_t r = 0; for (size_t i = 0; i < n; i++) r |= a[i] ^ b[i]; return r == 0; }

static int b64v(int ch) {
    if (ch >= 'A' && ch <= 'Z') return ch - 'A';
    if (ch >= 'a' && ch <= 'z') return ch - 'a' + 26;
    if (ch >= '0' && ch <= '9') return ch - '0' + 52;
    if (ch == '-' || ch == '+') return 62;
    if (ch == '_' || ch == '/') return 63;
    return -1;
}
static uint8_t *b64d(const char *s, size_t sl, size_t *ol) {
    uint8_t *o = (uint8_t *) malloc(sl * 3 / 4 + 4);
    if (!o) return NULL;
    size_t n = 0; uint32_t acc = 0; int bits = 0;
    for (size_t i = 0; i < sl; i++) {
        if (s[i] == '=') break;
        int v = b64v((unsigned char) s[i]);
        if (v < 0) { free(o); return NULL; }
        acc = (acc << 6) | (uint32_t) v; bits += 6;
        if (bits >= 8) { bits -= 8; o[n++] = (uint8_t) (acc >> bits); acc &= (1u << bits) - 1u; }
    }
    *ol = n;
    return o;
}

/* «v1.» şifri (Msg.decK / app_enc bilen birmeňzeş): ke = sha("tvmsg|"+k), km = sha("tvmac|"+k) */
static uint8_t *v1dec(const char *fk, const char *blob, size_t *ol) {
    if (strncmp(blob, "v1.", 3) != 0) return NULL;
    size_t bl = 0; uint8_t *b = b64d(blob + 3, strlen(blob + 3), &bl);
    if (!b) return NULL;
    if (bl < 28) { free(b); return NULL; }
    const uint8_t *n = b, *c = b + 12, *tag = b + bl - 16; size_t cl = bl - 28;
    uint8_t ke[32], km[32], t[32]; char pre[16]; Sh s;
    size_t pl = ds(S_TVMSG, pre, sizeof pre);
    sh_init(&s); sh_up(&s, pre, pl); sh_up(&s, fk, strlen(fk)); sh_fin(&s, ke);
    pl = ds(S_TVMAC, pre, sizeof pre);
    sh_init(&s); sh_up(&s, pre, pl); sh_up(&s, fk, strlen(fk)); sh_fin(&s, km);
    wipe(pre, sizeof pre);
    hmac2(km, 32, n, 12, c, cl, t);
    uint8_t *out = NULL;
    if (ct_eq(t, tag, 16) && (out = (uint8_t *) malloc(cl + 1)) != NULL) {
        uint8_t ks[32], ctr[4]; size_t i = 0; uint32_t k = 0;
        while (i < cl) {
            ctr[0] = (uint8_t) (k >> 24); ctr[1] = (uint8_t) (k >> 16); ctr[2] = (uint8_t) (k >> 8); ctr[3] = (uint8_t) k;
            hmac2(ke, 32, n, 12, ctr, 4, ks);
            for (int j = 0; j < 32 && i < cl; j++, i++) out[i] = c[i] ^ ks[j];
            k++;
        }
        out[cl] = 0; *ol = cl;
        wipe(ks, sizeof ks);
    }
    wipe(ke, 32); wipe(km, 32); wipe(t, 32); wipe(b, bl); free(b);
    return out;
}

/* açar: hex(SHA-256("tvy1|" fid "|" salt "|" mask "|" hex(şahadatnama))) — zäherlense başga */
static void yseed(const char *fid, const char *salt, const char *mask, const uint8_t cert[32], unsigned poison, char hex[65]) {
    char pre[16], ch[65]; uint8_t sd[32]; Sh s;
    size_t pl = ds(S_TVY, pre, sizeof pre);
    tohex(cert, 32, ch);
    sh_init(&s); sh_up(&s, pre, pl); sh_up(&s, fid, strlen(fid)); sh_up(&s, "|", 1); sh_up(&s, salt, strlen(salt));
    sh_up(&s, "|", 1); sh_up(&s, mask, strlen(mask)); sh_up(&s, "|", 1); sh_up(&s, ch, 64); sh_fin(&s, sd);
    if (poison) { uint8_t pz[4] = {(uint8_t) poison, (uint8_t) (poison >> 8), 0x21, 0x7e}; sh_init(&s); sh_up(&s, sd, 32); sh_up(&s, pz, 4); sh_fin(&s, sd); }
    tohex(sd, 32, hex);
    wipe(pre, sizeof pre); wipe(ch, sizeof ch); wipe(sd, sizeof sd);
}

/* abuna salgysyndan Drive faýlynyň kimligi ("/files/<fid>") */
static int getfid(char *out, size_t cap) {
    char *u = (char *) malloc(SN + 1); if (!u) return -1;
    for (int i = 0; i < SN; i++) u[i] = (char) (SD[i] ^ SK[i]);
    u[SN] = 0;
    char pat[16]; size_t pl = ds(S_FILES, pat, sizeof pat);
    char *p = strstr(u, pat); size_t n = 0;
    if (p) {
        p += pl;
        while (n + 1 < cap && ((*p >= 'a' && *p <= 'z') || (*p >= 'A' && *p <= 'Z') || (*p >= '0' && *p <= '9') || *p == '_' || *p == '-')) out[n++] = *p++;
    }
    out[n] = 0;
    wipe(pat, sizeof pat); wipe(u, SN + 1); free(u);
    return n ? 0 : -1;
}

/* ---------- APK gol blogy: ilkinji gol çekijiniň ilkinji şahadatnamasy (v2 / v3 / v3.1) ---------- */
static uint32_t le32(const uint8_t *p) { return (uint32_t) p[0] | (uint32_t) p[1] << 8 | (uint32_t) p[2] << 16 | (uint32_t) p[3] << 24; }
static uint64_t le64(const uint8_t *p) { return (uint64_t) le32(p) | (uint64_t) le32(p + 4) << 32; }
static int rd_at(int fd, long off, void *b, size_t n) {
    if (off < 0 || r_lseek(fd, off, SEEK_SET) != off) return -1;
    size_t got = 0;
    while (got < n) { long r = r_read(fd, (char *) b + got, n - got); if (r <= 0) return -1; got += (size_t) r; }
    return 0;
}
static int lp(const uint8_t *b, size_t bl, size_t *pos, const uint8_t **o, size_t *ol) {
    if (*pos > bl || bl - *pos < 4) return -1;
    uint32_t l = le32(b + *pos); *pos += 4;
    if (l > bl - *pos) return -1;
    *o = b + *pos; *ol = l; *pos += l;
    return 0;
}
static int first_cert(const uint8_t *v, size_t vl, uint8_t out[32]) {
    const uint8_t *sgs, *sg, *sd, *dg, *cs, *ce; size_t sgsl, sgl, sdl, dgl, csl, cel, p = 0, q = 0, r = 0, t = 0, u = 0;
    if (lp(v, vl, &p, &sgs, &sgsl)) return -1;
    if (lp(sgs, sgsl, &q, &sg, &sgl)) return -1;
    if (lp(sg, sgl, &r, &sd, &sdl)) return -1;
    if (lp(sd, sdl, &t, &dg, &dgl)) return -1;
    if (lp(sd, sdl, &t, &cs, &csl)) return -1;
    if (lp(cs, csl, &u, &ce, &cel) || cel < 16) return -1;
    sha(ce, cel, out);
    return 0;
}
static int apk_cert_fd(int fd, uint8_t out[32], unsigned *fl) {
    long sz = r_lseek(fd, 0, SEEK_END);
    if (sz < 128) return -1;
    size_t tl = sz < 65557 ? (size_t) sz : 65557;
    uint8_t *t = (uint8_t *) malloc(tl); if (!t) return -1;
    if (rd_at(fd, sz - (long) tl, t, tl)) { free(t); return -1; }
    long eo = -1;
    for (long i = (long) tl - 22; i >= 0; i--)
        if (le32(t + i) == 0x06054b50u && (size_t) i + 22 + (t[i + 20] | (size_t) t[i + 21] << 8) == tl) { eo = i; break; }
    if (eo < 0) { free(t); return -1; }
    uint32_t cdoff = le32(t + eo + 16); free(t);
    if (cdoff < 32 || (long) cdoff > sz) return -1;
    uint8_t f[24]; char mg[20];
    if (rd_at(fd, (long) cdoff - 24, f, 24)) return -1;
    ds(S_SIGMAGIC, mg, sizeof mg);
    int okm = memcmp(f + 8, mg, 16) == 0; wipe(mg, sizeof mg);
    if (!okm) return -1;
    uint64_t bsz = le64(f);
    if (bsz < 24 || bsz > 16u * 1024 * 1024 || bsz + 8 > cdoff) return -1;
    long bst = (long) cdoff - (long) bsz - 8;
    uint8_t h8[8];
    if (rd_at(fd, bst, h8, 8) || le64(h8) != bsz) return -1;
    size_t pl = (size_t) bsz - 24;
    uint8_t *pb = (uint8_t *) malloc(pl ? pl : 1); if (!pb) return -1;
    if (rd_at(fd, bst + 8, pb, pl)) { free(pb); return -1; }
    size_t pos = 0; int found = 0; uint8_t d[32];
    while (pl - pos >= 12) {
        uint64_t len = le64(pb + pos);
        if (len < 4 || len > pl - pos - 8) break;
        uint32_t id = le32(pb + pos + 8);
        if (id == 0x7109871au || id == 0xf05368c0u || id == 0x1b93ad61u) {
            if (first_cert(pb + pos + 12, (size_t) len - 4, d) == 0) {
                if (!found) { memcpy(out, d, 32); found = 1; }
                else if (memcmp(out, d, 32) != 0) *fl |= F_MULTI;
            } else *fl |= F_MULTI;
        }
        pos += 8 + (size_t) len;
    }
    free(pb);
    return found ? 0 : -1;
}

/* ---------- /proc/self/maps: APK ýoly + inode, Frida yzlary ---------- */
typedef struct { char apk[512]; unsigned long long ino; int have; unsigned fl; } Maps;
static int ci_has(const char *h, const char *n) {
    size_t nl = strlen(n);
    for (; *h; h++) {
        size_t i = 0;
        while (i < nl && h[i] && ((h[i] | 0x20) == (n[i] | 0x20))) i++;
        if (i == nl) return 1;
    }
    return 0;
}
static void maps_line(Maps *m, char *l, size_t n, const char *fr, const char *gj, const char *lj, const char *bapk, const char *need) {
    if (ci_has(l, fr) || ci_has(l, gj) || ci_has(l, lj)) m->fl |= F_FRIDA;
    if (m->have || !bapk) return;
    size_t bl = strlen(bapk);
    if (n <= bl || strcmp(l + n - bl, bapk) != 0 || !strstr(l, need)) return;
    char *p = l; int fld = 0;
    while (*p && fld < 4) { while (*p && *p != ' ') p++; while (*p == ' ') p++; fld++; }
    unsigned long long ino = 0;
    while (*p >= '0' && *p <= '9') ino = ino * 10 + (unsigned) (*p++ - '0');
    while (*p == ' ') p++;
    if (*p != '/') return;
    size_t k = strlen(p); if (k >= sizeof m->apk) return;
    memcpy(m->apk, p, k + 1); m->ino = ino; m->have = 1;
}
static void maps_scan(Maps *m, int want_apk) {
    char path[24], fr[8], gj[8], lj[12], bapk[12], pk[16], need[24];
    ds(S_MAPS, path, sizeof path);
    int fd = r_open(path, 0);
    wipe(path, sizeof path);
    if (fd < 0) { m->fl |= F_NOMAPS; return; }
    ds(S_FRIDA, fr, sizeof fr); ds(S_GUM, gj, sizeof gj); ds(S_LINJ, lj, sizeof lj); ds(S_BAPK, bapk, sizeof bapk); ds(S_PKG, pk, sizeof pk);
    snprintf(need, sizeof need, "/%s-", pk);
    char *buf = (char *) malloc(16384), line[1024]; size_t ll = 0; long r;
    if (buf) {
        while ((r = r_read(fd, buf, 16384)) > 0)
            for (long i = 0; i < r; i++) {
                char ch = buf[i];
                if (ch == '\n') { line[ll] = 0; maps_line(m, line, ll, fr, gj, lj, want_apk ? bapk : NULL, need); ll = 0; }
                else if (ll < sizeof line - 1) line[ll++] = ch;
            }
        if (ll) { line[ll] = 0; maps_line(m, line, ll, fr, gj, lj, want_apk ? bapk : NULL, need); }
        free(buf);
    }
    r_close(fd);
    wipe(fr, sizeof fr); wipe(gj, sizeof gj); wipe(lj, sizeof lj); wipe(bapk, sizeof bapk); wipe(pk, sizeof pk); wipe(need, sizeof need);
}

/* sapaklaryň atlary (Frida: gum-js-loop …) */
struct d64 { uint64_t ino; int64_t off; unsigned short reclen; unsigned char type; char name[1]; };
static unsigned thr_scan(void) {
    char tp[24], cm[8], fr[8], gj[8], lj[12], p[96], nm[40]; unsigned f = 0;
    ds(S_TASK, tp, sizeof tp);
    int fd = r_open(tp, O_DIRECTORY);
    if (fd < 0) { wipe(tp, sizeof tp); return 0; }
    ds(S_COMM, cm, sizeof cm); ds(S_FRIDA, fr, sizeof fr); ds(S_GUM, gj, sizeof gj); ds(S_LINJ, lj, sizeof lj);
    char *buf = (char *) malloc(8192); long n;
    if (buf) {
        while ((n = r_getdents(fd, buf, 8192)) > 0)
            for (long o = 0; o < n;) {
                struct d64 *e = (struct d64 *) (buf + o);
                if (e->reclen == 0) break;
                if (e->name[0] >= '0' && e->name[0] <= '9') {
                    snprintf(p, sizeof p, "%s/%s%s", tp, e->name, cm);
                    int cf = r_open(p, 0);
                    if (cf >= 0) {
                        long k = r_read(cf, nm, sizeof nm - 1); r_close(cf);
                        if (k > 0) { nm[k] = 0; if (ci_has(nm, gj) || ci_has(nm, fr) || ci_has(nm, lj)) f |= F_FRIDA; }
                    }
                }
                o += e->reclen;
            }
        free(buf);
    }
    r_close(fd);
    wipe(tp, sizeof tp); wipe(cm, sizeof cm); wipe(fr, sizeof fr); wipe(gj, sizeof gj); wipe(lj, sizeof lj); wipe(p, sizeof p);
    return f;
}

static unsigned tracer(void) {
    char p[24], k[16], b[4096];
    ds(S_STATUS, p, sizeof p);
    int fd = r_open(p, 0); wipe(p, sizeof p);
    if (fd < 0) return 0;
    long n = 0, r;
    while (n < (long) sizeof b - 1 && (r = r_read(fd, b + n, sizeof b - 1 - (size_t) n)) > 0) n += r;
    r_close(fd);
    if (n <= 0) return 0;
    b[n] = 0;
    size_t kl = ds(S_TRACER, k, sizeof k);
    char *q = strstr(b, k); wipe(k, sizeof k);
    if (!q) return 0;
    q += kl;
    while (*q == ' ' || *q == '\t') q++;
    return (*q >= '1' && *q <= '9') ? F_TRACER : 0;
}

/* öz kodunyň möhüri: ýerine ýetirilýän bölegiň SHA-256-sy derlemede SEAL-a ýazylýar (seal.py) */
static unsigned seal_check(void) {
    Dl_info di;
    if (!dladdr((void *) &seal_check, &di) || !di.dli_fbase) return F_SEALNA;
    const uint8_t *base = (const uint8_t *) di.dli_fbase;
    if (base[0] != 0x7f || base[1] != 'E' || base[2] != 'L' || base[3] != 'F') return F_SEALNA;
#if defined(__LP64__)
    const Elf64_Ehdr *eh = (const Elf64_Ehdr *) base; typedef Elf64_Phdr Ph;
#else
    const Elf32_Ehdr *eh = (const Elf32_Ehdr *) base; typedef Elf32_Phdr Ph;
#endif
    if (eh->e_phnum == 0 || eh->e_phnum > 64 || eh->e_phentsize != sizeof(Ph)) return F_SEALNA;
    const Ph *ph = (const Ph *) (base + eh->e_phoff);
    uintptr_t minv = (uintptr_t) -1; int nx = 0;
    for (int i = 0; i < eh->e_phnum; i++) if (ph[i].p_type == PT_LOAD && ph[i].p_vaddr < minv) minv = ph[i].p_vaddr;
    if (minv != 0) return F_SEALNA;
    uint8_t hsh[32]; Sh c; sh_init(&c);
    for (int i = 0; i < eh->e_phnum; i++)
        if (ph[i].p_type == PT_LOAD && (ph[i].p_flags & PF_X)) {
            if (ph[i].p_filesz > 64u * 1024 * 1024) return F_SEALNA;
            sh_up(&c, base + ph[i].p_vaddr, ph[i].p_filesz); nx++;
        }
    sh_fin(&c, hsh);
    if (!nx) return F_SEALNA;
    uint8_t diff = 0;
    for (int i = 0; i < 32; i++) diff |= (uint8_t) (hsh[i] ^ SEAL[32 + i] ^ SEAL[64 + i]);
    wipe(hsh, sizeof hsh);
    return diff ? F_SEAL : 0;
}

/* APK ýoly ulgamyňky däl ýa-da proses ady başga (klon / wirtual gurşaw) */
static unsigned path_check(const char *apk) {
    char a[16], b[16], pk[16], need[24], c[24], cm[128]; unsigned f = 0;
    size_t al = ds(S_DATAAPP, a, sizeof a), bl = ds(S_MNTEXP, b, sizeof b), pkl = ds(S_PKG, pk, sizeof pk);
    if (!apk || !apk[0] || (strncmp(apk, a, al) != 0 && strncmp(apk, b, bl) != 0)) f |= F_PATH;
    snprintf(need, sizeof need, "/%s-", pk);
    if (!apk || !strstr(apk, need)) f |= F_PATH;
    ds(S_CMDLINE, c, sizeof c);
    int fd = r_open(c, 0);
    if (fd >= 0) {
        long n = r_read(fd, cm, sizeof cm - 1); r_close(fd);
        if (n > 0) { cm[n] = 0; if (strncmp(cm, pk, pkl) != 0 || (cm[pkl] != 0 && cm[pkl] != ':')) f |= F_PATH; }
    }
    wipe(a, sizeof a); wipe(b, sizeof b); wipe(pk, sizeof pk); wipe(need, sizeof need); wipe(c, sizeof c);
    return f;
}

static unsigned dyn_flags(void) {
    Maps m; memset(&m, 0, sizeof m);
    maps_scan(&m, 0);
    return tracer() | (m.fl & F_FRIDA) | thr_scan();
}

/* bir gezek hasaplanýan ýagdaý */
static pthread_mutex_t g_mx = PTHREAD_MUTEX_INITIALIZER;
static int g_init, g_hf, g_hp;
static uint8_t g_cf[32], g_cp[32];
static unsigned g_fl;

/* ýadro: şifri aç (açar programmadan çykmaýar) */
static uint8_t *ydec_core(const char *salt, const char *mask, const char *blob, unsigned fl, size_t *ol) {
    unsigned long mv = strtoul(mask, NULL, 10);
    uint8_t zero[32]; memset(zero, 0, sizeof zero);
    const uint8_t *cert = g_hf ? g_cf : ((mv & F_PMFB) && g_hp ? g_cp : zero);
    unsigned poison = fl & (unsigned) mv & F_POISON;
    char fid[128], hx[65];
    if (getfid(fid, sizeof fid)) return NULL;
    yseed(fid, salt, mask, cert, poison, hx);
    uint8_t *pt = v1dec(hx, blob, ol);
    wipe(hx, sizeof hx); wipe(fid, sizeof fid);
    return pt;
}

#ifdef YTEST
/* ---------- Linux synagy üçin ---------- */
int yt_init(const char *apk_override) {
    pthread_mutex_lock(&g_mx);
    Maps m; memset(&m, 0, sizeof m);
    maps_scan(&m, 1);
    const char *path = m.have ? m.apk : apk_override;
    if (!m.have) g_fl |= F_NOMAPS;
    if (path && path[0]) {
        int fd = r_open(path, 0);
        if (fd >= 0) {
            struct stat st;
            if (m.have && m.ino && r_fstat(fd, &st) == 0 && (unsigned long long) st.st_ino != m.ino) g_fl |= F_INODE;
            if (apk_cert_fd(fd, g_cf, &g_fl) == 0) g_hf = 1;
            r_close(fd);
        }
    }
    if (!g_hf) g_fl |= F_NOCERT;
    g_fl |= path_check(path) | (m.fl & F_FRIDA);
    g_init = 1;
    pthread_mutex_unlock(&g_mx);
    return m.have;
}
void yt_cert(char hex[65]) { if (g_hf) tohex(g_cf, 32, hex); else hex[0] = 0; }
unsigned yt_flags(void) { return g_fl; }
unsigned yt_dyn(void) { return dyn_flags(); }
unsigned yt_seal(void) { return seal_check(); }
void yt_setcert(const char *hex) { for (int i = 0; i < 32; i++) { unsigned v; sscanf(hex + 2 * i, "%2x", &v); g_cf[i] = (uint8_t) v; } g_hf = 1; }
char *yt_dec(const char *salt, const char *mask, const char *blob, unsigned fl) { size_t ol = 0; return (char *) ydec_core(salt, mask, blob, fl, &ol); }
const char *yt_apk(void) { static Maps m; memset(&m, 0, sizeof m); maps_scan(&m, 1); return m.have ? m.apk : ""; }
#else
/* ---------- JNI ---------- */
static int jx(JNIEnv *e) { if ((*e)->ExceptionCheck(e)) { (*e)->ExceptionClear(e); return 1; } return 0; }
static jmethodID jm(JNIEnv *e, jobject o, int ni, int si) {
    char n[32], s[112];
    ds(ni, n, sizeof n); ds(si, s, sizeof s);
    jclass c = (*e)->GetObjectClass(e, o);
    jmethodID m = c ? (*e)->GetMethodID(e, c, n, s) : NULL;
    if (jx(e)) m = NULL;
    if (c) (*e)->DeleteLocalRef(e, c);
    wipe(n, sizeof n); wipe(s, sizeof s);
    return m;
}
static int jcopy(JNIEnv *e, jstring s, char *o, size_t cap) {
    if (!s) return -1;
    const char *c = (*e)->GetStringUTFChars(e, s, NULL);
    if (!c) { jx(e); return -1; }
    size_t n = strlen(c); int r = n < cap ? 0 : -1;
    if (!r) memcpy(o, c, n + 1);
    (*e)->ReleaseStringUTFChars(e, s, c);
    return r;
}
static int call_str(JNIEnv *e, jobject o, int ni, int si, char *out, size_t cap) {
    jmethodID m = jm(e, o, ni, si); if (!m) return -1;
    jstring s = (jstring) (*e)->CallObjectMethod(e, o, m);
    if (jx(e) || !s) return -1;
    int r = jcopy(e, s, out, cap);
    (*e)->DeleteLocalRef(e, s);
    return r;
}
static int sdk_int(JNIEnv *e) {
    char cn[32], fn[16], fs[4];
    ds(S_BVER, cn, sizeof cn); ds(S_SDKINT, fn, sizeof fn); ds(S_I, fs, sizeof fs);
    int v = 0;
    jclass c = (*e)->FindClass(e, cn);
    if (!jx(e) && c) {
        jfieldID f = (*e)->GetStaticFieldID(e, c, fn, fs);
        if (!jx(e) && f) { v = (*e)->GetStaticIntField(e, c, f); if (jx(e)) v = 0; }
        (*e)->DeleteLocalRef(e, c);
    }
    wipe(cn, sizeof cn); wipe(fn, sizeof fn); wipe(fs, sizeof fs);
    return v;
}
/* PackageManager-iň berýän şahadatnamasy (diňe deňeşdirmek / ätiýaç üçin — aldap bolýar) */
static int pm_cert(JNIEnv *e, jobject ctx, uint8_t out[32]) {
    int rc = -1; jobject pm = NULL, pn = NULL, pi = NULL, si = NULL, arr = NULL, sg = NULL, by = NULL;
    jmethodID m = jm(e, ctx, S_GPM, S_SIGPM); if (!m) return -1;
    pm = (*e)->CallObjectMethod(e, ctx, m); if (jx(e) || !pm) goto end;
    m = jm(e, ctx, S_GPN, S_SIGU); if (!m) goto end;
    pn = (*e)->CallObjectMethod(e, ctx, m); if (jx(e) || !pn) goto end;
    m = jm(e, pm, S_GPI, S_SIGPI); if (!m) goto end;
    int sdk = sdk_int(e);
    pi = (*e)->CallObjectMethod(e, pm, m, pn, (jint) (sdk >= 28 ? 0x08000000 : 0x40)); if (jx(e) || !pi) goto end;
    {
        char fn[24], fs[40]; jclass pc = (*e)->GetObjectClass(e, pi);
        if (sdk >= 28) {
            ds(S_SI, fn, sizeof fn); ds(S_SIGSI, fs, sizeof fs);
            jfieldID f = pc ? (*e)->GetFieldID(e, pc, fn, fs) : NULL;
            if (!jx(e) && f) si = (*e)->GetObjectField(e, pi, f);
            jx(e);
            if (si) { jmethodID g = jm(e, si, S_GACS, S_SIGACS); if (g) { arr = (*e)->CallObjectMethod(e, si, g); if (jx(e)) arr = NULL; } }
        } else {
            ds(S_SIGS2, fn, sizeof fn); ds(S_SIGARR, fs, sizeof fs);
            jfieldID f = pc ? (*e)->GetFieldID(e, pc, fn, fs) : NULL;
            if (!jx(e) && f) arr = (*e)->GetObjectField(e, pi, f);
            jx(e);
        }
        if (pc) (*e)->DeleteLocalRef(e, pc);
        wipe(fn, sizeof fn); wipe(fs, sizeof fs);
    }
    if (!arr || (*e)->GetArrayLength(e, (jobjectArray) arr) < 1) goto end;
    sg = (*e)->GetObjectArrayElement(e, (jobjectArray) arr, 0); if (jx(e) || !sg) goto end;
    m = jm(e, sg, S_TBA, S_SIGTBA); if (!m) goto end;
    by = (*e)->CallObjectMethod(e, sg, m); if (jx(e) || !by) goto end;
    {
        jsize n = (*e)->GetArrayLength(e, (jbyteArray) by);
        jbyte *b = n > 0 ? (*e)->GetByteArrayElements(e, (jbyteArray) by, NULL) : NULL;
        if (b) { sha(b, (size_t) n, out); (*e)->ReleaseByteArrayElements(e, (jbyteArray) by, b, JNI_ABORT); rc = 0; }
        jx(e);
    }
end:
    if (by) (*e)->DeleteLocalRef(e, by);
    if (sg) (*e)->DeleteLocalRef(e, sg);
    if (arr) (*e)->DeleteLocalRef(e, arr);
    if (si) (*e)->DeleteLocalRef(e, si);
    if (pi) (*e)->DeleteLocalRef(e, pi);
    if (pn) (*e)->DeleteLocalRef(e, pn);
    if (pm) (*e)->DeleteLocalRef(e, pm);
    return rc;
}
static void init_once(JNIEnv *e, jobject ctx) {
    pthread_mutex_lock(&g_mx);
    if (g_init) { pthread_mutex_unlock(&g_mx); return; }
    Maps m; memset(&m, 0, sizeof m);
    maps_scan(&m, 1);
    char path[512]; path[0] = 0;
    if (m.have) memcpy(path, m.apk, sizeof path);
    else { g_fl |= F_NOMAPS; if (ctx && call_str(e, ctx, S_GPCP, S_SIGU, path, sizeof path)) path[0] = 0; }
    if (path[0]) {
        int fd = r_open(path, 0);
        if (fd >= 0) {
            struct stat st;
            if (m.have && m.ino && r_fstat(fd, &st) == 0 && (unsigned long long) st.st_ino != m.ino) g_fl |= F_INODE;
            if (apk_cert_fd(fd, g_cf, &g_fl) == 0) g_hf = 1;
            r_close(fd);
        }
    }
    if (!g_hf) g_fl |= F_NOCERT;
    g_fl |= path_check(path) | (m.fl & F_FRIDA) | seal_check();
    if (ctx && pm_cert(e, ctx, g_cp) == 0) g_hp = 1;
    char pn[96], pk[16];
    ds(S_PKG, pk, sizeof pk);
    if (!ctx || call_str(e, ctx, S_GPN, S_SIGU, pn, sizeof pn) || strcmp(pn, pk) != 0) g_fl |= F_PKG;
    wipe(pk, sizeof pk); wipe(path, sizeof path);
    g_init = 1;
    pthread_mutex_unlock(&g_mx);
}

static jstring JNICALL n_u(JNIEnv *env, jclass cls) {
    (void) cls;
    char *b = (char *) malloc(SN + 1);
    if (!b) return NULL;
    for (int i = 0; i < SN; i++) b[i] = (char) (SD[i] ^ SK[i]);
    b[SN] = 0;
    jstring r = (*env)->NewStringUTF(env, b);
    wipe(b, SN + 1);
    free(b);
    return r;
}

static jbyteArray JNICALL n_d(JNIEnv *e, jclass cls, jobject ctx, jstring js, jstring jmk, jstring jb) {
    (void) cls;
    init_once(e, ctx);
    char salt[64], mask[16];
    if (jcopy(e, js, salt, sizeof salt) || jcopy(e, jmk, mask, sizeof mask) || !jb) return NULL;
    jsize bl = (*e)->GetStringUTFLength(e, jb);
    if (bl <= 0 || bl > 4 * 1024 * 1024) return NULL;
    char *blob = (char *) malloc((size_t) bl + 1);
    if (!blob) return NULL;
    if (jcopy(e, jb, blob, (size_t) bl + 1)) { free(blob); return NULL; }
    size_t ol = 0;
    uint8_t *pt = ydec_core(salt, mask, blob, g_fl | dyn_flags(), &ol);
    free(blob);
    if (!pt) return NULL;
    jbyteArray r = (*e)->NewByteArray(e, (jsize) ol);
    if (r) (*e)->SetByteArrayRegion(e, r, 0, (jsize) ol, (const jbyte *) pt);
    jx(e);
    wipe(pt, ol); free(pt);
    return r;
}

/* ýagdaý (bot üçin): "faýl8.pm8.flags" */
static jstring JNICALL n_s(JNIEnv *e, jclass cls, jobject ctx) {
    (void) cls;
    init_once(e, ctx);
    char a[9], b[9], o[48];
    if (g_hf) tohex(g_cf, 4, a); else strcpy(a, "-");
    if (g_hp) tohex(g_cp, 4, b); else strcpy(b, "-");
    snprintf(o, sizeof o, "%s.%s.%x", a, b, g_fl | dyn_flags());
    return (*e)->NewStringUTF(e, o);
}

JNIEXPORT jint JNICALL JNI_OnLoad(JavaVM *vm, void *res) {
    (void) res;
    JNIEnv *e = NULL;
    if ((*vm)->GetEnv(vm, (void **) &e, JNI_VERSION_1_6) != JNI_OK) return JNI_ERR;
    char cn[16], mu[4], md[4], ms[4], su[24], sd[112], s2[64];
    ds(S_CLS, cn, sizeof cn); ds(S_MU, mu, sizeof mu); ds(S_MD, md, sizeof md); ds(S_MS, ms, sizeof ms);
    ds(S_SIGU, su, sizeof su); ds(S_SIGD, sd, sizeof sd); ds(S_SIGS, s2, sizeof s2);
    jclass c = (*e)->FindClass(e, cn);
    if (!jx(e) && c) {
        JNINativeMethod mt[3] = {{mu, su, (void *) n_u}, {md, sd, (void *) n_d}, {ms, s2, (void *) n_s}};
        (*e)->RegisterNatives(e, c, mt, 3);
        jx(e);
        (*e)->DeleteLocalRef(e, c);
    }
    wipe(cn, sizeof cn); wipe(su, sizeof su); wipe(sd, sizeof sd); wipe(s2, sizeof s2);
    return JNI_VERSION_1_6;
}
#endif
