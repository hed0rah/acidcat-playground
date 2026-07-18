"""OGG dual-bitstream PoC: one .ogg carrying two concurrent logical bitstreams.

Ogg is a multiplexing container (RFC 3533): a single physical stream can carry
several logical bitstreams, each with its own serial number and BOS/EOS pages.
That is how Ogg video files ship Theora + Vorbis together, but nothing stops two
AUDIO codecs sharing one file. This builds a .ogg with a Vorbis "song A" and an
Opus "song B" (different tones so it is audible which you get): a Vorbis-only
decoder plays A, an Opus-only decoder plays B, a full decoder may surface both
(decoder-dependent). All spec-valid; every basic MIME/extension check says "audio/ogg".

Defensive point: a second logical bitstream is a place to carry content most
players never surface. The tell is simple, a conformant single-track Ogg has ONE
BOS page; more than one distinct BOS serial means multiple logical bitstreams.

Needs ffmpeg on PATH.

  python ogg_multiplex.py build -o dual.ogg [--a-hz 440] [--b-hz 660] [--secs 2]
  python ogg_multiplex.py analyze <file.ogg>
"""

import os
import subprocess
import sys
import tempfile

REPO = os.environ.get("ACIDCAT_REPO") or os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "acidcat")
# acidcat: a sibling checkout by default, or set ACIDCAT_REPO, or pip install acidcat
sys.path.insert(0, os.path.join(REPO, "src"))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from acidcat.core import ogg as oggmod  # noqa: E402


def _ff(*args):
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", *args], check=True)


def build(out, a_hz=440, b_hz=660, secs=2):
    """Mux a Vorbis tone (song A) and an Opus tone (song B) into one .ogg."""
    fd_a, a = tempfile.mkstemp(suffix=".ogg")
    fd_b, b = tempfile.mkstemp(suffix=".ogg")
    os.close(fd_a)
    os.close(fd_b)
    try:
        _ff("-f", "lavfi", "-i", f"sine=frequency={a_hz}:duration={secs}",
            "-c:a", "libvorbis", a)
        _ff("-f", "lavfi", "-i", f"sine=frequency={b_hz}:duration={secs}",
            "-c:a", "libopus", b)
        _ff("-i", a, "-i", b, "-map", "0:a", "-map", "1:a", "-c", "copy", out)
    finally:
        for p in (a, b):
            try:
                os.unlink(p)
            except OSError:
                pass


def analyze(path):
    """[(serial, codec)] for each logical bitstream (each BOS page)."""
    data = open(path, "rb").read()
    streams = []
    for pg in oggmod.iter_pages(data):
        if pg["header_type"] & 0x02:                       # BOS
            head = data[pg["data_off"]:pg["data_off"] + 8]
            codec = ("Vorbis" if head[1:7] == b"vorbis"
                     else "Opus" if head[:8] == b"OpusHead"
                     else "FLAC" if head[1:5] == b"FLAC"
                     else head[:8].decode("latin-1", "replace"))
            streams.append((pg["serial"], codec))
    return streams


if __name__ == "__main__":
    a = sys.argv[1:]
    out = a[a.index("-o") + 1] if "-o" in a else "dual.ogg"

    def opt(flag, d):
        return type(d)(a[a.index(flag) + 1]) if flag in a else d
    if a and a[0] == "build":
        build(out, opt("--a-hz", 440), opt("--b-hz", 660), opt("--secs", 2))
        s = analyze(out)
        print(f"wrote {out}: {len(s)} logical bitstream(s) -> "
              + ", ".join(f"{c}(serial {sn})" for sn, c in s))
    elif len(a) == 2 and a[0] == "analyze":
        s = analyze(a[1])
        print(f"{os.path.basename(a[1])}: {len(s)} logical bitstream(s)")
        for sn, c in s:
            print(f"  serial {sn}: {c}")
        if len(s) > 1:
            print("  ^ multiple bitstreams: a single-codec player surfaces only one")
    else:
        print(__doc__)
