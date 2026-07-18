"""RF64/WAV JUNK-chunk cavity PoC.

A RIFF "JUNK" chunk is spec'd as ignorable padding, conformant readers skip it.
In the RF64/BW64 world (EBU TECH 3306) a JUNK chunk is specifically the reserved
placeholder that becomes a ds64 chunk once a file grows past 4 GB; until then its
content is free bytes. So a plain WAV carrying a JUNK chunk full of non-zero data
plays normally everywhere while smuggling a payload inside the container (not
appended after it, this is a true cavity, the RIFF size field stays honest).

Under-documented as a hiding vector, and it has a clean detection rule: a
JUNK/PAD chunk whose bytes are not all zero.

  python junk_cavity.py embed carrier.wav secret.bin -o out.wav
  python junk_cavity.py extract out.wav -o secret.bin
  python junk_cavity.py analyze out.wav
"""

import struct
import sys

MAGIC = b"ACJK"                     # marker inside the JUNK chunk so extract finds ours


def _iter_chunks(wav):
    """Yield (cid, start_of_header, data_offset, size) for each RIFF chunk."""
    pos = 12
    while pos + 8 <= len(wav):
        cid = wav[pos:pos + 4]
        size = struct.unpack_from("<I", wav, pos + 4)[0]
        yield cid, pos, pos + 8, size
        pos += 8 + size + (size & 1)


def embed(wav, payload):
    if wav[:4] != b"RIFF" or wav[8:12] != b"WAVE":
        raise ValueError("not a RIFF/WAVE file")
    body = MAGIC + payload
    junk = b"JUNK" + struct.pack("<I", len(body)) + body
    if len(junk) & 1:                                    # RIFF chunks pad to even
        junk += b"\x00"
    # splice the JUNK chunk in right after the "WAVE" tag (before the first chunk)
    out = bytearray(wav)
    out[12:12] = junk
    riff_size = struct.unpack_from("<I", out, 4)[0] + len(junk)
    struct.pack_into("<I", out, 4, riff_size)
    return bytes(out)


def extract(wav):
    for cid, _hdr, doff, size in _iter_chunks(wav):
        if cid in (b"JUNK", b"PAD ") and wav[doff:doff + 4] == MAGIC:
            return wav[doff + 4:doff + size]
    return b""


def analyze(wav):
    out = []
    for cid, hdr, doff, size in _iter_chunks(wav):
        if cid in (b"JUNK", b"PAD "):
            blob = wav[doff:doff + size]
            nonzero = any(blob)
            out.append(f"{cid.decode('latin-1')} at 0x{hdr:04x}: {size} bytes, "
                       f"{'NON-ZERO (cavity)' if nonzero else 'all zero (padding)'}")
    return out or ["no JUNK/PAD chunks found"]


if __name__ == "__main__":
    a = sys.argv[1:]
    out = a[a.index("-o") + 1] if "-o" in a else None
    if a and a[0] == "embed" and len(a) >= 3:
        wav = open(a[1], "rb").read()
        payload = open(a[2], "rb").read()
        dst = out or "out.wav"
        open(dst, "wb").write(embed(wav, payload))
        print(f"wrote {dst}: {len(payload):,}-byte payload in a JUNK chunk")
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
