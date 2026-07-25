/*
 * gnss_sim -- synthesise base and rover RTCM3 observation streams
 * ==============================================================
 *
 * Generates the GNSS observables two receivers at two known positions would
 * produce, and encodes them as RTCM3. This exists so RTKLIB can be driven from
 * an arbitrary rover position -- in particular one that moves -- rather than
 * only from the fixed ground station in the bundled RINEX test data.
 *
 * That is the missing link for a single packet-to-propeller chain: the rest of
 * the harness can already take a malicious type 1033 into RTKLIB and hand the
 * resulting position to an autopilot, but RTKLIB needs rover observations from
 * wherever the vehicle actually is.
 *
 * Why the observables are constructed this way
 * -------------------------------------------
 * Both receivers' observables come from the SAME model at the SAME epoch:
 *
 *     P = |sat - rx| - c*dts
 *     L = P / lambda
 *
 * Every term common to the two receivers -- satellite position error,
 * satellite clock, and (being modelled identically) the atmosphere -- cancels
 * exactly when RTKLIB forms double differences. The double-differenced
 * residuals are therefore zero by construction, ambiguity resolution is
 * trivial, and the baseline RTKLIB recovers is exactly rover - base.
 *
 * This is not a realistic signal simulator: no atmosphere, no multipath, no
 * receiver clock drift. It does not need to be. The quantity under test is
 * what RTKLIB does with a corrupted *base station coordinate*, and for that
 * the observables only need to be self-consistent.
 *
 * Two modes
 * ---------
 *   batch: gnss_sim <nav> <base_ecef> <rover_ecef> <epochs> <rate> \
 *                   <base.rtcm3> <rover.rtcm3>
 *          Writes files plus .tag time tags for paced replay.
 *
 *   live:  gnss_sim <nav> <base_ecef> --live <:baseport> <:roverport> [rate]
 *          Reads "lat,lon,height" (deg, deg, m) from stdin, one line per
 *          epoch, and serves each stream over TCP for RTKLIB to connect to. This is what closes the loop: the vehicle's
 *          own position becomes the observations RTKLIB solves, so a corrupted
 *          base coordinate propagates back into the vehicle's control loop.
 */
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <math.h>
#include "rtklib.h"

int showmsg(const char *format, ...) { (void)format; return 0; }
void settspan(gtime_t ts, gtime_t te) { (void)ts; (void)te; }
void settime(gtime_t time) { (void)time; }

#define ELMIN (10.0 * D2R)

typedef struct {
    FILE *fp;          /* batch mode: plain file */
    stream_t *str;     /* live mode: RTKLIB stream (TCP server) */
    FILE *tag;
    rtcm_t rtcm;
    double pos[3];
} sstream_t;

static int parse_xyz(const char *s, double *p)
{
    return sscanf(s, "%lf,%lf,%lf", p, p + 1, p + 2) == 3;
}

/* Pick the ephemeris for `sat` whose toe is nearest `t`. */
static eph_t *select_eph(nav_t *nav, int sat, gtime_t t)
{
    eph_t *best = NULL;
    double bestdt = 1e30, dt;
    int i;
    for (i = 0; i < nav->n; i++) {
        if (nav->eph[i].sat != sat) continue;
        dt = fabs(timediff(nav->eph[i].toe, t));
        if (dt < bestdt) { bestdt = dt; best = nav->eph + i; }
    }
    return (best && bestdt <= MAXDTOE) ? best : NULL;
}

/*
 * Satellite state at transmit time, iterating on signal travel time.
 * geodist() returns the geometric range including the Sagnac correction and
 * fills the receiver-to-satellite unit vector.
 */
static int sat_state(eph_t *eph, gtime_t t, const double *rx,
                     double *rs, double *dts, double *r, double *e)
{
    double tau = 0.075, var;
    int i;
    for (i = 0; i < 3; i++) {
        gtime_t ts = timeadd(t, -tau);
        eph2pos(ts, eph, rs, dts, &var);
        *r = geodist(rs, rx, e);
        if (*r <= 0.0) return 0;
        tau = *r / CLIGHT;
    }
    return 1;
}

static void emit(sstream_t *s, int type, int sync)
{
    if (!gen_rtcm3(&s->rtcm, type, 0, sync)) return;
    if (s->str) strwrite(s->str, s->rtcm.buff, s->rtcm.nbyte);
    else        fwrite(s->rtcm.buff, 1, s->rtcm.nbyte, s->fp);
}

/* One epoch of observables for both receivers. Returns satellites used. */
static int gen_epoch(sstream_t *base, sstream_t *rover, nav_t *nav, gtime_t t,
                     double lam)
{
    int sat, n = 0;

    for (sat = 1; sat <= MAXSAT && n < MAXOBS; sat++) {
        eph_t *eph;
        double rs[6] = {0}, dts[2] = {0}, rb, rr, eb[3], er[3];
        double posb[3], azel[2];
        obsd_t ob = {{0}}, orv = {{0}};

        if (satsys(sat, NULL) != SYS_GPS) continue;
        if (!(eph = select_eph(nav, sat, t))) continue;
        if (eph->svh) continue;

        if (!sat_state(eph, t, base->pos, rs, dts, &rb, eb)) continue;
        if (!sat_state(eph, t, rover->pos, rs, dts, &rr, er)) continue;

        ecef2pos(base->pos, posb);
        if (satazel(posb, eb, azel) < ELMIN) continue;

        ob.time = orv.time = t;
        ob.sat = orv.sat = (uint8_t)sat;

        ob.P[0]  = rb - CLIGHT * dts[0];
        ob.L[0]  = ob.P[0] / lam;
        orv.P[0] = rr - CLIGHT * dts[0];
        orv.L[0] = orv.P[0] / lam;

        ob.code[0] = orv.code[0] = CODE_L1C;
        ob.SNR[0]  = orv.SNR[0]  = (uint16_t)(45.0 / SNR_UNIT);
        ob.LLI[0]  = orv.LLI[0]  = 0;

        base->rtcm.obs.data[n] = ob;
        rover->rtcm.obs.data[n] = orv;
        n++;
    }

    if (n < 5) return 0;

    base->rtcm.obs.n = rover->rtcm.obs.n = n;
    base->rtcm.time = rover->rtcm.time = t;

    emit(base, 1005, 1);
    emit(base, 1004, 0);
    emit(rover, 1004, 0);
    return n;
}

static void write_tag_header(FILE *tag, gtime_t t0)
{
    char tagh[64] = "";
    uint32_t tick_f = 0, time_time = (uint32_t)t0.time;
    double time_sec = t0.sec;
    snprintf(tagh, sizeof(tagh), "TIMETAG RTKLIB %s", VER_RTKLIB);
    memcpy(tagh + 64 - 4, &tick_f, 4);
    fwrite(tagh, 1, 64, tag);
    fwrite(&time_time, 1, 4, tag);
    fwrite(&time_sec, 1, 8, tag);
}

static int verbose_eph = 1;

static void emit_ephemerides(sstream_t *base, sstream_t *rover, nav_t *nav,
                             gtime_t tmid)
{
    int sat, neph = 0;
    for (sat = 1; sat <= MAXSAT; sat++) {
        eph_t *eph;
        if (satsys(sat, NULL) != SYS_GPS) continue;
        if (!(eph = select_eph(nav, sat, tmid))) continue;
        base->rtcm.nav.eph[sat - 1] = *eph;
        rover->rtcm.nav.eph[sat - 1] = *eph;
        base->rtcm.ephsat = rover->rtcm.ephsat = sat;
        base->rtcm.time = rover->rtcm.time = eph->toe;
        emit(base, 1019, 0);
        emit(rover, 1019, 0);
        neph++;
    }
    fprintf(stderr, "emitted %d ephemeris messages per stream\n", neph);
}

int main(int argc, char **argv)
{
    nav_t nav = {0};
    sstream_t base = {0}, rover = {0};
    gtime_t t0, t;
    double lam = CLIGHT / FREQ1, rate = 5.0;
    int live, epochs = 0, i, sat, nep, nobs_total = 0;
    const char *base_out, *rover_out;

    if (argc < 6) {
        fprintf(stderr,
            "batch: %s <nav> <base_x,y,z> <rover_x,y,z> <epochs> <rate>"
            " <base.rtcm3> <rover.rtcm3>\n"
            "live : %s <nav> <base_x,y,z> --live <base_out> <rover_out>"
            " [rate]\n", argv[0], argv[0]);
        return 1;
    }
    live = !strcmp(argv[3], "--live");

    if (!parse_xyz(argv[2], base.pos)) {
        fprintf(stderr, "bad base ECEF\n");
        return 1;
    }
    if (live) {
        base_out = argv[4];
        rover_out = argv[5];
        if (argc >= 7) rate = atof(argv[6]);
        for (i = 0; i < 3; i++) rover.pos[i] = base.pos[i];
    } else {
        if (argc < 8) { fprintf(stderr, "batch mode needs 7 arguments\n"); return 1; }
        if (!parse_xyz(argv[3], rover.pos)) {
            fprintf(stderr, "bad rover ECEF\n");
            return 1;
        }
        epochs = atoi(argv[4]);
        rate = atof(argv[5]);
        base_out = argv[6];
        rover_out = argv[7];
        if (epochs <= 0 || rate <= 0.0) {
            fprintf(stderr, "epochs and rate must be positive\n");
            return 1;
        }
    }

    if (!readrnx(argv[1], 1, "", NULL, &nav, NULL) || nav.n <= 0) {
        fprintf(stderr, "cannot read ephemerides from %s\n", argv[1]);
        return 1;
    }
    fprintf(stderr, "read %d ephemerides\n", nav.n);

    /*
     * RTCM3 type 1019 carries a 10-bit GPS week, so the consumer resolves the
     * 1024-week rollover against the current date. Replaying a 2005 dataset
     * today therefore lands the ephemerides ~20 years from the observations
     * and seleph() rejects every satellite.
     *
     * In batch mode the .tag file makes RTKLIB call timeset() to the dataset's
     * epoch, which hides this. Over TCP there is no tag file, so the dataset
     * has to be moved into the present rollover window explicitly. Shifting by
     * a whole number of weeks preserves every time difference that matters.
     */
    {
        int wk;
        if (getenv("SHIFT_WEEKS")) {
            wk = atoi(getenv("SHIFT_WEEKS"));
        } else {
            /*
             * Default: move the dataset into the CURRENT GPS week. RTCM3
             * observation messages carry only a time-of-week, so the consumer
             * reconstructs the week from its own clock. If the ephemerides sit
             * in a different week from the one the observations are decoded
             * into, seleph() rejects every satellite even though both were
             * shifted consistently here.
             */
            int ew = 0, cw = 0;
            time2gpst(nav.eph[0].toe, &ew);
            time2gpst(utc2gpst(timeget()), &cw);
            wk = cw - ew;
        }
        if (wk) {
            double dt = wk * 604800.0;
            for (i = 0; i < nav.n; i++) {
                nav.eph[i].toe = timeadd(nav.eph[i].toe, dt);
                nav.eph[i].toc = timeadd(nav.eph[i].toc, dt);
                nav.eph[i].ttr = timeadd(nav.eph[i].ttr, dt);
                nav.eph[i].week += wk;
            }
            fprintf(stderr, "shifted ephemerides by %d GPS weeks\n", wk);
        }
    }

    /*
     * Start at the earliest ephemeris epoch. Wall-clock time would put the
     * observations tens of thousands of seconds from any toe and seleph()
     * would reject every satellite.
     */
    t0 = nav.eph[0].toe;
    for (i = 1; i < nav.n; i++) {
        if (timediff(nav.eph[i].toe, t0) < 0.0) t0 = nav.eph[i].toe;
    }
    t0 = timeadd(t0, 60.0);

    if (live) {
        /*
         * Serve each stream over TCP rather than writing files. RTKLIB
         * connects as a client, and putting a relay in front of the base
         * port makes the 1033 injection a genuine on-path modification of
         * a correction stream rather than a file edit.
         */
        static stream_t sb, sr;
        strinit(&sb);
        strinit(&sr);
        if (!stropen(&sb, STR_TCPSVR, STR_MODE_W, base_out) ||
            !stropen(&sr, STR_TCPSVR, STR_MODE_W, rover_out)) {
            strclose(&sb); strclose(&sr);
            fprintf(stderr, "cannot open TCP servers %s / %s\n",
                    base_out, rover_out);
            return 1;
        }
        base.str = &sb;
        rover.str = &sr;
        fprintf(stderr, "serving base on %s, rover on %s\n",
                base_out, rover_out);
    } else {
        if (!(base.fp = fopen(base_out, "wb")) ||
            !(rover.fp = fopen(rover_out, "wb"))) {
            perror("open output");
            return 1;
        }
        char p[1080];
        snprintf(p, sizeof(p), "%s.tag", base_out);
        base.tag = fopen(p, "wb");
        snprintf(p, sizeof(p), "%s.tag", rover_out);
        rover.tag = fopen(p, "wb");
        if (!base.tag || !rover.tag) { perror("open tag"); return 1; }
        write_tag_header(base.tag, t0);
        write_tag_header(rover.tag, t0);
    }

    init_rtcm(&base.rtcm);
    init_rtcm(&rover.rtcm);
    base.rtcm.staid = 3040;
    rover.rtcm.staid = 759;
    for (i = 0; i < 3; i++) base.rtcm.sta.pos[i] = base.pos[i];
    base.rtcm.sta.deltype = 0;

    emit_ephemerides(&base, &rover, &nav,
                     timeadd(t0, live ? 300.0 : epochs / rate / 2.0));

    if (live) {
        char line[256];
        fprintf(stderr, "live mode: reading lat,lon,height from stdin\n");
        nep = 0;
        while (fgets(line, sizeof(line), stdin)) {
            double llh[3], xyz[3];
            int n;
            if (sscanf(line, "%lf,%lf,%lf", llh, llh + 1, llh + 2) != 3) continue;
            llh[0] *= D2R;
            llh[1] *= D2R;
            pos2ecef(llh, xyz);
            for (i = 0; i < 3; i++) rover.pos[i] = xyz[i];

            t = timeadd(t0, nep / rate);

            /*
             * Re-broadcast ephemerides periodically, as a real base station
             * does. Emitting them only at startup loses them entirely over
             * TCP: nothing is connected yet, so the consumer has no orbits
             * and rejects every satellite with "lack of valid sats".
             */
            if (nep % (int)(rate * 10) == 0) {
                emit_ephemerides(&base, &rover, &nav, t);
            }

            if ((n = gen_epoch(&base, &rover, &nav, t, lam))) {
                nobs_total += n;
            }
            nep++;
            if (nep % 50 == 0) {
                double bl[3];
                for (i = 0; i < 3; i++) bl[i] = rover.pos[i] - base.pos[i];
                fprintf(stderr, "  epoch %d, baseline %.2f m, %d sats\n",
                        nep, norm(bl, 3), n);
            }
        }
        fprintf(stderr, "live mode ended after %d epochs (%d obs)\n",
                nep, nobs_total);
    } else {
        double bl[3];
        for (i = 0; i < 3; i++) bl[i] = rover.pos[i] - base.pos[i];
        fprintf(stderr, "baseline: %.3f m\n", norm(bl, 3));

        for (nep = 0; nep < epochs; nep++) {
            int n;
            t = timeadd(t0, nep / rate);
            if (!(n = gen_epoch(&base, &rover, &nav, t, lam))) {
                fprintf(stderr, "epoch %d: too few satellites\n", nep);
                continue;
            }
            nobs_total += n;
            {
                uint32_t tick = (uint32_t)(timediff(t, t0) * 1000.0);
                uint32_t fb = (uint32_t)ftell(base.fp);
                uint32_t fr = (uint32_t)ftell(rover.fp);
                fwrite(&tick, 1, 4, base.tag);  fwrite(&fb, 1, 4, base.tag);
                fwrite(&tick, 1, 4, rover.tag); fwrite(&fr, 1, 4, rover.tag);
            }
        }
        fprintf(stderr, "wrote %d epochs (%d observations) -> %s / %s\n",
                nep, nobs_total, base_out, rover_out);
        fclose(base.tag);
        fclose(rover.tag);
    }

    if (base.str)  strclose(base.str);
    if (rover.str) strclose(rover.str);
    if (base.fp)   fclose(base.fp);
    if (rover.fp)  fclose(rover.fp);
    free_rtcm(&base.rtcm);
    free_rtcm(&rover.rtcm);
    free(nav.eph);
    (void)sat;
    return 0;
}
