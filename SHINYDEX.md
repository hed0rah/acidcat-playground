# The shiny-dex

A living field guide to odd, rare, and off-spec audio and preset files: the
quirks acidcat is built to survive and read. Two halves, same as the corpus:

- **made** , synthesized from scratch in `specimens/` (copyright-clean,
  regenerate with `python specimens/make_specimens.py`).
- **found** , real ones caught in a live library. Shareable finds go in
  `specimens/wild/`; copyrighted finds are recorded here only (with a hash),
  never committed. `shiny_hunt.py DIR` locates them and copies nothing.

## Status legend

| status | meaning |
|---|---|
| `SYN` | synthesized: a reproducible specimen exists in `specimens/` |
| `WILD` | a real one has been caught (in `specimens/wild/`, or recorded below) |
| `WANT` | known or theorized to exist, not yet caught |

A shiny can be both `SYN` and `WANT`: we can build one, but a real example from
the wild is still worth catching (it proves the quirk occurs naturally, and real
encoders do things our synthesis does not).

## Caught (synthesized)

| shiny | format | quirk | status | specimen |
|---|---|---|---|---|
| RF64 / BW64 | WAV | 64-bit sizes in a `ds64` chunk, `0xFFFFFFFF` placeholders | SYN | `formats/rf64.wav` |
| sowt AIFC | AIFF | little-endian PCM inside big-endian AIFF via `sowt` codec id | SYN | `formats/sowt.aifc` |
| wrapped RMID | MIDI | a Standard MIDI File inside a RIFF `data` chunk | SYN | `formats/wrapped.rmid` |
| MIDI format 2 | MIDI | independent self-contained patterns | SYN | `formats/format2.mid` |
| SMPTE division | MIDI | negative division word: fps + ticks/frame, not PPQN | SYN | `formats/smpte.mid` |
| float32 WAV | WAV | IEEE float samples, format tag 3 | SYN | `formats/float32.wav` |
| WAVE_FORMAT_EXTENSIBLE | WAV | 40-byte fmt, channel mask, sub-format GUID | SYN | `formats/extensible.wav` |
| data-before-fmt | WAV | `data` chunk precedes `fmt` (spec-violating) | SYN | `formats/data_before_fmt.wav` |
| ID3-in-WAV | WAV | an ID3v2 tag inside a RIFF `ID3 ` chunk | SYN | `formats/id3_in.wav` |
| Bitwig wavetable | WT | `vawt` container, frame-major int16 | SYN | `formats/bitwig.wt` |
| Bitwig multisample | ZIP | `multisample.xml` zone map + member WAVs | SYN | `formats/demo.multisample` |
| Vital preset | Vital | bare-JSON synth, `synth_version` marker | SYN | `formats/vital_init.vital` |
| Serum FXP | FXP | VST2 `FPCh` opaque-chunk preset, id `XfsX` | SYN | `formats/serum.fxp` |
| Bitwig preset | Bitwig | clean `BtWg` container with meta block | SYN | `formats/acid_bass.bwpreset` |
| ID3v2.4 synchsafe | MP3 | frame sizes synchsafe, not plain u32 | SYN | `formats/id3v24_synchsafe.mp3` |
| FLAC cuesheet+picture | FLAC | CUESHEET + embedded PICTURE metadata blocks | SYN | `formats/flac_cuesheet_picture.flac` |
| chained Ogg | OGG | two logical bitstreams (Vorbis + Opus) in one file | SYN, WANT | `formats/chained.ogg` |
| mdat coverage-gap | M4A | payload in `mdat` referenced by no sample | SYN | `formats/mp4_mdat_cavity.m4a` |
| multi-script alias | M4A | 8 scripts + combining mark in the title | SYN | `unicode/01_multiscript_alias.m4a` |
| combining zalgo | M4A | 40 stacked combining marks on one base | SYN | `unicode/03_combining_zalgo.m4a` |
| bidi override | M4A | RLO/LRO controls reorder the displayed title | SYN | `unicode/04_rtl_bidi.m4a` |
| astral codepoints | M4A | title chars > U+FFFF, surrogate-pair traps | SYN | `unicode/05_astral_emoji.m4a` |
| embedded NUL | M4A | a NUL truncates C-string readers mid-title | SYN | `unicode/06_embedded_null.m4a` |

## Caught in the wild

| shiny | format | where seen | sha256 | artifact |
|---|---|---|---|---|
| _(none yet)_ | | | | |

## Wanted

The hunt list. Some we can already synthesize; a real one from the wild still
counts as a catch.

| shiny | format | quirk | why it is interesting |
|---|---|---|---|
| QuickTime v2 float64 rate | M4A | timescale/rate stored as a 64-bit float (version-2 sound sample description) | a non-integer sample rate a naive u32 reader mangles |
| real VBRI header | MP3 | Fraunhofer VBRI (not Xing/LAME) toc after the side info | the other, rarer VBR header; most tooling only knows Xing |
| non-canonical FVER | AIFF | AIFC `FVER` timestamp other than `0xA2805140` | a version stamp readers assume is constant |
| custom ADPCM predictors | WAV | a WAV declaring non-standard ADPCM coefficient sets | per the spec it may never have existed in the wild: the grail shiny |
| free-format MP3 | MP3 | bitrate index `0000`: frame size is not derivable from the header, must be scanned | breaks the assumption that a frame header sizes its own frame |

## Logging a new find

1. Run `python shiny_hunt.py /path/to/library` to spot which shinies are present.
2. If it is shareable, add it to `specimens/wild/` (a full file, or a `*.head`
   extract for a copyrighted one), and add a row to **Caught in the wild** with
   status derived from the file.
3. If it is copyrighted, keep the file in `copyrighted/` (gitignored) and add the
   row anyway with `where seen` and the `sha256` (`sha256sum file`); leave the
   artifact cell empty or point at a `.head` extract in `specimens/wild/`.
4. If it is a quirk we do not yet have a specimen for, add a **Wanted** row and,
   when possible, a generator in `specimens/make_specimens.py`.
