"""JSON-preset cavities: side-channels a JSON-based synth preset tolerates.

Vital (`.vital`) presets are bare JSON; Serum and many soft-synths ship JSON or
JSON-bearing formats. JSON has no comment syntax, but two of its properties open a
channel a conformant loader ignores:

  key   an extra top-level member the synth's schema does not name. A loader that
        reads only the keys it knows leaves it in place; the file stays valid JSON
        and a valid preset. Deterministic and formatting-preserving here.
  tail  bytes after the top-level object's closing brace. A parser that stops at
        the end of the top-level value never reads them; the file still loads.

Both survive a load/save round-trip only if the synth preserves unknown members;
the key channel usually does, the tail channel usually does not (a re-serialize
drops it). That asymmetry is the point of keeping them as separate modes.

acidcat detection rules this motivates:
  json_unknown_key: for JSON-based presets, enumerate top-level members and flag
    any not in the format's known key set as an unvalidated metadata side-channel.
    acidcat currently walks a Vital preset as a single `vital` chunk with no
    key-level validation, so an injected member passes silently.
  json_trailing_data: bytes after the top-level JSON value's closing brace are
    trailing data (the trailing_data rule, applied to JSON container formats).

  python json_cavity.py embed preset.vital secret.bin -o out.vital [--mode key|tail]
  python json_cavity.py extract out.vital -o secret.bin
  python json_cavity.py analyze out.vital
"""

import base64
import json
import os
import sys

REPO = os.environ.get("ACIDCAT_REPO") or os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "acidcat")
# acidcat: a sibling checkout by default, or set ACIDCAT_REPO, or pip install acidcat
sys.path.insert(0, os.path.join(REPO, "src"))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

KEY = "_acid_cavity"                 # the unknown member we inject
TAIL_MAGIC = b"\x00ACIDTAIL\x00"     # delimiter for the tail channel


def embed_key(text, payload):
    """Insert an extra top-level member before the closing brace, preserving layout."""
    json.loads(text)                                  # must be valid JSON to start
    b64 = base64.b64encode(payload).decode("ascii")
    end = text.rstrip().rfind("}")
    if end < 0:
        raise ValueError("not a JSON object")
    head, tail = text[:end], text[end:]
    sep = "" if head.rstrip().endswith("{") else ","   # empty object vs populated
    return f'{head.rstrip()}{sep}{json.dumps(KEY)}:{json.dumps(b64)}{tail}'


def embed_tail(text, payload):
    return text.encode() + TAIL_MAGIC + payload if isinstance(text, str) else text


def extract(data):
    """Recover the payload from either channel. Returns (mode, bytes) or (None, None)."""
    if TAIL_MAGIC in data:
        return "tail", data.split(TAIL_MAGIC, 1)[1]
    try:
        obj = json.loads(data.decode("utf-8", "replace"))
        if isinstance(obj, dict) and KEY in obj:
            return "key", base64.b64decode(obj[KEY])
    except (json.JSONDecodeError, ValueError):
        pass
    return None, None


def analyze(path):
    from acidcat.core.walk import walk_file
    data = open(path, "rb").read()
    try:
        fmt, chunks, warns = walk_file(path, deep=False)
        cw = [f"{c['id']}:{w}" for c in chunks for w in c.get("warnings", [])]
        acid = (f"{fmt}  chunks={[c['id'] for c in chunks]}  "
                f"file_warnings={warns or 'none'}  chunk_warnings={cw or 'none'}")
    except Exception as e:                       # Unsupported on trailing bytes = a finding
        acid = f"{e.__class__.__name__}: {e}"
    valid_json = True
    try:
        json.loads(data.decode("utf-8", "replace"))
    except json.JSONDecodeError as e:
        valid_json = f"no ({e.msg} at pos {e.pos})"
    mode, payload = extract(data)
    print(f"{path} ({len(data):,} bytes)")
    print(f"  acidcat: {acid}")
    print(f"  parses as strict JSON: {valid_json}")
    print(f"  cavity: {mode or 'none'}" + (f", {len(payload):,}-byte payload recovered" if payload else ""))
    return mode is not None


if __name__ == "__main__":
    a = sys.argv[1:]
    mode = a[a.index("--mode") + 1] if "--mode" in a else "key"
    if len(a) >= 4 and a[0] == "embed" and "-o" in a:
        out = a[a.index("-o") + 1]
        text = open(a[1], "r", encoding="utf-8").read()
        payload = open(a[2], "rb").read()
        blob = embed_key(text, payload).encode() if mode == "key" else embed_tail(text, payload)
        open(out, "wb").write(blob)
        analyze(out)
    elif len(a) >= 2 and a[0] == "extract":
        out = a[a.index("-o") + 1] if "-o" in a else "recovered.bin"
        m, payload = extract(open(a[1], "rb").read())
        if payload is None:
            sys.exit("no cavity found")
        open(out, "wb").write(payload)
        print(f"wrote {out} ({len(payload):,} bytes, {m} channel)")
    elif len(a) == 2 and a[0] == "analyze":
        analyze(a[1])
    else:
        print(__doc__)
