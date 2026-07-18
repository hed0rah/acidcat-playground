"""fuzz_target.py -- feed mangled files to an external program and catch crashes.

Black-box fuzzing of third-party software: take a seed file, apply the
playground's mutation catalog, run a target command on each mangled variant, and
classify the result. Crashing/hanging inputs are saved for triage. Point it at
anything that opens the file type: a player, ffmpeg/ffprobe, a decoder, a
converter, a DAW's CLI.

  python fuzz_target.py seed.wav --target "ffprobe -v error {file}"
  python fuzz_target.py seed.mp3 --target "ffmpeg -v error -i {file} -f null -" -n 300
  python fuzz_target.py seed.mid --target "timidity {file}" --timeout 5 --out crashes/

{file} in the target command is replaced with each mangled file path; without it,
the path is appended. Verdicts:
  OK     exit 0
  ERROR  graceful non-zero exit (the program rejected the input cleanly)
  HANG   exceeded --timeout (possible infinite loop / resource exhaustion)
  CRASH  killed by a signal (POSIX) or a fatal exception (Windows NTSTATUS)
Only HANG and CRASH are saved: they are the interesting bugs.
"""

import os
import random
import shlex
import subprocess
import sys

REPO = os.environ.get("ACIDCAT_REPO") or os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "acidcat")
sys.path.insert(0, os.path.join(REPO, "src"))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import mutations  # noqa: E402


def classify(returncode, timed_out):
    if timed_out:
        return "HANG"
    if returncode == 0:
        return "OK"
    if returncode < 0 or (returncode & 0xFFFFFFFF) >= 0xC0000000:
        return "CRASH"                    # POSIX signal, or Windows fatal exception
    return "ERROR"                        # graceful non-zero exit


def run_target(cmd_tmpl, path, timeout):
    if "{file}" in cmd_tmpl:
        parts = [p.replace("{file}", path) for p in shlex.split(cmd_tmpl)]
    else:
        parts = shlex.split(cmd_tmpl) + [path]
    try:
        r = subprocess.run(parts, capture_output=True, timeout=timeout)
        return classify(r.returncode, False), r.returncode
    except subprocess.TimeoutExpired:
        return "HANG", None
    except FileNotFoundError:
        return "NOTFOUND", None


def fuzz_external(seed_path, target, iterations=200, timeout=10, out_dir="fuzz_crashes",
                 base_seed=0, on_result=None):
    """Run the fuzz loop. Returns a tally dict. on_result(i, name, verdict, rc) is
    called per run (for a UI); crashing/hanging inputs are written to out_dir."""
    with open(seed_path, "rb") as f:
        seed = f.read()
    suffix = os.path.splitext(seed_path)[1] or ".bin"
    names = list(mutations.ALL)
    tally = {}
    for i in range(iterations):
        rng = random.Random(base_seed + i)
        name = rng.choice(names)
        cat, fn = mutations.ALL[name]
        try:
            mangled = fn(seed, rng)
        except Exception:
            mangled = None
        if not mangled or mangled == seed:
            continue
        import tempfile
        fd, tmp = tempfile.mkstemp(suffix=suffix)
        os.write(fd, mangled)
        os.close(fd)
        try:
            verdict, rc = run_target(target, tmp, timeout)
        finally:
            keep = verdict in ("CRASH", "HANG")
            if keep:
                os.makedirs(out_dir, exist_ok=True)
                dst = os.path.join(out_dir, f"{i:05d}_{name}_{verdict}{suffix}")
                os.replace(tmp, dst)
            else:
                try:
                    os.unlink(tmp)
                except OSError:
                    pass
        tally[verdict] = tally.get(verdict, 0) + 1
        if verdict == "NOTFOUND":
            tally["NOTFOUND"] = 1
            return tally
        if on_result:
            on_result(i, name, verdict, rc)
    return tally


def _main(argv):
    if not argv or "--target" not in argv:
        print(__doc__)
        return 0 if not argv else 1
    seed = argv[0]
    o = {argv[i].lstrip("-"): argv[i + 1] for i in range(len(argv) - 1)
         if argv[i].startswith("--") or argv[i] in ("-n",)}
    target = o.get("target")
    iterations = int(o.get("n") or o.get("iterations") or 200)
    timeout = float(o.get("timeout") or 10)
    out_dir = o.get("out") or "fuzz_crashes"
    base_seed = int(o.get("seed") or 0)

    def report(i, name, verdict, rc):
        if verdict in ("CRASH", "HANG"):
            rcs = f" rc=0x{rc & 0xFFFFFFFF:08x}" if rc is not None else ""
            print(f"  [{verdict}] run {i} via {name}{rcs}  -> saved to {out_dir}/")

    print(f"fuzzing {os.path.basename(seed)} -> target: {target!r}  "
          f"({iterations} runs, {timeout}s timeout)")
    tally = fuzz_external(seed, target, iterations, timeout, out_dir, base_seed, report)
    if tally.get("NOTFOUND"):
        print("  target program not found (check the command)")
        return 2
    order = ["OK", "ERROR", "HANG", "CRASH"]
    summary = "  ".join(f"{k}={tally.get(k, 0)}" for k in order)
    crashes = tally.get("CRASH", 0) + tally.get("HANG", 0)
    print(f"done: {summary}")
    print(f"  {crashes} interesting input(s)"
          + (f" saved in {out_dir}/" if crashes else "; target survived"))
    return 0


if __name__ == "__main__":
    sys.exit(_main(sys.argv[1:]))
