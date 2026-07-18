"""shiny_hunt.py -- scan a directory for rare / off-spec audio-format variants.

The "found" half of the specimen archive: point it at a folder of real files and
it reports which shinies are present (and an example of each), without copying
the copyrighted files anywhere. Detection is header-based (fast), so it reads
only the first 64 KB + the ID3v1 trailer of each file.

  python shiny_hunt.py /path/to/samples
  python shiny_hunt.py .                 # current dir
"""

import os
import struct
import sys

_WAVE_TAGS = {3: "float", 6: "a-law", 7: "mu-law", 2: "ms-adpcm",
              17: "ima-adpcm", 0xFFFE: "extensible"}
_WAV_CHUNKS = (b"bext", b"acid", b"smpl", b"cue ", b"cart", b"iXML",
               b"fact", b"JUNK", b"LIST", b"ID3 ")


def hunt(root):
    finds = {}                       # shiny -> [count, example basename]

    def hit(k, p):
        finds.setdefault(k, [0, os.path.basename(p)])
        finds[k][0] += 1

    scanned = 0
    for r, _, fs in os.walk(root):
        for n in fs:
            if n.startswith("._"):
                continue
            ext = os.path.splitext(n)[1].lower()
            p = os.path.join(r, n)
            try:
                with open(p, "rb") as f:
                    head = f.read(65536)
            except OSError:
                continue
            scanned += 1
            if head[:4] in (b"RF64", b"BW64"):
                hit("RF64/BW64 (64-bit wav)", p)
            if head[:4] == b"RIFF" and head[8:12] == b"RMID":
                hit("RMID (RIFF-wrapped MIDI)", p)
            if head[:4] == b"RIFF" and head[8:12] == b"WAVE":
                fi = head.find(b"fmt ")
                if 0 <= fi and fi + 24 <= len(head):
                    tag = struct.unpack_from("<H", head, fi + 8)[0]
                    if tag in _WAVE_TAGS:
                        hit(f"WAV fmt={_WAVE_TAGS[tag]}", p)
                    bps = struct.unpack_from("<H", head, fi + 22)[0]
                    if bps == 24:
                        hit("WAV 24-bit", p)
                for ck in _WAV_CHUNKS:
                    if ck in head[12:]:
                        hit(f"WAV chunk {ck.decode().strip()}", p)
            if head[:4] == b"FORM" and head[8:12] == b"AIFC":
                hit("AIFF-C (compressed)", p)
            if head[:4] == b"FORM" and b"sowt" in head[:300]:
                hit("AIFC sowt (byte-swapped)", p)
            if head[:3] == b"ID3":
                hit(f"ID3v2.{head[3]}", p)
                if head[5] & 0x40:
                    hit("ID3v2 extended-header", p)
                if head[5] & 0x80:
                    hit("ID3v2 unsync", p)
            for tag in (b"Xing", b"VBRI", b"LAME"):
                if tag in head[:4000]:
                    hit(f"MP3 {tag.decode()} header", p)
            if head[:4] == b"MThd" and len(head) >= 14:
                if struct.unpack_from(">H", head, 8)[0] == 2:
                    hit("MIDI format 2", p)
                if struct.unpack_from(">h", head, 12)[0] < 0:
                    hit("MIDI SMPTE timing", p)
            if head[:4] == b"fLaC":
                i = 4
                for _ in range(32):
                    if i + 4 > len(head):
                        break
                    bt, last = head[i] & 0x7F, head[i] & 0x80
                    sz = int.from_bytes(head[i + 1:i + 4], "big")
                    hit({5: "FLAC cuesheet", 6: "FLAC picture",
                         2: "FLAC application"}.get(bt), p) if bt in (2, 5, 6) else None
                    if last:
                        break
                    i += 4 + sz
            if head[4:8] == b"ftyp":
                if b"moof" in head:
                    hit("MP4 fragmented", p)
                if b"alac" in head:
                    hit("ALAC (Apple Lossless)", p)
    return scanned, finds


def _main(argv):
    root = argv[0] if argv else "."
    if not os.path.isdir(root):
        print(f"not a directory: {root}")
        return 1
    scanned, finds = hunt(root)
    print(f"scanned {scanned} files under {root}\n")
    if not finds:
        print("  no rare variants found")
        return 0
    for k, (c, ex) in sorted(finds.items(), key=lambda x: -x[1][0]):
        print(f"  {c:5}  {k:30} e.g. {ex[:44]}")
    return 0


if __name__ == "__main__":
    sys.exit(_main(sys.argv[1:]))
