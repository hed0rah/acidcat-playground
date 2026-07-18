# Audio Polyglots & Cavities

An ongoing index of the file-format-abuse techniques prototyped in this
playground, each paired with the acidcat `inspect --anomalies` rule that catches
it. Every technique has a working PoC tool (build + extract/verify) and a
byte-exact round trip. See EXAMPLES.md to reproduce any of them.

Mechanisms: **tail-parasite** (bytes past the declared end), **cavity** (a
spec-ignorable region inside the container), **in-band** (hidden in the sample
stream), **multi-stream** (a second logical bitstream), **cross-endian** (one
byte block, two valid readings), **embedded-media** (a complete secondary format
inside a legitimate container field).

Items 1-9 are each paired with a shipping `inspect --anomalies` rule. Items 10-11
are newer and motivate rules acidcat does not yet have; those specs are in the dev
handoff, and the tools serve as their reproducers.

### how to read this

- **stego** hides a payload inside a carrier that stays a normal, valid file of its
  own type; only the carrier reads as valid, the payload is concealed.
- **cavity** is stego in a spec-ignorable region the format declares but ignores.
- **polyglot** is one file simultaneously valid as two formats, both readings real.
- **embedded** carries a complete secondary file in a legitimate container field:
  not concealed, but a whole file you carve back out.

These compose: a stego payload can itself be a polyglot, and layers nest (a polyglot
inside a cavity inside a container) -- the matryoshka case tracked in the roadmap.

Notation: `A = B` valid as both A and B (polyglot); `A ⊃ x` carrier A conceals
payload x (stego/cavity); `A ⊃ [B]` A carries a whole carveable B file; `A ≠ B` the
same bytes read as A vs B give different content; `*` a proposed acidcat rule, not
yet shipping (see the dev handoff).

| # | Technique | Type | Structure | acidcat rule | Tool |
|---|---|---|---|---|---|
| 1 | WAV + ZIP polyglot | polyglot | `WAV = ZIP` (ZIP appended past the RIFF size) | `polyglot` | polyglot.py |
| 2 | LSB steganography | stego | `WAV ⊃ payload` (PCM sample low bits) | `lsb` | stego.py |
| 3 | OGG dual-bitstream | polyglot | `Ogg(Vorbis) = Ogg(Opus)` (two BOS serials) | `ogg_multistream` | ogg_multiplex.py |
| 4 | MIDI SysEx / tail | stego | `MIDI ⊃ payload` (SysEx 0x7D, or after last MTrk) | SysEx warn / `trailing_data` | midi_carrier.py |
| 5 | RF64/WAV JUNK cavity | cavity | `WAV ⊃ payload` (JUNK / ds64 chunk) | `cavity_content` | junk_cavity.py |
| 6 | Dual-endianness twin | cross-endian | `WAV ≠ AIFF` (one byte block, two sounds) | `dual_endianness` | dual_endian.py |
| 7 | FLAC APPLICATION / PADDING | cavity | `FLAC ⊃ payload` (APPLICATION or non-zero PADDING) | `application_block` / `cavity_content` | flac_cavity.py |
| 8 | MP4 mdat coverage gap | cavity | `M4A ⊃ payload` (unreferenced mdat tail) | `mp4_mdat_coverage` | mp4_cavity.py |
| 9 | MP3 ID3 padding | cavity | `MP3 ⊃ payload` (declared ID3v2 padding) | `id3_padding_nonzero` | id3_cavity.py |
| 10 | MP3 APIC embedded JPEG | embedded | `MP3 ⊃ [JPEG]` (cover-art frame) | `embedded_standalone_media` `*` | mp3_jpeg.py |
| 11 | Preset JSON cavity | cavity | `Vital ⊃ payload` (unknown key, or tail bytes) | `json_unknown_key` `*` | json_cavity.py |

---

## 1. WAV + ZIP polyglot
A ZIP appended after the RIFF size boundary. The WAV plays; `unzip` reads the
archive from the tail (ZIP is parsed from its end-of-central-directory record).
Detected by the appended-ZIP-EOCD scan.

## 2. LSB steganography
A whitened payload written into PCM sample low bits (any depth). The low
bit-plane comes out near-uniform. Detected as a uniform-high LSB entropy floor,
honestly a *notice*, since a real noise floor looks the same.

## 3. OGG dual-bitstream
One `.ogg` carrying a Vorbis and an Opus logical bitstream (two BOS serials).
A single-codec player surfaces only one; the other rides along, spec-valid.
Detected by counting BOS serials.

## 4. MIDI SysEx / tail
Payload in a SysEx event tagged with the non-commercial manufacturer id `0x7D`
(no synth acts on it), or appended after the last MTrk. The same channel real
synths take firmware over. SysEx cavity warns; the tail is caught as trailing
data.

## 5. RF64/WAV JUNK cavity
A RIFF `JUNK` chunk (spec'd ignorable padding, and the RF64 ds64 placeholder)
carrying non-zero content. The RIFF size stays honest, so it is a true cavity,
not trailing data. Detected as non-zero bytes in a JUNK/PAD chunk.

## 6. Dual-endianness twin
16-bit PCM engineered so the little-endian (WAV) reading is one sound and the
big-endian (AIFF) reading is another, shipped as byte-identical `.wav`/`.aiff`
twins (there is no single-file dual-container: RIFF and FORM magics collide at
offset 0). Detected because *both* endian readings are structured audio, real
audio is structured only one way.

## 7. FLAC APPLICATION / PADDING cavity
An APPLICATION metadata block with an unregistered id, or a non-zero PADDING
block (spec'd zero). Both decode fine. acidcat already flagged both, a nice sign
its cavity rules generalize.

## 8. MP4 mdat coverage gap
Payload grown onto the tail of the `mdat` box; no `stsz` sample references it, so
the audio decodes bit-identically. Not a `free` atom, not trailing data, a true
cavity inside a top-level box. Detected by summing sample sizes vs the mdat
payload.

## 9. MP3 ID3 padding
Payload written into the ID3v2 tag's declared padding region (counted by the tag
length, so not trailing data). Detected as non-zero bytes after the last frame.

## 10. MP3 APIC embedded JPEG
A complete standalone JPEG carried in an ID3v2 APIC (cover-art) frame. The MP3
plays normally and the image bytes carve out byte-exact (FFD8..FFD9). Not a byte-0
dual-open polyglot (the file begins with "ID3") and not a cavity (APIC is
legitimate content): a container field holding a whole secondary file. acidcat
reads the MP3 with no warning today, collapsing ID3v2 into one chunk without
exposing picture frames as carveable regions. The true front-loaded polyglot (JPEG
first, MPEG frames appended) is decoder-dependent: a JPEG APP0 marker is 0xFFE0,
which satisfies the MPEG frame sync, so a resyncing decoder can lock onto the
picture; the APIC form is deterministic instead.

## 11. Preset JSON cavity
Two side-channels a JSON preset loader tolerates. `key`: an extra top-level member
outside the synth's schema; the file stays valid JSON and a valid Vital preset,
recovered byte-exact. `tail`: bytes after the top-level object's closing brace.
acidcat accepts the unknown key silently (no key-level validation), and rejects the
tail variant as Unsupported rather than reading the preset and warning on the
trailing bytes -- over-strict versus a loader that stops at the top-level value.
