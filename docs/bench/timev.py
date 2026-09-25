#!/usr/bin/env python3
"""Stand-in for `/usr/bin/time -v` (GNU time is not installed on the XPS).

Runs a command, then prints wall time and peak RSS of the child tree in the
same "Maximum resident set size (kbytes)" form so bench numbers are comparable.
"""

import resource
import subprocess
import sys
import time

start = time.monotonic()
code = subprocess.call(sys.argv[1:])
wall = time.monotonic() - start
peak_kb = resource.getrusage(resource.RUSAGE_CHILDREN).ru_maxrss
print(f"\tElapsed (wall clock) time (seconds): {wall:.2f}", file=sys.stderr)
print(f"\tMaximum resident set size (kbytes): {peak_kb}", file=sys.stderr)
print(f"\tExit status: {code}", file=sys.stderr)
sys.exit(code)
