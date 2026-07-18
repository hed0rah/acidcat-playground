# Weird-audio-format specimen archive

A growing corpus of odd, rare, and off-spec audio files, the shiny-dex. Every
file here is **synthesized from scratch** (silence, tones, hand-built headers),
so it is copyright-clean and safe to share. Real-world files that carry these
quirks are copyrighted; use `shiny_hunt.py` to find *those* in your own library
rather than committing them here.

Regenerate the whole set with `python specimens/make_specimens.py`.

## formats/

| file | what makes it a shiny |
|---|---|
| `rf64.wav` | RF64 / BW64, the 64-bit WAV; RIFF/data sizes are `0xFFFFFFFF` placeholders, real sizes in a `ds64` chunk |
| `sowt.aifc` | AIFF-C with `sowt` compression, little-endian PCM inside a big-endian AIFF |
| `wrapped.rmid` | RMID, a Standard MIDI File wrapped in a RIFF `data` chunk |
| `format2.mid` | MIDI format 2, independent self-contained patterns (rare; players often choke) |
| `smpte.mid` | MIDI with SMPTE timing, negative division word (fps + ticks/frame, not PPQN) |
| `float32.wav` | 32-bit IEEE float WAV (format tag 3) |
| `extensible.wav` | WAVE_FORMAT_EXTENSIBLE (tag `0xFFFE`), 40-byte fmt + channel mask + sub-format GUID |
| `data_before_fmt.wav` | WAV with the `data` chunk before `fmt` (spec-violating; tolerant readers cope) |
| `id3_in.wav` | a WAV carrying an `ID3 ` chunk (an ID3v2 tag inside RIFF; off the beaten path) |
| `bitwig.wt` | Bitwig wavetable: `vawt` container, 12-byte LE header + frame-major int16 samples |
| `demo.multisample` | Bitwig multisample: ZIP + `multisample.xml` zone map + member WAVs (mismatched CRC) |

## The goal

Aim bigger than a reference implementation's stock test files: every rare
variant, every polyglot, every cavity and glitch we make or characterize. Two
halves:

- **made** (here) , synthetic specimens + generated polyglots/cavities (copyright-clean).
- **found** , `shiny_hunt.py` scans a directory of real files and reports which
  rare variants are present (bext / acid / smpl / cue / ds64 / RF64 / float+extensible
  format tags / ID3 versions / Xing-LAME / AIFF-C sowt / RMID / FLAC cuesheet+picture / ...).

When the TUI migrates into acidcat proper, this archive stays in the playground
as the shared corpus.
