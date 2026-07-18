"""MP3 ID3v2 declared-padding cavity: non-zero bytes inside the tag's padding.

An ID3v2 tag is "ID3", version, flags, then a 4-byte *syncsafe* size (7 bits per
byte) giving the length of the tag body. Players read exactly that many bytes and
jump to the MPEG audio that follows. Taggers normally leave a run of ZERO padding
at the end of the body so a tag can grow in place without rewriting the file. That
padding is declared, inside the tag, and never rendered, so non-zero padding is a
cavity: the file plays identically and the size field stays honest (unlike a tail
parasite, this sits before the audio, counted by the tag length).

We enlarge the existing padding (or synthesize a minimal tag) and drop the payload
there. Extraction reads the declared size and recovers the marked run byte-exact.

Novelty: moderate but under-appreciated. GEOB/PRIV frames are the documented
"carry a blob" features; the raw *padding* region is rarely checked, and no
conformant tagger ever writes non-zero bytes into it. The genuinely spicier
cousin (noted, not built here to keep the PoC deterministic) is an ANTISYNC
cavity: bytes wedged BETWEEN valid MPEG frames that avoid forming an 0xFFE frame
sync, which a resyncing decoder skips with no tag involved at all.

acidcat detection rule this motivates (id3_padding_nonzero):
  After the last parsed ID3v2 frame, any byte up to the declared tag size that is
  non-zero is padding-cavity content. (Generalizes the cavity_content rule to the
  ID3v2 padding region.)

  python id3_cavity.py embed carrier.mp3 secret.bin -o out.mp3
  python id3_cavity.py extract out.mp3 -o secret.bin
  python id3_cavity.py analyze out.mp3
"""

import os
import struct
import sys

REPO = os.environ.get("ACIDCAT_REPO") or os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "acidcat")
# acidcat: a sibling checkout by default, or set ACIDCAT_REPO, or pip install acidcat
sys.path.insert(0, os.path.join(REPO, "src"))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

MAGIC = b"ACID"                    # marker at the head of our padding cavity


def _syncsafe(n):
    return bytes([(n >> 21) & 0x7F, (n >> 14) & 0x7F, (n >> 7) & 0x7F, n & 0x7F])


def _unsync(b):
    return (b[0] << 21) | (b[1] << 14) | (b[2] << 7) | b[3]


def _split(buf):
    """Return (header10, body, audio) for an ID3v2-prefixed MP3, else synth."""
    if buf[:3] == b"ID3":
        size = _unsync(buf[6:10])
        return buf[:10], buf[10:10 + size], buf[10 + size:]
    # no tag: synthesize a v2.4 header with one TIT2 "carrier" frame
    title = b"\x00carrier"                          # text encoding 0x00 + text
    frame = b"TIT2" + struct.pack(">I", len(title)) + b"\x00\x00" + title
    return b"ID3\x04\x00\x00" + _syncsafe(len(frame)), frame, buf


def _frames_len(body):
    """Length of real frames before padding (first byte that is not a frame id)."""
    pos = 0
    while pos + 10 <= len(body) and body[pos] != 0:
        # a frame id is 4 chars A-Z0-9; a 0x00 there means padding started
        fid = body[pos:pos + 4]
        if not all(65 <= c <= 90 or 48 <= c <= 57 for c in fid):
            break
        size = struct.unpack_from(">I", body, pos + 4)[0]
        pos += 10 + size
    return pos


def embed(buf, payload):
    hdr, body, audio = _split(buf)
    cavity = MAGIC + struct.pack(">I", len(payload)) + payload
    new_body = body + cavity                         # append into padding region
    return hdr[:6] + _syncsafe(len(new_body)) + new_body + audio


def extract(buf):
    if buf[:3] != b"ID3":
        return b""
    size = _unsync(buf[6:10])
    body = buf[10:10 + size]
    i = body.find(MAGIC)
    if i == -1:
        return b""
    n = struct.unpack_from(">I", body, i + 4)[0]
    return body[i + 8:i + 8 + n]


def analyze(buf):
    if buf[:3] != b"ID3":
        return ["no ID3v2 tag"]
    size = _unsync(buf[6:10])
    body = buf[10:10 + size]
    flen = _frames_len(body)
    pad = body[flen:]
    nonzero = sum(1 for b in pad if b)
    out = [f"ID3v2.{buf[3]} tag: declared body {size:,} bytes",
           f"real frames: {flen:,} bytes, padding: {len(pad):,} bytes",
           f"padding non-zero bytes: {nonzero:,} "
           + ("(CAVITY)" if nonzero else "(clean)")]
    if MAGIC in pad:
        out.append(f"  ^ contains our marker {MAGIC!r}")
    return out


if __name__ == "__main__":
    a = sys.argv[1:]
    out = a[a.index("-o") + 1] if "-o" in a else None
    if a and a[0] == "embed" and len(a) >= 3:
        buf = open(a[1], "rb").read()
        payload = open(a[2], "rb").read()
        dst = out or "out.mp3"
        open(dst, "wb").write(embed(buf, payload))
        print(f"wrote {dst}: {len(payload):,}-byte ID3v2 padding cavity")
    elif a and a[0] == "extract" and len(a) >= 2:
        dst = out or "payload.bin"
        got = extract(open(a[1], "rb").read())
        open(dst, "wb").write(got)
        print(f"recovered {len(got):,} bytes to {dst}")
    elif a and a[0] == "analyze" and len(a) >= 2:
        for line in analyze(open(a[1], "rb").read()):
            print(line)
    else:
        print(__doc__)
