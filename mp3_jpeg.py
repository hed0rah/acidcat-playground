"""MP3 carrying a byte-exact standalone JPEG in an ID3v2 APIC frame.

An ID3v2 APIC (attached picture) frame stores cover art as: text-encoding byte,
null-terminated MIME string, picture-type byte, null-terminated description, then
the raw image bytes to end of frame. Those image bytes are a complete file in their
own right: carve them out and they open as a JPEG with no modification. The MP3
plays normally; the picture is legitimate ID3 content, not a parasite.

This is not a byte-0 dual-open polyglot: the file begins with "ID3", so a JPEG
decoder reading from offset 0 does not see an image. It is a container carrying a
byte-exact secondary format that a carver recovers whole. The true front-loaded
polyglot (JPEG SOI..EOI first, MPEG frames appended, so the same bytes open as both
image and audio) is left unbuilt here because its MP3 side is decoder-dependent: a
JPEG's APP0 marker is 0xFFE0, which satisfies the 11-bit MPEG frame-sync pattern, so
a resyncing decoder can lock onto the picture instead of the audio. The APIC form is
deterministic and always plays; that is the trade.

acidcat detection rule this motivates (embedded_standalone_media):
  The MP3 walker collapses ID3v2 into one chunk. It should enumerate picture frames
  (APIC in v2.3/2.4, PIC in v2.2) as byte regions with an xref to their image data,
  and flag any frame whose payload begins with a known file magic and ends with that
  format's terminator (JPEG FFD8..FFD9, PNG 89504E47..49454E44) as a complete
  embedded file, so `carve` can extract it. Generalizes to any container frame
  holding a self-delimited secondary format.

  python mp3_jpeg.py embed carrier.mp3 cover.jpg -o out.mp3
  python mp3_jpeg.py extract out.mp3 -o recovered.jpg
  python mp3_jpeg.py analyze out.mp3
"""

import os
import struct
import sys

REPO = os.environ.get("ACIDCAT_REPO") or os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "acidcat")
# acidcat: a sibling checkout by default, or set ACIDCAT_REPO, or pip install acidcat
sys.path.insert(0, os.path.join(REPO, "src"))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")


def _syncsafe(n):
    return bytes([(n >> 21) & 0x7F, (n >> 14) & 0x7F, (n >> 7) & 0x7F, n & 0x7F])


def _unsync(b):
    return (b[0] << 21) | (b[1] << 14) | (b[2] << 7) | b[3]


def _audio_of(mp3):
    """Return the MPEG audio, dropping any leading ID3v2 tag."""
    if mp3[:3] == b"ID3":
        return mp3[10 + _unsync(mp3[6:10]):]
    return mp3


def _apic_frame(jpeg, desc=b""):
    """An ID3v2.3 APIC frame (plain-u32 frame size) holding a JPEG as front cover."""
    body = b"\x00" + b"image/jpeg\x00" + b"\x03" + desc + b"\x00" + jpeg
    return b"APIC" + struct.pack(">I", len(body)) + b"\x00\x00" + body


def build(mp3, jpeg):
    """Prepend a fresh ID3v2.3 tag carrying `jpeg` as APIC to the carrier's audio."""
    if jpeg[:2] != b"\xff\xd8" or jpeg[-2:] != b"\xff\xd9":
        raise ValueError("payload is not a complete JPEG (want FFD8..FFD9)")
    frame = _apic_frame(jpeg)
    tag = b"ID3\x03\x00\x00" + _syncsafe(len(frame)) + frame
    return tag + _audio_of(mp3)


def carve(mp3):
    """Recover the APIC image bytes byte-exact, or None."""
    if mp3[:3] != b"ID3":
        return None
    size = _unsync(mp3[6:10])
    body, off = mp3[10:10 + size], 0
    while off + 10 <= len(body):
        fid = body[off:off + 4]
        if fid == b"\x00\x00\x00\x00" or not fid.strip():
            break
        fsize = struct.unpack(">I", body[off + 4:off + 8])[0]
        frame = body[off + 10:off + 10 + fsize]
        if fid == b"APIC":
            p = frame.index(b"\x00", 1)            # end of MIME
            p = frame.index(b"\x00", p + 2) + 1    # skip pic-type + end of desc
            return frame[p:]
        off += 10 + fsize
    return None


def analyze(path):
    from acidcat.core.walk import walk_file
    data = open(path, "rb").read()
    fmt, chunks, warns = walk_file(path, deep=False)
    img = carve(data)
    print(f"{path} ({len(data):,} bytes)")
    print(f"  acidcat: {fmt}  chunks={[c['id'] for c in chunks]}  warnings={warns or 'none'}")
    if img is None:
        print("  APIC: none found")
        return False
    ok = img[:2] == b"\xff\xd8" and img[-2:] == b"\xff\xd9"
    print(f"  APIC image: {len(img):,} bytes, {'valid standalone JPEG' if ok else 'NOT a complete JPEG'} "
          f"(FFD8..{img[-2:].hex()})")
    try:
        import io
        from PIL import Image
        im = Image.open(io.BytesIO(img)); im.verify()
        print(f"  PIL opens carved bytes: {im.format} {im.size}")
    except Exception as e:
        print(f"  PIL: {e.__class__.__name__}: {e}")
    return ok


if __name__ == "__main__":
    a = sys.argv[1:]
    if len(a) >= 4 and a[0] == "embed" and "-o" in a:
        out = a[a.index("-o") + 1]
        open(out, "wb").write(build(open(a[1], "rb").read(), open(a[2], "rb").read()))
        analyze(out)
    elif len(a) >= 2 and a[0] == "extract":
        out = a[a.index("-o") + 1] if "-o" in a else "recovered.jpg"
        img = carve(open(a[1], "rb").read())
        if img is None:
            sys.exit("no APIC frame found")
        open(out, "wb").write(img)
        print(f"wrote {out} ({len(img):,} bytes)")
    elif len(a) == 2 and a[0] == "analyze":
        analyze(a[1])
    else:
        print(__doc__)
