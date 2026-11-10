#include <jni.h>
#include <stdlib.h>
#include <string.h>
#include "sec_data.h"

/* Abonelik adresi yalnız burada, XOR'lu durur; çözülen kopya hemen silinir. */
JNIEXPORT __attribute__((visibility("default"))) jstring JNICALL
Java_tm_yol_vpn_N_u(JNIEnv *env, jclass cls) {
    (void) cls;
    char *b = (char *) malloc(SN + 1);
    if (!b) return NULL;
    for (int i = 0; i < SN; i++) b[i] = (char) (SD[i] ^ SK[i]);
    b[SN] = 0;
    jstring r = (*env)->NewStringUTF(env, b);
    volatile char *p = b;
    for (int i = 0; i < SN; i++) p[i] = 0;
    free(b);
    return r;
}
