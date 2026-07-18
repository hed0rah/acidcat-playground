"""forge.py -- a surgical editing bench for audio containers.

The playground's chemistry set: locate any chunk or decoded field by name (via
acidcat's own walker, which hands back each field's absolute offset and length),
then patch it, fill it, or corrupt it, and save a weird-but-often-still-loadable
file. Addressing is format-aware; the edits are not policed. Writing nonsense is
the entire point.

inspect (read-only):
  python forge.py FILE show                          chunks + addressable fields
  python forge.py FILE examine OFFSET [--fmt u16 --count 8]  typed read of a byte range
  python forge.py FILE hexdump OFFSET [--len 256]    annotated hexdump
  python forge.py FILE find HEX_OR_TEXT              byte-pattern search
  python forge.py FILE scan VALUE [--fmt u16]        scan the file for a value
  python forge.py FILE strings [--min 4]             printable ASCII runs
  python forge.py FILE diff OTHER                    changed byte ranges vs OTHER

edit (writes -o, default FILE_forged.ext):
  python forge.py FILE set CHUNK FIELD VALUE         rewrite a decoded field
  python forge.py FILE replace OLDHEX NEWHEX         equal-length find/replace
  python forge.py FILE fill CHUNK BYTE               fill a chunk payload
  python forge.py FILE corrupt CHUNK [--mode M --rate R]
  python forge.py FILE patch OFFSET HEX              raw byte patch at an offset
  python forge.py FILE recipe NAME [--play]          a built-in glitch recipe

VALUE / BYTE / OFFSET accept 0x-hex or decimal; HEX is raw hex ("ff00ba").
fmt is u8/i8/u16/i16/u32/i32/u64/i64/f32/f64. play: forge.py FILE play [CHUNK].
Programmatic: Forge(p).set_field("fmt","sample_rate",96000).save("out.wav")
"""

import os
import random
import struct  # noqa: F401  (handy for recipes / interactive use)
import sys
import tempfile

REPO = os.environ.get("ACIDCAT_REPO") or os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "acidcat")
sys.path.insert(0, os.path.join(REPO, "src"))

from acidcat.core.walk import walk_file  # noqa: E402

# typed reads: name -> (struct code, byte size)
_FMT_STRUCT = {"u8": ("B", 1), "i8": ("b", 1), "u16": ("H", 2), "i16": ("h", 2),
               "u32": ("I", 4), "i32": ("i", 4), "u64": ("Q", 8), "i64": ("q", 8),
               "f32": ("f", 4), "f64": ("d", 8)}


def _as_bytes(x):
    """Accept a hex string ('ff00ba'), a text string, or raw bytes."""
    if isinstance(x, (bytes, bytearray)):
        return bytes(x)
    s = str(x)
    hexchars = set("0123456789abcdefABCDEF")
    compact = s.replace(" ", "")
    if compact and len(compact) % 2 == 0 and all(c in hexchars for c in compact):
        return bytes.fromhex(compact)
    return s.encode("latin-1", "replace")


class Forge:
    """Load a file, walk it to locate chunks/fields, mutate the bytes, save."""

    def __init__(self, path):
        self.path = path
        self.data = bytearray(open(path, "rb").read())
        self._walk()

    def _walk(self):
        """Re-parse current bytes so field offsets reflect the latest edits."""
        fd, tmp = tempfile.mkstemp(suffix=os.path.splitext(self.path)[1])
        os.close(fd)
        try:
            with open(tmp, "wb") as f:
                f.write(self.data)
            self.fmt, self.chunks, self.warns = walk_file(tmp)
        except Exception as e:
            self.fmt, self.chunks, self.warns = "unparsed", [], [repr(e)]
        finally:
            os.unlink(tmp)
        self.be = any(t in self.fmt for t in ("AIFF", "AIFC", "MP4"))  # big-endian?

    # -- addressing -------------------------------------------------------
    def _chunk(self, cid):
        for c in self.chunks:
            if str(c.get("id", "")).strip() == cid:
                return c
        return None

    def chunk(self, cid):
        """(offset, size) of a chunk, or None."""
        c = self._chunk(cid)
        return (c["offset"], c.get("size")) if c else None

    def field(self, cid, name):
        """(abs_offset, length, current_value) of a decoded field, or None."""
        c = self._chunk(cid)
        if not c:
            return None
        pb = c.get("payload_base", (c.get("offset") or 0) + 8)
        for f in c.get("fields", []):
            if f.get("name") == name and f.get("off") is not None:
                return pb + f["off"], f.get("len") or 0, f.get("value")
        return None

    # -- edits (all return self, so they chain) ---------------------------
    def patch(self, offset, blob):
        self.data[offset:offset + len(blob)] = bytes(blob)
        self._walk()
        return self

    def set_int(self, offset, value, length, endian=None):
        e = "big" if (endian == "big" or (endian is None and self.be)) else "little"
        self.data[offset:offset + length] = int(value).to_bytes(
            length, e, signed=int(value) < 0)
        self._walk()
        return self

    def set_field(self, cid, name, value, endian=None):
        loc = self.field(cid, name)
        if not loc:
            raise KeyError(f"no field {cid}/{name} (try `show`)")
        off, ln, _ = loc
        if isinstance(value, (bytes, bytearray)):
            self.data[off:off + ln] = bytes(value).ljust(ln, b"\x00")[:ln]
        elif isinstance(value, str) and not _looks_int(value):
            self.data[off:off + ln] = value.encode("utf-8").ljust(ln, b"\x00")[:ln]
        else:
            return self.set_int(off, _asint(value), ln, endian)
        self._walk()
        return self

    def fill(self, offset, length, byte=0x00):
        self.data[offset:offset + length] = bytes([byte & 0xFF]) * length
        self._walk()
        return self

    def fill_chunk(self, cid, byte=0xAA):
        """Fill a chunk's payload region (payload_base .. +size)."""
        c = self._chunk(cid)
        if not c:
            raise KeyError(f"no chunk {cid} (try `show`)")
        pb = c.get("payload_base", (c.get("offset") or 0) + 8)
        return self.fill(pb, c.get("size") or 0, byte)

    def corrupt(self, offset, length, mode="bitflip", rate=0.01, seed=1337):
        rng = random.Random(seed)
        region = self.data[offset:offset + length]
        if mode == "reverse":
            region.reverse()
        elif mode == "xor":
            k = rng.randint(1, 255)
            for i in range(len(region)):
                region[i] ^= k
        else:                                   # bitflip / random
            for i in range(len(region)):
                if rng.random() < rate:
                    region[i] = (rng.randint(0, 255) if mode == "random"
                                 else region[i] ^ (1 << rng.randint(0, 7)))
        self.data[offset:offset + length] = region
        self._walk()
        return self

    def corrupt_chunk(self, cid, **kw):
        c = self._chunk(cid)
        if not c:
            raise KeyError(f"no chunk {cid} (try `show`)")
        pb = c.get("payload_base", (c.get("offset") or 0) + 8)
        return self.corrupt(pb, c.get("size") or 0, **kw)

    # -- inspection: examine / search / strings / diff (RE primitives) ----
    def read(self, offset, fmt="u8", count=1, endian=None):
        """Read `count` typed values at `offset`. fmt is u8/i16/
        u32/f32/... ; endianness defaults to the container's."""
        code, sz = _FMT_STRUCT[fmt]
        e = ">" if (endian == "big" or (endian is None and self.be)) else "<"
        return list(struct.unpack_from(e + code * count, self.data, offset))

    def find(self, pattern, limit=256):
        """Every offset of a byte pattern (hex string, text, or bytes)."""
        needle = _as_bytes(pattern)
        offs = []
        i = self.data.find(needle)
        while i != -1 and len(offs) < limit:
            offs.append(i)
            i = self.data.find(needle, i + 1)
        return offs

    def find_value(self, value, fmt="u16", endian=None, limit=256):
        """Value scan: every offset where the typed value equals value."""
        code, sz = _FMT_STRUCT[fmt]
        e = ">" if (endian == "big" or (endian is None and self.be)) else "<"
        return self.find(struct.pack(e + code, value), limit)

    def strings(self, minlen=4, limit=400):
        """Extract printable ASCII runs, as (offset, text)."""
        out = []
        cur = bytearray()
        start = 0
        for i, b in enumerate(self.data):
            if 32 <= b < 127:
                if not cur:
                    start = i
                cur.append(b)
            else:
                if len(cur) >= minlen:
                    out.append((start, cur.decode("latin-1")))
                    if len(out) >= limit:
                        return out
                cur = bytearray()
        if len(cur) >= minlen:
            out.append((start, cur.decode("latin-1")))
        return out

    def hexdump(self, offset, length=256):
        """Annotated hexdump of a region."""
        lines = []
        for r in range(offset, offset + length, 16):
            row = self.data[r:r + 16]
            if not row:
                break
            hexs = " ".join(f"{b:02x}" for b in row)
            asc = "".join(chr(b) if 32 <= b < 127 else "." for b in row)
            lines.append(f"{r:08x}  {hexs:<47}  {asc}")
        return "\n".join(lines)

    def diff(self, other_path, limit=128):
        """Changed byte ranges vs another file: [(start, end)], + both lengths."""
        with open(other_path, "rb") as f:
            other = f.read()
        a, b = self.data, other
        n = min(len(a), len(b))
        ranges = []
        i = 0
        while i < n and len(ranges) < limit:
            if a[i] != b[i]:
                s = i
                while i < n and a[i] != b[i]:
                    i += 1
                ranges.append((s, i))
            else:
                i += 1
        return ranges, len(a), len(b)

    def replace(self, old, new):
        """Find-and-replace an equal-length byte sequence everywhere."""
        o, nw = _as_bytes(old), _as_bytes(new)
        if len(o) != len(nw):
            raise ValueError("replace needs equal-length sequences "
                             f"(old {len(o)}, new {len(nw)})")
        self.data = bytearray(bytes(self.data).replace(o, nw))
        self._walk()
        return self

    def save(self, outpath=None):
        if not outpath:
            base, ext = os.path.splitext(self.path)
            outpath = base + "_forged" + ext
        with open(outpath, "wb") as f:
            f.write(self.data)
        return outpath

    def show(self):
        lines = [f"{self.fmt}  ({len(self.data):,} bytes)"
                 + ("  [now unparsed]" if self.fmt == "unparsed" else "")]
        for c in self.chunks:
            lines.append(f"  {str(c.get('id','?')).strip():<8} "
                         f"@0x{c.get('offset',0):08x}  {c.get('size','?')} bytes")
            for f in c.get("fields", []):
                if f.get("off") is not None:
                    lines.append(f"      {f.get('name'):<20} = "
                                 f"{str(f.get('value'))[:40]}")
        return "\n".join(lines)


# -- recipes: named, repeatable weirdness ---------------------------------
def _p(params, key, default):
    return (params or {}).get(key, default)


def _recipe_padding_noise(fg, params=None):
    """Fill every ignorable/padding-ish chunk with random bytes."""
    import random as _r
    rng = _r.Random(1337)
    for c in list(fg.chunks):
        cid = str(c.get("id", "")).strip().upper()
        if cid in ("JUNK", "PAD", "PADDING", "FREE", "SKIP") and (c.get("size") or 0) > 0:
            pb = c.get("payload_base", (c.get("offset") or 0) + 8)
            fg.patch(pb, bytes(rng.randint(0, 255) for _ in range(c["size"])))
    return fg


def _recipe_data_bitflip(fg, params=None):
    """Corrupt the main audio payload (data / mdat / SDAT)."""
    rate = float(_p(params, "rate", 0.002))
    mode = _p(params, "mode", "bitflip")
    for c in fg.chunks:
        if str(c.get("id", "")).strip().upper() in ("DATA", "MDAT", "SDAT"):
            fg.corrupt_chunk(str(c["id"]).strip(), mode=mode, rate=rate)
            break
    return fg


def _recipe_wav_rate_bend(fg, params=None):
    """Scale the declared WAV sample rate by `factor`: same samples, different
    speed + pitch. The purest databend, one field, dramatic result."""
    factor = float(_p(params, "factor", 0.5))
    loc = fg.field("fmt", "sample_rate")
    if loc:
        off, ln, val = loc
        try:
            cur = int(str(val).replace(",", ""))
        except ValueError:
            cur = 44100
        fg.set_int(off, max(1, int(cur * factor)), ln, "little")
    return fg


def _recipe_wav_data_sort(fg, params=None):
    """Windowed byte-sort of the PCM data: a rhythmic pixel-sort-style glitch."""
    win = max(2, int(_p(params, "window", 4096)))
    c = fg._chunk("data")
    if c:
        pb = c.get("payload_base", c["offset"] + 8)
        n = c.get("size") or 0
        buf = bytearray(fg.data[pb:pb + n])
        for s in range(0, len(buf), win):
            buf[s:s + win] = bytes(sorted(buf[s:s + win]))
        fg.patch(pb, bytes(buf))
    return fg


def _recipe_mp3_bitrate_scramble(fg, params=None):
    """Rewrite the bitrate nibble of every MPEG frame header to a random value:
    the classic 'change bitrates over and over throughout the file' glitch. The
    decoder improvises frame by frame."""
    import random as _r
    rng = _r.Random(1337)
    d = fg.data
    c = fg._chunk("frame0")
    i = c["offset"] if c else 0
    while i + 3 < len(d):
        if d[i] == 0xFF and (d[i + 1] & 0xE0) == 0xE0:      # frame sync
            d[i + 2] = (d[i + 2] & 0x0F) | (rng.randint(1, 14) << 4)
            i += 2
        else:
            i += 1
    fg._walk()
    return fg


def _recipe_midi_tempo_warp(fg, params=None):
    """Randomize every set-tempo meta event (FF 51 03) within a BPM range."""
    import random as _r
    rng = _r.Random(1337)
    lo = int(_p(params, "lo_bpm", 40))
    hi = int(_p(params, "hi_bpm", 220))
    lo, hi = min(lo, hi), max(lo, hi)
    us_lo = int(60_000_000 / max(1, hi))       # faster bpm -> smaller us/quarter
    us_hi = int(60_000_000 / max(1, lo))
    d = fg.data
    marker = bytes([0xFF, 0x51, 0x03])
    j = d.find(marker)
    while j != -1 and j + 6 <= len(d):
        d[j + 3:j + 6] = rng.randint(us_lo, us_hi).to_bytes(3, "big")
        j = d.find(marker, j + 3)
    fg._walk()
    return fg


def _wav_data(fg):
    """(payload_base, size, block_align) of the WAV data chunk, or None."""
    c = fg._chunk("data")
    if not c:
        return None
    pb = c.get("payload_base", c["offset"] + 8)
    ba = 2
    loc = fg.field("fmt", "block_align")
    if loc:
        try:
            ba = max(1, int(str(loc[2]).replace(",", "")))
        except ValueError:
            pass
    return pb, c.get("size") or 0, ba


def _recipe_wav_reverse(fg, params=None):
    """Reverse the PCM by sample frame: the loop plays backwards."""
    r = _wav_data(fg)
    if r:
        pb, n, ba = r
        buf = fg.data[pb:pb + n]
        usable = len(buf) - len(buf) % ba
        frames = [buf[i:i + ba] for i in range(0, usable, ba)]
        frames.reverse()
        fg.patch(pb, b"".join(bytes(f) for f in frames) + bytes(buf[usable:]))
    return fg


def _recipe_wav_bitcrush(fg, params=None):
    """Mask the low `bits` of every 16-bit sample: crushed resolution (8 = the
    classic low-byte zero; higher = grittier)."""
    bits = max(1, min(15, int(_p(params, "bits", 8))))
    mask = (0xFFFF << bits) & 0xFFFF
    r = _wav_data(fg)
    if r:
        pb, n, _ = r
        buf = bytearray(fg.data[pb:pb + n])
        for i in range(0, len(buf) - 1, 2):
            v = (buf[i] | (buf[i + 1] << 8)) & mask
            buf[i] = v & 0xFF
            buf[i + 1] = (v >> 8) & 0xFF
        fg.patch(pb, bytes(buf))
    return fg


def _recipe_wav_stutter(fg, params=None):
    """Repeat each window twice: a rhythmic stutter/hesitation."""
    win_req = max(2, int(_p(params, "window", 4096)))
    r = _wav_data(fg)
    if r:
        pb, n, ba = r
        win = (win_req // ba) * ba or ba
        buf = fg.data[pb:pb + n]
        out = bytearray()
        for s in range(0, len(buf), win * 2):
            block = buf[s:s + win]
            out += block + block
        fg.patch(pb, bytes(out[:n]))
    return fg


RECIPES = {
    "padding-noise": _recipe_padding_noise,
    "data-bitflip": _recipe_data_bitflip,
    "wav-rate-bend": _recipe_wav_rate_bend,
    "wav-data-sort": _recipe_wav_data_sort,
    "wav-reverse": _recipe_wav_reverse,
    "wav-bitcrush": _recipe_wav_bitcrush,
    "wav-stutter": _recipe_wav_stutter,
    "mp3-bitrate-scramble": _recipe_mp3_bitrate_scramble,
    "midi-tempo-warp": _recipe_midi_tempo_warp,
}

# adjustable knobs per recipe (name, kind, range/choices, default value).
# recipes not listed here take no parameters.
RECIPE_PARAMS = {
    "data-bitflip": [
        {"name": "rate", "kind": "float", "min": 0.0005, "max": 0.05,
         "step": 0.0005, "value": 0.002},
        {"name": "mode", "kind": "enum",
         "choices": ["bitflip", "random", "xor"], "value": "bitflip"},
    ],
    "wav-rate-bend": [
        {"name": "factor", "kind": "float", "min": 0.25, "max": 4.0,
         "step": 0.25, "value": 0.5},
    ],
    "wav-data-sort": [
        {"name": "window", "kind": "int", "min": 256, "max": 16384,
         "step": 256, "value": 4096},
    ],
    "wav-bitcrush": [
        {"name": "bits", "kind": "int", "min": 1, "max": 15, "step": 1, "value": 8},
    ],
    "wav-stutter": [
        {"name": "window", "kind": "int", "min": 512, "max": 16384,
         "step": 512, "value": 4096},
    ],
    "midi-tempo-warp": [
        {"name": "lo_bpm", "kind": "int", "min": 20, "max": 300, "step": 10, "value": 40},
        {"name": "hi_bpm", "kind": "int", "min": 20, "max": 300, "step": 10, "value": 220},
    ],
}


def _looks_int(s):
    try:
        int(str(s), 0)
        return True
    except ValueError:
        return False


def _asint(s):
    return int(str(s), 0) if isinstance(s, str) else int(s)


def _main(argv):
    if len(argv) < 2:
        print(__doc__)
        return 0
    path, op = argv[0], argv[1]
    rest = argv[2:]
    out = rest[rest.index("-o") + 1] if "-o" in rest else None
    pos = [a for i, a in enumerate(rest)
           if a != "-o" and (i == 0 or rest[i - 1] != "-o") and not a.startswith("--")]
    opt = {rest[i][2:]: rest[i + 1] for i in range(len(rest))
           if rest[i].startswith("--") and i + 1 < len(rest)}
    fg = Forge(path)
    if op == "show":
        print(fg.show())
        return 0
    if op == "play":                                   # hear a chunk, or the file
        from acidcat.util import play as _play
        if pos:
            c = fg._chunk(pos[0])
            if not c:
                print(f"no chunk {pos[0]} (try `show`)")
                return 1
            pb = c.get("payload_base", (c.get("offset") or 0) + 8)
            print(f"playing {pos[0]} payload ({c.get('size')} bytes) as PCM...")
            _play.play_region(path, pb, c.get("size") or 0,
                              rate=int(opt.get("rate", 44100)),
                              ch=int(opt.get("ch", 2)),
                              bits=int(opt.get("bits", 16)), block=True)
        else:
            _play.play(path)
        return 0
    if op == "examine" and pos:
        off = _asint(pos[0])
        fmt = opt.get("fmt", "u8")
        vals = fg.read(off, fmt, int(opt.get("count", "8")))
        print(f"0x{off:08x}  {fmt}:  " + "  ".join(str(v) for v in vals))
        return 0
    if op == "hexdump" and pos:
        print(fg.hexdump(_asint(pos[0]), int(opt.get("len", "256"))))
        return 0
    if op == "find" and pos:
        offs = fg.find(pos[0])
        print(f"{len(offs)} match(es): "
              + "  ".join(f"0x{o:08x}" for o in offs[:40]))
        return 0
    if op == "scan" and pos:
        fmt = opt.get("fmt", "u16")
        offs = fg.find_value(_asint(pos[0]), fmt)
        print(f"{len(offs)} offset(s) hold {pos[0]} as {fmt}: "
              + "  ".join(f"0x{o:08x}" for o in offs[:40]))
        return 0
    if op == "strings":
        for off, s in fg.strings(int(opt.get("min", "4"))):
            print(f"0x{off:08x}  {s}")
        return 0
    if op == "diff" and pos:
        ranges, la, lb = fg.diff(pos[0])
        print(f"{os.path.basename(path)} ({la:,}) vs "
              f"{os.path.basename(pos[0])} ({lb:,}): {len(ranges)} changed range(s)")
        for s, e in ranges[:40]:
            print(f"  0x{s:08x} .. 0x{e:08x}  ({e - s} bytes)")
        return 0
    if op == "set" and len(pos) >= 3:
        fg.set_field(pos[0], pos[1], pos[2])
    elif op == "replace" and len(pos) >= 2:
        fg.replace(pos[0], pos[1])
    elif op == "fill" and len(pos) >= 2:
        fg.fill_chunk(pos[0], _asint(pos[1]))
    elif op == "corrupt" and len(pos) >= 1:
        fg.corrupt_chunk(pos[0], mode=opt.get("mode", "bitflip"),
                         rate=float(opt.get("rate", 0.01)))
    elif op == "patch" and len(pos) >= 2:
        fg.patch(_asint(pos[0]), bytes.fromhex(pos[1]))
    elif op == "recipe" and len(pos) >= 1 and pos[0] in RECIPES:
        RECIPES[pos[0]](fg)
    else:
        print(__doc__)
        return 1
    dst = fg.save(out)
    print(f"forged -> {dst}\n  now parses as: {fg.fmt}"
          + (f"  (warnings: {len(fg.warns)})" if fg.warns else ""))
    if "--play" in rest and dst.lower().endswith((".wav", ".mp3")):
        from acidcat.util import play as _play
        print("  playing the forged result...")
        _play.play(dst)
    return 0


if __name__ == "__main__":
    sys.exit(_main(sys.argv[1:]))
