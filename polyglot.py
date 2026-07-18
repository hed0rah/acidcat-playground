"""Build polyglots: single files that are simultaneously valid as two formats.

WAV+ZIP is the cleanest: a RIFF/WAVE reader reads only up to the RIFF size and
ignores trailing bytes, while a ZIP reader scans from the END for the central
directory and tolerates arbitrary prepended data (the self-extracting-archive
trick). So `wav_bytes + zip_bytes` opens as audio in a DAW and as an archive in
unzip, from the exact same bytes.

This is the same shape as Bitwig's embed (a preset with a zip of assets after the
meta), turned into a true dual-format file. Also a robustness probe: acidcat must
read the WAV cleanly and treat the trailing zip as trailing bytes, not choke.

  python polyglot.py wav-zip <wav> <file-to-embed> [more...] -o out.wav
  python polyglot.py verify <polyglot>
"""

import io
import os
import sys
import zipfile
import tempfile

REPO = os.environ.get("ACIDCAT_REPO") or os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "acidcat")
# acidcat: a sibling checkout by default, or set ACIDCAT_REPO, or pip install acidcat
sys.path.insert(0, os.path.join(REPO, "src"))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from acidcat.commands import inspect as I  # noqa: E402
from acidcat.core.walk import walk_file, Unsupported  # noqa: E402


def build_wav_zip(wav_bytes, payload):
    """payload: {archive_name: bytes}. Returns the polyglot bytes."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for name, data in payload.items():
            z.writestr(name, data)
    return wav_bytes + buf.getvalue()


def verify(polyglot):
    """Confirm the same bytes parse as BOTH a WAV (acidcat) and a ZIP."""
    ok_wav = ok_zip = False
    wav_detail = zip_detail = ""
    fd, tmp = tempfile.mkstemp(suffix=".wav")
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(polyglot)
        try:
            fmt, chunks, _ = walk_file(tmp, deep=False)
            ok_wav = True
            ids = ",".join(c["id"].strip() for c in chunks[:6])
            wav_detail = f"{fmt}: {ids}"
        except Exception as e:
            wav_detail = f"{e.__class__.__name__}: {e}"
    finally:
        try:
            os.unlink(tmp)
        except OSError:
            pass
    try:
        zf = zipfile.ZipFile(io.BytesIO(polyglot))
        bad = zf.testzip()
        ok_zip = bad is None
        zip_detail = ("entries: " + ", ".join(zf.namelist())) if ok_zip \
            else f"corrupt entry: {bad}"
    except Exception as e:
        zip_detail = f"{e.__class__.__name__}: {e}"
    return ok_wav, wav_detail, ok_zip, zip_detail


def _report(polyglot, label=""):
    ok_wav, wd, ok_zip, zd = verify(polyglot)
    print(f"polyglot {label}({len(polyglot):,} bytes)")
    print(f"  as WAV  {'OK ' if ok_wav else 'FAIL'}  {wd}")
    print(f"  as ZIP  {'OK ' if ok_zip else 'FAIL'}  {zd}")
    return ok_wav and ok_zip


if __name__ == "__main__":
    a = sys.argv[1:]
    if a and a[0] == "wav-zip" and "-o" in a:
        out = a[a.index("-o") + 1]
        wav = a[1]
        embed = a[2:a.index("-o")]
        wav_bytes = open(wav, "rb").read()
        payload = {os.path.basename(p): open(p, "rb").read() for p in embed}
        poly = build_wav_zip(wav_bytes, payload)
        open(out, "wb").write(poly)
        _report(poly, out + " ")
    elif len(a) == 2 and a[0] == "verify":
        _report(open(a[1], "rb").read(), a[1] + " ")
    else:
        print(__doc__)
