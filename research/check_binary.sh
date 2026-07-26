#!/bin/bash
# Which column does a shipped binary fall into -- loud abort, or silent
# coordinate corruption?
#
#   ./check_binary.sh <file|directory|package.deb> ...
#   ./check_binary.sh rtklib_2.4.3.b34+dfsg-1+b2_armhf.deb
#   ./check_binary.sh /usr/bin/rtkrcv
#
# The fortified strncpy is the only thing that turns the 1033 overflow into a
# loud failure. It exists only if the build had _FORTIFY_SOURCE, which shows up
# as a __strncpy_chk import. Plain names present with zero *_chk of any kind is
# the signature of a build without it.
#
# The second check is the one that is easy to skip and invalidates everything
# if you do: absence of *_chk means nothing unless the binary being tested
# actually CONTAINS decode_type1033. A launcher that links the decoder from a
# library elsewhere will look clean while the vulnerable code sits next door.
# The decoder is identified by its trace strings, which survive stripping.
#
# Measured this way: both Windows distributions and Debian's armhf package are
# unfortified. See "The distro package is unfortified too" in README.md.
set -u

for t in objdump file; do
    command -v "$t" >/dev/null || { echo "need $t (binutils)" >&2; exit 1; }
done

inspect_elf() {
    local b="$1"
    file -b "$b" 2>/dev/null | grep -q '^ELF' || return 1

    printf '\n  === %s ===\n' "$(basename "$b")"
    printf '      %s\n' "$(file -b "$b" | cut -c1-95)"

    # Is the decoder here at all? Trace strings from decode_type1033.
    local has=no
    for s in 'rtcm3 1033 length error' 'ant=%s:%s rec=%s:%s:%s' 'rtcm3 1033'; do
        if grep -aq -- "$s" "$b" 2>/dev/null; then has=yes; break; fi
    done
    printf '      1033 decoder present : %s\n' "$has"
    if [ "$has" = no ]; then
        printf '      -> the fortification result below says nothing about this\n'
        printf '         bug unless the decoder is linked in from elsewhere.\n'
    fi

    local chk
    chk=$(objdump -T "$b" 2>/dev/null | grep -oE '__[a-z0-9]+_chk' | sort -u)
    if echo "$chk" | grep -q '__strncpy_chk'; then
        printf '      __strncpy_chk        : PRESENT\n'
        printf '      => FORTIFIED: one 1033 frame aborts the process (remote DoS)\n'
    else
        printf '      __strncpy_chk        : absent\n'
        if [ -z "$chk" ]; then
            printf '      any *_chk import     : none at all\n'
        else
            printf '      other *_chk imports  : %s\n' "$(echo "$chk" | tr '\n' ' ')"
        fi
        printf '      => UNFORTIFIED: the coordinate is corrupted silently\n'
    fi
    # Corroboration: the unfortified names should be there instead.
    printf '      plain libc names     : %s\n' \
        "$(objdump -T "$b" 2>/dev/null \
           | grep -oE '\b(strncpy|strcpy|sprintf|memcpy)\b' | sort -u | tr '\n' ' ')"
    return 0
}

walk() {
    local p="$1"
    if [ -d "$p" ]; then
        find "$p" -type f | while read -r f; do inspect_elf "$f"; done
    else
        inspect_elf "$p" || echo "  (not an ELF, skipped: $p)"
    fi
}

[ $# -gt 0 ] || { sed -n '2,12p' "$0"; exit 1; }

for target in "$@"; do
    echo "########## $target ##########"
    case "$target" in
    *.deb)
        d=$(mktemp -d) || exit 1
        (cd "$d" && ar x "$(realpath "$target")" >/dev/null 2>&1 \
             && tar xf data.tar.* 2>/dev/null) || {
            echo "  could not unpack $target"; continue; }
        walk "$d"
        rm -rf "$d"
        ;;
    *)  walk "$target" ;;
    esac
done
