# EXAMPLES

Reproduce and explore every playground technique. Each block: build the specimen
with a playground tool, then dissect it with acidcat. Kept in sync as PoCs land.

Assumes `acidcat` is importable (editable install, or `PYTHONPATH=.../acidcat/src`)
and `ffmpeg` on PATH for the Ogg PoC. Set these once:

```bash
CORPUS=/path/to/your/samples        # any folder of audio/preset files
PLAY=.                               # this repo
OUT=/tmp                      # scratch dir for specimens
```

---

## 1. WAV + ZIP polyglot  (tail-parasite)

A ZIP appended after the RIFF size boundary. Plays as audio, unzips as an archive.

```bash
python "$PLAY/polyglot.py" wav-zip "$CORPUS/audio/samples/Snare1.wav" "$PLAY/README.md" -o "$OUT/poly.wav"
python "$PLAY/polyglot.py" verify "$OUT/poly.wav"     # confirms both views
unzip -l "$OUT/poly.wav"                              # the zip is real

acidcat inspect --anomalies "$OUT/poly.wav"           # -> alert: appended ZIP polyglot
```

## 2. LSB steganography  (in-band, PCM sample low bits)

Payload whitened and written into sample LSBs. Works on 8/16/24/32-bit PCM.

```bash
python "$PLAY/stego.py" embed "$CORPUS/audio/recordings/dr40-plain-44k24-1332.wav" "$PLAY/README.md" -o "$OUT/st.wav"
python "$PLAY/stego.py" extract "$OUT/st.wav" -o "$OUT/back.md"   # round-trips
python "$PLAY/stego.py" capacity "$CORPUS/audio/samples/Snare1.wav"

acidcat inspect --anomalies "$OUT/st.wav"             # -> notice: uniform-high LSB entropy
acidcat explore "$OUT/st.wav" -o "$OUT/st.html"       # heat-map: the low bit-plane goes hot
```

## 3. OGG dual-bitstream  (multiple logical bitstreams)

One .ogg carrying a Vorbis stream and an Opus stream. A single-codec player
surfaces only one; the other rides along. Needs ffmpeg.

```bash
python "$PLAY/ogg_multiplex.py" build -o "$OUT/dual.ogg"
python "$PLAY/ogg_multiplex.py" analyze "$OUT/dual.ogg"
ffplay -loglevel quiet "$OUT/dual.ogg"                # both tones present

acidcat inspect --anomalies "$OUT/dual.ogg"           # -> notice: 2 logical bitstreams
```

## 4. MIDI carrier  (SysEx cavity + tail-parasite)

Two hiding spots in a Standard MIDI File. The SysEx cavity uses manufacturer id
0x7D ("non-commercial"): a valid MIDI event no synth acts on. The tail is bytes
after the last MTrk. Same channel real synths take firmware over.

```bash
python "$PLAY/midi_carrier.py" sysex "$PLAY/README.md" -o "$OUT/sysex.mid"
python "$PLAY/midi_carrier.py" tail  "$PLAY/README.md" -o "$OUT/tail.mid"
python "$PLAY/midi_carrier.py" extract "$OUT/sysex.mid" -o "$OUT/back.md"   # round-trips
python "$PLAY/midi_carrier.py" analyze "$OUT/sysex.mid"

acidcat inspect --anomalies "$OUT/sysex.mid"          # -> warn: 0x7D SysEx payload cavity
acidcat inspect --anomalies "$OUT/tail.mid"           # -> notice: trailing_data
```

## 5. RF64/WAV JUNK cavity  (spec-ignorable chunk)

A RIFF `JUNK` chunk is defined as ignorable padding (and the RF64 ds64
placeholder). Non-zero content there rides inside the container, the RIFF size
field stays honest, no trailing data, but it is a hiding spot.

```bash
python "$PLAY/junk_cavity.py" embed "$CORPUS/audio/samples/Snare1.wav" "$PLAY/README.md" -o "$OUT/junk.wav"
python "$PLAY/junk_cavity.py" extract "$OUT/junk.wav" -o "$OUT/back.md"   # round-trips
python "$PLAY/junk_cavity.py" analyze "$OUT/junk.wav"

acidcat inspect --anomalies "$OUT/junk.wav"           # -> notice: non-zero bytes in RIFF JUNK chunk
```

## 6. Dual-endianness WAV/AIFF  (one PCM block, two sounds)

Shared 16-bit PCM engineered so the little-endian (WAV) view is one tone and the
big-endian (AIFF) view is another. The `.wav` and `.aiff` carry byte-identical
audio payloads. Zero-dep (no corpus file needed).

```bash
python "$PLAY/dual_endian.py" build -o "$OUT/dual" --a-hz 440 --b-hz 880 --secs 2
python "$PLAY/dual_endian.py" verify "$OUT/dual.wav" "$OUT/dual.aiff"   # byte-identical PCM
ffplay -loglevel quiet "$OUT/dual.wav"                 # sound A (440 Hz)
ffplay -loglevel quiet "$OUT/dual.aiff"                # sound B (880 Hz), same bytes

acidcat inspect --anomalies "$OUT/dual.wav"            # flags dual_endianness (since 0.16.0)
```

## 7. FLAC metadata-block cavity  (APPLICATION + non-zero PADDING)

Two spec-valid hiding spots inside the FLAC metadata chain. The file still decodes.

```bash
python "$PLAY/flac_cavity.py" app "$OUT/small.flac" "$PLAY/README.md" -o "$OUT/app.flac"
python "$PLAY/flac_cavity.py" pad "$OUT/small.flac" "$PLAY/README.md" -o "$OUT/pad.flac"
python "$PLAY/flac_cavity.py" extract "$OUT/app.flac" -o "$OUT/back.md"   # round-trips
python "$PLAY/flac_cavity.py" analyze "$OUT/app.flac"

acidcat inspect --anomalies "$OUT/app.flac"           # -> notice: APPLICATION block
acidcat inspect --anomalies "$OUT/pad.flac"           # -> notice: non-zero FLAC PADDING (cavity_content)
```

## 8. MP4/M4A mdat coverage-gap cavity  (bytes no sample references)

Payload appended to the tail of the `mdat` payload; `mdat`'s size grows but no
stco offset points at the new bytes, so the audio decodes bit-identically.

```bash
python "$PLAY/mp4_cavity.py" analyze "$OUT/small.m4a"          # baseline: 0-byte gap
python "$PLAY/mp4_cavity.py" embed "$OUT/small.m4a" "$PLAY/README.md" -o "$OUT/cav.m4a"
python "$PLAY/mp4_cavity.py" extract "$OUT/cav.m4a" -o "$OUT/back.md"   # round-trips
python "$PLAY/mp4_cavity.py" analyze "$OUT/cav.m4a"           # gap == cavity size

acidcat inspect --anomalies "$OUT/cav.m4a"            # flags mp4_mdat_coverage (since 0.16.0)
```

## 9. MP3 ID3v2 declared-padding cavity  (non-zero tag padding)

Payload written into the ID3v2 tag's padding region (spec'd to be zero). Counted
by the tag length, so it is not trailing data, and the audio is untouched.

```bash
python "$PLAY/id3_cavity.py" embed "$OUT/small.mp3" "$PLAY/README.md" -o "$OUT/cav.mp3"
python "$PLAY/id3_cavity.py" extract "$OUT/cav.mp3" -o "$OUT/back.md"   # round-trips
python "$PLAY/id3_cavity.py" analyze "$OUT/cav.mp3"

acidcat inspect --anomalies "$OUT/cav.mp3"            # flags id3_padding_nonzero (since 0.16.0)
```

---

## 10. MP3 APIC embedded standalone JPEG  (a whole file in a cover-art frame)

The MP3 plays normally; the APIC image bytes are a complete JPEG that carves out
byte-exact. acidcat reads the MP3 but does not yet surface the embedded file.

```bash
python "$PLAY/mp3_jpeg.py" embed "$OUT/small.mp3" cover.jpg -o "$OUT/art.mp3"
python "$PLAY/mp3_jpeg.py" extract "$OUT/art.mp3" -o "$OUT/back.jpg"   # byte-exact
python "$PLAY/mp3_jpeg.py" analyze "$OUT/art.mp3"

acidcat inspect --anomalies "$OUT/art.mp3"            # no warning yet (embedded_standalone_media, proposed)
```

## 11. Preset JSON cavity  (unknown member / trailing bytes)

`key` stays valid JSON and a valid preset; `tail` is rejected by acidcat's strict
Vital parse rather than read-with-a-warning.

```bash
python "$PLAY/json_cavity.py" embed preset.vital "$PLAY/README.md" -o "$OUT/k.vital" --mode key
python "$PLAY/json_cavity.py" embed preset.vital "$PLAY/README.md" -o "$OUT/t.vital" --mode tail
python "$PLAY/json_cavity.py" extract "$OUT/k.vital" -o "$OUT/back.md"   # byte-exact
python "$PLAY/json_cavity.py" analyze "$OUT/k.vital"  # Vital preset; unknown key accepted silently
python "$PLAY/json_cavity.py" analyze "$OUT/t.vital"  # Unsupported: over-strict on trailing bytes
```

---

## Robustness / research runs (no single specimen; they sweep the corpus)

```bash
python "$PLAY/mangle.py" list                         # available mutations
python "$PLAY/mangle.py" fuzz                         # fuzz all formats, expect 0 crashes
python "$PLAY/cve_immunity.py"                        # 6/6 historical CVE classes survive
python "$PLAY/differential.py"                        # acidcat vs mutagen agreement
```

## Visual exploration (TUI)

```bash
python "$PLAY/tui.py"
# EXPLORER tab: pick a file, then press v to cycle VISUAL modes:
#   STRUCTURE -> MAP -> ENTROPY -> HILBERT -> ANOMALIES
# ENTROPY: braille entropy curve + byte-value histogram (flat top = encrypted)
# HILBERT: binvis-style byte-map (offset -> 2D space-filling curve, colored by
#          byte class); headers / PCM / appended-payload show as distinct blocks
# keys: ? help   e export loaded file to HTML explorer   s save SVG screenshot

python "$PLAY/tui.py" /path/to/dir       # browse a directory
python "$PLAY/tui.py" /path/to/file.wav  # root at its folder + auto-load it
```

Visualizations use `viz.py` (zero-dep braille + Hilbert primitives), reusable
anywhere a graph is wanted.

## General acidcat dissection (any file)

```bash
acidcat inspect FILE                                  # structural table
acidcat inspect --pretty FILE                         # decoded fields
acidcat inspect --hex FILE                            # hex + structure
acidcat inspect --full FILE                           # JSON dump (feeds explore)
acidcat inspect --anomalies FILE                      # forensic checks
acidcat explore FILE -o out.html                      # interactive HTML byte-explorer
```

---

## Technique -> detection map

| Technique | Vector | acidcat rule that catches it |
|---|---|---|
| WAV+ZIP polyglot | tail-parasite | `polyglot` (appended ZIP EOCD) |
| LSB stego | in-band | `lsb` (uniform-high low-bit entropy) |
| OGG dual-bitstream | multi-stream | `ogg_multistream` (>1 BOS serial) |
| MIDI SysEx | cavity | walker warning (0x7D / oversized SysEx) |
| MIDI tail | tail-parasite | `trailing_data` (past last MTrk) |
| RF64/WAV JUNK | cavity | `cavity_content` (non-zero JUNK/PAD chunk) |
| Dual-endianness WAV/AIFF | dual-interpretation | `dual_endianness` (swapped view also structured) [new] |
| FLAC APPLICATION | cavity | `application_block` (freeform block; refine on unregistered id) |
| FLAC non-zero PADDING | cavity | `cavity_content` (already caught) |
| MP4 mdat coverage gap | cavity | `mp4_mdat_coverage` (sum stsz < mdat payload) [new] |
| MP3 ID3v2 padding | cavity | `id3_padding_nonzero` (non-zero declared padding) [new] |
