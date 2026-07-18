"""acidcat playground: mangle files + fuzz the parsers.

  python mangle.py list                       # show mutations by category
  python mangle.py fuzz [--category riff]      # every input x mutation -> assert no crash
  python mangle.py fuzz --report report.md     # + write a markdown coverage report
  python mangle.py one <file> <mutation>       # write one corrupted specimen to mangled/

acidcat is supposed to raise a clean Unsupported or emit lint warnings on hostile
input, never crash (uncaught traceback) or hang. This proves that on a real corpus
crossed with adversarial-but-structured mutations. Any CRASH row is a hardening
bug in acidcat.
"""

import os
import sys
import glob
import random
import tempfile
import traceback

REPO = os.environ.get("ACIDCAT_REPO") or os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "acidcat")
# acidcat: a sibling checkout by default, or set ACIDCAT_REPO, or pip install acidcat
sys.path.insert(0, os.path.join(REPO, "src"))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import mutations  # noqa: E402
from acidcat.commands import inspect as I  # noqa: E402
from acidcat.core.walk import walk_file, Unsupported  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
CORPUS = os.environ.get("ACIDCAT_CORPUS") or os.path.join(HERE, "specimens")
MANGLED = os.path.join(HERE, "mangled")


def _walk_ok(data, suffix):
    """Run acidcat's walker on bytes. -> ('clean'|'CRASH', detail)."""
    fd, tmp = tempfile.mkstemp(suffix=suffix)
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(data)
        try:
            walk_file(tmp, deep=True)   # deep = the widest code path
            return "clean", ""
        except Unsupported:
            return "clean", ""
        except Exception:
            return "CRASH", traceback.format_exc().strip().splitlines()[-1]
    finally:
        try:
            os.unlink(tmp)
        except OSError:
            pass


def _corpus_files():
    return [f for f in glob.glob(os.path.join(CORPUS, "**", "*"), recursive=True)
            if os.path.isfile(f) and os.path.getsize(f) < 40 * 1024 * 1024]


def fuzz(category=None, report=None):
    files = _corpus_files()
    muts = {n: (c, fn) for n, (c, fn) in mutations.ALL.items()
            if category is None or c == category}
    total = applied = crashes = 0
    by_cat = {}
    seen = []
    for path in files:
        suffix = os.path.splitext(path)[1] or ".bin"
        with open(path, "rb") as fh:
            data = fh.read()
        for name, (cat, fn) in muts.items():
            r = random.Random(hash((path, name)) & 0xFFFFFFFF)
            try:
                mangled = fn(data, r)
            except Exception:
                mangled = None
            total += 1
            if mangled is None or mangled == data:
                continue                       # not applicable to this file
            applied += 1
            status, detail = _walk_ok(mangled, suffix)
            slot = by_cat.setdefault(cat, [0, 0])
            slot[0] += 1
            if status == "CRASH":
                slot[1] += 1
                crashes += 1
                seen.append((os.path.basename(path), name, cat, detail))
    print(f"corpus files: {len(files)}   mutations: {len(muts)}   "
          f"applicable runs: {applied}   CRASHES: {crashes}")
    for cat in sorted(by_cat):
        ran, cr = by_cat[cat]
        print(f"  {cat:10} {ran:5} runs   {cr} crash")
    for f, m, c, d in seen[:60]:
        print(f"  CRASH  [{c}/{m}]  {f}  {d}")
    if report:
        _write_report(report, files, muts, applied, crashes, by_cat, seen)
        print(f"wrote {report}")
    return crashes


def _write_report(path, files, muts, applied, crashes, by_cat, seen):
    lines = ["# acidcat fuzz report", "",
             f"- corpus files: {len(files)}",
             f"- mutations: {len(muts)}",
             f"- applicable runs: {applied}",
             f"- **crashes: {crashes}**", "", "## by category", "",
             "| category | runs | crashes |", "|---|---|---|"]
    for cat in sorted(by_cat):
        ran, cr = by_cat[cat]
        lines.append(f"| {cat} | {ran} | {cr} |")
    if seen:
        lines += ["", "## crashes", "", "| category | mutation | file | error |",
                  "|---|---|---|---|"]
        for f, m, c, d in seen:
            lines.append(f"| {c} | {m} | {f} | {d} |")
    else:
        lines += ["", "No crashes: every applicable mutation over the corpus "
                  "degraded to a clean parse or warning."]
    open(path, "w", encoding="utf-8", newline="\n").write("\n".join(lines) + "\n")


def one(path, mutation):
    if mutation not in mutations.ALL:
        sys.exit(f"unknown mutation {mutation!r}; run: python mangle.py list")
    cat, fn = mutations.ALL[mutation]
    with open(path, "rb") as f:
        data = f.read()
    out_bytes = fn(data, random.Random(1234))
    if out_bytes is None:
        sys.exit(f"{mutation} does not apply to {os.path.basename(path)}")
    os.makedirs(MANGLED, exist_ok=True)
    base = os.path.basename(path)
    out = os.path.join(MANGLED, f"{base}.{mutation}{os.path.splitext(path)[1]}")
    with open(out, "wb") as f:
        f.write(out_bytes)
    print(f"wrote {out} ({len(out_bytes)} bytes)")


def _list():
    for cat, fns in mutations.REGISTRY.items():
        print(f"\n{cat}:")
        for fn in fns:
            doc = (fn.__doc__ or "").strip().split("\n")[0]
            print(f"  {fn.__name__:34} {doc}")


if __name__ == "__main__":
    a = sys.argv[1:]
    if a and a[0] == "list":
        _list()
    elif a and a[0] == "fuzz":
        cat = None
        report = None
        if "--category" in a:
            cat = a[a.index("--category") + 1]
        if "--report" in a:
            report = a[a.index("--report") + 1]
        sys.exit(1 if fuzz(cat, report) else 0)
    elif len(a) == 3 and a[0] == "one":
        one(a[1], a[2])
    else:
        print(__doc__)
