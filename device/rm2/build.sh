#!/bin/sh
# Builds unremarkable/bin/tabloid-show-rm2-armv7, the reMarkable 2 display program.
#
# Run on Linux (or WSL) with an ARM cross compiler that supports C++20:
#   sudo apt install g++-arm-linux-gnueabihf git curl
#   sh device/rm2/build.sh
#
# It fetches two pinned third-party sources, checks them, and compiles them
# together with main.cpp into one static binary:
#   - swtcon, the software display driver from timower/rM2-stuff (GPL-3.0)
#   - stb_image.h, the PNG/JPEG decoder from nothings/stb (public domain / MIT)
set -eu

RM2_STUFF_REPO=https://github.com/timower/rM2-stuff
RM2_STUFF_COMMIT=451577081b9eaa3d582e50bbca8c4adfd4911b53
STB_COMMIT=1da9ade1e66195252114f5da497f244704a6c58d
STB_SHA256=dfc2aadda6295f67f677587773f25e5bf8c8ad427ed0db7c518525c91e72e020

HERE=$(cd "$(dirname "$0")" && pwd)
OUT="$HERE/../../unremarkable/bin/tabloid-show-rm2-armv7"
BUILD=${BUILD_DIR:-"$HERE/build"}
CXX=${CXX:-arm-linux-gnueabihf-g++}
STRIP=${STRIP:-arm-linux-gnueabihf-strip}

mkdir -p "$BUILD"
if [ ! -d "$BUILD/rM2-stuff/.git" ]; then
  git clone -q "$RM2_STUFF_REPO" "$BUILD/rM2-stuff"
fi
git -C "$BUILD/rM2-stuff" fetch -q origin "$RM2_STUFF_COMMIT" 2>/dev/null || true
git -C "$BUILD/rM2-stuff" checkout -q "$RM2_STUFF_COMMIT"

if [ ! -f "$BUILD/stb_image.h" ]; then
  curl -fsSL -o "$BUILD/stb_image.h" \
    "https://raw.githubusercontent.com/nothings/stb/$STB_COMMIT/stb_image.h"
fi
echo "$STB_SHA256  $BUILD/stb_image.h" | sha256sum -c - >/dev/null

SW="$BUILD/rM2-stuff/libs/swtcon"
# Target flags from rM2-stuff's own cmake/rm-toolchain.cmake (Cortex-A7, NEON).
FLAGS="-std=c++20 -mfpu=neon -mfloat-abi=hard -mcpu=cortex-a7 -D_TIME_BITS=64 -D_FILE_OFFSET_BITS=64"
FLAGS="$FLAGS -DSWTCON_KERNEL_MODE=3 -I$SW -I$SW/include -I$BUILD"

OBJ="$BUILD/obj"
rm -rf "$OBJ" && mkdir -p "$OBJ"
for f in swtcon init wbf update display; do
  $CXX $FLAGS -O2 -w -c "$SW/$f.cpp" -o "$OBJ/$f.o"
done
# The per-pixel waveform loop is the hot path: rM2-stuff builds it with -O3 too.
$CXX $FLAGS -O3 -w -c "$SW/playback_kernel_intrinsics.cpp" -o "$OBJ/playback_kernel.o"
$CXX $FLAGS -O2 -Wall -Wno-unused-function -c "$HERE/main.cpp" -o "$OBJ/main.o"

# Static, so it does not depend on the C library version of a given firmware.
$CXX -static "$OBJ"/*.o -o "$OUT" -lpthread 2>"$BUILD/link.log" || { cat "$BUILD/link.log"; exit 1; }
$STRIP "$OUT"

echo "built $OUT"
ls -l "$OUT"
sha256sum "$OUT"
