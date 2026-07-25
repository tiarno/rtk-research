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
 *   e2e_harness <rover> <base> [seconds] [speed] [file|serial]
 *
 * With "serial" the two arguments are RTKLIB serial paths
 * (port:baud:bits:parity:stop:fctrl) instead of files, so the same attack can
 * be delivered over a UART -- the transport a UHF/VHF base-rover radio link
 * uses -- rather than over a file or socket. Note RTKLIB prefixes the port
 * with /dev/, so a pty under /tmp is reached as "../tmp/ttyX".
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

    if (serial) {
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

    strs[0] = serial ? STR_SERIAL : STR_FILE;
    strs[1] = serial ? STR_SERIAL : STR_FILE;
    paths[0] = rovpath;  formats[0] = STRFMT_RTCM3;
    paths[1] = basepath; formats[1] = STRFMT_RTCM3;
    for (i = 2; i < 8; i++) { strs[i] = STR_NONE; paths[i] = (char *)""; }
    if (getenv("NMEA_OUT")) {
        strs[3] = STR_FILE;              /* solution output 1 */
        paths[3] = getenv("NMEA_OUT");
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
            svr.nsol = 0;
            rtksvrunlock(&svr);

            if (n > 0 && sol.stat != SOLQ_NONE) {
                double pos[3];
                char tstr[32];
                ecef2pos(sol.rr, pos);
                time2str(sol.time, tstr, 1);
                if (getenv("PRINT_ALL") || sol.stat != lastq || nout < 3 ||
                    fabs(rb[0] - rb_prev[0]) > 1e-6) {
                    printf("%-10s %-3d %14.9f %15.9f %10.4f  %.3f %.3f %.3f\n",
                           tstr + 11, sol.stat, pos[0] * R2D, pos[1] * R2D,
                           pos[2], rb[0], rb[1], rb[2]);
                }
                lastq = sol.stat;
                for (j = 0; j < 3; j++) rb_prev[j] = rb[j];
                nout++;
            }
        }
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
