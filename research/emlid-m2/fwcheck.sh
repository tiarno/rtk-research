#!/usr/bin/env bash
# fwcheck.sh <zip-url> : download an Emlid image, find every ELF that carries
# the RTCM3 1033 decoder, and report whether its five antenna/receiver copies
# go through __strncpy_chk (abort) or plain strncpy (silent corruption).
# No root: fdisk/dd/debugfs on the file. Deletes the image afterwards.
# Work dir: $RTK_BISECT (default ~/.cache/rtk-bisect), needs armtools/ there.
set -uo pipefail
URL="$1"
S=${RTK_BISECT:-$HOME/.cache/rtk-bisect}
V=$(basename "$URL" .zip)
W=$S/work/$V
mkdir -p "$W" && cd "$W" || exit 1

[ -s fw.zip ] || curl -sSfLo fw.zip "$URL" || { echo "$V DOWNLOAD-FAIL"; rm -rf "$W"; exit 1; }
IMGNAME=$(unzip -Z1 fw.zip | grep -E '\.img$' | head -1)
[ -n "$IMGNAME" ] || { echo "$V NO-IMG in zip: $(unzip -Z1 fw.zip | head -3 | tr '\n' ' ')"; exit 1; }
BUILD=$(unzip -l fw.zip "$IMGNAME" | awk 'NR==4{print $2}')
unzip -p fw.zip "$IMGNAME" > fw.img

# largest Linux (83) partition
read -r ST SEC < <(fdisk -l -u=sectors fw.img 2>/dev/null \
  | awk '$1 ~ /fw\.img[0-9]/ { off=($2=="*")?1:0; if ($(6+off)=="83") print $(2+off), $(4+off) }' \
  | sort -k2 -n | tail -1)
[ -n "${ST:-}" ] || { echo "$V NO-LINUX-PARTITION"; exit 1; }
dd if=fw.img of=root.img bs=1M skip=$((ST*512)) count=$((SEC*512)) iflag=skip_bytes,count_bytes status=none
rm -f fw.img
mkdir -p fs
for d in /usr /opt; do debugfs -R "rdump $d fs" root.img >/dev/null 2>&1; done
rm -f root.img

found=0
while IFS= read -r f; do
  file -b "$f" | grep -q '^ELF' || continue
  found=1
  arch=$(file -b "$f" | grep -oE 'ARM aarch64|ARM,' | head -1)
  case "$arch" in
    "ARM aarch64") OD=$S/armtools/a64/usr/bin/aarch64-linux-gnu-objdump; export LD_LIBRARY_PATH=$S/armtools/a64/usr/lib/x86_64-linux-gnu ;;
    *) OD=$S/armtools/x/usr/bin/arm-linux-gnueabihf-objdump; export LD_LIBRARY_PATH=$S/armtools/x/usr/lib/x86_64-linux-gnu ;;
  esac
  chk=$(readelf --dyn-syms -W "$f" | grep -c '__strncpy_chk@')
  "$OD" -d "$f" 2>/dev/null | grep -E '<(__strncpy_chk|strncpy)@plt>' \
    | grep -E '\s(blx?|bl)\s' \
    | awk '{a=$1; sub(":","",a); k=($0 ~ /__strncpy_chk/)?"CHK":"PLAIN"; print a, k}' \
    | while read -r a k; do echo "$((16#$a)) $k"; done > calls.txt
  # every window of >=5 copies within 320 bytes (decode_type1033 and siblings)
  cluster=$(awk '{ad[NR]=$1+0; kd[NR]=$2} END{
      for(i=1;i<=NR-4;i++) if (ad[i+4]-ad[i] < 320) { s=""; for(j=i;j<i+5;j++) s=s kd[j] " "; printf "[0x%x %s] ", ad[i], s; i+=4 } }' calls.txt)
  printf '%s\t%s\t%s\t%s\tchk-imports=%s\t1033-cluster: %s\n' "$V" "$BUILD" "${f#fs/}" "$arch" "$chk" "${cluster:-none-found}"
done < <(grep -rlaF 'rtcm3 1033' fs 2>/dev/null)
[ $found = 1 ] || echo "$V	$BUILD	NO-1033-DECODER-FOUND"
cd "$S" && rm -rf "$W"
