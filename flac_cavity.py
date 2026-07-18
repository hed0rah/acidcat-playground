"""FLAC metadata-block cavities: two spec-valid hiding spots inside a .flac.

A FLAC stream is "fLaC" then a chain of METADATA_BLOCKs, then audio frames. Each
block is a 4-byte header (bit7 = is-last-block flag, bits6-0 = block type) plus a
24-bit big-endian length, then the block body. Decoders play the audio no matter
what optional metadata blocks are present, so metadata is a container-internal
cavity (not a tail parasite; the frames and every length field stay honest).

Two vectors, both round-tripped here:

  app  : an APPLICATION block (type 2). Body = 4-byte application id + free data.
         Decoders skip application ids they do not know, so an unregistered id
         (we use "ACFC") carries an arbitrary payload while the file stays valid.
  pad  : a PADDING block (type 1). The spec says padding bytes are all zero, so
         non-zero PADDING is a clean cavity, the FLAC analog of a non-zero RIFF
         JUNK chunk. We fill it with the payload.

We insert the new block right after STREAMINFO and rewrite the is-last-block
flags so the chain stays conformant. Extraction reverses it byte-exactly.

Under-documented as a *hiding* vector: FLAC APPLICATION/PADDING blocks are
usually discussed as legitimate features, not as smuggling spots, and most
tools never surface their contents.

acidcat detection rules this motivates:
  flac_app_unregistered : APPLICATION block whose id is not in the Xiph registry
                          (or is high-entropy / looks like a payload marker).
  flac_padding_nonzero  : PADDING block containing any non-zero byte (reuse the
                          cavity_content rule already used for RIFF JUNK/PAD).

  python flac_cavity.py app carrier.flac secret.bin -o out.flac
  python flac_cavity.py pad carrier.flac secret.bin -o out.flac
  python flac_cavity.py extract out.flac -o secret.bin
  python flac_cavity.py analyze out.flac
"""

import os
import struct
import sys

REPO = os.environ.get("ACIDCAT_REPO") or os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "acidcat")
# acidcat: a sibling checkout by default, or set ACIDCAT_REPO, or pip install acidcat
sys.path.insert(0, os.path.join(REPO, "src"))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

APP_ID = b"ACFC"                    # unregistered application id (the tell)
MAGIC = b"ACFL"                     # marker so extract finds our block

_TYPE = {0: "STREAMINFO", 1: "PADDING", 2: "APPLICATION", 3: "SEEKTABLE",
         4: "VORBIS_COMMENT", 5: "CUESHEET", 6: "PICTURE"}


def _blocks(flac):
    """Yield (btype, is_last, body_bytes) for each metadata block."""
    if flac[:4] != b"fLaC":
        raise ValueError("not a FLAC stream")
    pos = 4
    while pos + 4 <= len(flac):
        hdr = flac[pos]
        is_last = bool(hdr & 0x80)
        btype = hdr & 0x7F
        size = struct.unpack(">I", b"\x00" + flac[pos + 1:pos + 4])[0]
        body = flac[pos + 4:pos + 4 + size]
        yield btype, is_last, body
        pos += 4 + size
        if is_last:
            break
    globals()["_frames_off"] = pos            # where audio frames start


def _emit(btype, body, is_last):
    hdr = (0x80 if is_last else 0) | (btype & 0x7F)
    return bytes([hdr]) + struct.pack(">I", len(body))[1:] + body


def _rebuild(flac, new_type, new_body):
    """Insert a metadata block after STREAMINFO, fix is-last flags, keep frames."""
    blocks = [(t, b) for t, _last, b in _blocks(flac)]
    frames = flac[_frames_off:]
    # STREAMINFO must stay first; splice ours in at index 1
    blocks.insert(1, (new_type, new_body))
    out = bytearray(b"fLaC")
    for i, (t, b) in enumerate(blocks):
        out += _emit(t, b, is_last=(i == len(blocks) - 1))
    out += frames
    return bytes(out)


def embed_app(flac, payload):
    return _rebuild(flac, 2, APP_ID + MAGIC + payload)


def embed_pad(flac, payload):
    return _rebuild(flac, 1, MAGIC + payload)


def extract(flac):
    for btype, _last, body in _blocks(flac):
        if btype == 2 and body[:4] == APP_ID and body[4:8] == MAGIC:
            return body[8:]
        if btype == 1 and body[:4] == MAGIC:
            return body[4:]
    return b""


def analyze(flac):
    out = []
    for btype, is_last, body in _blocks(flac):
        name = _TYPE.get(btype, f"RESERVED({btype})")
        note = ""
        if btype == 2:
            aid = body[:4]
            note = f" app id {aid!r}" + (" (unregistered/cavity)"
                                         if aid == APP_ID else "")
        elif btype == 1:
            note = " NON-ZERO (cavity)" if any(body) else " all zero (padding)"
        out.append(f"{name}: {len(body)} bytes{note}"
                   + (" [last]" if is_last else ""))
    return out


if __name__ == "__main__":
    a = sys.argv[1:]
    out = a[a.index("-o") + 1] if "-o" in a else None
    if a and a[0] in ("app", "pad") and len(a) >= 3:
        flac = open(a[1], "rb").read()
        payload = open(a[2], "rb").read()
        data = (embed_app if a[0] == "app" else embed_pad)(flac, payload)
        dst = out or "out.flac"
        open(dst, "wb").write(data)
        print(f"wrote {dst}: {len(payload):,}-byte payload via {a[0].upper()} block "
              f"({len(data):,} bytes total)")
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
