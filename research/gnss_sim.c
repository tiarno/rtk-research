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
 * Every term that is common to the two receivers -- satellite position error,
 * satellite clock, and (being modelled identically) the atmosphere -- cancels
 * exactly when RTKLIB forms double differences. The double-differenced
 * residuals are therefore zero by construction, ambiguity resolution is
 * trivial, and the baseline RTKLIB recovers is exactly rover - base.
 *
 * This is not a realistic signal simulator: there is no atmosphere, no
 * multipath and no receiver clock drift. It does not need to be. The quantity
 * under test is what RTKLIB does with a corrupted *base station coordinate*,
 * and for that the observables only need to be self-consistent.
 *
 * Usage:
 *   gnss_sim <nav.rnx> <base_ecef> <rover_ecef> <epochs> <rate_hz> \
 *            <base.rtcm3> <rover.rtcm3>
 *
 *   base_ecef / rover_ecef are "x,y,z" in metres.
 *
 * Example (rover 10 m north of the base):
 *   gnss_sim brdc.nav -3978242.4348,3382841.1715,3649902.7667 \
 *                     -3978247.1,3382837.2,3649910.9 120 5 base.rtcm3 rover.rtcm3
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
    FILE *fp;
    FILE *tag;
    rtcm_t rtcm;
    double pos[3];
} stream_t_;

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
 * Satellite position at transmit time, iterating on the signal travel time.
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

static void emit(stream_t_ *s, int type, int sync)
{
    if (gen_rtcm3(&s->rtcm, type, 0, sync)) {
        fwrite(s->rtcm.buff, 1, s->rtcm.nbyte, s->fp);
    }
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

int main(int argc, char **argv)
{
    nav_t nav = {0};
    stream_t_ base = {0}, rover = {0};
    gtime_t t0, t;
    double lam = CLIGHT / FREQ1;
    int epochs, i, k, sat, nep, nobs_total = 0;
    double rate;

    if (argc < 8) {
        fprintf(stderr,
            "usage: %s <nav.rnx> <base_x,y,z> <rover_x,y,z> <epochs> <rate_hz>"
            " <base.rtcm3> <rover.rtcm3>\n", argv[0]);
        return 1;
    }
    if (!parse_xyz(argv[2], base.pos) || !parse_xyz(argv[3], rover.pos)) {
        fprintf(stderr, "bad ECEF coordinates\n");
        return 1;
    }
    epochs = atoi(argv[4]);
    rate = atof(argv[5]);
    if (epochs <= 0 || rate <= 0.0) {
        fprintf(stderr, "epochs and rate must be positive\n");
        return 1;
    }

    if (!readrnx(argv[1], 1, "", NULL, &nav, NULL) || nav.n <= 0) {
        fprintf(stderr, "cannot read ephemerides from %s\n", argv[1]);
        return 1;
    }
    fprintf(stderr, "read %d ephemerides\n", nav.n);

    {
        double bl[3];
        for (i = 0; i < 3; i++) bl[i] = rover.pos[i] - base.pos[i];
        fprintf(stderr, "baseline: %.3f m\n", norm(bl, 3));
    }

    /*
     * Start at the epoch of the first ephemeris. Using wall-clock time would
     * put the observations tens of thousands of seconds from any toe, and
     * seleph() would reject every satellite.
     */
    t0 = nav.eph[0].toe;
    for (i = 1; i < nav.n; i++) {
        if (timediff(nav.eph[i].toe, t0) < 0.0) t0 = nav.eph[i].toe;
    }
    t0 = timeadd(t0, 60.0);

    if (!(base.fp = fopen(argv[6], "wb")) || !(rover.fp = fopen(argv[7], "wb"))) {
        perror("open output");
        return 1;
    }
    {
        char p[1080];
        snprintf(p, sizeof(p), "%s.tag", argv[6]);
        base.tag = fopen(p, "wb");
        snprintf(p, sizeof(p), "%s.tag", argv[7]);
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

    /* Ephemerides up front: one per satellite, nearest the run's midpoint. */
    {
        gtime_t tmid = timeadd(t0, epochs / rate / 2.0);
        int neph = 0;
        for (sat = 1; sat <= MAXSAT; sat++) {
            eph_t *eph;
            if (satsys(sat, NULL) != SYS_GPS) continue;
            if (!(eph = select_eph(&nav, sat, tmid))) continue;
            base.rtcm.nav.eph[sat - 1] = *eph;
            rover.rtcm.nav.eph[sat - 1] = *eph;
            base.rtcm.ephsat = rover.rtcm.ephsat = sat;
            base.rtcm.time = rover.rtcm.time = eph->toe;
            emit(&base, 1019, 0);
            emit(&rover, 1019, 0);
            neph++;
        }
        fprintf(stderr, "emitted %d ephemeris messages per stream\n", neph);
        if (neph < 5) {
            fprintf(stderr, "too few usable ephemerides -- check the nav file\n");
            return 1;
        }
    }

    for (nep = 0; nep < epochs; nep++) {
        int n = 0;
        t = timeadd(t0, nep / rate);

        for (sat = 1; sat <= MAXSAT && n < MAXOBS; sat++) {
            eph_t *eph;
            double rs[6] = {0}, dts[2] = {0}, rb, rr, eb[3], er[3];
            double posb[3], azel[2];
            obsd_t ob = {{0}}, orv = {{0}};

            if (satsys(sat, NULL) != SYS_GPS) continue;
            if (!(eph = select_eph(&nav, sat, t))) continue;
            if (eph->svh) continue;

            if (!sat_state(eph, t, base.pos, rs, dts, &rb, eb)) continue;
            if (!sat_state(eph, t, rover.pos, rs, dts, &rr, er)) continue;

            /* Elevation mask, evaluated at the base. */
            ecef2pos(base.pos, posb);
            if (satazel(posb, eb, azel) < ELMIN) continue;

            ob.time = orv.time = t;
            ob.sat = orv.sat = (uint8_t)sat;

            ob.P[0]  = rb - CLIGHT * dts[0];
            ob.L[0]  = ob.P[0] / lam;
            orv.P[0] = rr - CLIGHT * dts[0];
            orv.L[0] = orv.P[0] / lam;

            for (k = 0; k < 1; k++) {
                ob.code[k] = orv.code[k] = CODE_L1C;
                ob.SNR[k]  = orv.SNR[k]  = (uint16_t)(45.0 / SNR_UNIT);
                ob.LLI[k]  = orv.LLI[k]  = 0;
            }

            base.rtcm.obs.data[n] = ob;
            rover.rtcm.obs.data[n] = orv;
            n++;
        }

        if (n < 5) {
            fprintf(stderr, "epoch %d: only %d satellites, skipping\n", nep, n);
            continue;
        }

        base.rtcm.obs.n = rover.rtcm.obs.n = n;
        base.rtcm.time = rover.rtcm.time = t;

        emit(&base, 1005, 1);
        emit(&base, 1004, 0);
        emit(&rover, 1004, 0);
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
            nep, nobs_total, argv[6], argv[7]);

    fclose(base.tag); fclose(rover.tag);
    fclose(base.fp);  fclose(rover.fp);
    free_rtcm(&base.rtcm); free_rtcm(&rover.rtcm);
    free(nav.eph);
    return 0;
}
