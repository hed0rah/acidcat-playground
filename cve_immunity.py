"""CVE-immunity suite: reproduce historical audio-parser bug CLASSES as benign
fixtures and confirm acidcat survives (no crash, no hang, warns where apt).

acidcat is pure Python, so the memory-corruption CVEs cannot become RCE; what
survives translation is the input pattern (forged counts, zero-size elements,
channels<=0, odd UTF-16, inflated durations) -> DoS/hang/huge-alloc/wrong-output.
Each fixture below encodes one such pattern; the runner walks it under a wall-clock
timeout in a subprocess so a hang shows up as a failure rather than freezing us.
"""

import os
import sys
import struct
import subprocess
import tempfile

REPO = os.environ.get("ACIDCAT_REPO") or os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "acidcat")
# acidcat: a sibling checkout by default, or set ACIDCAT_REPO, or pip install acidcat
sys.path.insert(0, os.path.join(REPO, "src"))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
_ENV = {**os.environ, "PYTHONPATH": os.path.join(REPO, "src")}


def _chunk(cid, p):
    return cid + struct.pack("<I", len(p)) + p + (b"\x00" if len(p) % 2 else b"")


def _wav(*chunks):
    body = b"WAVE" + b"".join(chunks)
    return b"RIFF" + struct.pack("<I", len(body)) + body


_FMT = _chunk(b"fmt ", struct.pack("<HHIIHH", 1, 2, 44100, 176400, 4, 16))


def forged_smpl_loops():
    """CVE-2018-10536 / Stagefright class: a forged loop/sample count that a
    naive parser multiplies into an allocation. acidcat should clamp to payload."""
    smpl = struct.pack("<9I", 0, 0, 0, 60, 0, 0, 0, 0xFFFFFFFF, 0)  # num_loops = 4.3e9
    return _wav(_FMT, _chunk(b"data", b"\x00" * 16), _chunk(b"smpl", smpl))


def forged_cue_count():
    """A cue chunk claiming 4 billion cue points in a few bytes (unbounded loop)."""
    cue = struct.pack("<I", 0xFFFFFFFF)  # num_cues, then no data
    return _wav(_FMT, _chunk(b"data", b"\x00" * 16), _chunk(b"cue ", cue))


def zero_size_list_subchunk():
    """FFmpeg AVI LIST-size-0 class: a zero-size sub-chunk must not spin the loop."""
    lst = b"INFO" + b"IART" + struct.pack("<I", 0) + b"INAM" + struct.pack("<I", 2) + b"hi"
    return _wav(_FMT, _chunk(b"data", b"\x00" * 16), _chunk(b"LIST", lst))


def inflated_data_duration():
    """data chunk declares far more audio than the file holds (Xing/num_frames
    divergence class): acidcat should warn, not trust the header."""
    body = b"WAVE" + _FMT + b"data" + struct.pack("<I", 0x7FFFFFF0) + b"\x00" * 16
    return b"RIFF" + struct.pack("<I", len(body)) + body


def odd_utf16_id3():
    """libid3tag CVE-2017-11551 class: ID3v2.4 TXXX frame, UTF-16 encoding, odd
    body length. In C this looped forever; Python's decoder must just cope."""
    # frame body: encoding byte 0x01 (utf-16) + an odd number of trailing bytes
    fbody = b"\x01\xff\xfeA"          # BOM + one stray byte = odd content
    frame = b"TXXX" + struct.pack(">I", len(fbody)) + b"\x00\x00" + fbody
    n = len(frame)
    synch = bytes([(n >> 21) & 0x7f, (n >> 14) & 0x7f, (n >> 7) & 0x7f, n & 0x7f])
    tag = b"ID3\x04\x00\x00" + synch + frame
    mpeg = b"\xff\xfb\x90\x00" + b"\x00" * 417   # one MPEG1 L3 128k 44.1k frame
    return tag + mpeg


def channels_zero_ogg():
    """libvorbis CVE-2017-14632/14633 class: a Vorbis ident header with 0 channels.
    acidcat must not divide by zero or emit garbage; report 0 and move on."""
    ident = b"\x01vorbis" + struct.pack("<I", 0) + bytes([0]) + struct.pack("<I", 0)
    seg = [len(ident)]
    hdr = (b"OggS\x00\x02" + b"\x00" * 8 + struct.pack("<I", 1) + b"\x00" * 4
           + b"\x00" * 4 + bytes([len(seg)]) + bytes(seg))
    return hdr + ident


FIXTURES = {
    "forged_smpl_loops": (".wav", forged_smpl_loops, "CVE-2018-10536/Stagefright: forged count"),
    "forged_cue_count": (".wav", forged_cue_count, "unbounded cue-count loop"),
    "zero_size_list_subchunk": (".wav", zero_size_list_subchunk, "FFmpeg AVI LIST size 0"),
    "inflated_data_duration": (".wav", inflated_data_duration, "Xing/num_frames divergence"),
    "odd_utf16_id3": (".mp3", odd_utf16_id3, "libid3tag CVE-2017-11551: odd UTF-16"),
    "channels_zero_ogg": (".ogg", channels_zero_ogg, "libvorbis CVE-2017-14632: channels<=0"),
}


def run():
    print(f"{'fixture':26} {'outcome':10} time  note")
    worst = 0
    for name, (suffix, fn, cve) in FIXTURES.items():
        data = fn()
        fd, tmp = tempfile.mkstemp(suffix=suffix)
        with os.fdopen(fd, "wb") as f:
            f.write(data)
        try:
            r = subprocess.run(
                [sys.executable, "-m", "acidcat", "inspect", "--frames", tmp,
                 "--color", "never"],
                capture_output=True, env=_ENV, timeout=12)
            out = (r.stdout + r.stderr).decode("utf-8", "replace")
            warned = "warn" in out.lower() or "!" in out
            outcome = "SURVIVED" if r.returncode in (0, 2) else f"rc={r.returncode}"
            note = "warned" if warned else ""
        except subprocess.TimeoutExpired:
            outcome, note = "HANG", "!! exceeded 12s"
            worst = max(worst, 2)
        finally:
            try:
                os.unlink(tmp)
            except OSError:
                pass
        if outcome not in ("SURVIVED",):
            worst = max(worst, 1)
        print(f"  {name:24} {outcome:10} {'':4}  {cve}" + (f" [{note}]" if note else ""))
    print("\nall fixtures survived" if worst == 0 else "\nSOME FIXTURES FAILED - investigate")
    return worst


if __name__ == "__main__":
    sys.exit(run())
