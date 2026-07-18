# notebooks

Interactive exploration of audio-file specimens, driving acidcat's public API
alongside librosa / pandas / matplotlib. Prototypes for the shiny-dex work.

## Running them

Use the `audio` conda env (has `acidcat[viz]` + librosa + jupyterlab):

```bash
conda activate audio
jupyter lab          # then pick the "Python (audio/acidcat)" kernel
```

Both notebooks ship already executed, so they render on open; re-run to point them
at your own files.

## What's here

- **`01_single_file_anatomy.ipynb`** -- one file, top to bottom. `acidcat.walk_file()`
  for the container structure (chunks, offsets, field-level breakdown), a byte-value
  histogram + windowed-entropy trace for the byte structure, then librosa for the
  waveform/spectrogram and the `ACOUSTIC_PROPERTIES.md` metrics (RMS, crest factor,
  spectral centroid, tempo, ...). Set `TARGET` to any file. Seed of the interactive
  explorer.

- **`02_library_census.ipynb`** -- a whole directory at once. Walks every file, builds
  a DataFrame, then reports the format distribution, the chunk-frequency census, the
  chunk co-occurrence matrix, and the oddballs (files carrying warnings or rare
  chunks -- automated shiny-hunting). Set `LIBRARY = Path('~/sample_packs')` for a
  census over 1,286 real files.
