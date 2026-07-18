"""Generate the weird-audio-format specimen archive.

Every file here is SYNTHESIZED from scratch (silence / tones / hand-built
headers), so it is copyright-clean and safe to share, unlike the real sample-pack
files that carry these quirks in the wild (use shiny_hunt.py to find those in
your own library). Each function documents the exact quirk it demonstrates.

  python make_specimens.py            # (re)generate specimens/formats/*
"""

import os
import struct

OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "formats")


def _w(name, data):
    os.makedirs(OUT, exist_ok=True)
    with open(os.path.join(OUT, name), "wb") as f:
        f.write(data)
    return name, len(data)


def rf64():
    """RF64 / BW64: the 64-bit WAV. The RIFF/data sizes are 0xFFFFFFFF
    placeholders; the real 64-bit sizes live in a ds64 chunk. Lets a WAV exceed
    the 4 GB RIFF limit (this one is tiny, but structured as the real thing)."""
    pcm = bytes(4000)
    fmt = b"fmt " + struct.pack("<IHHIIHH", 16, 1, 2, 44100, 176400, 4, 16)
    ds64 = (b"ds64" + struct.pack("<I", 28)
            + struct.pack("<QQQ", 36 + len(pcm) + 36, len(pcm), len(pcm) // 4)
            + struct.pack("<I", 0))
    body = b"WAVE" + ds64 + fmt + b"data" + struct.pack("<I", 0xFFFFFFFF) + pcm
    return _w("rf64.wav", b"RF64" + struct.pack("<I", 0xFFFFFFFF) + body)


def sowt_aifc():
    """AIFF-C with compressionType 'sowt': the sample data is little-endian PCM
    inside an otherwise big-endian AIFF. A byte-swap hidden behind a codec id."""
    comm = (b"COMM" + struct.pack(">I", 22 + 2)
            + struct.pack(">hIh", 2, 1000, 16)
            + b"\x40\x0e\xac\x44\x00\x00\x00\x00\x00\x00"   # 80-bit float 44100
            + b"sowt" + b"\x00\x00")
    fver = b"FVER" + struct.pack(">II", 4, 0xA2805140)
    ssnd = b"SSND" + struct.pack(">I", 8 + 4000) + struct.pack(">II", 0, 0) + bytes(4000)
    body = b"AIFC" + fver + comm + ssnd
    return _w("sowt.aifc", b"FORM" + struct.pack(">I", len(body)) + body)


def _min_midi(fmt=0, ntrks=1, division=96):
    trk = b"MTrk" + struct.pack(">I", 4) + bytes([0x00, 0xFF, 0x2F, 0x00])
    return b"MThd" + struct.pack(">IHHH", 6, fmt, ntrks, division) + trk


def rmid():
    """RMID: a Standard MIDI File wrapped in a RIFF 'data' chunk. Cursed but
    real, MIDI dressed up as a RIFF container."""
    midi = _min_midi()
    body = b"RMID" + b"data" + struct.pack("<I", len(midi)) + midi
    return _w("wrapped.rmid", b"RIFF" + struct.pack("<I", len(body)) + body)


def midi_format2():
    """MIDI format 2: independent, self-contained patterns (vs format 0/1).
    Almost never seen; many players choke on it."""
    trk = b"MTrk" + struct.pack(">I", 4) + bytes([0x00, 0xFF, 0x2F, 0x00])
    return _w("format2.mid", b"MThd" + struct.pack(">IHHH", 6, 2, 2, 96) + trk + trk)


def midi_smpte():
    """MIDI with SMPTE-based timing: the division word is negative, encoding
    frames-per-second + ticks-per-frame instead of ticks-per-quarter-note."""
    div = struct.pack(">bB", -25, 40)                      # 25 fps, 40 ticks/frame
    trk = b"MTrk" + struct.pack(">I", 4) + bytes([0x00, 0xFF, 0x2F, 0x00])
    return _w("smpte.mid", b"MThd" + struct.pack(">IHH", 6, 0, 1) + div + trk)


def _tone_pcm(n, bits=16, fmt_float=False):
    import math
    out = bytearray()
    for i in range(n):
        v = math.sin(2 * math.pi * 220 * i / 44100) * 0.4
        if fmt_float:
            out += struct.pack("<f", v)
        else:
            out += struct.pack("<h", int(v * 32767))
    return bytes(out)


def float32_wav():
    """32-bit IEEE float WAV (format tag 3). Common in DAWs, still trips naive
    readers that assume integer PCM."""
    pcm = _tone_pcm(2000, fmt_float=True)
    fmt = b"fmt " + struct.pack("<IHHIIHH", 16, 3, 1, 44100, 44100 * 4, 4, 32)
    body = b"WAVE" + fmt + b"data" + struct.pack("<I", len(pcm)) + pcm
    return _w("float32.wav", b"RIFF" + struct.pack("<I", len(body)) + body)


def extensible_wav():
    """WAVE_FORMAT_EXTENSIBLE (tag 0xFFFE): a 40-byte fmt with a channel mask and
    a 16-byte sub-format GUID. Used for >2ch / >16-bit / surround."""
    pcm = _tone_pcm(2000)
    pcm_guid = (struct.pack("<H", 1)
                + b"\x00\x00\x00\x00\x10\x00\x80\x00\x00\xaa\x00\x38\x9b\x71")
    fmt = (b"fmt " + struct.pack("<IHHIIHH", 40, 0xFFFE, 2, 44100, 176400, 4, 16)
           + struct.pack("<HHI", 22, 16, 0x3) + pcm_guid)   # cbSize, validBits, mask, GUID
    body = b"WAVE" + fmt + b"data" + struct.pack("<I", len(pcm)) + pcm
    return _w("extensible.wav", b"RIFF" + struct.pack("<I", len(body)) + body)


def data_before_fmt():
    """A WAV with the data chunk BEFORE fmt. Spec says fmt must precede data;
    real files sometimes violate it and tolerant readers cope."""
    pcm = _tone_pcm(1000)
    fmt = b"fmt " + struct.pack("<IHHIIHH", 16, 1, 1, 44100, 88200, 2, 16)
    body = b"WAVE" + b"data" + struct.pack("<I", len(pcm)) + pcm + fmt
    return _w("data_before_fmt.wav", b"RIFF" + struct.pack("<I", len(body)) + body)


def id3_in_wav():
    """A WAV carrying an ID3 chunk (RIFF 'ID3 ' chunk holding an ID3v2 tag).
    RIFF's native metadata is LIST/INFO; ID3-in-WAV is off the beaten path but
    real (seen from some sample-pack tooling)."""
    pcm = _tone_pcm(1000)
    fmt = b"fmt " + struct.pack("<IHHIIHH", 16, 1, 1, 44100, 88200, 2, 16)
    frame = b"TIT2" + struct.pack(">I", 12) + b"\x00\x00" + b"\x00Weird WAV"
    id3v2 = b"ID3" + b"\x03\x00\x00" + bytes([0, 0, 0, len(frame)]) + frame
    if len(id3v2) & 1:
        id3v2 += b"\x00"
    id3ck = b"ID3 " + struct.pack("<I", len(id3v2)) + id3v2
    body = b"WAVE" + fmt + b"data" + struct.pack("<I", len(pcm)) + pcm + id3ck
    return _w("id3_in.wav", b"RIFF" + struct.pack("<I", len(body)) + body)


def bitwig_wt():
    """Bitwig wavetable (.wt): a 'vawt' container, a 12-byte LE header (samples
    per single-cycle wave, frame count, data offset=12) then frame-major int16
    LE samples. Bitwig writes these from Polymer and other wavetable devices."""
    import math
    frame_samples, frame_count = 256, 4
    body = bytearray()
    for fr in range(frame_count):                      # one sine per frame, rising harmonic
        for i in range(frame_samples):
            v = math.sin(2 * math.pi * (fr + 1) * i / frame_samples)
            body += struct.pack("<h", int(v * 32767))
    head = b"vawt" + struct.pack("<IHH", frame_samples, frame_count, 12)
    return _w("bitwig.wt", head + bytes(body))


def bitwig_multisample():
    """Bitwig .multisample: a ZIP with a multisample.xml zone map plus member
    WAVs. Two chromatic zones over one tiny WAV each. Bitwig writes a mismatched
    CRC on entries; a normal zip here still exercises the walker."""
    import zipfile, io
    def tiny_wav():
        pcm = _tone_pcm(256)
        fmt = b"fmt " + struct.pack("<IHHIIHH", 16, 1, 1, 44100, 88200, 2, 16)
        body = b"WAVE" + fmt + b"data" + struct.pack("<I", len(pcm)) + pcm
        return b"RIFF" + struct.pack("<I", len(body)) + body
    xml = (b'<?xml version="1.0" encoding="UTF-8"?><multisample name="Demo Kit">'
           b'<generator>acidcat-playground</generator><category>Drums</category>'
           b'<creator>specimen</creator><description/>'
           b'<sample file="a.wav" sample-start="0.000" sample-stop="256.000">'
           b'<key high="36" low="36" root="36" track="1.00" tune="0.00"/>'
           b'<velocity/><loop mode="off" start="0.000" stop="256.000"/></sample>'
           b'<sample file="b.wav" sample-start="0.000" sample-stop="256.000">'
           b'<key high="38" low="38" root="38" track="1.00" tune="0.00"/>'
           b'<velocity/><loop mode="off" start="0.000" stop="256.000"/></sample>'
           b'</multisample>')
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_STORED) as z:
        z.writestr("multisample.xml", xml)
        z.writestr("a.wav", tiny_wav())
        z.writestr("b.wav", tiny_wav())
    return _w("demo.multisample", buf.getvalue())


SPECIMENS = [rf64, sowt_aifc, rmid, midi_format2, midi_smpte,
             float32_wav, extensible_wav, data_before_fmt, id3_in_wav, bitwig_wt, bitwig_multisample]

if __name__ == "__main__":
    for fn in SPECIMENS:
        name, size = fn()
        print(f"  {name:22} {size:6} B   {(fn.__doc__ or '').strip().splitlines()[0]}")
