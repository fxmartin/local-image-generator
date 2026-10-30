#!/usr/bin/env python3
"""Stub `gemma`: record argv and stdin, reply with a fixture.

Env: STUB_ARGV_FILE (append argv as a JSON line), STUB_STDIN_FILE (write stdin),
STUB_GEMMA_REPLY (reply text, default a padded fixture), STUB_FAIL=1 (30 stderr lines +
exit 2), STUB_SLEEP=<seconds> (delay before replying), STUB_FAIL_HTTP=<code> + STUB_FAIL_TIMES=<n>
(the first n calls, counted in STUB_ARGV_FILE, fail like the gateway CLI: "(HTTP <code>)" + exit 1),
STUB_ENV_FILE (write the LARM_API_KEY the stub was given, or "<unset>").
Self-contained: copied alone to a temp dir under the real binary name.
"""

import json
import os
import sys
import time


def main(argv: list[str]) -> int:
    stdin = sys.stdin.read()
    argv_file = os.environ.get("STUB_ARGV_FILE")
    if argv_file:
        with open(argv_file, "a") as fh:
            fh.write(json.dumps(argv) + "\n")
    stdin_file = os.environ.get("STUB_STDIN_FILE")
    if stdin_file:
        with open(stdin_file, "w") as fh:
            fh.write(stdin)

    env_file = os.environ.get("STUB_ENV_FILE")
    if env_file:
        with open(env_file, "w") as fh:
            fh.write(os.environ.get("LARM_API_KEY", "<unset>"))

    fail_http = os.environ.get("STUB_FAIL_HTTP")
    if fail_http and argv_file:
        with open(argv_file) as fh:
            calls = len(fh.read().splitlines())
        if calls <= int(os.environ.get("STUB_FAIL_TIMES", "1")):
            print(f"gemma: gateway error (HTTP {fail_http}): model busy", file=sys.stderr)
            return 1

    delay = float(os.environ.get("STUB_SLEEP", "0") or 0)
    if delay > 0:
        time.sleep(delay)

    if os.environ.get("STUB_FAIL") == "1":
        for i in range(30):
            print(f"gemma: stub failure line {i}", file=sys.stderr)
        return 2

    reply = os.environ.get("STUB_GEMMA_REPLY", '{"shots": []}')
    print(f"\n  {reply}\n")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
