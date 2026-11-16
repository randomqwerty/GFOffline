"""Entry point of the built release. The release has the same folders as the source, next to the two programs, which only supply Python:

  GF Offline.exe            the launcher, with no console window
  gfpython.exe <script>     runs a script like python.exe would; the launcher starts everything through it
"""
import runpy
import sys
from pathlib import Path

ROOT = Path(sys.executable).resolve().parent


def run(script, args):
    script = Path(script).resolve()
    sys.argv = [str(script), *args]
    sys.path.insert(0, str(script.parent))
    runpy.run_path(str(script), run_name="__main__")


def main():
    # the frozen program ignores PYTHONUNBUFFERED, so through the launcher's pipe a tool's progress would only show when it ends
    for stream in (sys.stdout, sys.stderr):
        if stream is not None:
            stream.reconfigure(line_buffering=True, encoding="utf-8", errors="replace")
    if Path(sys.executable).stem.lower() != "gfpython":
        run(ROOT / "launcher.pyw", [])
    elif len(sys.argv) < 2:
        sys.exit("usage: gfpython <script> [arguments]")
    else:
        run(sys.argv[1], sys.argv[2:])


if __name__ == "__main__":
    main()
