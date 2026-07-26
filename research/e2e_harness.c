/*
 * End-to-end harness: RTCM3 correction stream -> rtksvr -> position solution
 * =========================================================================
 *
 * Drives RTKLIB's real-time server (rtksvrstart / rtksvrstop) directly, with
 * rover and base correction streams replayed from files. This is the same
 * server rtkrcv wraps -- rtkrcv is only a console front-end, and its terminal
 * handling needs a tty, which makes it awkward to script. Using the API
 * directly exercises the identical code path, including update_antpos(), which
 * is the step the earlier two-stage demonstration could only establish by
 * reading the source.
 *
 * Reports, per epoch: solution quality, position, and the base position the
 * server is actually using (svr.rtk.rb).
 *
 * Usage:
 *   e2e_harness <rover> <base> [seconds] [speed] [file|serial|tcp]
 *
 * With "serial" the two arguments are RTKLIB serial paths
 * (port:baud:bits:parity:stop:fctrl) instead of files, so the same attack can
 * be delivered over a UART -- the transport a UHF/VHF base-rover radio link
 * uses -- rather than over a file or socket. Note RTKLIB prefixes the port
 * with /dev/, so a pty under /tmp is reached as "../tmp/ttyX".
 *
 * NMEA_VEL=1 makes the harness format the NMEA itself, with a ground speed
 * derived by differencing successive solutions, instead of letting RTKLIB's
 * solution stream do it. See derive_vel() for why that is necessary and what
 * it costs.
 */
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <math.h>
#include "rtklib.h"

int showmsg(const char *format, ...) { (void)format; return 0; }
void settspan(gtime_t ts, gtime_t te) { (void)ts; (void)te; }
void settime(gtime_t time) { (void)time; }

static rtksvr_t svr;
static stream_t nmeastr;

/* Both live in solution.c, not rtklib.h, so they are not visible here. Same
 * values, so the sentence own_rmc() writes stays identical to RTKLIB's. */
#define NMEA_TID "GN"           /* talker id: $GNRMC */
#define KNOT2M   0.514444444    /* m/s per knot */

/*
 * Ground speed for the RMC sentence, by differencing successive solutions.
 * =======================================================================
 *
 * RTKLIB's rtksvr path leaves the solution velocity at zero -- measured, with
 * prcopt.dynamics both on and off, against a rover fed a known 1 m/s ramp --
 * so outnmea_rmc(), which derives speed and course from sol->rr[3..5], emits
 * 0.00 knots however fast the rover is moving. An autopilot fusing that is
 * being told it is stationary mid-flight. ArduPilot's EKF3 fuses GPS velocity
 * by default, and the result was an oscillation that doubled in amplitude
 * every ~9 s with no attack present at all. The demo worked around it with
 * EK3_SRC1_VELXY 0, which is a deviation from a stock configuration that an
 * audience can reasonably ask about.
 *
 * So derive the velocity here and hand outnmea_rmc() a solution it can format
 * correctly. Nothing else about the sentence changes.
 *
 * Be plain about what this is: **differencing stands in for the Doppler
 * velocity a real receiver measures.** A real receiver derives velocity from
 * the carrier Doppler shift, independently of its position solution. This is
 * position-derived, which differs in two ways that matter:
 *
 *  - it is noisier, by roughly (position noise)/dt;
 *  - it responds to a *step* in the position solution, which Doppler does not.
 *
 * The second one is this harness's problem specifically: when the malicious
 * 1033 lands, the base coordinate moves and the solution jumps ~2.4 m in a
 * single epoch. Differenced, that is a ~12 m/s velocity spike for one sample,
 * reporting motion that never happened -- an artifact of the method, not of
 * the attack, and not something a Doppler receiver would emit. A median of the
 * last three samples removes an isolated one-epoch outlier exactly, while
 * passing any real acceleration the vehicle can produce at 5 Hz.
 */
#define VELWIN 3

static double med3(double a, double b, double c)
{
    if (a > b) { double t = a; a = b; b = t; }
    if (b > c) { double t = b; b = c; c = t; }
    if (a > b) { double t = a; a = b; b = t; }
    return b;
}

static void derive_vel(sol_t *sol)
{
    static gtime_t prev_time = {0};
    static double prev_rr[3] = {0};
    static double hist[VELWIN][3];
    static int nhist = 0, have_prev = 0;
    double v[3] = {0};
    double dt;
    int i, j;

    dt = have_prev ? timediff(sol->time, prev_time) : 0.0;
    /* A gap means the previous position is too old to difference against:
     * report no velocity rather than a fabricated one. */
    if (have_prev && dt > 0.01 && dt < 2.0) {
        for (j = 0; j < 3; j++) v[j] = (sol->rr[j] - prev_rr[j]) / dt;
    } else {
        nhist = 0;
    }
    prev_time = sol->time;
    for (j = 0; j < 3; j++) prev_rr[j] = sol->rr[j];
    have_prev = 1;

    for (i = VELWIN - 1; i > 0; i--)
        for (j = 0; j < 3; j++) hist[i][j] = hist[i - 1][j];
    for (j = 0; j < 3; j++) hist[0][j] = v[j];
    if (nhist < VELWIN) nhist++;

    /* Until the window is full there is nothing to reject a spike with, so
     * emit zero rather than a value that might be one. */
    for (j = 0; j < 3; j++)
        sol->rr[3 + j] = nhist < VELWIN ? 0.0
                       : med3(hist[0][j], hist[1][j], hist[2][j]);
}

/*
 * RMC, formatted here rather than by RTKLIB's outnmea_rmc().
 * =========================================================
 *
 * Everything about outnmea_rmc() is reusable except one line:
 *
 *     if (vel>=1.0) { dir=...; dirp=dir; } else dir=dirp;
 *
 * Below 1 m/s it reports the *previous* course, and `dirp` starts at 0.0. A
 * consumer that rebuilds velocity as speed x course -- which is what
 * ArduPilot's NMEA driver does -- then gets a vector with the right length
 * pointing the wrong way. Measured: fed 0.5 m/s due east, the RMC reports
 * 0.499 m/s on a course of 0.0 degrees, a 90 degree error.
 *
 * That is worse than noise, because it is a *consistent* error the EKF
 * integrates rather than averages away, and a hovering multirotor lives
 * entirely in the sub-1 m/s band. With RTKLIB's RMC and a derived speed the
 * aircraft oscillated +-3 m while holding; the waypoint leg, flown above
 * 1 m/s where the course is live, was unaffected.
 *
 * So: same sentence, same field layout, course computed at every speed.
 */
static int own_rmc(uint8_t *buff, const sol_t *sol)
{
    static double dirp = 0.0;
    gtime_t time;
    double ep[6], pos[3], enuv[3], dms1[3], dms2[3], vel, dir, amag = 0.0;
    char *p = (char *)buff, *q, sum;
    const char *emag = "E", *mode = "A", *status = "V";

    if (sol->stat <= SOLQ_NONE) return 0;

    time = gpst2utc(sol->time);
    if (time.sec >= 0.995) { time.time++; time.sec = 0.0; }
    time2epoch(time, ep);
    ecef2pos(sol->rr, pos);
    ecef2enu(pos, sol->rr + 3, enuv);
    /* Ground speed is horizontal: enuv is [E,N,U] and the vertical rate has
     * no business in RMC. RTKLIB uses norm(enuv,3) here, which folds climb
     * rate into the reported ground speed. */
    vel = norm(enuv, 2);
    /* A deadband, not a latch: below it the vector is too short for its
     * direction to mean anything, and holding the last bearing on a ~0 m/s
     * speed contributes ~0 velocity either way. */
    if (vel >= 0.05) {
        dir = atan2(enuv[0], enuv[1]) * R2D;
        if (dir < 0.0) dir += 360.0;
        dirp = dir;
    } else {
        dir = dirp;
    }
    if      (sol->stat == SOLQ_DGPS  || sol->stat == SOLQ_SBAS) mode = "D";
    else if (sol->stat == SOLQ_FLOAT || sol->stat == SOLQ_FIX)  mode = "R";
    else if (sol->stat == SOLQ_PPP)                             mode = "P";
    deg2dms(fabs(pos[0]) * R2D, dms1, 7);
    deg2dms(fabs(pos[1]) * R2D, dms2, 7);
    p += sprintf(p, "$%sRMC,%02.0f%02.0f%05.2f,A,%02.0f%010.7f,%s,%03.0f%010.7f,"
                 "%s,%4.2f,%4.2f,%02.0f%02.0f%02d,%.1f,%s,%s,%s",
                 NMEA_TID, ep[3], ep[4], ep[5], dms1[0], dms1[1] + dms1[2] / 60.0,
                 pos[0] >= 0 ? "N" : "S", dms2[0], dms2[1] + dms2[2] / 60.0,
                 pos[1] >= 0 ? "E" : "W", vel / KNOT2M, dir, ep[2], ep[1],
                 (int)ep[0] % 100, amag, emag, mode, status);
    for (q = (char *)buff + 1, sum = 0; *q; q++) sum ^= *q;
    p += sprintf(p, "*%02X\r\n", sum);
    return p - (char *)buff;
}

int main(int argc, char **argv)
{
    prcopt_t prcopt = prcopt_default;
    solopt_t solopt[2];
    stream_t moni;
    char errmsg[2048] = "";
    char *paths[8], *cmds[3] = {NULL, NULL, NULL};
    char *cmds_periodic[3] = {NULL, NULL, NULL};
    char *rcvopts[3];
    char ropt[3][64] = {{0}, {0}, {0}};
    int strs[8] = {0}, formats[8] = {0};
    double nmeapos[3] = {0};
    int i, secs = 20, speed = 400, nout = 0, lastq = -1, serial = 0;
    double rb_prev[3] = {0};
    char rovpath[1100], basepath[1100];
    /* NMEA_VEL: the harness formats the sentences, so it can supply the
     * solution velocity RTKLIB's server never populates. */
    int own_nmea = getenv("NMEA_VEL") != NULL;
    const char *nmea_path = NULL;
    static ssat_t ssat[MAXSAT];
    uint8_t nbuf[4096];
    int nsent = 0;

    if (argc < 3) {
        fprintf(stderr,
                "usage: %s <rover> <base> [seconds] [speed] [file|serial]\n",
                argv[0]);
        return 1;
    }
    if (argc >= 4) secs = atoi(argv[3]);
    if (argc >= 5) speed = atoi(argv[4]);
    if (argc >= 6) serial = !strcmp(argv[5], "serial");

    solopt[0] = solopt_default;
    solopt[1] = solopt_default;
    solopt[0].posf = SOLF_LLH;
    /* NMEA_OUT=<path> emits the solution as NMEA instead, so it can be fed
     * to an autopilot as an ordinary GPS. GGA carries a fix-quality field
     * (4 = RTK fixed), which is what makes the "still reports fixed"
     * property survive all the way to the consumer. */
    if (getenv("NMEA_OUT")) solopt[0].posf = SOLF_NMEA;
    solopt[0].timef = 1;
    solopt[0].sstat = 0;

    /* RTK kinematic, GPS only, base position taken from the correction
     * stream -- the configuration the 1033 attack targets. */
    prcopt.mode    = PMODE_KINEMA;
    prcopt.navsys  = SYS_GPS;
    prcopt.nf      = 1;
    prcopt.elmin   = 15.0 * D2R;
    prcopt.modear  = ARMODE_CONT;
    prcopt.refpos  = POSOPT_RTCM;   /* <- base position from RTCM */
    prcopt.rovpos  = POSOPT_SINGLE;

    /*
     * DYNAMICS=1 adds velocity states to the filter. It was tried as the fix
     * for the zero-velocity RMC and does NOT work: the solution velocity is
     * identically zero with it on and off, measured against a rover fed a
     * known 1 m/s ramp. NMEA_VEL is the actual answer -- see derive_vel().
     * Kept as a knob because the harness prints the solution speed, and this
     * is the thing to re-check if RTKLIB's filter is ever fixed upstream.
     *
     * Off by default so the file and serial runs documented in README.md
     * reproduce byte for byte.
     */
    if (getenv("DYNAMICS")) prcopt.dynamics = 1;

    if (serial || (argc >= 6 && !strcmp(argv[5], "tcp"))) {
        /* Paths are used verbatim; an external feeder paces the bytes. */
        snprintf(rovpath, sizeof(rovpath), "%s", argv[1]);
        snprintf(basepath, sizeof(basepath), "%s", argv[2]);
    } else {
        /* ::T uses the companion .tag file, ::x<n> multiplies replay speed. The
         * dataset is 30 s epochs over an hour, so it needs compressing to run in
         * seconds -- but it must still be paced, not dumped in one read. */
        snprintf(rovpath, sizeof(rovpath), "%s::T::x%d", argv[1], speed);
        snprintf(basepath, sizeof(basepath), "%s::T::x%d", argv[2], speed);
    }

    if (!strcmp(argv[argc > 5 ? 5 : 1], "tcp") ||
        (argc >= 6 && !strcmp(argv[5], "tcp"))) {
        strs[0] = strs[1] = STR_TCPCLI;
    } else {
        strs[0] = serial ? STR_SERIAL : STR_FILE;
        strs[1] = serial ? STR_SERIAL : STR_FILE;
    }
    paths[0] = rovpath;  formats[0] = STRFMT_RTCM3;
    paths[1] = basepath; formats[1] = STRFMT_RTCM3;
    for (i = 2; i < 8; i++) { strs[i] = STR_NONE; paths[i] = (char *)""; }
    if (getenv("NMEA_OUT")) {
        strs[3] = STR_FILE;              /* solution output 1 */
        paths[3] = getenv("NMEA_OUT");
    }
    /* NMEA_TCP=:port serves the solution so an autopilot can connect to it. */
    if (getenv("NMEA_TCP")) {
        nmea_path = getenv("NMEA_TCP");
        if (own_nmea) {
            /* The harness writes the sentences below; RTKLIB's own solution
             * stream stays off so there is exactly one writer on the port. */
            strs[3] = STR_NONE;
            paths[3] = (char *)"";
            solopt[0].posf = SOLF_LLH;
        } else {
            solopt[0].posf = SOLF_NMEA;
            strs[3] = STR_TCPSVR;
            paths[3] = getenv("NMEA_TCP");
        }
    }
    if (own_nmea && !nmea_path) {
        fprintf(stderr, "NMEA_VEL set without NMEA_TCP -- nothing to write to\n");
        return 1;
    }

    for (i = 0; i < 3; i++) rcvopts[i] = ropt[i];

    /* TRACE_LEVEL=<n> writes RTKLIB's own trace to e2e.trace (needs -DTRACE) */
    if (getenv("TRACE_LEVEL")) {
        traceopen("e2e.trace");
        tracelevel(atoi(getenv("TRACE_LEVEL")));
    }

    strinit(&moni);
    rtksvrinit(&svr);

    if (!rtksvrstart(&svr, 10, 32768, strs, paths, formats, 1, cmds,
                     cmds_periodic, rcvopts, 0, 0, nmeapos, &prcopt,
                     solopt, &moni, errmsg)) {
        fprintf(stderr, "rtksvrstart failed: %s\n", errmsg);
        return 1;
    }

    if (own_nmea) {
        strinit(&nmeastr);
        if (!stropen(&nmeastr, STR_TCPSVR, STR_MODE_W, nmea_path)) {
            fprintf(stderr, "cannot serve NMEA on %s\n", nmea_path);
            rtksvrstop(&svr, cmds);
            return 1;
        }
        printf("serving harness-formatted NMEA on %s "
               "(velocity by differencing)\n", nmea_path);
    }

    printf("%-10s %-3s %-14s %-15s %-10s %s\n",
           "time", "Q", "lat", "lon", "height", "base position (rtk.rb)");

    for (i = 0; i < secs * 10; i++) {
        sleepms(100);

        rtksvrlock(&svr);
        {
            int n = svr.nsol;
            sol_t sol = svr.rtk.sol;
            double rb[3];
            int j;
            for (j = 0; j < 3; j++) rb[j] = svr.rtk.rb[j];
            if (own_nmea) memcpy(ssat, svr.rtk.ssat, sizeof(ssat));
            svr.nsol = 0;
            rtksvrunlock(&svr);

            if (own_nmea && n > 0 && sol.stat != SOLQ_NONE) {
                /* Same sentences, and the same order, RTKLIB's solution
                 * stream would have written. GGA/GSA/GSV are RTKLIB's own
                 * and byte-identical; only RMC is ours -- see own_rmc(). */
                uint8_t *p = nbuf;
                derive_vel(&sol);
                p += own_rmc(p, &sol);
                p += outnmea_gga(p, &sol);
                p += outnmea_gsa(p, &sol, ssat);
                p += outnmea_gsv(p, &sol, ssat);
                strwrite(&nmeastr, nbuf, (int)(p - nbuf));
                nsent++;
            }

            if (n > 0 && sol.stat != SOLQ_NONE) {
                double pos[3];
                char tstr[32];
                ecef2pos(sol.rr, pos);
                time2str(sol.time, tstr, 1);
                if (getenv("PRINT_ALL") || sol.stat != lastq || nout < 3 ||
                    fabs(rb[0] - rb_prev[0]) > 1e-6) {
                    /* Solution speed is printed because the NMEA RMC the
                     * autopilot consumes derives its speed from it, and a
                     * receiver reporting 0 knots while the vehicle moves
                     * destabilises the vehicle. It is only non-zero when
                     * velocity states exist -- see DYNAMICS above. */
                    printf("%-10s %-3d %14.9f %15.9f %10.4f  %.3f %.3f %.3f"
                           "  v=%.3f\n",
                           tstr + 11, sol.stat, pos[0] * R2D, pos[1] * R2D,
                           pos[2], rb[0], rb[1], rb[2], norm(sol.rr + 3, 3));
                }
                lastq = sol.stat;
                for (j = 0; j < 3; j++) rb_prev[j] = rb[j];
                nout++;
            }
        }
    }

    if (own_nmea) {
        printf("\nNMEA epochs written: %d\n", nsent);
        strclose(&nmeastr);
    }
    printf("\nsolutions emitted: %d\n", nout);
    printf("final base position: %.4f %.4f %.4f\n",
           svr.rtk.rb[0], svr.rtk.rb[1], svr.rtk.rb[2]);
    printf("obs msgs: rover=%u base=%u   eph msgs: rover=%u base=%u\n",
           svr.nmsg[0][0], svr.nmsg[1][0], svr.nmsg[0][1], svr.nmsg[1][1]);
    printf("antpos msgs: rover=%u base=%u   nav.n=%d  prcout=%d\n",
           svr.nmsg[0][4], svr.nmsg[1][4], svr.nav.n, svr.prcout);
    printf("last solution status=%d  rover obs n=%d base obs n=%d\n",
           svr.rtk.sol.stat, svr.obs[0][0].n, svr.obs[1][0].n);
    if (*svr.rtk.errbuf) printf("rtk errmsg: %.200s\n", svr.rtk.errbuf);

    rtksvrstop(&svr, cmds);
    rtksvrfree(&svr);
    return 0;
}
