#!/bin/sh
# Build the decode_type1033 harness against an unmodified RTKLIB checkout.
#
#   RTKLIB=/path/to/RTKLIB ./build.sh            # plain build
#   RTKLIB=/path/to/RTKLIB ASAN=1 ./build.sh     # +AddressSanitizer
#
# The checkout should be on the rtklib_2.4.3 branch (b34 is what these
# findings were measured against).
set -e

RTKLIB="${RTKLIB:-../rtklib}"
SRC="$RTKLIB/src"

if [ ! -f "$SRC/rtklib.h" ]; then
    echo "error: no rtklib.h under $SRC" >&2
    echo "set RTKLIB to your RTKLIB checkout, e.g. RTKLIB=~/src/RTKLIB ./build.sh" >&2
    exit 1
fi

CFLAGS="-I$SRC -DTRACE -Wno-unused-result -g -O0"
[ -n "$ASAN" ] && CFLAGS="$CFLAGS -fsanitize=address -fno-omit-frame-pointer"

# rtkcmn.c supplies getbitu/crc24q/ecef2pos/enu2ecef; rtcm.c the input_rtcm3
# entry point; rtcm2/rtcm3/rtcm3e the decoders it dispatches to.
gcc $CFLAGS -o harness harness.c \
    "$SRC/rtcm.c" "$SRC/rtcm2.c" "$SRC/rtcm3.c" "$SRC/rtcm3e.c" \
    "$SRC/rtkcmn.c" \
    -lm -lpthread

echo "built ./harness"
