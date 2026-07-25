/*
 * decode_type1033 station-position harness
 * ========================================
 *
 * Feeds a raw RTCM3 byte stream into RTKLIB's real decoder (input_rtcm3) and
 * dumps the station-parameter struct after every complete message, so the
 * effect of an oversized descriptor length on sta.pos can be observed
 * directly.
 *
 * This links against unmodified RTKLIB sources -- nothing here patches or
 * stubs the decoder.
 *
 * Build:  ./build.sh            (see that script for the RTKLIB path)
 * Run:    ./harness stream.bin
 */
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <stddef.h>
#include "rtklib.h"

/* RTKLIB expects the application to provide these. */
int showmsg(const char *format, ...) { (void)format; return 0; }
void settspan(gtime_t ts, gtime_t te) { (void)ts; (void)te; }
void settime(gtime_t time) { (void)time; }

static rtcm_t rtcm;

/* Print a descriptor field with its length, escaping non-printables. */
static void dump_str(const char *label, const char *s, size_t cap)
{
    size_t i, n = strnlen(s, cap);
    printf("    %-8s len=%-3zu \"", label, n);
    for (i = 0; i < n && i < 24; i++) {
        putchar((s[i] >= 32 && s[i] < 127) ? s[i] : '.');
    }
    printf("%s\"\n", n > 24 ? "..." : "");
}

static void dump_sta(const char *when)
{
    printf("  [%s]\n", when);
    dump_str("antdes",  rtcm.sta.antdes,  MAXANT);
    dump_str("rectype", rtcm.sta.rectype, MAXANT);
    dump_str("recsno",  rtcm.sta.recsno,  MAXANT);
    printf("    sta.pos  = %.4f %.4f %.4f\n",
           rtcm.sta.pos[0], rtcm.sta.pos[1], rtcm.sta.pos[2]);
    printf("    sta.del  = %.4f %.4f %.4f   hgt=%.4f\n",
           rtcm.sta.del[0], rtcm.sta.del[1], rtcm.sta.del[2], rtcm.sta.hgt);
    printf("    sta.itrf = %d  antsetup=%d  deltype=%d\n",
           rtcm.sta.itrf, rtcm.sta.antsetup, rtcm.sta.deltype);
    printf("    rtcm.dgps = %p   (field immediately after sta)\n",
           (void *)rtcm.dgps);
}

/*
 * Verbatim copy of the base-position adoption in update_antpos(),
 * src/rtksvr.c:250-267. Reproduced here rather than linking the whole
 * server so the consequence of a corrupted sta.pos is visible without
 * standing up a full rtksvr instance. Note the absence of any norm()
 * guard -- the post-processing path in postpos.c:843 has one, this
 * path does not.
 */
static void adopt_base_position(double *rb)
{
    double pos[3], del[3] = {0}, dr[3];
    int i;

    for (i = 0; i < 3; i++) rb[i] = rtcm.sta.pos[i];

    ecef2pos(rb, pos);
    if (rtcm.sta.deltype) { /* xyz */
        del[2] = rtcm.sta.hgt;
        enu2ecef(pos, del, dr);
        for (i = 0; i < 3; i++) rb[i] += rtcm.sta.del[i] + dr[i];
    } else { /* enu */
        enu2ecef(pos, rtcm.sta.del, dr);
        for (i = 0; i < 3; i++) rb[i] += dr[i];
    }
}

int main(int argc, char **argv)
{
    unsigned char *buf;
    long size, i;
    FILE *fp;
    int ret, nmsg = 0;
    double rb[3] = {0};

    if (argc < 2) {
        fprintf(stderr, "usage: %s <rtcm3-stream.bin>\n", argv[0]);
        return 1;
    }
    if (!(fp = fopen(argv[1], "rb"))) {
        perror(argv[1]);
        return 1;
    }
    fseek(fp, 0, SEEK_END);
    size = ftell(fp);
    fseek(fp, 0, SEEK_SET);
    buf = malloc(size);
    if (fread(buf, 1, size, fp) != (size_t)size) {
        fprintf(stderr, "short read\n");
        return 1;
    }
    fclose(fp);

    init_rtcm(&rtcm);

    /*
     * init_rtcm() leaves dgps NULL, which would hide any write that lands on
     * it. Plant a recognisable non-zero value so corruption of the field
     * immediately following sta is visible rather than a no-op.
     */
    rtcm.dgps = (dgps_t *)0x4141414141414141ULL;

    printf("sizeof(sta_t)=%zu  offsetof(rtcm_t,sta)=%zu  offsetof(rtcm_t,dgps)=%zu\n",
           sizeof(sta_t), offsetof(rtcm_t, sta), offsetof(rtcm_t, dgps));
    printf("sta spans rtcm_t[%zu..%zu); dgps at +%zu\n",
           offsetof(rtcm_t, sta), offsetof(rtcm_t, sta) + sizeof(sta_t),
           offsetof(rtcm_t, dgps));
    printf("feeding %ld bytes\n\n", size);

    for (i = 0; i < size; i++) {
        ret = input_rtcm3(&rtcm, buf[i]);
        if (ret == 0) continue;

        nmsg++;
        printf("message %d: type=%d input_rtcm3 ret=%d\n",
               nmsg, getbitu(rtcm.buff, 24, 12), ret);
        dump_sta("after decode");

        if (ret == 5) {
            /* rtksvr.c:325 dispatches ret==5 to update_antpos() */
            adopt_base_position(rb);
            printf("    -> adopted into rtk.rb = %.4f %.4f %.4f\n",
                   rb[0], rb[1], rb[2]);
        }
        printf("\n");
    }

    printf("final base position rtk.rb = %.4f %.4f %.4f\n", rb[0], rb[1], rb[2]);
    printf("norm(rb) = %.4f m\n", norm(rb, 3));

    free(buf);
    /* Clear the sentinel: free_rtcm() calls free() on this field, and the
     * planted value is not a real allocation. */
    rtcm.dgps = NULL;
    free_rtcm(&rtcm);
    return 0;
}
