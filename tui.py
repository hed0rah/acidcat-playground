"""acidcat-playground TUI -- an in-terminal file-format research lab.

A Textual console that drives the playground toolkit against a corpus of real
audio/preset files. Pick a file and acidcat's own walker decodes its structure, and see every decoded
field tinted over the raw bytes it came from -- the terminal-native cousin of
acidcat explore's HTML byte-grid.

    python tui.py                 # default root ($ACIDCAT_CORPUS or ./specimens)
    python tui.py path/to/dir      # browse that directory instead
    python tui.py path/to/file.wav # root at its folder and auto-load it

Modes (switch with the number keys or the tab bar):
  1 EXPLORER   tree + chunks + tinted hex + fields, with v-cycled analysis views
               (STRUCTURE / MAP / ENTROPY / HILBERT / ANOMALIES)
  2 LAB        glitch + mangle the current file: recipes and mutations, most with
               adjustable knobs (the slider editor)
  3 STEGO      embed / construct: polyglots, cavities, LSB, dual-endian, ...
  4 METADATA   friendly tags + a decoded structure tree + technical summary
  5 FUZZ       mutate a seed against an external target, classify OK/ERROR/HANG/CRASH
  6 REPORTS    render reports/*.md

Keys:  : palette   1-6 jump to a mode   v cycle the explorer view   p play (. stop)
       x edit field   b byte patch   m metadata   g recipe   / search   u undo   w save
Editing is non-destructive (a working copy; the original is untouched until w).

Nothing here reimplements parsing or writing: the walker is acidcat's
acidcat.core.walk.walk_file, the scan is acidcat.core.anomalies.scan, metadata
writes go through acidcat's write engine, and the stego recipes call the
playground's PoC tools.
"""

import os
import sys
import glob
import math
import struct
import random
import subprocess
import webbrowser

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.environ.get("ACIDCAT_REPO") or os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "acidcat")
# acidcat: a sibling checkout by default, or set ACIDCAT_REPO, or pip install acidcat
sys.path.insert(0, os.path.join(REPO, "src"))
sys.path.insert(0, HERE)

from rich.text import Text  # noqa: E402
from rich.markup import escape  # noqa: E402

from textual import on, work  # noqa: E402
from textual.app import App, ComposeResult  # noqa: E402
from textual.binding import Binding  # noqa: E402
from textual.screen import ModalScreen  # noqa: E402
from textual.containers import Horizontal, Vertical, VerticalScroll  # noqa: E402
from textual.widgets import (  # noqa: E402
    Header, Footer, DirectoryTree, DataTable, Static, TabbedContent, TabPane,
    Markdown, RichLog, Button, Label, Input, OptionList, Tree,
)

from acidcat.core.walk import walk_file, Unsupported  # noqa: E402
from acidcat.core import anomalies as ac_anom  # noqa: E402
from acidcat.tui_theme import PALETTE, TEAL, ORANGE, AMBER, DIM, byte_color  # noqa: E402
from acidcat import edit_metadata, read_tags, read_id3v2, list_id3v2_frames  # noqa: E402
import mutations  # noqa: E402
# these PoC modules reconfigure the real stdout at import; import at module level
# (before Textual replaces stdout) so the stego recipes can call them mid-run.
import polyglot  # noqa: E402
import stego  # noqa: E402
import junk_cavity  # noqa: E402
import flac_cavity  # noqa: E402
import mp4_cavity  # noqa: E402
import id3_cavity  # noqa: E402
import midi_carrier  # noqa: E402
import ogg_multiplex  # noqa: E402
import dual_endian  # noqa: E402
from acidcat import viz  # noqa: E402
import forge as forge_mod  # noqa: E402
from acidcat.util import play as play_mod  # noqa: E402

CORPUS = os.environ.get("ACIDCAT_CORPUS") or os.path.join(HERE, "specimens")

# PALETTE (per-field tint cycle) comes from the shared brand theme (imported above).
HEX_CAP = 2048          # bytes of each region drawn in the hex pane (headers, not mdat)
SEV_STYLE = {"alert": f"bold {ORANGE}", "warn": AMBER, "notice": TEAL, "info": DIM}


# ── the model: acidcat's walker, enriched with absolute offsets + raw bytes ──

def walk_enriched(path):
    """Run acidcat's walker and attach each chunk's absolute payload base, its
    fields' absolute offsets, and a capped slice of its raw region bytes. Mirrors
    inspect._full_chunk / acidcat explore so the hex pane can tint fields in place."""
    fmt, chunks, warns = walk_file(path, deep=False)
    out = []
    with open(path, "rb") as fh:
        for c in chunks:
            pb = c.get("payload_base", c["offset"] + 8)
            fields = []
            for f in c["fields"]:
                f2 = dict(f)
                f2["abs"] = pb + f["off"] if f["off"] is not None else None
                fields.append(f2)
            e = {**c, "payload_base": pb, "fields": fields, "raw_base": c["offset"]}
            positioned = [f for f in fields if f["abs"] is not None]
            if positioned:
                # cover the header plus every positioned field's span (a data
                # field can declare a huge length, so cap the region at HEX_CAP).
                end = max([c["offset"] + 8]
                          + [f["abs"] + max(1, f["len"]) for f in positioned])
                fh.seek(c["offset"])
                e["raw"] = fh.read(min(end - c["offset"], HEX_CAP))
            else:
                e["raw"] = b""
            out.append(e)
    return fmt, out, warns


def field_colors(chunk):
    """Map each field to a palette index: positioned fields get a distinct color,
    derived (offset-less) fields get None."""
    ci = {}
    n = 0
    for i, f in enumerate(chunk["fields"]):
        if f["abs"] is not None:
            ci[i] = n
            n += 1
        else:
            ci[i] = None
    return ci


def render_hex(chunk, colors, hi_field=None):
    """Rich Text hex dump of a chunk's region with each field tinted over its
    bytes; the highlighted field's span is reversed so it pops."""
    raw = chunk["raw"]
    base = chunk["raw_base"]
    if not raw:
        return Text("  (no positioned fields in this region)\n", style="dim")
    owner = {}
    end = base + len(raw)
    for i, f in enumerate(chunk["fields"]):
        if f["abs"] is None or colors[i] is None:
            continue
        for o in range(f["abs"], min(f["abs"] + max(1, f["len"]), end)):
            owner.setdefault(o, colors[i])

    hi = None
    if hi_field is not None:
        f = chunk["fields"][hi_field]
        if f["abs"] is not None:
            hi = (f["abs"], max(1, f["len"]))

    def lit(o):
        return hi is not None and hi[0] <= o < hi[0] + hi[1]

    t = Text()
    for row in range(0, len(raw), 16):
        t.append(f"{base + row:08x}  ", style="#565B63")
        line = raw[row:row + 16]
        for i, byte in enumerate(line):
            o = base + row + i
            ci = owner.get(o)
            style = PALETTE[ci] if ci is not None else "#8A9099"
            if lit(o):
                style += " reverse bold"
            t.append(f"{byte:02x}", style=style)
            t.append(" ")
        t.append("   " * (16 - len(line)))
        t.append(" ")
        for i, byte in enumerate(line):
            o = base + row + i
            ci = owner.get(o)
            style = PALETTE[ci] if ci is not None else "#565B63"
            if lit(o):
                style += " reverse bold"
            t.append(chr(byte) if 32 <= byte < 127 else ".", style=style)
        t.append("\n")
    return t


# ── whole-file views: MAP (bird's-eye) and ENTROPY ──────

_BLOCKS = " ▁▂▃▄▅▆▇█"


def _heat(e):
    """Map normalized entropy e in [0,1] to the brand ramp (teal -> orange)."""
    e = max(0.0, min(1.0, e))
    return PALETTE[min(len(PALETTE) - 1, int(e * len(PALETTE)))]


def render_map(chunks, size, width, sel_idx=None):
    """Bird's-eye band: one proportional run of blocks per region, colored per
    chunk, sized to its byte span, so a huge mdat dwarfs a tiny header."""
    if not chunks or size <= 0:
        return Text("  (no regions)\n", style="dim")
    cells = max(20, width)
    t = Text()
    t.append("  whole-file map  ", style="bold #08F9DF")
    t.append(f"{size:,} bytes across {len(chunks)} region(s)\n\n", style="dim")
    # proportional band
    band = Text("  ")
    for i, c in enumerate(chunks):
        n = max(1, round(c["size"] / size * cells))
        col = PALETTE[i % len(PALETTE)]
        style = f"{col} reverse bold" if i == sel_idx else col
        band.append("█" * n, style=style)
    t.append(band)
    t.append("\n\n")
    # legend, one row per region
    for i, c in enumerate(chunks):
        col = PALETTE[i % len(PALETTE)]
        pct = c["size"] / size * 100
        marker = "►" if i == sel_idx else " "
        row = Text(f"  {marker} ")
        row.append("██ ", style=col)
        cid = (c["id"].strip() or "?")[:12]
        line = f"{cid:<12} 0x{c['offset']:08x}  {c['size']:>12,}  {pct:5.1f}%"
        row.append(line, style="bold #C9CDD3" if i == sel_idx else "#8A9099")
        t.append(row)
        t.append("\n")
    return t


def file_entropy(path, num_windows):
    """Per-window Shannon entropy (0..1, normalized from 0..8 bits) across the
    whole file. For a window larger than SAMPLE bytes (big files), sample the
    window head instead of reading all of it; flags that it sampled."""
    size = os.path.getsize(path)
    if size == 0:
        return [], size, False
    win = max(1, math.ceil(size / num_windows))
    SAMPLE = 8192
    sampled = win > SAMPLE
    ents = []
    with open(path, "rb") as f:
        for i in range(num_windows):
            start = i * win
            if start >= size:
                break
            f.seek(start)
            data = f.read(min(win, SAMPLE))
            if not data:
                break
            counts = [0] * 256
            for byte in data:
                counts[byte] += 1
            n = len(data)
            h = 0.0
            for c in counts:
                if c:
                    p = c / n
                    h -= p * math.log2(p)
            ents.append(h / 8.0)
    return ents, size, sampled


def render_entropy(path, width, declared_end=None):
    """energy view: a colored, block-height entropy sparkline across
    the whole file. Hot columns = compressed/encrypted/high-entropy; a hot band
    past the declared container end is a polyglot / appended-payload tell."""
    cols = max(20, width)
    ents, size, sampled = file_entropy(path, cols)
    if not ents:
        return Text("  (empty file)\n", style="dim")
    t = Text()
    t.append("  entropy  ", style="bold #08F9DF")
    note = "  (sampled window heads)" if sampled else ""
    t.append(f"{len(ents)} windows over {size:,} bytes{note}\n\n", style="dim")
    win = max(1, math.ceil(size / cols))
    # mark the column where declared container data ends (trailing-data boundary)
    end_col = None
    if declared_end and 0 < declared_end < size:
        end_col = min(len(ents) - 1, declared_end // win)
    # smooth braille curve across the file, colored per column by heat
    n = len(ents)
    for row in viz.braille_line(list(ents), width=cols, height=6, vmin=0, vmax=1):
        line = Text("  ")
        for cx, ch in enumerate(row):
            vi = min(n - 1, int(round(cx * (n - 1) / max(1, cols - 1))))
            style = _heat(ents[vi])
            if end_col is not None and vi == end_col:
                style += " underline"
            line.append(ch, style=style)
        t.append(line)
        t.append("\n")
    t.append("\n")
    lo, hi = min(ents), max(ents)
    mean = sum(ents) / len(ents)
    t.append(f"  min {lo * 8:.2f}  mean {mean * 8:.2f}  max {hi * 8:.2f}  bits/byte\n",
             style="#8A9099")
    if end_col is not None:
        tail = ents[end_col:]
        tail_mean = sum(tail) / len(tail) if tail else 0
        t.append(f"  underline marks the declared container end (0x{declared_end:08x}); "
                 f"{size - declared_end:,} trailing bytes, entropy {tail_mean * 8:.2f} bits\n",
                 style="#FF4D00")
    if hi * 8 > 7.5:
        t.append("  hot columns (>7.5 bits) look compressed/encrypted or packed\n",
                 style="#FF4D00")
    # whole-file byte-value distribution: flat top = encrypted/compressed,
    # peaks = structure. the visual companion to the entropy number above.
    with open(path, "rb") as f:
        sample = f.read(1 << 20)
    t.append("\n  byte distribution", style="bold #08F9DF")
    t.append("  (flat = encrypted/compressed, spiky = structured)\n\n", style="dim")
    for row in viz.byte_histogram(sample, width=min(cols, 128), height=4):
        t.append("  " + row + "\n", style="#8A9099")
    return t


def render_hilbert(path, width):
    """binvis-style Hilbert byte-map: file offset -> 2D via a space-filling curve,
    colored by byte class. Regions (header / PCM / appended / cavity) show up as
    spatially distinct blocks. Half-block chars pack two grid rows per line."""
    order = 6                                    # 64x64 grid -> 64 wide, 32 rows
    with open(path, "rb") as f:
        data = f.read(16 * 1024 * 1024)
    grid, side = viz.hilbert_grid(data, order=order)
    t = Text()
    t.append("  hilbert byte-map  ", style="bold #08F9DF")
    t.append(f"{side}x{side} cells over {os.path.getsize(path):,} bytes   ", style="dim")
    for b, label in ((0x41, "ascii"), (0x80, "high"), (0x09, "ctrl"),
                     (0xFF, "0xff"), (0x00, "null")):
        t.append("▀", style=byte_color(b))
        t.append(f" {label}  ", style="dim")
    t.append("\n\n")
    for y in range(0, side, 2):
        line = Text("  ")
        for x in range(side):
            top = grid[y][x]
            bot = grid[y + 1][x] if y + 1 < side else None
            line.append("▀", style=f"{byte_color(top)} on {byte_color(bot)}")
        t.append(line)
        t.append("\n")
    return t


# ── the app ──────────────────────────────────────────────────────────────

def _find_all(data, needle, limit=256):
    """Every offset of a byte pattern (used by the explorer search)."""
    offs = []
    if not needle:
        return offs
    i = data.find(needle)
    while i != -1 and len(offs) < limit:
        offs.append(i)
        i = data.find(needle, i + 1)
    return offs


_HELP = """[b #08F9DF]acidcat playground -- keys[/]

  [b]:[/]      command palette -- every function, type to filter
  [b]1..5[/]   switch mode: explorer / lab / stego / metadata / reports
  [b]v[/]      cycle VISUAL mode: STRUCTURE -> MAP -> ENTROPY -> HILBERT
  [b]r[/]      run the focused action (fuzz sweep, lab, ...)
  [b]e[/]      export the loaded file to an HTML explorer (opens in browser)
  [b]s[/]      save an SVG screenshot of the current view
  [b]p[/]      play the selected region as raw PCM ([b].[/] stops playback)
  [b]x[/] / [b]enter[/]  edit the highlighted field in place (forge), then p to hear it
  [b]b[/]      raw byte patch at an offset (OFFSET HEXBYTES)
  [b]t[/]      examine the selected field's bytes as u16/i16/u32/f32 (LE + BE)
  [b]m[/]      metadata editor: title/artist/bpm/key/... (WAV, MP3, FLAC, AIFF)
  [b]g[/]      apply a glitch recipe (reverse, bitcrush, stutter, sort, ...)
  [b]/[/]      search: HEX bytes, text, v:NUMBER (value scan), or s:TEXT (strings)
  [b]d[/]      diff: what this forge session changed vs the original
  [b]u[/]      undo the last edit      [b]o[/]  goto: hexdump at any offset
  [b]w[/]      write the forged result to <name>_forged
  [b]?[/]      this help      [b]q[/]  quit

[b #08F9DF]explorer nav[/]  arrows move the highlight; [b]enter[/] drills in (tree -> chunks
  -> fields), [b]enter[/] on a field edits it; the focused pane has a cyan edge; [b]tab[/] cycles panes

[b #08F9DF]VISUAL modes[/] (explorer tab, press v)
  STRUCTURE  chunk list + tinted hex + field table
  MAP        proportional region map of the file
  ENTROPY    braille entropy curve + byte histogram (flat top = encrypted)
  HILBERT    binvis byte-map (offset -> 2D, colored by byte class)
  ANOMALIES  forensic scan findings (severity, offset, rule, message)

[dim]press any key to close[/]"""


class HelpScreen(ModalScreen):
    CSS = """
    HelpScreen { align: center middle; }
    #help_panel { width: auto; max-width: 84%; height: auto; padding: 1 3;
                  background: #16181C; border: round #08F9DF; }
    """

    def compose(self) -> ComposeResult:
        yield Static(_HELP, id="help_panel")

    def on_key(self, event):
        self.dismiss()

    def on_mouse_down(self, event):
        self.dismiss()


class EditScreen(ModalScreen):
    """A one-line modal input for editing a field value in place."""

    CSS = """
    EditScreen { align: center middle; }
    #edit_panel { width: 76; height: auto; padding: 1 2; background: #16181C;
                  border: round #FF4D00; }
    #edit_prompt { color: #FF4D00; padding-bottom: 1; }
    """

    def __init__(self, prompt, value):
        super().__init__()
        self._prompt = prompt
        self._value = value

    def compose(self) -> ComposeResult:
        with Vertical(id="edit_panel"):
            yield Static(self._prompt, id="edit_prompt")
            yield Input(value=self._value, id="edit_input")

    def on_mount(self):
        self.query_one("#edit_input", Input).focus()

    def on_input_submitted(self, event):
        self.dismiss(event.value)

    def on_key(self, event):
        if event.key == "escape":
            self.dismiss(None)


class PickScreen(ModalScreen):
    """Pick one item from a list (recipes, metadata fields, ...)."""

    CSS = """
    PickScreen { align: center middle; }
    #recipe_panel { width: 62; height: auto; max-height: 80%; padding: 1 2;
                    background: #16181C; border: round #08F9DF; }
    #recipe_title { color: #08F9DF; padding-bottom: 1; }
    """

    def __init__(self, names, title="pick one  (Enter to run, Esc to cancel)"):
        super().__init__()
        self._names = names
        self._title = title

    def compose(self) -> ComposeResult:
        with Vertical(id="recipe_panel"):
            yield Static(self._title, id="recipe_title")
            yield OptionList(*self._names, id="recipe_list")

    def on_mount(self):
        self.query_one("#recipe_list", OptionList).focus()

    def on_option_list_option_selected(self, event):
        self.dismiss(self._names[event.option_index])

    def on_key(self, event):
        if event.key == "escape":
            self.dismiss(None)


class CommandScreen(ModalScreen):
    """Type-to-run command palette; filters as you type, Enter runs the match."""

    CSS = """
    CommandScreen { align: center middle; }
    #cmd_panel { width: 72; height: auto; max-height: 80%; padding: 1 2;
                 background: #16181C; border: round #08F9DF; }
    #cmd_input { margin-bottom: 1; }
    """

    def __init__(self, commands):
        super().__init__()
        self._commands = commands           # [(label, callable), ...]
        self._filtered = list(commands)

    def compose(self) -> ComposeResult:
        with Vertical(id="cmd_panel"):
            yield Input(placeholder="type to filter commands (down to pick)...",
                        id="cmd_input")
            yield OptionList(*[c[0] for c in self._commands], id="cmd_list")

    def on_mount(self):
        self.query_one("#cmd_input", Input).focus()

    def on_input_changed(self, event):
        q = event.value.lower()
        self._filtered = [c for c in self._commands if q in c[0].lower()]
        ol = self.query_one("#cmd_list", OptionList)
        ol.clear_options()
        for c in self._filtered:
            ol.add_option(c[0])

    def on_input_submitted(self, event):
        self.dismiss(self._filtered[0][1] if self._filtered else None)

    def on_option_list_option_selected(self, event):
        if 0 <= event.option_index < len(self._filtered):
            self.dismiss(self._filtered[event.option_index][1])

    def on_key(self, event):
        if event.key == "escape":
            self.dismiss(None)
        elif event.key == "down":
            self.query_one("#cmd_list", OptionList).focus()


class ParamScreen(ModalScreen):
    """Keyboard parameter editor -- ASCII sliders + enum selectors, no typing.
    up/down select a param, left/right adjust it live, enter runs, esc cancels."""

    CSS = """
    ParamScreen { align: center middle; }
    #param_panel { width: 60; height: auto; padding: 1 2; background: #16181C;
                   border: round #08F9DF; }
    #param_title { color: #08F9DF; text-style: bold; padding-bottom: 1; }
    #param_help { color: #565B63; padding-top: 1; }
    """

    def __init__(self, title, params):
        super().__init__()
        self._title = title
        self._params = [dict(p) for p in params]
        self._sel = 0

    def compose(self) -> ComposeResult:
        with Vertical(id="param_panel"):
            yield Static(self._title, id="param_title")
            yield Static("", id="param_body")
            yield Static("up/down select    left/right adjust    enter run    esc cancel",
                         id="param_help")

    def on_mount(self):
        self._redraw()

    def _bar(self, p, width=18):
        lo, hi, v = p["min"], p["max"], p["value"]
        frac = 0.0 if hi == lo else max(0.0, min(1.0, (v - lo) / (hi - lo)))
        fill = int(round(frac * width))
        return "█" * fill + "░" * (width - fill)

    def _redraw(self):
        lines = []
        for i, p in enumerate(self._params):
            sel = i == self._sel
            arrow = "▸ " if sel else "  "
            name = p["name"][:12].ljust(12)
            if p["kind"] == "enum":
                widget = f"◄ {p['value']} ►"
            else:
                if p["kind"] == "float":
                    val = f"{p['value']:.4f}".rstrip("0").rstrip(".")
                else:
                    val = str(int(p["value"]))
                widget = f"│{self._bar(p)}│  {val}"
            color = "#08F9DF" if sel else "#8A9099"
            lines.append(f"[{color}]{arrow}{name} {widget}[/]")
        self.query_one("#param_body", Static).update("\n".join(lines))

    def on_key(self, event):
        k = event.key
        if k == "escape":
            self.dismiss(None)
        elif k == "enter":
            self.dismiss({p["name"]: p["value"] for p in self._params})
        elif k in ("up", "down") and self._params:
            self._sel = (self._sel + (1 if k == "down" else -1)) % len(self._params)
            self._redraw()
        elif k in ("left", "right") and self._params:
            p = self._params[self._sel]
            d = 1 if k == "right" else -1
            if p["kind"] == "enum":
                ch = p["choices"]
                p["value"] = ch[(ch.index(p["value"]) + d) % len(ch)]
            else:
                v = max(p["min"], min(p["max"], p["value"] + d * p["step"]))
                p["value"] = round(v, 5) if p["kind"] == "float" else int(round(v))
            self._redraw()


class DiffScreen(ModalScreen):
    """Show what the forge session changed vs the original file."""

    CSS = """
    DiffScreen { align: center middle; }
    #diff_panel { width: 80; max-height: 82%; height: auto; padding: 1 2;
                  background: #16181C; border: round #FF4D00; }
    #diff_body { color: #C9CDD3; }
    """

    def __init__(self, text, markup=True):
        super().__init__()
        self._text = text
        self._markup = markup

    def compose(self) -> ComposeResult:
        with VerticalScroll(id="diff_panel"):
            yield Static(self._text, id="diff_body", markup=self._markup)

    def on_key(self, event):
        self.dismiss()

    def on_mouse_down(self, event):
        self.dismiss()


class PlaygroundApp(App):
    TITLE = "acidcat // format research lab"
    SUB_TITLE = "no-holds-barred sandbox"

    CSS = """
    Screen { background: #16181C; }
    Header { background: #16181C; color: #08F9DF; text-style: bold; }
    Footer { background: #16181C; }
    #helpbar { dock: bottom; height: 1; background: #16181C; color: #565B63;
               padding: 0 1; }
    #status { height: 1; background: #101217; color: #FF4D00; padding: 0 1; }
    TabbedContent { background: #101217; }
    Tabs { background: #16181C; }
    Tab { color: #8A9099; }
    DataTable { background: #101217; }
    DataTable > .datatable--cursor { background: #3A3E45; color: #C9CDD3; }
    DataTable > .datatable--header { background: #16181C; color: #08F9DF;
                                     text-style: bold; }
    #tree_pane { width: 34; border: round #3A3E45; border-title-color: #8A9099;
                 border-title-align: left; }
    #tree_pane:focus-within { border: round #08F9DF; }
    #chunks { height: 42%; border: round #3A3E45; border-title-color: #8A9099;
              border-title-align: left; }
    #chunks:focus { border: round #08F9DF; }
    #fields { width: 48%; border: round #3A3E45; border-title-color: #8A9099;
              border-title-align: left; }
    #fields:focus { border: round #08F9DF; }
    #hexwrap { width: 1fr; border: round #3A3E45; border-title-color: #8A9099;
               border-title-align: left; }
    #hexwrap:focus-within { border: round #08F9DF; }
    #hex { padding: 0 1; }
    #explorer_head { height: auto; color: #08F9DF; padding: 0 1; }
    #mode_map, #mode_entropy, #mode_hilbert, #mode_anomalies { width: 1fr; }
    #meta_left { width: 46%; }
    #meta_tags { border: round #3A3E45; border-title-color: #8A9099;
                 border-title-align: left; }
    #meta_tags:focus { border: round #08F9DF; }
    #meta_tech { height: auto; color: #8A9099; padding: 1 1; }
    #meta_tree_wrap { width: 1fr; border: round #3A3E45; border-title-color: #8A9099;
                      border-title-align: left; padding: 0 1; }
    #meta_tree { background: #16181C; color: #8A9099; padding: 0 1; }
    #meta_tree > .tree--guides { color: #3A3E45; }
    #meta_tree > .tree--guides-selected { color: #08F9DF; text-style: bold; }
    #meta_tree > .tree--cursor { background: #3A3E45; color: #C9CDD3; }
    #meta_tree > .tree--label { color: #8A9099; }
    #stego_left { width: 56%; }
    #stego_recipes { border: round #3A3E45; border-title-color: #8A9099;
                     border-title-align: left; }
    #stego_recipes:focus { border: round #08F9DF; }
    #stego_log { border: round #3A3E45; }
    #stego_head { color: #08F9DF; padding: 0 1; }
    #fuzz_config { height: auto; color: #8A9099; padding: 1 1; border-bottom: solid #3A3E45; }
    #fuzz_tbl { height: 1fr; }
    #fuzz_summary { height: auto; color: #FF4D00; padding: 0 1; }
    #map, #entropy { padding: 1 1; }
    #lab_log { background: #101217; border: round #3A3E45; }
    #report_list { width: 40; border-right: solid #3A3E45; }
    #report_body { padding: 0 2; }
    .danger { color: #FF4D00; text-style: bold; }
    .panehdr { color: #08F9DF; text-style: bold; padding: 0 1; }
    """

    BINDINGS = [
        Binding("q", "request_quit", "quit"),
        Binding("colon", "palette", "commands"),
        Binding("1", "tab('explorer')", "explorer"),
        Binding("2", "tab('lab')", "lab"),
        Binding("3", "tab('stego')", "stego"),
        Binding("4", "tab('metadata')", "metadata"),
        Binding("5", "tab('fuzz')", "fuzz"),
        Binding("6", "tab('reports')", "reports"),
        Binding("r", "run", "run"),
        Binding("v", "cycle_mode", "view mode"),
        Binding("e", "export_html", "export html"),
        Binding("s", "screenshot", "screenshot"),
        Binding("p", "play_region", "play"),
        Binding("full_stop", "stop_play", "stop", show=False),
        Binding("x", "edit_field", "edit"),
        Binding("b", "byte_patch", "patch"),
        Binding("t", "examine_type", "types", show=False),
        Binding("m", "metadata", "metadata"),
        Binding("g", "recipe", "glitch"),
        Binding("slash", "search", "search"),
        Binding("d", "diff", "diff", show=False),
        Binding("u", "undo", "undo"),
        Binding("o", "goto", "goto", show=False),
        Binding("w", "write_forged", "write"),
        Binding("question_mark", "help", "help"),
    ]

    VIEW_MODES = ["STRUCTURE", "MAP", "ENTROPY", "HILBERT", "ANOMALIES"]

    # (technique, formats, effect) -- the embed/construct catalog for STEGO mode
    STEGO_RECIPES = [
        ("wav+zip polyglot", "WAV", "append a ZIP past the RIFF end (plays + unzips)"),
        ("lsb embed", "PCM WAV", "hide a payload in the sample low bits"),
        ("dual-endian twin", "WAV/AIFF", "one PCM block, two sounds (LE vs BE)"),
        ("junk cavity", "WAV/RF64", "stuff a spec-ignorable JUNK chunk"),
        ("ogg dual-bitstream", "Ogg", "a second logical bitstream rides along"),
        ("flac app/padding", "FLAC", "hide in APPLICATION or PADDING blocks"),
        ("mp4 mdat cavity", "MP4/M4A", "unreferenced bytes inside mdat"),
        ("id3 padding", "MP3", "payload in the ID3v2 padding region"),
        ("midi sysex/tail", "MIDI", "0x7D SysEx or bytes after the last MTrk"),
    ]

    def check_action(self, action, parameters):
        # while a modal (pick / param / edit / command / diff / help) is open,
        # don't fire the app-global bindings (tab jumps, view cycle, edit keys),
        # so keys typed into a dialog do not leak to the main screen.
        if len(self.screen_stack) > 1:
            return False
        return True

    def __init__(self, root=CORPUS, autoload=None):
        super().__init__()
        self.root_dir = root
        self.autoload = autoload
        self.cur_file = None
        self.cur_fmt = ""
        self.cur_chunks = []
        self.cur_chunk = None
        self.cur_chunk_idx = None
        self.cur_colors = {}
        self.mode_idx = 0
        self._forged = False          # has the loaded file been forge-edited?
        self._workpath = None         # accumulating working copy of the edits
        self._forged_from = None      # the original path, for save-as naming
        self._history = []            # undo stack of pre-edit snapshots
        self._player = None           # current ffplay process (killable)
        self._msg = ""                # transient message shown in the header
        self._fuzz_target = "ffprobe -v error {file}"   # external target command
        self._fuzz_iters = 100
        self._fuzz_timeout = 8.0
        self._fuzzing = False

    def compose(self) -> ComposeResult:
        yield Header()
        yield Static("no file loaded", id="status")
        with TabbedContent(initial="explorer"):
            with TabPane("1 EXPLORER", id="explorer"):
                with Horizontal():
                    with Vertical(id="tree_pane"):
                        yield Label(
                            os.path.basename(os.path.normpath(self.root_dir)).upper()
                            or "ROOT", classes="panehdr")
                        yield DirectoryTree(self.root_dir, id="tree")
                    with Vertical():
                        yield Static("select a file", id="explorer_head")
                        with Vertical(id="mode_structure"):
                            yield DataTable(id="chunks", cursor_type="row")
                            with Horizontal():
                                yield DataTable(id="fields", cursor_type="row")
                                with VerticalScroll(id="hexwrap"):
                                    yield Static(id="hex")
                        with VerticalScroll(id="mode_map"):
                            yield Static(id="map")
                        with VerticalScroll(id="mode_entropy"):
                            yield Static(id="entropy")
                        with VerticalScroll(id="mode_hilbert"):
                            yield Static(id="hilbert")
                        with Vertical(id="mode_anomalies"):
                            yield Static("forensic scan  (v cycles here, or r rescans)",
                                         id="anom_head")
                            yield DataTable(id="anom", cursor_type="row")
            with TabPane("2 LAB", id="lab"):
                with Horizontal():
                    with Vertical(id="lab_left"):
                        yield DataTable(id="lab_recipes", cursor_type="row")
                        yield DataTable(id="lab_muts", cursor_type="row")
                    with Vertical(id="lab_right"):
                        yield Static(
                            "LAB  --  glitch + mangle the CURRENT file. Enter applies the "
                            "selected recipe or mutation (non-destructive: u undoes, p plays, "
                            "w saves). Press : for fuzz-external-target and more.",
                            id="lab_head")
                        yield RichLog(id="lab_log", highlight=True, markup=True, wrap=True)
            with TabPane("3 STEGO", id="stego"):
                with Horizontal():
                    with Vertical(id="stego_left"):
                        yield DataTable(id="stego_recipes", cursor_type="row")
                    with Vertical(id="stego_right"):
                        yield Static(
                            "STEGO  --  embed / construct. Enter runs the selected "
                            "technique on the CURRENT file (carrier); the result loads back "
                            "so the analysis views show where the payload lives. Payload "
                            "picker + full recipe set land next.",
                            id="stego_head")
                        yield RichLog(id="stego_log", highlight=True, markup=True, wrap=True)
            with TabPane("4 METADATA", id="metadata"):
                with Horizontal():
                    with Vertical(id="meta_left"):
                        yield DataTable(id="meta_tags", cursor_type="row")
                        yield Static("", id="meta_tech", markup=False)
                    with Vertical(id="meta_tree_wrap"):
                        yield Tree("(open a file)", id="meta_tree")
            with TabPane("5 FUZZ", id="fuzz"):
                with Vertical():
                    yield Static("", id="fuzz_config", markup=False)
                    yield DataTable(id="fuzz_tbl", cursor_type="row")
                    yield Static("", id="fuzz_summary")
            with TabPane("6 REPORTS", id="reports"):
                with Horizontal():
                    with Vertical(id="report_list"):
                        yield Label("REPORTS", classes="panehdr")
                        yield DataTable(id="reports_tbl", cursor_type="row")
                    with VerticalScroll():
                        yield Markdown("select a report on the left", id="report_body")
        yield Static("", id="helpbar")

    def on_mount(self):
        self.theme = "textual-dark"
        self.query_one("#chunks", DataTable).add_columns(
            "#", "id", "offset", "size", "summary")
        self.query_one("#fields", DataTable).add_columns(
            "offset", "field", "value", "note")
        self.query_one("#anom", DataTable).add_columns(
            "sev", "offset", "rule", "message")
        lr = self.query_one("#lab_recipes", DataTable)
        lr.add_columns("recipe", "effect")
        for name, fn in forge_mod.RECIPES.items():
            doc = (fn.__doc__ or "").strip().splitlines()[0] if fn.__doc__ else ""
            lr.add_row(name, doc[:56])
        lm = self.query_one("#lab_muts", DataTable)
        lm.add_columns("mutation", "category")
        for name, (cat, _fn) in sorted(mutations.ALL.items()):
            lm.add_row(name, cat)
        self.query_one("#meta_tags", DataTable).add_columns("tag", "value")
        sr2 = self.query_one("#stego_recipes", DataTable)
        sr2.add_columns("technique", "formats", "effect")
        for name, fmts, eff in self.STEGO_RECIPES:
            sr2.add_row(name, fmts, eff)
        self.query_one("#fuzz_tbl", DataTable).add_columns(
            "run", "mutation", "verdict", "code")
        self._refresh_fuzz_config()
        rt = self.query_one("#reports_tbl", DataTable)
        rt.add_columns("report")
        for p in self._report_files():
            rt.add_row(os.path.relpath(p, HERE), key=p)
        for wid, title in (("#tree_pane", "tree"), ("#chunks", "chunks"),
                           ("#fields", "fields"), ("#hexwrap", "hex / ascii"),
                           ("#lab_recipes", "glitch recipes"), ("#lab_muts", "mutations"),
                           ("#meta_tags", "tags"), ("#meta_tree_wrap", "structure tree"),
                           ("#stego_recipes", "techniques")):
            try:
                self.query_one(wid).border_title = title
            except Exception:
                pass
        self.apply_mode()
        self._update_helpbar()
        if self.autoload:
            self.load_file(self.autoload)

    # ── explorer ────────────────────────────────────────────────────────

    @on(DirectoryTree.FileSelected, "#tree")
    def _file_picked(self, event: DirectoryTree.FileSelected):
        self._forged = False          # a fresh file, drop any prior forge session
        self._workpath = None
        self._forged_from = None
        self._history = []
        self.load_file(str(event.path))

    def load_file(self, path):
        head = self.query_one("#explorer_head", Static)
        try:
            fmt, chunks, warns = walk_enriched(path)
        except Unsupported as e:
            head.update(f"[#FF4D00]unsupported[/]  {os.path.basename(path)}: {e}")
            self._reset_explorer()
            return
        except Exception as e:
            head.update(f"[#FF4D00]walk error[/]  {e.__class__.__name__}: {e}")
            self._reset_explorer()
            return
        self.cur_file = path
        self.cur_chunks = chunks
        self.cur_fmt = fmt
        size = os.path.getsize(path)
        warn_txt = f"  [#FF4D00]! {len(warns)} file warning(s)[/]" if warns else ""
        head.update(f"[b]{os.path.basename(path)}[/]  [#8A9099]{fmt}[/]  "
                    f"{size:,} bytes  {len(chunks)} region(s){warn_txt}")
        ct = self.query_one("#chunks", DataTable)
        ct.clear()
        for i, c in enumerate(chunks):
            ct.add_row(str(i), c["id"].strip() or "?", f"0x{c['offset']:08x}",
                       f"{c['size']:,}", c["summary"][:70])
        if chunks:
            ct.move_cursor(row=0)
            self.load_chunk(0)
            ct.focus()                 # arrows navigate chunks immediately
        self.apply_mode()
        try:
            self._refresh_metadata()   # shared spine: metadata mode reflects this file
            self._refresh_fuzz_config()
        except Exception:
            pass
        self._status()                 # refresh the always-on file header

    def _reset_explorer(self):
        self.cur_file = None
        self.cur_fmt = ""
        self.cur_chunks = []
        self.cur_chunk = None
        self.cur_chunk_idx = None
        self.query_one("#chunks", DataTable).clear()
        self.query_one("#fields", DataTable).clear()
        self.query_one("#hex", Static).update("")
        self.apply_mode()

    @on(DataTable.RowHighlighted, "#chunks")
    def _chunk_moved(self, event: DataTable.RowHighlighted):
        if 0 <= event.cursor_row < len(self.cur_chunks):
            self.load_chunk(event.cursor_row)
            # the MAP view highlights whatever region is selected here
            if self.VIEW_MODES[self.mode_idx] == "MAP":
                self.refresh_mode()

    def load_chunk(self, idx):
        chunk = self.cur_chunks[idx]
        self.cur_chunk = chunk
        self.cur_chunk_idx = idx
        self.cur_colors = field_colors(chunk)
        ft = self.query_one("#fields", DataTable)
        ft.clear()
        for i, f in enumerate(chunk["fields"]):
            ci = self.cur_colors[i]
            off = f"{f['abs']:08x}" if f["abs"] is not None else "--------"
            name = Text(str(f["name"]), style=PALETTE[ci] if ci is not None else "dim")
            ft.add_row(off, name, str(f["value"])[:28], str(f.get("note", ""))[:34])
        self.query_one("#hex", Static).update(render_hex(chunk, self.cur_colors))
        for w in chunk.get("warnings", []):
            pass  # surfaced in the anomalies tab; keep the hex pane clean

    @on(DataTable.RowHighlighted, "#fields")
    def _field_moved(self, event: DataTable.RowHighlighted):
        if self.cur_chunk is None:
            return
        self.query_one("#hex", Static).update(
            render_hex(self.cur_chunk, self.cur_colors, hi_field=event.cursor_row))

    @on(DataTable.RowSelected, "#chunks")
    def _chunk_selected(self, event: DataTable.RowSelected):
        self.query_one("#fields", DataTable).focus()   # Enter drills into fields

    @on(DataTable.RowSelected, "#fields")
    def _field_selected(self, event: DataTable.RowSelected):
        self.action_edit_field()               # Enter on a field edits it

    # ── forge: play + edit the loaded file ──────────────────────────────

    def _header_text(self):
        """Always-on file header: name, format, size, chunk count, modified flag."""
        if not self.cur_file:
            tail = f"   ::  {self._msg}" if self._msg else ""
            return "no file loaded  --  pick one in the tree" + tail
        name = escape(os.path.basename(self._forged_from or self.cur_file))
        mod = "  [#FF4D00]*modified[/]" if self._forged else ""
        try:
            size = os.path.getsize(self.cur_file)
        except OSError:
            size = 0
        info = (f"[b]{name}[/]  [#8A9099]{escape(self.cur_fmt)}[/]  {size:,} B  "
                f"{len(self.cur_chunks)} chunks{mod}")
        return info + (f"   ::  [#FF4D00]{escape(self._msg)}[/]" if self._msg else "")

    def _status(self, msg=""):
        self._msg = msg
        self.query_one("#status", Static).update(self._header_text())

    def _wav_params(self):
        """Infer (rate, ch, bits, floating) from a WAV fmt chunk for accurate
        playback; fall back to 44100/stereo/16-bit for anything else."""
        rate, ch, bits, floating = 44100, 2, 16, False
        for c in self.cur_chunks:
            if str(c.get("id", "")).strip() == "fmt":
                for f in c.get("fields", []):
                    v = str(f.get("value", "")).replace(",", "")
                    if f.get("name") == "sample_rate" and v.isdigit():
                        rate = int(v)
                    elif f.get("name") == "channels" and v.isdigit():
                        ch = max(1, int(v))
                    elif f.get("name") == "bits_per_sample" and v.isdigit():
                        bits = int(v)
                    elif f.get("name") == "format_tag" and "float" in str(f.get("note", "")).lower():
                        floating = True
        return rate, ch, bits, floating

    def action_play_region(self):
        if self._player and self._player.poll() is None:   # p again = stop
            self._kill_player()
            self._status("playback stopped")
            return
        if not self.cur_file or self.cur_chunk is None:
            self._status("no region to play -- load a file")
            return
        c = self.cur_chunk
        pb = c.get("payload_base", (c.get("offset") or 0) + 8)
        size = c.get("size") or 0
        if size <= 0:
            self._status("selected region is empty")
            return
        self._kill_player()
        rate, ch, bits, floating = self._wav_params()
        try:
            self._player = play_mod.play_region(
                self.cur_file, pb, min(size, 8_000_000),
                rate=rate, ch=ch, bits=bits, floating=floating, block=False)
        except Exception as e:
            self._status(f"play failed: {e}")
            return
        self._status(f"playing {str(c['id']).strip()} ({size:,} B) {rate}Hz x{ch} "
                     f"{bits}-bit   --   . to stop")

    def _kill_player(self):
        play_mod.stop(self._player)
        self._player = None

    def action_stop_play(self):
        if self._player and self._player.poll() is None:
            self._kill_player()
            self._status("playback stopped")
        else:
            self._status("nothing playing")

    def _work_path(self):
        import tempfile
        if not self._workpath:
            self._workpath = os.path.join(
                tempfile.gettempdir(), "forge_" + os.path.basename(self.cur_file))
        return self._workpath

    _UNDO_CAP = 32                     # most snapshots to keep
    _UNDO_BYTES_CAP = 64 * 1024 * 1024  # total snapshot bytes to keep

    def _snapshot(self):
        """Push the current file state onto the undo stack (before an edit)."""
        if not self.cur_file:
            return
        with open(self.cur_file, "rb") as f:
            data = f.read()
        self._history.append((data, self.cur_file, self._forged, self._forged_from))
        # bound by count AND total bytes so a big file edited many times cannot
        # pin gigabytes of snapshots; the newest snapshot always survives.
        while len(self._history) > 1 and (
                len(self._history) > self._UNDO_CAP
                or sum(len(h[0]) for h in self._history) > self._UNDO_BYTES_CAP):
            self._history.pop(0)

    def action_undo(self):
        if not self._history:
            self._status("nothing to undo")
            return
        data, cf, forged, ff = self._history.pop()
        if forged:
            target = self._work_path()
            with open(target, "wb") as f:
                f.write(data)
            self._forged, self._forged_from = True, ff
            self.load_file(target)
        else:
            self._forged, self._forged_from, self._workpath = False, None, None
            self.load_file(cf)
        self._status(f"undo: reverted last edit  ({len(self._history)} left)")

    def action_goto(self):
        if not self.cur_file:
            self._status("no file loaded")
            return

        def _show(off):
            if not off:
                return
            try:
                text = forge_mod.Forge(self.cur_file).hexdump(int(off, 0), 256)
            except Exception as e:
                self._status(f"goto failed: {e}")
                return
            self.push_screen(DiffScreen(f"hexdump @ {off}\n\n{text}\n\n"
                                        "(press any key to close)", markup=False))

        self.push_screen(EditScreen("goto offset (0xHEX or decimal):\n(Esc cancels):",
                                    "0x"), _show)

    def _field_row(self):
        try:
            return self.query_one("#fields", DataTable).cursor_row
        except Exception:
            return None

    def _restore_cursor(self, chunk_idx, field_row):
        """After a reload, put the highlight back where the user was."""
        if chunk_idx is None or not (0 <= chunk_idx < len(self.cur_chunks)):
            return
        self.query_one("#chunks", DataTable).move_cursor(row=chunk_idx)
        self.load_chunk(chunk_idx)
        if field_row is not None:
            flds = self.cur_chunks[chunk_idx].get("fields", [])
            if 0 <= field_row < len(flds):
                self.query_one("#fields", DataTable).move_cursor(row=field_row)

    def _forge_apply(self, mutate, label):
        """Run a forge mutation on the current file, save to the working copy,
        reload so the view reflects it. Edits accumulate; original untouched."""
        self._snapshot()
        keep = (self.cur_chunk_idx, self._field_row())
        origin = self._forged_from or self.cur_file
        try:
            fg = forge_mod.Forge(self.cur_file)
            mutate(fg)
            work = fg.save(self._work_path())
        except Exception as e:
            self._status(f"{label} failed: {e}")
            return
        self._forged = True
        self._forged_from = origin
        self.load_file(work)
        self._restore_cursor(*keep)
        self._status(f"{label}   now: {self.cur_fmt}   (p to hear, w to save-as)")

    def action_edit_field(self):
        if self.cur_chunk is None:
            self._status("no field to edit -- select a chunk, then a field")
            return
        row = self.query_one("#fields", DataTable).cursor_row
        fields = self.cur_chunk.get("fields", [])
        if not (0 <= row < len(fields)):
            self._status("no field selected")
            return
        fld = fields[row]
        if fld.get("abs") is None:
            self._status(f"'{fld.get('name')}' is derived -- no bytes to edit")
            return
        cid = str(self.cur_chunk.get("id", "")).strip()
        fname = fld.get("name")
        prompt = (f"edit  {cid} / {fname}   (0x{fld['abs']:08x}, {fld['len']} bytes)"
                  f"\nenter a number, 0xHEX, or text  (Esc cancels):")

        def _apply(val):
            if val is None:
                self._status("edit cancelled")
                return
            self._forge_apply(lambda fg: fg.set_field(cid, fname, val),
                              f"set {cid}/{fname} = {val}")

        self.push_screen(EditScreen(prompt, str(fld.get("value", ""))), _apply)

    def action_recipe(self):
        if not self.cur_file:
            self._status("no file loaded -- pick one first")
            return
        names = list(forge_mod.RECIPES)
        self.push_screen(
            PickScreen(names, "apply a recipe  (Enter to run, Esc to cancel)"),
            lambda name: self._apply_recipe(name) if name
            else self._status("recipe cancelled"))

    _META_FIELDS = {
        "wav": ["title", "artist", "album", "genre", "comment", "date",
                "engineer", "track", "software", "bpm", "key", "root"],
        "aiff": ["title", "artist", "comment", "bpm", "key"],
        "tagged": ["title", "artist", "album", "date", "genre", "comment",
                   "tracknumber"],
    }

    def _meta_kind(self):
        f = self.cur_fmt
        if "WAVE" in f or "RF64" in f:
            return "wav"
        if "AIFF" in f or "AIFC" in f:
            return "aiff"
        if any(t in f for t in ("MP3", "FLAC", "MP4", "M4A", "Ogg", "OGG")):
            return "tagged"
        return None

    def action_metadata(self):
        if not self.cur_file:
            self._status("no file loaded -- pick one first")
            return
        kind = self._meta_kind()
        if not kind:
            self._status(f"no metadata editor for {self.cur_fmt} "
                         "(try x for raw fields, or b for byte patch)")
            return
        fields = self._META_FIELDS[kind]

        def _picked(field):
            if not field:
                self._status("metadata edit cancelled")
                return
            prompt = (f"set {field}  (empty value deletes the tag)"
                      "\n(Esc cancels):")
            self.push_screen(
                EditScreen(prompt, ""),
                lambda val: self._meta_apply(field, val if val else None))

        self.push_screen(
            PickScreen(fields, f"edit {kind} metadata  (Enter to set, Esc cancels)"),
            _picked)

    def _meta_apply(self, field, value):
        self._snapshot()
        keep = (self.cur_chunk_idx, self._field_row())
        origin = self._forged_from or self.cur_file
        try:
            label, new, applied = edit_metadata(self.cur_file, {field: value})
            work = self._work_path()
            with open(work, "wb") as f:
                f.write(new)
        except Exception as e:
            self._status(f"metadata edit failed: {e}")
            return
        self._forged = True
        self._forged_from = origin
        self.load_file(work)
        self._restore_cursor(*keep)
        shown = "(deleted)" if value is None else value
        self._status(f"set {field} = {shown}   ({label})   (w to save-as, p to hear)")

    def action_search(self):
        if not self.cur_file:
            self._status("no file loaded -- pick one first")
            return
        prompt = ("search  --  HEX bytes (ff00), text, v:NUMBER (value scan), "
                  "or s:TEXT (strings)\n(Esc cancels):")
        self.push_screen(EditScreen(prompt, ""), self._do_search)

    def _do_search(self, query):
        if not query:
            self._status("search cancelled")
            return
        with open(self.cur_file, "rb") as f:
            data = f.read()
        if query.startswith("s:"):
            needle = query[2:].encode("latin-1", "replace")
            hits = [i for i in _find_all(data, needle)]
            desc = f"string '{query[2:]}'"
        elif query.startswith("v:"):
            try:
                val = int(query[2:], 0)
                needle = struct.pack("<I", val) if val > 0xFFFF else struct.pack("<H", val)
            except ValueError:
                self._status("bad value after v:")
                return
            hits = _find_all(data, needle)
            desc = f"value {query[2:]}"
        else:
            compact = query.replace(" ", "")
            try:
                needle = (bytes.fromhex(compact)
                          if compact and len(compact) % 2 == 0
                          and all(c in "0123456789abcdefABCDEF" for c in compact)
                          else query.encode("latin-1", "replace"))
            except ValueError:
                needle = query.encode("latin-1", "replace")
            hits = _find_all(data, needle)
            desc = f"'{query}'"
        if not hits:
            self._status(f"{desc}: no matches")
            return
        # jump the chunk cursor to the chunk containing the first hit
        first = hits[0]
        target = None
        for i, c in enumerate(self.cur_chunks):
            if c["offset"] <= first < c["offset"] + max(1, c.get("size", 0)) + 8:
                target = i
        if target is not None:
            self.query_one("#chunks", DataTable).move_cursor(row=target)
        locs = "  ".join(f"0x{h:08x}" for h in hits[:8])
        self._status(f"{desc}: {len(hits)} hit(s)  {locs}"
                     + ("  ..." if len(hits) > 8 else ""))

    def action_byte_patch(self):
        if not self.cur_file:
            self._status("no file loaded -- pick one first")
            return
        pre = f"0x{self.cur_chunk['offset']:08x} " if self.cur_chunk else "0x"
        prompt = ("raw patch  --  OFFSET HEXBYTES   (e.g. 0x2c ff00ba)"
                  "\n(Esc cancels):")

        def _apply(v):
            if not v:
                self._status("patch cancelled")
                return
            parts = v.split()
            if len(parts) < 2:
                self._status("need: OFFSET HEXBYTES")
                return
            try:
                off = int(parts[0], 0)
                blob = bytes.fromhex("".join(parts[1:]).replace(" ", ""))
            except ValueError as e:
                self._status(f"bad input: {e}")
                return
            self._forge_apply(lambda fg: fg.patch(off, blob),
                              f"patch 0x{off:08x} ({len(blob)} bytes)")

        self.push_screen(EditScreen(prompt, pre), _apply)

    def action_examine_type(self):
        """Cycle the selected field's bytes through typed interpretations."""
        if self.cur_chunk is None:
            self._status("select a chunk + field to examine")
            return
        row = self.query_one("#fields", DataTable).cursor_row
        fields = self.cur_chunk.get("fields", [])
        if not (0 <= row < len(fields)) or fields[row].get("abs") is None:
            self._status("no positioned field selected")
            return
        off = fields[row]["abs"]
        with open(self.cur_file, "rb") as f:
            f.seek(off)
            raw = f.read(8)
        bits = []
        for code, sz, name in (("<H", 2, "u16le"), (">H", 2, "u16be"),
                               ("<h", 2, "i16le"), ("<I", 4, "u32le"),
                               (">I", 4, "u32be"), ("<f", 4, "f32le")):
            if len(raw) >= sz:
                bits.append(f"{name}={struct.unpack_from(code, raw)[0]}")
        self._status(f"0x{off:08x}: " + "  ".join(bits))

    def action_diff(self):
        if not self._forged:
            self._status("no edits yet -- diff shows what you have forged vs the original")
            return
        with open(self.cur_file, "rb") as f:
            a = f.read()
        with open(self._forged_from, "rb") as f:
            b = f.read()
        n = min(len(a), len(b))
        ranges = []
        i = 0
        while i < n and len(ranges) < 200:
            if a[i] != b[i]:
                s = i
                while i < n and a[i] != b[i]:
                    i += 1
                ranges.append((s, i))
            else:
                i += 1
        lines = [f"[b #FF4D00]forged vs original[/]  --  {len(ranges)} changed range(s)",
                 f"original {len(b):,} bytes  ->  forged {len(a):,} bytes", ""]
        for s, e in ranges[:28]:
            ln = e - s
            if ln <= 8:
                lines.append(f"  0x{s:08x}  {b[s:e].hex()} -> {a[s:e].hex()}  ({ln}B)")
            else:
                lines.append(f"  0x{s:08x} .. 0x{e:08x}  ({ln} bytes changed)")
        if len(ranges) > 28:
            lines.append(f"  ... and {len(ranges) - 28} more range(s)")
        if len(a) != len(b):
            lines.append(f"\n  size changed by {len(a) - len(b):+,} bytes")
        lines.append("\n[dim]press any key to close[/]")
        self.push_screen(DiffScreen("\n".join(lines)))

    def action_write_forged(self):
        if not self._forged:
            self._status("nothing forged yet -- edit a field with x first")
            return
        import shutil
        origin = self._forged_from or self.cur_file
        base, ext = os.path.splitext(origin)
        dst = base + "_forged" + ext
        try:
            shutil.copyfile(self.cur_file, dst)
        except Exception as e:
            self._status(f"save failed: {e}")
            return
        self._status(f"saved forged file -> {dst}")

    # ── file / menu / palette ────────────────────────────────────────────

    def action_open(self):
        self.query_one("#tree").focus()
        self._status("browse the tree and press enter to open a file")

    def action_save_as(self):
        if not self.cur_file:
            self._status("no file loaded")
            return
        base, ext = os.path.splitext(self._forged_from or self.cur_file)

        def _do(path):
            if not path:
                self._status("save cancelled")
                return
            try:
                with open(self.cur_file, "rb") as s, open(path, "wb") as d:
                    d.write(s.read())
            except Exception as e:
                self._status(f"save failed: {e}")
                return
            self._status(f"saved to {path}")

        self.push_screen(EditScreen("save as (full path):\n(Esc cancels):",
                                    base + "_edited" + ext), _do)

    def action_revert(self):
        if not self._forged:
            self._status("nothing to revert")
            return
        orig = self._forged_from
        self._forged, self._forged_from, self._workpath, self._history = \
            False, None, None, []
        self.load_file(orig)
        self._status("reverted to the original file")

    def action_request_quit(self):
        if not self._forged:
            self.exit()
            return

        def _resp(choice):
            if choice and choice.startswith("Save"):
                self.action_save_as()
            elif choice and choice.startswith("Discard"):
                self.exit()
            else:
                self._status("quit cancelled")

        self.push_screen(
            PickScreen(["Save As...", "Discard changes and quit", "Cancel"],
                       "unsaved edits -- what now?"), _resp)

    def _set_view_mode(self, name):
        if name in self.VIEW_MODES:
            self.mode_idx = self.VIEW_MODES.index(name)
            self.apply_mode()
            self._status(f"view: {name}")

    def action_scan_here(self):
        self.query_one(TabbedContent).active = "explorer"
        self._set_view_mode("ANOMALIES")

    def action_strings_view(self):
        if not self.cur_file:
            self._status("no file loaded")
            return
        try:
            strs = forge_mod.Forge(self.cur_file).strings(minlen=4, limit=400)
        except Exception as e:
            self._status(f"strings failed: {e}")
            return
        if not strs:
            self._status("no printable strings (>= 4 chars)")
            return
        lines = [f"strings  ({len(strs)} runs, >= 4 chars)", ""]
        for off, s in strs[:220]:
            lines.append(f"  0x{off:08x}  {s[:72]}")
        if len(strs) > 220:
            lines.append(f"  ... and {len(strs) - 220} more")
        lines += ["", "(press any key to close)"]
        self.push_screen(DiffScreen("\n".join(lines), markup=False))

    def _command_list(self):
        m = self.VIEW_MODES
        return [
            ("File: Open", self.action_open),
            ("File: Save As...", self.action_save_as),
            ("File: Save forged copy", self.action_write_forged),
            ("File: Revert to original", self.action_revert),
            ("File: Quit", self.action_request_quit),
            ("Edit: Field value", self.action_edit_field),
            ("Edit: Byte patch", self.action_byte_patch),
            ("Edit: Metadata", self.action_metadata),
            ("Edit: Undo", self.action_undo),
            ("View: Structure", lambda: self._set_view_mode(m[0])),
            ("View: Map", lambda: self._set_view_mode(m[1])),
            ("View: Entropy", lambda: self._set_view_mode(m[2])),
            ("View: Hilbert byte-map", lambda: self._set_view_mode(m[3])),
            ("View: Export HTML explorer", self.action_export_html),
            ("Analyze: Anomalies scan", self.action_scan_here),
            ("Analyze: Strings", self.action_strings_view),
            ("Analyze: Diff vs original", self.action_diff),
            ("Analyze: Examine field as types", self.action_examine_type),
            ("Analyze: Search", self.action_search),
            ("Analyze: Goto offset", self.action_goto),
            ("Mangle: Recipe...", self.action_recipe),
            ("Fuzz: run campaign", self._start_fuzz),
            ("Fuzz: configure target...", self.action_fuzz_target),
            ("Fuzz: settings (runs, timeout)...", self.action_fuzz_settings),
            ("Play: Play region", self.action_play_region),
            ("Play: Stop", self.action_stop_play),
            ("Options: Help", self.action_help),
        ]

    def action_palette(self):
        self.push_screen(CommandScreen(self._command_list()),
                         lambda fn: fn() if fn else None)

    _HELP_BARS = {
        "explorer": "[b #08F9DF]v[/] view  [b #08F9DF]x[/] edit  [b #08F9DF]b[/] patch  "
                    "[b #08F9DF]m[/] meta  [b #08F9DF]g[/] glitch  [b #08F9DF]/[/] search  "
                    "[b #08F9DF]p[/] play  [b #08F9DF]:[/] cmds  [b #08F9DF]q[/] quit",
        "lab": "[b #08F9DF]enter[/] apply recipe / mutation (knobs open a slider)  "
               "[b #08F9DF]p[/] play  [b #08F9DF]u[/] undo  [b #08F9DF]w[/] save  "
               "[b #08F9DF]:[/] cmds",
        "stego": "[b #08F9DF]enter[/] run technique (prompts for a payload)  "
                 "[b #08F9DF]w[/] save  [b #08F9DF]:[/] cmds",
        "metadata": "[b #08F9DF]enter[/] edit the selected tag  [b #08F9DF]1[/] explorer  "
                    "[b #08F9DF]:[/] cmds",
        "fuzz": "[b #08F9DF]r[/] run campaign against the target  "
                "[b #08F9DF]:[/] configure target / settings  [b #08F9DF]q[/] quit",
        "reports": "[b #08F9DF]enter[/] open a report  [b #08F9DF]:[/] cmds  [b #08F9DF]q[/] quit",
    }

    def _update_helpbar(self):
        try:
            tab = self.query_one(TabbedContent).active
            self.query_one("#helpbar", Static).update(
                self._HELP_BARS.get(tab, "[b #08F9DF]:[/] commands   [b #08F9DF]q[/] quit"))
        except Exception:
            pass

    @on(TabbedContent.TabActivated)
    def _tab_changed(self, event):
        self.call_after_refresh(self._update_helpbar)

    # ── anomalies ───────────────────────────────────────────────────────

    def run_anomalies(self):
        head = self.query_one("#anom_head", Static)
        tbl = self.query_one("#anom", DataTable)
        tbl.clear()
        if not self.cur_file:
            head.update("[#FF4D00]no file selected[/] -- pick one in EXPLORER first")
            return
        try:
            fmt, chunks, warns = walk_file(self.cur_file, deep=False)
            findings = ac_anom.scan(self.cur_file, fmt, chunks, warns)
        except Exception as e:
            head.update(f"[#FF4D00]scan error[/]  {e.__class__.__name__}: {e}")
            return
        clean = "  [#08F9DF]clean[/]" if not findings else ""
        head.update(f"forensic scan: [b]{os.path.basename(self.cur_file)}[/]  "
                    f"{len(findings)} finding(s){clean}")
        for f in findings:
            sev = f["severity"]
            tbl.add_row(
                Text(sev.upper(), style=SEV_STYLE.get(sev, "")),
                f"0x{f['offset']:08x}", f["rule"], f["message"][:80])

    # ── metadata mode ────────────────────────────────────────────────────

    def _refresh_metadata(self):
        if not self.cur_file:
            return
        tbl = self.query_one("#meta_tags", DataTable)
        tbl.clear()
        for k, v in self._friendly_tags(self.cur_file):
            tbl.add_row(str(k), str(v)[:60])
        self._build_meta_tree()
        self.query_one("#meta_tech", Static).update(self._metadata_tech())

    def _friendly_tags(self, path):
        out = []
        try:
            rec = read_tags(path)
            if rec is not None:
                for k in ("title", "artist", "album", "genre", "date",
                          "track_number", "disc_number", "bpm", "key", "comment",
                          "copyright", "publisher", "encoder"):
                    v = rec.get(k)
                    if v not in (None, "", []):
                        out.append((k, v))
                return out
        except Exception:
            pass
        for c in self.cur_chunks:                       # WAV/AIFF: decoded strings
            if str(c.get("id", "")).strip() in ("LIST", "acid", "bext", "INFO"):
                for f in c.get("fields", []):
                    v = f.get("value")
                    if isinstance(v, str) and v and f.get("name"):
                        out.append((f["name"], v))
        return out

    _ENC_NAMES = {0: "latin-1", 1: "utf-16", 2: "utf-16-be", 3: "utf-8"}

    def _id3_flag_names(self, flags, major):
        if not flags or len(flags) < 2:
            return "none"
        s, f = flags[0], flags[1]
        n = []
        if major == 4:
            if s & 0x40: n.append("tag-alter-preserve")
            if s & 0x20: n.append("file-alter-preserve")
            if s & 0x10: n.append("read-only")
            if f & 0x40: n.append("grouped")
            if f & 0x08: n.append("compressed")
            if f & 0x04: n.append("encrypted")
            if f & 0x02: n.append("unsync")
            if f & 0x01: n.append("data-length")
        else:
            if s & 0x80: n.append("tag-alter-discard")
            if s & 0x40: n.append("file-alter-discard")
            if s & 0x20: n.append("read-only")
            if f & 0x80: n.append("compressed")
            if f & 0x40: n.append("encrypted")
            if f & 0x20: n.append("grouped")
        return ", ".join(n) or "none"

    def _build_meta_tree(self):
        tree = self.query_one("#meta_tree", Tree)
        tree.reset(Text(str(self.cur_fmt), style="bold #08F9DF"))
        tree.root.expand()
        for c in self.cur_chunks:
            cid = str(c.get("id", "?")).strip() or "?"
            summ = (c.get("summary") or "")[:44]
            node = tree.root.add(Text(f"{cid}  {c.get('size','?')} B  {summ}"),
                                 expand=False)
            if cid == "ID3v2" and self.cur_file:
                self._add_id3_nodes(node)
            else:
                for f in c.get("fields", []):
                    if f.get("name"):
                        node.add_leaf(Text(f"{f['name']} = {str(f.get('value'))[:46]}"))
        try:
            with open(self.cur_file, "rb") as fh:
                fh.seek(-128, 2)
                if fh.read(128)[:3] == b"TAG":
                    tree.root.add_leaf(Text("ID3v1 trailer  128 B  (present)"))
        except Exception:
            pass

    def _add_id3_nodes(self, node):
        frames = list_id3v2_frames(self.cur_file)
        tag = read_id3v2(self.cur_file)
        major = tag["major"] if tag else 3
        if tag:
            fl = tag.get("flags", 0)
            hdrbits = [nm for bit, nm in ((0x80, "unsync"), (0x40, "extended-header"),
                                          (0x20, "experimental"), (0x10, "footer"))
                       if fl & bit] or ["none"]
            node.add_leaf(Text(f"version = 2.{major}   header flags = {', '.join(hdrbits)}"))
        for fr in frames:
            preview = fr["text"] or ("embedded image" if fr["id"] in ("PIC", "APIC")
                                     else f"{fr['size']} bytes")
            fnode = node.add(Text(f"{fr['id']}  {fr['size']} B   {preview[:36]}"),
                             expand=False)
            fnode.add_leaf(Text(f"offset = 0x{fr['offset']:08x}"))
            fnode.add_leaf(Text(f"size = {fr['size']} bytes"))
            if fr["flags"]:
                fnode.add_leaf(Text(f"flags = 0x{fr['flags'].hex()} "
                                    f"({self._id3_flag_names(fr['flags'], major)})"))
            if fr["encoding"] is not None:
                fnode.add_leaf(Text(f"encoding = {self._ENC_NAMES.get(fr['encoding'], fr['encoding'])}"))
            if fr["text"]:
                fnode.add_leaf(Text(f"value = {fr['text'][:60]}"))

    def _metadata_tech(self):
        bits = []
        try:
            rec = read_tags(self.cur_file)
            if rec is not None:
                for k in ("duration", "bitrate", "sample_rate", "channels",
                          "bits_per_sample", "format_type", "encoder"):
                    v = rec.get(k)
                    if v not in (None, ""):
                        bits.append(f"{k}={v}")
        except Exception:
            pass
        return "  ".join(bits) or "(no technical summary for this format)"

    @on(DataTable.RowSelected, "#meta_tags")
    def _meta_tag_selected(self, event):
        tbl = self.query_one("#meta_tags", DataTable)
        try:
            key = str(tbl.get_row_at(event.cursor_row)[0])
        except Exception:
            return
        key = {"track_number": "tracknumber", "disc_number": "discnumber"}.get(key, key)
        self.push_screen(
            EditScreen(f"set {key}  (empty deletes)\n(Esc cancels):", ""),
            lambda val: self._meta_apply(key, val if val else None))

    # ── stego mode ────────────────────────────────────────────────────────

    def _stego_log(self, msg):
        try:
            self.query_one("#stego_log", RichLog).write(msg)
        except Exception:
            pass

    # recipes that embed a chosen payload (vs. synthesize a fresh file)
    _STEGO_NEEDS_PAYLOAD = {"wav+zip polyglot", "lsb embed", "junk cavity",
                            "flac app/padding", "mp4 mdat cavity", "id3 padding",
                            "midi sysex/tail"}
    # which analysis view best shows each embed
    _STEGO_VIEW = {"lsb embed": "ENTROPY", "midi sysex/tail": "STRUCTURE",
                   "dual-endian twin": "STRUCTURE"}

    @on(DataTable.RowSelected, "#stego_recipes")
    def _stego_selected(self, event):
        if not (0 <= event.cursor_row < len(self.STEGO_RECIPES)):
            return
        name = self.STEGO_RECIPES[event.cursor_row][0]
        if name in self._STEGO_NEEDS_PAYLOAD:
            if not self.cur_file and name != "midi sysex/tail":
                self._stego_log("[#FF4D00]no carrier -- open a file in EXPLORER first[/]")
                return
            self.push_screen(
                EditScreen("payload  --  a file path, or type text to embed:"
                           "\n(Esc cancels):", ""),
                lambda spec: self._stego_do(name, spec))
        else:
            self._stego_do(name, None)

    def _resolve_payload(self, spec):
        if os.path.isfile(spec):
            with open(spec, "rb") as f:
                return f.read()
        return spec.encode("utf-8", "replace")

    def _stego_do(self, name, spec):
        if spec == "":
            self._stego_log("cancelled")
            return
        payload = self._resolve_payload(spec) if spec is not None else None
        try:
            out = self._stego_build(name, payload)
        except Exception as e:
            self._stego_log(f"[#FF4D00]{name}: {e}[/]")
            return
        if not out:
            return
        self._snapshot()
        keep = (self.cur_chunk_idx, self._field_row())
        with open(self._work_path(), "wb") as f:
            f.write(out)
        self._forged = True
        self._forged_from = self._forged_from or self.cur_file
        self.load_file(self._work_path())
        self._restore_cursor(*keep)
        self._stego_log(f"[#08F9DF]{name}[/]  ->  {len(out):,} bytes, now {self.cur_fmt}")
        view = self._STEGO_VIEW.get(name, "ANOMALIES")
        self.query_one(TabbedContent).active = "explorer"
        self._set_view_mode(view)
        self._stego_log(f"showing {view} view -- see the embed in the analysis")

    def _stego_build(self, name, payload):
        ext = os.path.splitext(self.cur_file or "")[1].lower()
        synth = name in ("midi sysex/tail", "dual-endian twin", "ogg dual-bitstream")
        carrier = b""
        if self.cur_file and not synth:
            with open(self.cur_file, "rb") as f:
                carrier = f.read()

        def need(want, label):
            if ext not in (want if isinstance(want, tuple) else (want,)):
                raise ValueError(f"needs a {label} carrier (current: {ext or '?'})")

        if name == "wav+zip polyglot":
            need(".wav", "WAV")
            return polyglot.build_wav_zip(carrier, {"hidden.bin": payload})
        if name == "lsb embed":
            need(".wav", "PCM WAV")
            return stego.embed(carrier, payload)
        if name == "junk cavity":
            need(".wav", "WAV/RF64")
            return junk_cavity.embed(carrier, payload)
        if name == "flac app/padding":
            need(".flac", "FLAC")
            return flac_cavity.embed_app(carrier, payload)
        if name == "mp4 mdat cavity":
            need((".mp4", ".m4a"), "MP4/M4A")
            return mp4_cavity.embed(carrier, payload)
        if name == "id3 padding":
            need(".mp3", "MP3")
            return id3_cavity.embed(carrier, payload)
        if name == "midi sysex/tail":
            return midi_carrier.build_sysex(payload or b"acidcat")
        if name == "ogg dual-bitstream":
            import tempfile
            fd, tmp = tempfile.mkstemp(suffix=".ogg")
            os.close(fd)
            try:
                ogg_multiplex.build(tmp)
                with open(tmp, "rb") as f:
                    return f.read()
            finally:
                try:
                    os.unlink(tmp)
                except OSError:
                    pass
        if name == "dual-endian twin":
            import tempfile
            base = os.path.join(tempfile.gettempdir(), "acidcat_dual")
            wav_path, aiff_path, _pcm = dual_endian.build(base)
            with open(wav_path, "rb") as f:
                data = f.read()
            self._stego_log(f"dual-endian: also wrote the AIFF twin ({os.path.basename(aiff_path)})")
            for p in (wav_path, aiff_path):
                try:
                    os.unlink(p)
                except OSError:
                    pass
            return data
        return None

    # ── lab: interactive mangle (recipes + mutations) on the current file ─

    def _lab_log(self, msg):
        try:
            self.query_one("#lab_log", RichLog).write(msg)
        except Exception:
            pass

    @on(DataTable.RowSelected, "#lab_recipes")
    def _lab_recipe(self, event):
        if not self.cur_file:
            self._lab_log("[#FF4D00]no file loaded -- open one in EXPLORER first[/]")
            return
        names = list(forge_mod.RECIPES)
        if 0 <= event.cursor_row < len(names):
            name = names[event.cursor_row]
            self._lab_log(f"[#08F9DF]recipe[/]  {name}")
            self._apply_recipe(name)

    def _apply_recipe(self, name):
        """Apply a recipe; if it has knobs, open the slider editor first."""
        spec = forge_mod.RECIPE_PARAMS.get(name)
        if not spec:
            self._forge_apply(forge_mod.RECIPES[name], f"recipe {name}")
            return

        def _run(vals):
            if vals is None:
                self._status("recipe cancelled")
                return
            self._forge_apply(lambda fg: forge_mod.RECIPES[name](fg, vals),
                              f"recipe {name} {vals}")
        self.push_screen(ParamScreen(f"recipe: {name}", spec), _run)

    @on(DataTable.RowSelected, "#lab_muts")
    def _lab_mutation(self, event):
        if not self.cur_file:
            self._lab_log("[#FF4D00]no file loaded -- open one in EXPLORER first[/]")
            return
        names = sorted(mutations.ALL)
        if 0 <= event.cursor_row < len(names):
            self._apply_mutation(names[event.cursor_row])

    def _apply_mutation(self, name):
        cat, fn = mutations.ALL[name]
        spec = getattr(mutations, "MUTATION_PARAMS", {}).get(name)
        if spec:
            def _run(vals):
                if vals is None:
                    self._status("mutation cancelled")
                    return
                self._do_mutation(name, fn, cat, vals)
            self.push_screen(ParamScreen(f"mutation: {name}", spec), _run)
        else:
            self._do_mutation(name, fn, cat, None)

    def _do_mutation(self, name, fn, cat, params):
        def mut(fg):
            data = bytes(fg.data)
            out = (fn(data, random.Random(0xAC1D), params) if params
                   else fn(data, random.Random(0xAC1D)))
            if not out or out == data:
                raise ValueError("mutation did not change this file")
            fg.data = bytearray(out)
            fg._walk()

        self._lab_log(f"[#FF4D00]mutation[/]  {name} [{cat}]"
                      + (f"  {params}" if params else ""))
        self._forge_apply(mut, f"mutation {name}")

    # ── reports ─────────────────────────────────────────────────────────

    def _report_files(self):
        found = []
        found += sorted(glob.glob(os.path.join(HERE, "reports", "*.md")))
        for extra in ("CVE-IMMUNITY.md",):
            p = os.path.join(HERE, extra)
            if os.path.isfile(p):
                found.append(p)
        return found

    @on(DataTable.RowHighlighted, "#reports_tbl")
    def _report_picked(self, event: DataTable.RowHighlighted):
        key = event.row_key.value
        if not key:
            return
        body = self.query_one("#report_body", Markdown)
        try:
            with open(key, encoding="utf-8") as f:
                body.update(f.read())
        except OSError as e:
            body.update(f"# error\n\n{e}")

    # ── actions ─────────────────────────────────────────────────────────

    def action_tab(self, tab):
        self.query_one(TabbedContent).active = tab

    def action_run(self):
        active = self.query_one(TabbedContent).active
        if active == "fuzz":
            self._start_fuzz()
        elif (active == "explorer"
              and self.VIEW_MODES[self.mode_idx] == "ANOMALIES"):
            self.run_anomalies()

    # ── fuzz mode: external-target campaign with a live feed ──────────────

    def _refresh_fuzz_config(self):
        seed = (os.path.basename(self._forged_from or self.cur_file)
                if self.cur_file else "(no file loaded)")
        txt = ("Fuzz an external target with mangled copies of the current file.\n"
               f"  seed:    {seed}\n"
               f"  target:  {self._fuzz_target}\n"
               f"  runs:    {self._fuzz_iters}     timeout: {self._fuzz_timeout}s\n"
               "  r = run campaign      : palette for 'configure target' / 'set runs'")
        try:
            self.query_one("#fuzz_config", Static).update(txt)
        except Exception:
            pass

    def _start_fuzz(self):
        if self._fuzzing:
            self._status("a fuzz campaign is already running")
            return
        if not self.cur_file:
            self._status("no seed -- open a file in EXPLORER first")
            return
        self._fuzz_worker(self.cur_file, self._fuzz_target,
                          self._fuzz_iters, self._fuzz_timeout)

    @work(exclusive=True, thread=True)
    def _fuzz_worker(self, seed, target, iters, timeout):
        import tempfile
        import fuzz_target as ft
        self._fuzzing = True
        tbl = self.query_one("#fuzz_tbl", DataTable)
        summ_w = self.query_one("#fuzz_summary", Static)
        self.call_from_thread(tbl.clear)
        self.call_from_thread(summ_w.update, f"[#FF4D00]launching: {escape(target)}[/]")
        out = os.path.join(tempfile.gettempdir(), "acidcat_fuzz_crashes")
        counts = {}

        def on_result(i, name, verdict, rc):
            counts[verdict] = counts.get(verdict, 0) + 1
            if verdict in ("CRASH", "HANG"):
                rcs = f"0x{rc & 0xFFFFFFFF:08x}" if rc is not None else "-"
                self.call_from_thread(
                    tbl.add_row, str(i), name,
                    Text(verdict, style=f"bold {ORANGE}" if verdict == "CRASH" else AMBER),
                    rcs)
            if i % 10 == 0:
                s = "  ".join(f"{k}={counts.get(k, 0)}" for k in ("OK", "ERROR", "HANG", "CRASH"))
                self.call_from_thread(summ_w.update, f"[#FF4D00]run {i}/{iters}:[/]  {s}")

        try:
            tally = ft.fuzz_external(seed, target, iters, timeout, out, 0, on_result)
        except Exception as e:
            self.call_from_thread(summ_w.update, f"[#FF4D00]fuzz failed: {escape(str(e))}[/]")
            self._fuzzing = False
            return
        self._fuzzing = False
        if tally.get("NOTFOUND"):
            self.call_from_thread(summ_w.update,
                                  "[#FF4D00]target program not found -- check the command[/]")
            return
        crashes = tally.get("CRASH", 0) + tally.get("HANG", 0)
        s = "  ".join(f"{k}={tally.get(k, 0)}" for k in ("OK", "ERROR", "HANG", "CRASH"))
        tail = f"   {crashes} saved in {out}" if crashes else "   (target survived)"
        self.call_from_thread(summ_w.update, f"[#08F9DF]done:[/]  {s}{tail}")

    def action_fuzz_target(self):
        self.push_screen(
            EditScreen("fuzz target command ({file} = the mangled file):\n(Esc cancels):",
                       self._fuzz_target),
            self._set_fuzz_target)

    def _set_fuzz_target(self, v):
        if v:
            self._fuzz_target = v
            self._refresh_fuzz_config()
            self._status(f"fuzz target set: {v}")

    def action_fuzz_settings(self):
        spec = [{"name": "runs", "kind": "int", "min": 10, "max": 2000, "step": 10,
                 "value": self._fuzz_iters},
                {"name": "timeout", "kind": "float", "min": 1.0, "max": 30.0,
                 "step": 1.0, "value": self._fuzz_timeout}]

        def _apply(vals):
            if vals:
                self._fuzz_iters = int(vals["runs"])
                self._fuzz_timeout = float(vals["timeout"])
                self._refresh_fuzz_config()
                self._status(f"fuzz: {self._fuzz_iters} runs, {self._fuzz_timeout}s timeout")
        self.push_screen(ParamScreen("fuzz settings", spec), _apply)

    # ── visual modes (v cycles STRUCTURE / MAP / ENTROPY) ──

    def action_cycle_mode(self):
        self.query_one(TabbedContent).active = "explorer"
        self.mode_idx = (self.mode_idx + 1) % len(self.VIEW_MODES)
        self.apply_mode()

    def action_help(self):
        self.push_screen(HelpScreen())

    def action_screenshot(self):
        base = ("tui-" + os.path.splitext(os.path.basename(self.cur_file))[0]
                if self.cur_file else "tui")
        path = self.save_screenshot(f"{base}.svg")
        self.notify(f"screenshot -> {path}")

    def action_export_html(self):
        if not self.cur_file:
            self.notify("load a file first (EXPLORER tab)", severity="warning")
            return
        self.notify("building HTML explorer...")
        self._export_html_worker(self.cur_file)

    @work(thread=True)
    def _export_html_worker(self, src):
        out = os.path.splitext(src)[0] + ".html"
        r = subprocess.run(
            [sys.executable, "-m", "acidcat", "explore", src, "-o", out],
            capture_output=True)
        if r.returncode == 0:
            webbrowser.open("file://" + os.path.abspath(out))
            self.call_from_thread(
                self.notify, f"explorer -> {os.path.basename(out)} (opened)")
        else:
            msg = r.stderr.decode("utf-8", "replace")[:100] or "explore failed"
            self.call_from_thread(self.notify, msg, severity="error")

    def apply_mode(self):
        mode = self.VIEW_MODES[self.mode_idx]
        self.query_one("#mode_structure").display = mode == "STRUCTURE"
        self.query_one("#mode_map").display = mode == "MAP"
        self.query_one("#mode_entropy").display = mode == "ENTROPY"
        self.query_one("#mode_hilbert").display = mode == "HILBERT"
        self.query_one("#mode_anomalies").display = mode == "ANOMALIES"
        self._status(f"view {mode}  ([v] cycles)")
        self.refresh_mode()

    def refresh_mode(self):
        mode = self.VIEW_MODES[self.mode_idx]
        if mode == "MAP":
            self._render_map_pane()
        elif mode == "ENTROPY":
            self._render_entropy_pane()
        elif mode == "HILBERT":
            self._render_hilbert_pane()
        elif mode == "ANOMALIES":
            self.run_anomalies()

    def _view_width(self):
        return max(40, self.size.width - 40)

    def _render_map_pane(self):
        st = self.query_one("#map", Static)
        if not self.cur_file or not self.cur_chunks:
            st.update(Text("  load a file (EXPLORER) to map its regions\n", style="dim"))
            return
        size = os.path.getsize(self.cur_file)
        st.update(render_map(self.cur_chunks, size, self._view_width(),
                             self.cur_chunk_idx))

    def _render_entropy_pane(self):
        st = self.query_one("#entropy", Static)
        if not self.cur_file:
            st.update(Text("  load a file (EXPLORER) to see its entropy\n", style="dim"))
            return
        st.update(render_entropy(self.cur_file, self._view_width(),
                                 self._declared_end()))

    def _render_hilbert_pane(self):
        st = self.query_one("#hilbert", Static)
        if not self.cur_file:
            st.update(Text("  load a file (EXPLORER) to see its Hilbert byte-map\n",
                           style="dim"))
            return
        st.update(render_hilbert(self.cur_file, self._view_width()))

    def _declared_end(self):
        """The container's declared end offset from its size field, so ENTROPY can
        mark where trailing/appended data begins. None for headerless formats."""
        try:
            with open(self.cur_file, "rb") as f:
                head = f.read(8)
        except OSError:
            return None
        if len(head) >= 8 and head[:4] in (b"RIFF", b"RF64"):
            return 8 + struct.unpack_from("<I", head, 4)[0]
        if len(head) >= 8 and head[:4] == b"FORM":
            return 8 + struct.unpack_from(">I", head, 4)[0]
        return None


def _resolve_target(argv):
    """First CLI arg selects what the tree shows: a directory becomes the root, a
    file sets the root to its folder and auto-loads it. Default: the corpus."""
    if len(argv) > 1:
        p = os.path.abspath(os.path.expanduser(argv[1]))
        if os.path.isfile(p):
            return os.path.dirname(p) or ".", p
        if os.path.isdir(p):
            return p, None
        print(f"tui: {argv[1]}: no such file or directory; using corpus",
              file=sys.stderr)
    return CORPUS, None


if __name__ == "__main__":
    _root, _autoload = _resolve_target(sys.argv)
    PlaygroundApp(_root, _autoload).run()
