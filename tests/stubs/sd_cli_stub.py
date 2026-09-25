#!/usr/bin/env python3
"""Stub `sd-cli`: echo argv, print fake progress, write a tiny PNG to `-o`.

Env: STUB_ARGV_FILE (append argv as a JSON line), STUB_FAIL=1 (stderr + exit 2),
STUB_SLEEP=<seconds> (delay before doing work). Self-contained: copied alone to a
temp dir under the real binary name, so it must not import sibling modules.
"""

import json
import os
import sys
import time


def main(argv: list[str]) -> int:
    argv_file = os.environ.get("STUB_ARGV_FILE")
    if argv_file:
        with open(argv_file, "a") as fh:
            fh.write(json.dumps(argv) + "\n")

    delay = float(os.environ.get("STUB_SLEEP", "0") or 0)
    if delay > 0:
        time.sleep(delay)

    if os.environ.get("STUB_FAIL") == "1":
        print("sd-cli: stub failure requested (STUB_FAIL=1)", file=sys.stderr)
        return 2

    if "-o" not in argv or argv.index("-o") + 1 >= len(argv):
        print("sd-cli: missing -o <output path>", file=sys.stderr)
        return 1
    out = argv[argv.index("-o") + 1]

    for step in (1, 2, 3, 4):
        print(f"|{step}/4 - 1.00it/s", flush=True)

    from PIL import Image

    Image.new("RGB", (64, 64), (32, 96, 160)).save(out, format="PNG")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
