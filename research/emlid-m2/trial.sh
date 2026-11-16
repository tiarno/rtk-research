#!/usr/bin/env bash
# trial.sh <rtcm-file> <port> : fresh logger, RINEX-convert the stream, report outcome
# Needs in $RTK_BISECT: qemu/usr/bin/qemu-arm-static (qemu-user-static .deb, unpacked)
# and m2-331/rootfs (Reach M2 v33.1 root fs), plus the firmware redis-server
# running under qemu on 127.0.0.1:1500.
H=$(dirname "$(readlink -f "$0")"); B=${RTK_BISECT:-$HOME/.cache/rtk-bisect}; Q=$B/qemu/usr/bin/qemu-arm-static; R=$B/m2-331/rootfs; mkdir -p $B/run/out && cd $B/run
L=trial-$(basename $1 .rtcm3).log; rm -f $L
setsid bun $H/serve.ts $1 $2 > srv-$2.log 2>&1 & SP=$!
setsid bash -c "timeout 25 $Q -L $R $R/usr/bin/reach-gnss-logger -d $R/etc/reach-gnss-logger > $L 2>&1; echo exit=\$? >> $L" &
for i in $(seq 60); do grep -q 'IPC FD' $L 2>/dev/null && break; timeout 0.3 tail -f /dev/null; done
bun $H/startlog.ts tcpcli://localhost:$2 $B/run/out $(basename $1 .rtcm3) >/dev/null
while ! grep -q exit= $L; do timeout 0.5 tail -f /dev/null; done
kill $SP 2>/dev/null
printf '%-14s %s | %s | %s\n' "$(basename $1)" "$(grep -c 'client connected' srv-$2.log) connect" "$(grep -oE 'buffer overflow detected|success: (true|false)' $L | tr '\n' ' ')" "$(grep exit= $L)"
