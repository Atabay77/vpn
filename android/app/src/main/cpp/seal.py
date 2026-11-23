#!/usr/bin/env python3
"""1.47.16: libyolsec.so möhüri — ýerine ýetirilýän (R-X) bölekleriň SHA-256-syny SEAL[64:96]-a ýazýar.
SEAL = [magic 32][mask 32][slot 32]; slot = sha ^ mask. Soňra magic tötänleýin baýtlar bilen çalyşylýar.
Programma işlände öz kodunyň SHA-256-syny hasaplap deňeşdirýär (sec.c: seal_check)."""
import hashlib, os, struct, sys

so, magic_src = sys.argv[1], sys.argv[2]
magic = bytes.fromhex(open(magic_src).read().strip() if os.path.exists(magic_src) else magic_src)
b = bytearray(open(so, "rb").read())
off = b.find(magic)
if off < 0 or b.find(magic, off + 1) >= 0:
    sys.exit(f"seal: magic tapylmady ýa-da birnäçe ({so})")
if b[:4] != b"\x7fELF":
    sys.exit("seal: ELF däl")
c64 = b[4] == 2
if b[5] != 1:
    sys.exit("seal: little-endian däl")
if c64:
    phoff, = struct.unpack_from("<Q", b, 0x20); phentsize, phnum = struct.unpack_from("<HH", b, 0x36)
else:
    phoff, = struct.unpack_from("<I", b, 0x1C); phentsize, phnum = struct.unpack_from("<HH", b, 0x2A)
loads = []
for i in range(phnum):
    o = phoff + i * phentsize
    if c64:
        p_type, p_flags, p_offset, p_vaddr, _pa, p_filesz = struct.unpack_from("<IIQQQQ", b, o)
    else:
        p_type, p_offset, p_vaddr, _pa, p_filesz, _ms, p_flags = struct.unpack_from("<IIIIIII", b, o)
    if p_type == 1:
        loads.append((p_offset, p_vaddr, p_filesz, p_flags))
if not loads or min(l[1] for l in loads) != 0:
    sys.exit("seal: ilkinji PT_LOAD vaddr 0 däl")
h = hashlib.sha256(); nx = 0
for p_offset, p_vaddr, p_filesz, p_flags in loads:
    if p_flags & 1:   # PF_X
        if p_offset <= off < p_offset + p_filesz or p_offset <= off + 96 <= p_offset + p_filesz:
            sys.exit("seal: SEAL ýerine ýetirilýän bölekde — möhür özüni üýtgeder")
        h.update(bytes(b[p_offset:p_offset + p_filesz])); nx += 1
if not nx:
    sys.exit("seal: ýerine ýetirilýän bölek ýok")
d = h.digest()
mask = bytes(b[off + 32:off + 64])
b[off + 64:off + 96] = bytes(x ^ y for x, y in zip(d, mask))
b[off:off + 32] = os.urandom(32)
open(so, "wb").write(bytes(b))
print(f"seal: {os.path.basename(os.path.dirname(so)) or so} R-X={d.hex()[:16]}… slot@{off + 64:#x}")
