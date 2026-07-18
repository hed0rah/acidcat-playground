"""Dual-endianness audio polyglot: one PCM block, two different sounds.

A 16-bit sample is two bytes. A WAV (RIFF, little-endian) reads them low-byte
first; an AIFF (big-endian) reads them high-byte first. So the SAME on-disk
sample bytes decode to two different sample values depending on endianness. This
tool exploits that to carry two recognizable sounds in one shared PCM block:

  on-disk sample bytes = [ B_byte , A_byte ]   (little-endian order)
    WAV  reads sample = A_byte<<8 | B_byte  -> high byte A_byte dominates -> SOUND A
    AIFF reads sample = B_byte<<8 | A_byte  -> high byte B_byte dominates -> SOUND B

Each sound is effectively 8-bit (its samples live in the high byte of one
endianness; the other sound rides in the low byte as ~quiet dither). We write
out.wav and out.aiff that share the EXACT same PCM payload bytes: the .wav plays
sound A, the .aiff plays sound B, byte-for-byte the same audio data.

Why not a single file valid as both containers? RIFF needs "RIFF" at offset 0 and
AIFF needs "FORM" at offset 0; the magics collide, so no clean single-file
audio+audio dual-container exists (unlike WAV+ZIP, where ZIP scans from the tail
and tolerates a prefix). The under-documented, real artifact here is the shared dual-
endianness PCM, not a magic-byte trick.

Established? Byte-swapping a real recording is well known to produce noise. What
is under-documented is *designing* PCM so both endian views are clean, distinct
sounds, and shipping it as byte-identical WAV/AIFF.

acidcat detection rule this motivates (dual_endianness):
  For 16-bit PCM, compute a cheap signal metric (zero-crossing rate or low-order
  autocorrelation) on BOTH the native and the byte-swapped interpretation. A
  normal recording is structured one way and noise-like when swapped. If the
  swapped view is *also* strongly structured (low ZCR / high autocorrelation),
  the samples were engineered for two endiannesses -> flag it.

  python dual_endian.py build -o out [--a-hz 440] [--b-hz 660] [--secs 2] [--rate 22050]
  python dual_endian.py verify out.wav out.aiff
"""

import math
import os
import struct
import sys

REPO = os.environ.get("ACIDCAT_REPO") or os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "acidcat")
# acidcat: a sibling checkout by default, or set ACIDCAT_REPO, or pip install acidcat
sys.path.insert(0, os.path.join(REPO, "src"))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from acidcat.core.walk import walk_file  # noqa: E402


def _tone8(hz, rate, secs):
    """A mono sine as signed 8-bit samples in [-127, 127]."""
    n = int(rate * secs)
    return bytes((int(round(120 * math.sin(2 * math.pi * hz * i / rate))) & 0xFF)
                 for i in range(n))


def _pcm(a8, b8):
    """Interleave two 8-bit streams into shared 16-bit little-endian PCM.

    file bytes per frame = [b_byte, a_byte]; WAV surfaces a8, AIFF surfaces b8.
    """
    n = min(len(a8), len(b8))
    out = bytearray(2 * n)
    out[0::2] = b8[:n]           # low byte  -> AIFF high byte (sound B)
    out[1::2] = a8[:n]           # high byte -> WAV high byte  (sound A)
    return bytes(out)


def _wav(pcm, rate):
    """RIFF/WAVE, 16-bit mono, PCM payload used verbatim (little-endian)."""
    fmt = struct.pack("<HHIIHH", 1, 1, rate, rate * 2, 2, 16)
    body = (b"WAVE"
            + b"fmt " + struct.pack("<I", len(fmt)) + fmt
            + b"data" + struct.pack("<I", len(pcm)) + pcm)
    return b"RIFF" + struct.pack("<I", len(body)) + body


def _ext80(num):
    """IEEE 754 80-bit extended (big-endian), for the AIFF COMM sample rate."""
    if num == 0:
        return b"\x00" * 10
    sign = 0x8000 if num < 0 else 0
    num = abs(num)
    fmant, expon = math.frexp(num)
    expon += 16382                              # 0.5<=fmant<1 -> unbias offset
    fmant = math.ldexp(fmant, 32)
    hi = int(math.floor(fmant))
    lo = int(math.floor(math.ldexp(fmant - hi, 32)))
    return struct.pack(">HII", (expon & 0x7FFF) | sign, hi, lo)


def _aiff(pcm, rate):
    """AIFF, 16-bit mono, SSND samples used verbatim (big-endian)."""
    frames = len(pcm) // 2
    comm = struct.pack(">hIh", 1, frames, 16) + _ext80(rate)
    ssnd = struct.pack(">II", 0, 0) + pcm       # offset, blockSize, then samples
    body = (b"AIFF"
            + b"COMM" + struct.pack(">I", len(comm)) + comm
            + b"SSND" + struct.pack(">I", len(ssnd)) + ssnd)
    return b"FORM" + struct.pack(">I", len(body)) + body


def _data_chunk(buf, cid, magic_at):
    """Return the payload bytes of chunk `cid`, endianness by container magic."""
    endian = "<" if magic_at == b"RIFF" else ">"
    pos = 12
    while pos + 8 <= len(buf):
        cur = buf[pos:pos + 4]
        size = struct.unpack_from(endian + "I", buf, pos + 4)[0]
        if cur == cid:
            return buf[pos + 8:pos + 8 + size]
        pos += 8 + size + (size & 1)
    raise ValueError(f"chunk {cid!r} not found")


def _zcr(sig8):
    """Zero-crossing rate of a signed-8-bit waveform (fraction of samples)."""
    s = [b - 256 if b > 127 else b for b in sig8]
    cross = sum(1 for i in range(1, len(s)) if (s[i - 1] < 0) != (s[i] < 0))
    return cross / max(1, len(s))


def _freq(sig8, rate):
    """Estimate dominant frequency of a signed-8-bit sine via zero crossings."""
    return _zcr(sig8) * rate / 2


def build(out, a_hz=440, b_hz=660, secs=2, rate=22050):
    a8 = _tone8(a_hz, rate, secs)
    b8 = _tone8(b_hz, rate, secs)
    pcm = _pcm(a8, b8)
    open(out + ".wav", "wb").write(_wav(pcm, rate))
    open(out + ".aiff", "wb").write(_aiff(pcm, rate))
    return out + ".wav", out + ".aiff", pcm


def verify(wav_path, aiff_path):
    wav = open(wav_path, "rb").read()
    aiff = open(aiff_path, "rb").read()
    wav_pcm = _data_chunk(wav, b"data", b"RIFF")
    ssnd = _data_chunk(aiff, b"SSND", b"FORM")
    aiff_pcm = ssnd[8:]                          # skip offset + blockSize
    same = wav_pcm == aiff_pcm
    # WAV surfaces the high byte of each LE sample (sound A);
    # AIFF surfaces the high byte of each BE sample (= the low file byte, sound B)
    a_wave = wav_pcm[1::2]
    b_wave = aiff_pcm[0::2]
    # both containers must parse cleanly in acidcat
    def _acidcat_ok(path):
        try:
            fmt, chunks, _ = walk_file(path, deep=False)
            return True, f"{fmt}: " + ",".join(c["id"].strip() for c in chunks[:4])
        except Exception as e:
            return False, f"{e.__class__.__name__}: {e}"
    return {
        "shared_pcm": same,
        "pcm_bytes": len(wav_pcm),
        "a_wave": a_wave,
        "b_wave": b_wave,
        "wav_ok": _acidcat_ok(wav_path),
        "aiff_ok": _acidcat_ok(aiff_path),
    }


if __name__ == "__main__":
    a = sys.argv[1:]

    def opt(flag, d):
        return type(d)(a[a.index(flag) + 1]) if flag in a else d
    out = a[a.index("-o") + 1] if "-o" in a else "dual"
    if a and a[0] == "build":
        rate = opt("--rate", 22050)
        wp, ap, pcm = build(out, opt("--a-hz", 440), opt("--b-hz", 660),
                            opt("--secs", 2), rate)
        r = verify(wp, ap)
        print(f"wrote {wp} + {ap}: {r['pcm_bytes']:,} shared PCM bytes")
        print(f"  shared payload byte-identical: {r['shared_pcm']}")
        print(f"  {wp}  measured ~{_freq(r['a_wave'], rate):.0f} Hz (sound A)")
        print(f"  {ap} measured ~{_freq(r['b_wave'], rate):.0f} Hz (sound B)")
    elif a and a[0] == "verify" and len(a) >= 3:
        r = verify(a[1], a[2])
        print(f"shared PCM byte-identical: {r['shared_pcm']} ({r['pcm_bytes']:,} bytes)")
        wo, wd = r["wav_ok"]
        ao, ad = r["aiff_ok"]
        print(f"  WAV  acidcat {'OK ' if wo else 'FAIL'} {wd}")
        print(f"  AIFF acidcat {'OK ' if ao else 'FAIL'} {ad}")
        print(f"  WAV surfaces  ~{_freq(r['a_wave'], 22050):.0f} Hz (assumes 22050)")
        print(f"  AIFF surfaces ~{_freq(r['b_wave'], 22050):.0f} Hz")
    else:
        print(__doc__)
