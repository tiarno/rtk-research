/*
 * rnx2rtcm3 -- RINEX observation/navigation files to an RTCM3 byte stream
 * =====================================================================
 *
 * Encodes a RINEX obs+nav pair into the RTCM3 messages a real base station or
 * rover would emit, using RTKLIB's own encoder (gen_rtcm3). The output is a
 * plain byte stream suitable for replay into rtkrcv as a file input stream.
 *
 * Exists so the type 1033 attack can be demonstrated end-to-end against the
 * real-time server rather than inferred from the post-processing path: it
 * turns a static RINEX pair into the live correction stream rtkrcv expects.
 *
 * Messages emitted:
 *   1019  GPS ephemeris (once per satellite, up front)
 *   1005  stationary RTK reference station ARP (once per epoch, base only)
 *   1004  extended L1/L2 GPS observables (once per epoch)
 *
 * Usage:
 *   rnx2rtcm3 <obs> <nav> <out.rtcm3> [staid] [X Y Z]
 *
 * Supplying X Y Z emits 1005 with that position; omitting them uses the
 * position from the RINEX header (and emits no 1005 if the header has none).
 *
 * A companion <out.rtcm3>.tag time-tag file is written so RTKLIB can replay
 * the stream at a controlled rate (path::T::x<speed>). Without it a file
 * stream is consumed in a single read, which overruns the server's base
 * observation buffer and prevents rover/base epoch pairing.
 *
 * Tag file layout, per src/stream.c:
 *   HEADER(60) + TICK(4) + TIME(4+8) + TICK0(4)+FPOS0(4) + TICK1(4)+FPOS1(4)...
 */
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include "rtklib.h"

int showmsg(const char *format, ...) { (void)format; return 0; }
void settspan(gtime_t ts, gtime_t te) { (void)ts; (void)te; }
void settime(gtime_t time) { (void)time; }

static int emit(FILE *fp, rtcm_t *rtcm, int type, int sync)
{
    if (!gen_rtcm3(rtcm, type, 0, sync)) return 0;
    fwrite(rtcm->buff, 1, rtcm->nbyte, fp);
    return 1;
}

int main(int argc, char **argv)
{
    obs_t obs = {0};
    nav_t nav = {0};
    sta_t sta = {0};
    rtcm_t rtcm;
    FILE *fp, *ftag;
    gtime_t t0;
    int i, j, n, nep = 0, neph = 0, nobs = 0, staid = 1234;
    int havepos = 0;
    double pos[3] = {0};

    if (argc < 4) {
        fprintf(stderr, "usage: %s <obs> <nav> <out.rtcm3> [staid] [X Y Z]\n",
                argv[0]);
        return 1;
    }
    if (argc >= 5) staid = atoi(argv[4]);
    if (argc >= 8) {
        pos[0] = atof(argv[5]); pos[1] = atof(argv[6]); pos[2] = atof(argv[7]);
        havepos = 1;
    }

    if (!readrnx(argv[1], 1, "", &obs, &nav, &sta)) {
        fprintf(stderr, "cannot read obs: %s\n", argv[1]);
        return 1;
    }
    readrnx(argv[2], 1, "", NULL, &nav, NULL);
    sortobs(&obs);
    uniqnav(&nav);

    if (!havepos && norm(sta.pos, 3) > 0.0) {
        for (i = 0; i < 3; i++) pos[i] = sta.pos[i];
        havepos = 1;
    }

    /*
     * RTCM3 type 1019 carries a 10-bit GPS week, so the decoder has to resolve
     * the 1024-week rollover against the current date. Replaying an old
     * dataset therefore lands the ephemeris ~20 years from where it belongs
     * and every satellite position comes out wrong. Shifting the whole dataset
     * by a whole number of weeks moves it into the present rollover window
     * while preserving every time difference the positioning math depends on.
     */
    if (getenv("SHIFT_WEEKS")) {
        int wk = atoi(getenv("SHIFT_WEEKS"));
        double dt = wk * 604800.0;
        for (i = 0; i < obs.n; i++) {
            obs.data[i].time = timeadd(obs.data[i].time, dt);
        }
        for (i = 0; i < nav.n; i++) {
            nav.eph[i].toe = timeadd(nav.eph[i].toe, dt);
            nav.eph[i].toc = timeadd(nav.eph[i].toc, dt);
            nav.eph[i].ttr = timeadd(nav.eph[i].ttr, dt);
            nav.eph[i].week += wk;
        }
        fprintf(stderr, "shifted dataset by %d GPS weeks\n", wk);
    }

    fprintf(stderr, "read %d obs records, %d ephemerides\n", obs.n, nav.n);
    if (havepos) {
        fprintf(stderr, "station position: %.4f %.4f %.4f\n",
                pos[0], pos[1], pos[2]);
    } else {
        fprintf(stderr, "no station position (no 1005 will be emitted)\n");
    }

    if (!(fp = fopen(argv[3], "wb"))) {
        perror(argv[3]);
        return 1;
    }
    {
        char tagpath[1080];
        char tagh[64] = "";
        uint32_t tick_f = 0, time_time;
        double time_sec;
        snprintf(tagpath, sizeof(tagpath), "%s.tag", argv[3]);
        if (!(ftag = fopen(tagpath, "wb"))) {
            perror(tagpath);
            return 1;
        }
        t0 = obs.n > 0 ? obs.data[0].time : nav.eph[0].toe;
        snprintf(tagh, sizeof(tagh), "TIMETAG RTKLIB %s", VER_RTKLIB);
        memcpy(tagh + 64 - 4, &tick_f, 4);
        time_time = (uint32_t)t0.time;
        time_sec = t0.sec;
        fwrite(tagh, 1, 64, ftag);
        fwrite(&time_time, 1, 4, ftag);
        fwrite(&time_sec, 1, 8, ftag);
    }

    init_rtcm(&rtcm);
    rtcm.staid = staid;
    for (i = 0; i < 3; i++) rtcm.sta.pos[i] = pos[i];
    rtcm.sta.deltype = 0;

    /*
     * Ephemerides first, so the consumer can compute satellite positions
     * before the first observation epoch arrives.
     *
     * Emit only ONE ephemeris per satellite -- the one whose toe is nearest
     * the middle of the observation window. A RINEX nav file keeps every
     * record and lets seleph() choose, but the RTCM path has a single slot
     * per satellite (nav.eph[sat-1]), so emitting all of them just leaves
     * each slot holding whichever was decoded last. That is typically hours
     * from the observations, and seleph() then rejects it as stale with
     * "no broadcast ephemeris". A real base station broadcasts the currently
     * valid ephemeris, which is what this reproduces.
     */
    {
        gtime_t tmid = obs.n > 0 ? obs.data[obs.n / 2].time : t0;
        int sat;
        for (sat = 1; sat <= MAXSAT; sat++) {
            int best = -1;
            double bestdt = 1e30, dt;
            if (satsys(sat, NULL) != SYS_GPS) continue;
            for (i = 0; i < nav.n; i++) {
                if (nav.eph[i].sat != sat) continue;
                dt = fabs(timediff(nav.eph[i].toe, tmid));
                if (dt < bestdt) { bestdt = dt; best = i; }
            }
            if (best < 0 || bestdt > MAXDTOE) continue;
            rtcm.nav.eph[sat - 1] = nav.eph[best];
            rtcm.ephsat = sat;
            rtcm.time = nav.eph[best].toe;
            if (emit(fp, &rtcm, 1019, 0)) neph++;
        }
    }

    /* Observation epochs. */
    for (i = 0; i < obs.n; ) {
        for (j = i; j < obs.n &&
             fabs(timediff(obs.data[j].time, obs.data[i].time)) < 0.001; j++) ;

        n = j - i;
        if (n > MAXOBS) n = MAXOBS;
        memcpy(rtcm.obs.data, obs.data + i, sizeof(obsd_t) * n);
        rtcm.obs.n = n;
        rtcm.time = obs.data[i].time;

        if (havepos) emit(fp, &rtcm, 1005, 1);
        if (emit(fp, &rtcm, 1004, 0)) { nep++; nobs += n; }

        /* time tag: by this tick the reader should have consumed up to here */
        {
            uint32_t tick = (uint32_t)(timediff(obs.data[i].time, t0) * 1000.0);
            uint32_t fpos = (uint32_t)ftell(fp);
            fwrite(&tick, 1, 4, ftag);
            fwrite(&fpos, 1, 4, ftag);
        }

        i = j;
    }

    fclose(ftag);
    fclose(fp);
    fprintf(stderr, "wrote %d epochs (%d obs), %d ephemeris messages -> %s\n",
            nep, nobs, neph, argv[3]);

    free(obs.data);
    free(nav.eph);
    free_rtcm(&rtcm);
    return 0;
}
