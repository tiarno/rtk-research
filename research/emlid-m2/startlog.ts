// startlog.ts <input_stream_path> <out_dir> <filename> : publish a GNSSLogger
// StartLoggingRequest (RINEX output, RTCM3 input) on the logger's Redis channel.
import { connect } from "net";
const [inPath, outDir, fname] = process.argv.slice(2);

const varint = (n: number) => { const o: number[] = []; do { let b = n & 0x7f; n = Math.floor(n / 128); if (n) b |= 0x80; o.push(b); } while (n); return Buffer.from(o); };
const tag = (f: number, w: number) => varint(f * 8 + w);
const vint = (f: number, v: number) => Buffer.concat([tag(f, 0), varint(v)]);
const lenf = (f: number, b: Buffer | string) => { const x = Buffer.isBuffer(b) ? b : Buffer.from(b); return Buffer.concat([tag(f, 2), varint(x.length), x]); };

const log = Buffer.concat([vint(1, 2 /*TYPE_RINEX*/), lenf(2, inPath), lenf(3, outDir), lenf(4, fname)]);
const rinex = Buffer.concat([vint(1, 2 /*FMT_RTCM3*/), vint(2, 8 /*VER_3_04*/), vint(3, 0), vint(3, 6), vint(4, 1000), lenf(6, "TEST")]);
const options = Buffer.concat([lenf(1, log), lenf(2, rinex)]);
const start = Buffer.concat([lenf(1, "11111111-2222-3333-4444-555555555555"), lenf(2, options)]);
const any = Buffer.concat([lenf(1, "type.googleapis.com/GNSSLogger.proto.StartLoggingRequest"), lenf(2, start)]);
const req = Buffer.concat([lenf(1, "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"), lenf(2, any)]);

const resp = (parts: (string | Buffer)[]) => Buffer.concat([Buffer.from(`*${parts.length}\r\n`), ...parts.flatMap(p => { const b = Buffer.isBuffer(p) ? p : Buffer.from(p); return [Buffer.from(`$${b.length}\r\n`), b, Buffer.from("\r\n")]; })]);
const s = connect(1500, "127.0.0.1", () => s.write(resp(["PUBLISH", "gnss-logger-request", req])));
s.on("data", d => { console.log("redis:", d.toString().trim()); s.end(); });
