"""MIDI carrier PoC: hide a payload in a Standard MIDI File, two ways.

1. SysEx cavity: a System Exclusive event (F0 ... F7) tagged with the
   "non-commercial" manufacturer id 0x7D. No synth acts on 0x7D, so the payload
   rides inside a structurally valid MIDI event and the file plays normally.
   (SysEx data bytes must be 7-bit, so the payload is base64'd first.)
2. Tail parasite: raw bytes appended after the final MTrk chunk. MIDI parsers
   stop at the last chunk's length and ignore the tail, same idea as WAV+ZIP.

SysEx as a payload channel is well established (US patent 7402744, and tools
like stegano_midi); the under-examined part is that no player surfaces a 0x7D
SysEx and detection is rare. This is also the exact channel old synths take
firmware over (SysEx = arbitrary bytes into the device). Both hiding spots
are recoverable, and both are detected by acidcat (SysEx -> cavity warning on
the 0x7D id, tail -> trailing_data).

  python midi_carrier.py sysex secret.bin -o carrier.mid
  python midi_carrier.py tail  secret.bin -o carrier.mid
  python midi_carrier.py extract carrier.mid -o out.bin
  python midi_carrier.py analyze carrier.mid
"""

import base64
import os
import struct
import sys

MAGIC = b"AC7D"                     # marker after the 0x7D id so extract finds ours


def _vlq(n):
    out = bytearray([n & 0x7F])
    n >>= 7
    while n:
        out.insert(0, (n & 0x7F) | 0x80)
        n >>= 7
    return bytes(out)


def _read_vlq(data, pos):
    val = 0
    while pos < len(data):
        b = data[pos]
        val = (val << 7) | (b & 0x7F)
        pos += 1
        if not b & 0x80:
            break
    return val, pos


def _chunk(tag, data):
    return tag + struct.pack(">I", len(data)) + data


def _base_track(extra=b""):
    # one note on/off, an optional extra event, then end-of-track
    return (bytes([0x00, 0x90, 60, 64, 0x60, 0x80, 60, 0])
            + extra + bytes([0x00, 0xFF, 0x2F, 0x00]))


def _mthd():
    return _chunk(b"MThd", struct.pack(">HHH", 0, 1, 96))


def build_sysex(payload):
    body = bytes([0x7D]) + MAGIC + base64.b64encode(payload)   # 7-bit-safe body
    event = bytes([0x00, 0xF0]) + _vlq(len(body) + 1) + body + bytes([0xF7])
    return _mthd() + _chunk(b"MTrk", _base_track(event))


def build_tail(payload):
    return _mthd() + _chunk(b"MTrk", _base_track()) + payload


def _last_chunk_end(data):
    pos = 0
    end = 0
    while pos + 8 <= len(data) and data[pos:pos + 4] in (b"MThd", b"MTrk"):
        size = struct.unpack_from(">I", data, pos + 4)[0]
        pos = pos + 8 + size
        end = pos
    return end


def extract(data):
    # 1. our SysEx cavity
    i = data.find(bytes([0xF0]))
    while i != -1:
        ln, p = _read_vlq(data, i + 1)
        body = data[p:p + ln]
        if body[:1] == bytes([0x7D]) and body[1:5] == MAGIC:
            return base64.b64decode(body[5:-1])          # drop id+magic and F7
        i = data.find(bytes([0xF0]), i + 1)
    # 2. tail parasite
    end = _last_chunk_end(data)
    if 0 < end < len(data):
        return data[end:]
    return b""


def analyze(data):
    out = []
    i = data.find(bytes([0xF0]))
    while i != -1:
        ln, p = _read_vlq(data, i + 1)
        body = data[p:p + ln]
        mfr = ("non-commercial (0x7D)" if body[:1] == bytes([0x7D])
               else f"0x{body[0]:02X}" if body else "empty")
        out.append(f"SysEx at 0x{i:04x}: {mfr}, {ln} bytes")
        i = data.find(bytes([0xF0]), i + 1)
    end = _last_chunk_end(data)
    if 0 < end < len(data):
        out.append(f"trailing data: {len(data) - end} bytes after the last MTrk")
    return out or ["no SysEx or trailing data found"]


if __name__ == "__main__":
    a = sys.argv[1:]
    out = a[a.index("-o") + 1] if "-o" in a else None
    if a and a[0] in ("sysex", "tail") and len(a) >= 2:
        payload = open(a[1], "rb").read()
        data = (build_sysex if a[0] == "sysex" else build_tail)(payload)
        dst = out or "carrier.mid"
        open(dst, "wb").write(data)
        print(f"wrote {dst}: {len(payload):,}-byte payload via {a[0]} "
              f"({len(data):,} bytes total)")
    elif a and a[0] == "extract" and len(a) >= 2:
        data = open(a[1], "rb").read()
        dst = out or "payload.bin"
        got = extract(data)
        open(dst, "wb").write(got)
        print(f"recovered {len(got):,} bytes to {dst}")
    elif a and a[0] == "analyze" and len(a) >= 2:
        for line in analyze(open(a[1], "rb").read()):
            print(line)
    else:
        print(__doc__)
