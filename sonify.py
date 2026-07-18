"""sonify.py -- cross-domain databending: hear files as audio, see audio as
images, and round-trip between the two.

Any bytes are just numbers. A WAV header calls them samples; a PGM header calls
them pixels. sonify swaps the interpretation, so you can hear a JPEG, view a
drum loop as a grid, or -- the classic databend -- turn audio into an image,
smear it, and turn it back into sound. The image formats are Netpbm (PGM/PPM):
a tiny text header plus raw bytes, so any image editor opens them and no
dependency is needed.

  python sonify.py hear FILE [-o out.wav] [--rate R --ch N --bits B --skip OFF]
  python sonify.py see  FILE [-o out.pgm --width W]         # grayscale (P5)
  python sonify.py see  FILE -o out.ppm --rgb               # color    (P6)
  python sonify.py load IMG [-o out.wav] [--rate R --ch N --bits B]
  python sonify.py bend FILE --op OP [--width W -o out.wav] # in-code databend

bend ops: invert, reverse, rowsort, rowshift, xor, transpose. Add --play to any
command to hear the result immediately (needs ffplay).
"""

import math
import os
import struct
import sys


def _wav(pcm, rate=44100, ch=1, bits=16, tag=1):
    block = ch * bits // 8
    if block and len(pcm) % block:
        pcm = pcm + b"\x00" * (block - len(pcm) % block)
    return (b"RIFF" + struct.pack("<I", 36 + len(pcm)) + b"WAVE"
            + b"fmt " + struct.pack("<IHHIIHH", 16, tag, ch, rate,
                                    rate * block, block, bits)
            + b"data" + struct.pack("<I", len(pcm)) + pcm)


def _read(path):
    with open(path, "rb") as f:
        return f.read()


# ── file -> audio ────────────────────────────────────────────────────────
def hear(path, out=None, rate=44100, ch=1, bits=16, skip=0):
    """Wrap a file's raw bytes as PCM so you can hear it."""
    data = _read(path)[skip:]
    out = out or os.path.splitext(path)[0] + "_heard.wav"
    with open(out, "wb") as f:
        f.write(_wav(data, rate, ch, bits))
    return out


# ── file -> image (Netpbm) ─────────────────────────────────────────────────
def see(path, out=None, width=512, rgb=False):
    """Lay a file's bytes out as a grayscale (P5) or RGB (P6) image."""
    data = _read(path)
    px = 3 if rgb else 1
    row = width * px
    if len(data) % row:
        data = data + b"\x00" * (row - len(data) % row)
    height = len(data) // row
    magic = b"P6" if rgb else b"P5"
    out = out or os.path.splitext(path)[0] + (".ppm" if rgb else ".pgm")
    with open(out, "wb") as f:
        f.write(magic + b"\n%d %d\n255\n" % (width, height))
        f.write(data)
    return out, width, height


# ── image (Netpbm) -> audio ────────────────────────────────────────────────
def _read_pnm(path):
    """Return (pixel_bytes, width, height, channels) from a P5/P6 file."""
    data = _read(path)
    if data[:2] not in (b"P5", b"P6"):
        raise ValueError("not a P5/P6 Netpbm image")
    ch = 3 if data[:2] == b"P6" else 1
    pos = 2
    vals = []
    while len(vals) < 3:                       # width, height, maxval
        while pos < len(data) and data[pos:pos + 1].isspace():
            pos += 1
        if data[pos:pos + 1] == b"#":          # comment line
            while pos < len(data) and data[pos:pos + 1] != b"\n":
                pos += 1
            continue
        start = pos
        while pos < len(data) and not data[pos:pos + 1].isspace():
            pos += 1
        vals.append(int(data[start:pos]))
    return data[pos + 1:], vals[0], vals[1], ch


def load(path, out=None, rate=44100, ch=1, bits=16):
    """Read an image's pixel bytes back as PCM audio."""
    pixels, w, h, _ = _read_pnm(path)
    out = out or os.path.splitext(path)[0] + "_loaded.wav"
    with open(out, "wb") as f:
        f.write(_wav(pixels, rate, ch, bits))
    return out


# ── in-code databend: file -> byte grid -> op -> audio ─────────────────────
def _grid(data, width):
    if len(data) % width:
        data = data + b"\x00" * (width - len(data) % width)
    return [bytearray(data[i:i + width]) for i in range(0, len(data), width)], width


def bend(path, op="invert", out=None, width=512, rate=44100, ch=1, bits=16):
    """Apply an image-style operation to the file's byte grid, then hear it."""
    rows, width = _grid(_read(path), width)
    if op == "invert":
        rows = [bytearray(255 - b for b in r) for r in rows]
    elif op == "reverse":
        for r in rows:
            r.reverse()
    elif op == "rowsort":
        rows = [bytearray(sorted(r)) for r in rows]
    elif op == "rowshift":
        rows = [r[i % width:] + r[:i % width] for i, r in enumerate(rows)]
    elif op == "xor":
        rows = [bytearray(b ^ 0x55 for b in r) for r in rows]
    elif op == "transpose":
        cols = [bytearray(rows[y][x] for y in range(len(rows))) for x in range(width)]
        rows = cols
    else:
        raise ValueError(f"unknown op {op!r} (invert reverse rowsort rowshift xor transpose)")
    pcm = b"".join(bytes(r) for r in rows)
    out = out or os.path.splitext(path)[0] + f"_{op}.wav"
    with open(out, "wb") as f:
        f.write(_wav(pcm, rate, ch, bits))
    return out


def _main(argv):
    if len(argv) < 2:
        print(__doc__)
        return 0
    op, path = argv[0], argv[1]
    rest = argv[2:]
    out = rest[rest.index("-o") + 1] if "-o" in rest else None
    o = {rest[i][2:]: rest[i + 1] for i in range(len(rest) - 1) if rest[i].startswith("--")}
    rate, ch, bits = int(o.get("rate", 44100)), int(o.get("ch", 1)), int(o.get("bits", 16))
    dst = None
    if op == "hear":
        dst = hear(path, out, rate, ch, bits, int(o.get("skip", "0"), 0))
    elif op == "see":
        dst, w, h = see(path, out, int(o.get("width", 512)), "--rgb" in rest)
        print(f"wrote {dst}  ({w} x {h})")
    elif op == "load":
        dst = load(path, out, rate, ch, bits)
    elif op == "bend":
        dst = bend(path, o.get("op", "invert"), out, int(o.get("width", 512)),
                   rate, ch, bits)
    else:
        print(__doc__)
        return 1
    if op != "see":
        print(f"wrote {dst}")
    if "--play" in rest and dst and dst.lower().endswith(".wav"):
        repo = os.environ.get("ACIDCAT_REPO") or os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "acidcat")
        sys.path.insert(0, os.path.join(repo, "src"))
        from acidcat.util import play
        play.play(dst)
    return 0


if __name__ == "__main__":
    sys.exit(_main(sys.argv[1:]))
