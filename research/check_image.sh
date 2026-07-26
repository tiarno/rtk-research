#!/bin/bash
# Look inside a firmware or OS image for RTKLIB, without root.
#
#   ./check_image.sh <image.img|image.img.xz>
#
# sudo is neither required nor used: fdisk reads the partition table straight
# out of the file, dd carves the largest Linux partition, and debugfs reads
# ext4 without mounting it. That matters on a machine where you would rather
# not hand root to a downloaded disk image, and it is the difference between
# this being runnable and not on a locked-down box.
#
# Two traps this encodes, both hit for real:
#
#   - A raw `grep str2str` over a rootfs hits OpenLDAP symbols
#     (ldap_str2structurerule and friends) and looks like a positive. The
#     name scan below reports context, not just counts, for that reason.
#   - A hit in /var/lib/apt/lists is repository *metadata*: the distro offers
#     RTKLIB as a package, which is not the same as the image shipping it.
#     Worth knowing -- that is how the Debian packaging was found -- but it is
#     not evidence the binary is present.
#
# Used on emlid-raspbian-20220608.img: no RTKLIB, cleanly. See
# "The distro package is unfortified too" in README.md.
set -u

IMG="${1:-}"
[ -n "$IMG" ] && [ -f "$IMG" ] || { sed -n '2,6p' "$0"; exit 1; }
for t in fdisk debugfs dd; do
    command -v "$t" >/dev/null || { echo "need $t (util-linux / e2fsprogs)" >&2; exit 1; }
done

W="$(dirname "$IMG")"
case "$IMG" in
*.xz)
    RAW="${IMG%.xz}"
    if [ ! -s "$RAW" ]; then
        echo "=== decompressing (keeping the .xz) ==="
        xz -d -k -T0 "$IMG" || exit 1
    fi
    IMG="$RAW"
    ;;
esac
echo "image: $IMG ($(du -h "$IMG" | cut -f1))"

ROOT="$W/rootfs.img"
if [ ! -s "$ROOT" ]; then
    echo
    echo "=== partition table ==="
    fdisk -l -u=sectors "$IMG" 2>/dev/null | sed 's/^/    /'
    # Largest partition = rootfs, by sector count.
    read -r START SECTORS < <(fdisk -l -u=sectors "$IMG" 2>/dev/null \
        | awk -v img="$(basename "$IMG")" '$1 ~ img"[0-9]" {print $2, $4}' \
        | sort -k2 -n | tail -1)
    [ -n "${START:-}" ] || { echo "no partition found"; exit 1; }
    echo
    echo "=== carving rootfs from sector $START ($SECTORS sectors) ==="
    dd if="$IMG" of="$ROOT" bs=512 skip="$START" count="$SECTORS" \
       status=none conv=sparse || exit 1
fi

echo
echo "=== filesystem ==="
debugfs -R "stats -h" "$ROOT" 2>/dev/null | head -8 | sed 's/^/    /'

echo
echo "=== RTKLIB tool names, with context (substring hits are common) ==="
for s in rtkrcv rtknavi rtkpost convbin str2str RTKLIB; do
    # grep -c prints 0 AND exits 1 on no match, so `|| echo 0` would print it
    # twice. No set -e here, so the non-zero status is simply ignored.
    n=$(grep -a -c -- "$s" "$ROOT" 2>/dev/null)
    printf '    %-9s %s hits\n' "$s" "${n:-0}"
done
echo
echo "    context for the first few hits (is it a binary, a symbol, or apt metadata?):"
grep -a -b -o -E 'rtkrcv|rtknavi|convbin|str2str|RTKLIB' "$ROOT" 2>/dev/null \
  | head -8 | while IFS=: read -r off tok; do
    printf '\n      --- %s @ %s ---\n' "$tok" "$off"
    dd if="$ROOT" bs=1 skip=$((off > 160 ? off - 160 : 0)) count=320 status=none \
      | tr -c '[:print:]\n' ' ' | tr -s ' ' | sed 's/^/        /'
done

echo
echo
echo "=== GNSS-looking executables in the usual places ==="
for d in /usr/bin /usr/sbin /usr/local/bin /usr/local/sbin /bin /opt; do
    debugfs -R "ls -l $d" "$ROOT" 2>/dev/null | awk '{print $NF}' \
      | grep -iE 'rtk|gnss|gps|ubx|nmea|rtcm|str2' | sed "s|^|    $d/|"
done
echo "    (nothing above = no GNSS tooling shipped in this image)"
echo
echo "To pull a binary out for ./check_binary.sh:"
echo "    debugfs -R \"dump /usr/bin/rtkrcv ./rtkrcv\" $ROOT"
