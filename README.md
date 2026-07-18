# acidcat-playground

A research playground for **breaking audio and synth/DAW preset files on purpose**
and proving a parser survives it. Companion to
[acidcat](https://github.com/hed0rah/acidcat), a pure-Python tool that reads and
writes deep metadata across WAV/AIFF/MP3/FLAC/OGG/M4A/MIDI plus Bitwig, Native
Instruments, and Vital/Serum presets.

Media parsers are a classic soft target (Android's Stagefright, the Windows ANI
RIFF chunk-size overflow, a long list of image/audio CVEs). This is where the
adversarial inputs get generated and acidcat is confirmed to degrade to a clean
warning instead of crashing, hanging, or emitting confidently-wrong output.

## Tools

### tui.py, the in-terminal workbench

An in-terminal audio-format reverse-engineering and editing tool (Textual). It
imports acidcat as the engine, so every walker and detector in acidcat proper is
available visually, and layers the forge, play, and sonify tools on top. This is
the primary interface; the standalone tools below are the same capabilities from
the command line.

```
python tui.py [path]      # a directory to browse, or a file to open
```

Modes: `1` explorer, `2` lab (mangle/glitch), `3` stego (embed/construct), `4` metadata, `5` fuzz (external target), `6` reports. In the explorer, `v` cycles the analysis view (STRUCTURE / MAP / ENTROPY / HILBERT / ANOMALIES); editing keys (x field, b byte, m metadata, g recipe, / search, u undo, w save) and `:` for the command palette.

Keys (explorer):

```
p  play the selected region as raw PCM (databending: hear the bytes)
x  edit the highlighted decoded field in place
b  raw byte patch at an offset (OFFSET HEXBYTES)
t  examine the selected field as u16/i16/u32/f32 (LE + BE)
m  metadata editor (title/artist/bpm/key/..., variable-length, via acidcat write)
g  apply a glitch recipe (reverse, bitcrush, stutter, sort, ...)
/  search: HEX bytes, text, v:NUMBER (value scan), or s:TEXT (strings)
d  diff what this session changed     o  goto: hexdump at any offset
u  undo the last edit                 w  write the forged result to <name>_forged
```

Edits are non-destructive (they accumulate on a working copy; the original is
untouched until you `w`), and every edit re-parses so the view stays honest.

### forge.py, the editing bench

Surgical, format-aware editing for WAV / MP3 / MIDI: locate any chunk or decoded
field by name (via acidcat's walker, which hands back each field's offset and
length), then patch, fill, or corrupt it, and hear the result. This is the
chemistry set, edits are not policed; writing nonsense is the point.

Inspect (read-only):

```
python forge.py song.wav show                        # addressable chunks + fields
python forge.py song.wav examine 0x14 --fmt u16 --count 8   # typed read of a byte range
python forge.py song.wav hexdump 0 --len 64          # annotated hexdump
python forge.py song.wav find 64617461               # byte-pattern search
python forge.py song.wav scan 44100 --fmt u32        # scan the file for a numeric value
python forge.py song.wav strings --min 4             # printable ASCII runs
python forge.py song.wav diff other.wav              # changed byte ranges
```

Edit (writes `-o`, default `FILE_forged.ext`):

```
python forge.py song.wav set fmt sample_rate 96000   # rewrite a decoded field
python forge.py song.wav replace 64617461 6d796368   # equal-length find/replace
python forge.py song.wav fill JUNK 0xAA             # weird bytes into padding/cavities
python forge.py song.wav corrupt data --mode bitflip --rate 0.001
python forge.py song.wav patch 0x2c ff00ba           # raw byte patch at an offset
python forge.py song.wav recipe wav-reverse --play   # a named glitch, then listen
```

Recipes: `wav-rate-bend` (halve declared rate), `wav-reverse` (backwards),
`wav-bitcrush` (crush to 8-bit), `wav-stutter`, `wav-data-sort`,
`mp3-bitrate-scramble`, `midi-tempo-warp`, `padding-noise`, `data-bitflip`.
Programmatic: `Forge(p).set_field("fmt","sample_rate",96000).save()`,
`Forge(p).find_value(0x100,"i16")`, `Forge(p).diff("other.wav")`.

Playback uses acidcat's ffplay helper (`acidcat.util.play`, from ffmpeg, no new
deps): a whole file, or (the databending trick) any byte range reinterpreted as
raw PCM, so you can hear a header, a cavity, or freshly-mangled data as sound.

```
python forge.py song.wav play                # hear the whole file
python forge.py song.wav play data           # hear one chunk as raw PCM
python forge.py song.wav recipe wav-reverse --play   # glitch, then listen
```
In the TUI, `p` plays the selected region (`.` stops).

### sonify.py, cross-domain databending

Any bytes are just numbers: a WAV header calls them samples, a PGM header calls
them pixels. sonify swaps the interpretation, so you can hear a JPEG, view a
drum loop as an image, or turn audio into an image, smear it, and turn it back
into sound. Netpbm (PGM/PPM) images are a text header plus raw bytes, so any
editor opens them and nothing extra is needed.

```
python sonify.py hear forge.py -o code.wav --rate 8000    # hear any file as PCM
python sonify.py see  loop.wav -o loop.pgm --width 256    # audio as a grayscale image
python sonify.py load loop.pgm -o back.wav --ch 2         # image bytes back to audio
python sonify.py bend loop.wav --op rowsort --play        # in-code databend, then hear it
```

The audio->image->audio round trip is byte-exact until you edit the image. `bend`
does the edit in code (ops: invert, reverse, rowsort, rowshift, xor, transpose)
so you can glitch without leaving the terminal; add `--play` to hear any result.

### mangle.py + mutations.py, corrupt + fuzz
```
python mangle.py list                    # mutations by category
python mangle.py fuzz                     # every input x mutation -> assert no crash
python mangle.py fuzz --category riff      # target one class
python mangle.py fuzz --report reports/r.md
python mangle.py one <file> <mutation>     # write one specimen to mangled/
```
`mutations.py` is a categorized registry: **generic** (truncate, bitflip, scramble,
zero-tail, junk-prefix), **riff** (forged sizes, duplicate/insert/drop chunks,
un-padded odd chunk, 4000-deep nested LIST recursion probe), **container** (magic
swap, bit-flip, wrong subtype). Each returns `None` when it does not apply, so the
fuzzer only counts real hits.

Latest run: **818 applicable runs across 57 files, 0 crashes** (deep mode). See
`reports/`.

### fuzz_target.py, black-box fuzz an external program

Feed mangled files to any third-party program and catch crashes. Applies the
mutation catalog to a seed, runs a target command on each variant, and classifies
the result: OK, ERROR (graceful reject), HANG (timeout), CRASH (signal / fatal
exception). Only HANG and CRASH inputs are saved, for triage.

```
python fuzz_target.py seed.wav --target "ffprobe -v error {file}" -n 300
python fuzz_target.py seed.mp3 --target "ffmpeg -v error -i {file} -f null -"
python fuzz_target.py seed.mid --target "timidity {file}" --timeout 5 --out crashes/
```

`{file}` is replaced with each mangled path (appended if omitted). Point it at a
player, decoder, converter, or DAW CLI. This is distinct from `mangle.py`, which
tests acidcat's own parser; this tests everyone else's.

### shiny_hunt.py + specimens/, the weird-format corpus

`shiny_hunt.py DIR` scans a folder of real files and reports which rare/off-spec
variants are present (bext, acid, smpl, cue, RF64, float/extensible fmt tags, ID3
versions, Xing/LAME, AIFF-C sowt, RMID, FLAC cuesheet/picture, ...), copying
nothing. `specimens/` is the made half: synthesized, copyright-clean examples of
those variants (regenerate with `python specimens/make_specimens.py`).

```
python shiny_hunt.py /path/to/samples
python specimens/make_specimens.py
```

### polyglot.py, one file, two formats
```
python polyglot.py wav-zip <wav> <file-to-embed>... -o out.wav
python polyglot.py verify <polyglot>
```
Builds a WAV that is also a valid ZIP (a DAW plays it, `unzip` extracts it). The
same shape as Bitwig's embedded-asset zip, and a probe that acidcat reads the WAV
while treating the trailing archive as trailing bytes.

### ogg_multiplex.py, dual-bitstream Ogg PoC
```
python ogg_multiplex.py build -o dual.ogg     # a Vorbis tone + an Opus tone, one file
python ogg_multiplex.py analyze file.ogg      # count logical bitstreams
```
Builds one .ogg carrying two concurrent logical bitstreams (Vorbis "song A" +
Opus "song B", different tones). A single-codec player surfaces only one; the
other rides along, spec-valid. Detected by `acidcat inspect --anomalies` (flags
more than one BOS serial). Needs ffmpeg. From the polyglot/stego research hunt.

### stego.py, LSB steganography lab
```
python stego.py embed carrier.wav secret.txt -o stego.wav [--key N] [--raw]
python stego.py extract stego.wav -o out.bin [--key N]
python stego.py capacity carrier.wav
```
Hides a payload in 16-bit PCM sample LSBs (whitened by default, so the low
bit-plane comes out uniform, the encrypted-payload case). Gives the
`--anomalies` LSB detector and the explorer heat-map real specimens. It also
exposed a real limit of entropy-only steganalysis: a mic noise floor is
statistically identical to an encrypted payload, so the detector was downgraded
from an alert to a heuristic notice (acidcat 0.14.1).

### dual_endian.py, dual-endianness WAV/AIFF
```
python dual_endian.py build -o out [--a-hz 440] [--b-hz 880] [--secs 2]
python dual_endian.py verify out.wav out.aiff
```
One 16-bit PCM block engineered so the little-endian (WAV) view is one tone and
the big-endian (AIFF) view is another. Writes a `.wav` and `.aiff` with
byte-identical audio payloads: the same bytes play two different sounds. No clean
single-file audio+audio dual-container exists (RIFF and FORM both want offset 0),
so this is a shared-PCM data polyglot. Detected by `acidcat inspect --anomalies`
(the `dual_endianness` rule, since 0.16.0): the byte-swapped view is also structured,
not the noise a real recording turns into.

### flac_cavity.py, FLAC metadata-block cavities
```
python flac_cavity.py app carrier.flac secret.bin -o out.flac   # APPLICATION block
python flac_cavity.py pad carrier.flac secret.bin -o out.flac   # non-zero PADDING
python flac_cavity.py extract out.flac -o secret.bin
python flac_cavity.py analyze out.flac
```
Hides a payload in a FLAC APPLICATION block (unregistered id) or a non-zero
PADDING block. Spec-valid, decodes normally. acidcat already notices both; the
`app` case motivates flagging unregistered application ids specifically.

### mp4_cavity.py, MP4/M4A mdat coverage gap
```
python mp4_cavity.py embed carrier.m4a secret.bin -o out.m4a
python mp4_cavity.py extract out.m4a -o secret.bin
python mp4_cavity.py analyze out.m4a
```
Appends the payload to the tail of the `mdat` box and grows only `mdat`'s size;
no stco sample offset points at the new bytes, so the audio decodes
bit-identically and the region is dead space. Detected by `acidcat inspect --anomalies`
(`mp4_mdat_coverage`, since 0.16.0: sum of stsz sample sizes < mdat payload).

### id3_cavity.py, MP3 ID3v2 padding cavity
```
python id3_cavity.py embed carrier.mp3 secret.bin -o out.mp3
python id3_cavity.py extract out.mp3 -o secret.bin
python id3_cavity.py analyze out.mp3
```
Writes the payload into the ID3v2 tag's declared padding (spec'd to be zero).
Counted by the tag length so it is not trailing data; audio untouched. Detected by
`acidcat inspect --anomalies` (`id3_padding_nonzero`, since 0.16.0).

### mp3_jpeg.py, MP3 carrying a standalone JPEG
```
python mp3_jpeg.py embed carrier.mp3 cover.jpg -o out.mp3
python mp3_jpeg.py extract out.mp3 -o recovered.jpg
python mp3_jpeg.py analyze out.mp3
```
Embeds a complete standalone JPEG in an ID3v2 APIC (cover-art) frame. The MP3 plays
normally and the image carves out byte-exact. Not a byte-0 dual-open polyglot (the file
starts with "ID3") and not a cavity (APIC is legitimate content): a container field
holding a whole secondary file. acidcat reads the MP3 without exposing the embedded
image, which motivates a walker rule (`embedded_standalone_media`, proposed) that
surfaces picture frames as carveable regions.

### json_cavity.py, JSON-preset side-channels
```
python json_cavity.py embed preset.vital secret.bin -o out.vital [--mode key|tail]
python json_cavity.py extract out.vital -o secret.bin
python json_cavity.py analyze out.vital
```
Two channels a JSON preset loader tolerates: an unknown top-level member (`key`, the file
stays valid JSON and a valid Vital preset) or bytes after the closing brace (`tail`).
acidcat accepts the unknown key silently and rejects the tail variant as Unsupported
rather than reading the preset and warning, which motivate walker rules
(`json_unknown_key`, `json_trailing_data`, proposed).

### pathological-Unicode specimens
`specimens/` includes synthetic AAC/WAV carriers whose metadata isolates one class
of pathological Unicode each (multi-script strings, stacked combining marks, bidi
overrides, astral codepoints, embedded NUL) -- a real-world stress test for every
text layer a file touches, and a demonstration of why acidcat survives them.

## corpus

Tools default to the shipped `specimens/` directory, which holds only synthetic,
non-copyright files that ship with this repo. Point `ACIDCAT_CORPUS` at a larger
private library of real-world inputs (copyrighted audio, exports, captures) to run
the sweeps against it; those raw inputs are never committed here.
