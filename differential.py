"""Differential correctness oracle: acidcat's own parsers vs mutagen.

For every audio file in the corpus, compare the exact integer facts both tools
report, sample_rate, channels, bits_per_sample. acidcat decodes these from its
own byte-level parsers (RIFF fmt, FLAC STREAMINFO, AIFF COMM, MP4 stsd, ...);
mutagen is an independent reference. A mismatch is a confidently-wrong-output
bug in acidcat (or a genuine reference disagreement worth understanding), the
class of bug that fuzzing (which only looks for crashes) never catches.

  python differential.py [--report reports/diff.md]
"""

import os
import sys
import glob
import json
import subprocess

REPO = os.environ.get("ACIDCAT_REPO") or os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "acidcat")
# acidcat: a sibling checkout by default, or set ACIDCAT_REPO, or pip install acidcat
sys.path.insert(0, os.path.join(REPO, "src"))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

HERE = os.path.dirname(os.path.abspath(__file__))
CORPUS = os.environ.get("ACIDCAT_CORPUS") or os.path.join(HERE, "specimens")
_ENV = {**os.environ, "PYTHONPATH": os.path.join(REPO, "src")}
FIELDS = ("sample_rate", "channels", "bits_per_sample")
AUDIO = (".wav", ".aif", ".aiff", ".flac", ".mp3", ".ogg", ".m4a")


def _acidcat(path):
    r = subprocess.run([sys.executable, "-m", "acidcat", "inspect", "--full", path],
                       capture_output=True, env=_ENV)
    if r.returncode != 0:
        return None
    try:
        rec = json.loads(r.stdout.decode("utf-8", "replace"))
    except Exception:
        return None
    out = {}
    for c in rec.get("chunks", []):
        for fl in c.get("fields", []):
            n = fl.get("name")
            if n in FIELDS and n not in out:
                try:
                    out[n] = int(str(fl.get("value")).split()[0].replace(",", ""))
                except (ValueError, IndexError):
                    pass
    return out


def _mutagen(path):
    import mutagen
    m = mutagen.File(path)
    if not m or not getattr(m, "info", None):
        return None
    info = m.info
    return {k: v for k, v in (
        ("sample_rate", getattr(info, "sample_rate", None)),
        ("channels", getattr(info, "channels", None)),
        ("bits_per_sample", getattr(info, "bits_per_sample", None)),
    ) if v}


def main(report=None):
    files = [f for f in glob.glob(os.path.join(CORPUS, "**", "*"), recursive=True)
             if os.path.isfile(f) and os.path.splitext(f)[1].lower() in AUDIO
             and os.path.getsize(f) < 60 * 1024 * 1024]
    checked = agree = 0
    diffs = []
    for path in files:
        ac = _acidcat(path)
        mu = _mutagen(path)
        if not ac or not mu:
            continue
        checked += 1
        shared = set(ac) & set(mu)
        mism = {k: (ac[k], mu[k]) for k in shared if ac[k] != mu[k]}
        if mism:
            diffs.append((os.path.basename(path), mism))
        else:
            agree += 1
    print(f"compared {checked} files (fields: {', '.join(FIELDS)})")
    print(f"  agree: {agree}   disagree: {len(diffs)}")
    for name, mism in diffs[:60]:
        for k, (a, m) in mism.items():
            print(f"  DIFF  {name}  {k}: acidcat={a} mutagen={m}")
    if report:
        lines = ["# acidcat vs mutagen differential", "",
                 f"- files compared: {checked}",
                 f"- agree: {agree}", f"- **disagree: {len(diffs)}**", ""]
        if diffs:
            lines += ["| file | field | acidcat | mutagen |", "|---|---|---|---|"]
            for name, mism in diffs:
                for k, (a, m) in mism.items():
                    lines.append(f"| {name} | {k} | {a} | {m} |")
        else:
            lines.append("Every shared field matched the reference.")
        open(report, "w", encoding="utf-8", newline="\n").write("\n".join(lines) + "\n")
        print(f"wrote {report}")
    return len(diffs)


if __name__ == "__main__":
    rep = sys.argv[sys.argv.index("--report") + 1] if "--report" in sys.argv else None
    main(rep)
