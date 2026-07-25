#!/bin/sh
# Regenerate the three RTCM3 streams and run each through the harness.
#   RTKLIB=/path/to/RTKLIB ./run.sh          # plain
#   RTKLIB=/path/to/RTKLIB ASAN=1 ./run.sh   # +AddressSanitizer
set -e

PY="${PY:-python3}"
"$PY" gen_rtcm.py benign.bin --benign
"$PY" gen_rtcm.py attack.bin --field rectype
"$PY" gen_rtcm.py oob.bin    --field recsno

./build.sh

for f in benign attack oob; do
    echo
    echo "======== $f.bin ========"
    ./harness "$f.bin" 2>&1 | grep -E 'sta\.pos|dgps =|adopted|ERROR|SUMMARY|norm\(rb\)' || true
done
