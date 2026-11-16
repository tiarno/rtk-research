// serve.ts <file> <port> : TCP server that streams an RTCM3 file to every
// client once a second and logs connections, so we can see who connects.
import { readFileSync } from "fs";
const [file, port] = [process.argv[2], Number(process.argv[3])];
const data = readFileSync(file);
Bun.listen({
  hostname: "127.0.0.1",
  port,
  socket: {
    open(s) {
      console.log(`${new Date().toISOString()} client connected`);
      const t = setInterval(() => { try { s.write(data); } catch { clearInterval(t); } }, 1000);
      (s as any).data = t;
    },
    data(_s, d) { console.log(`client sent ${d.length} bytes: ${d.toString("latin1").slice(0, 80)}`); },
    close(s) { clearInterval((s as any).data); console.log(`${new Date().toISOString()} client closed`); },
  },
});
console.log(`serving ${file} (${data.length} B) on ${port}`);
