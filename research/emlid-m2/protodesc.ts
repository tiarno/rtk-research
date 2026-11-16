// protodesc.ts <elf> <proto-file-name> : find the serialized FileDescriptorProto
// embedded in a binary and print its messages/enums/fields as .proto-ish text.
import { readFileSync } from "fs";
const [bin, name] = [process.argv[2], process.argv[3]];
const buf = readFileSync(bin);

function varint(b: Buffer, i: number): [number, number] {
  let r = 0, s = 0, x;
  do { x = b[i++]; r += (x & 0x7f) * 2 ** s; s += 7; } while (x & 0x80);
  return [r, i];
}
type F = { n: number; w: number; v: number | Buffer };
function parse(b: Buffer): F[] {
  const out: F[] = []; let i = 0;
  while (i < b.length) {
    let k; [k, i] = varint(b, i); const n = Math.floor(k / 8), w = k & 7;
    if (w === 0) { let v; [v, i] = varint(b, i); out.push({ n, w, v }); }
    else if (w === 2) { let l; [l, i] = varint(b, i); out.push({ n, w, v: b.subarray(i, i + l) }); i += l; }
    else if (w === 5) { out.push({ n, w, v: b.readUInt32LE(i) }); i += 4; }
    else if (w === 1) { out.push({ n, w, v: 0 }); i += 8; }
    else throw new Error(`bad wire ${w} at ${i}`);
  }
  return out;
}
const str = (f?: F) => (f ? (f.v as Buffer).toString() : "");
const TYPES: Record<number, string> = { 1: "double", 2: "float", 3: "int64", 4: "uint64", 5: "int32", 8: "bool", 9: "string", 12: "bytes", 13: "uint32", 14: "enum", 11: "message", 17: "sint32", 18: "sint64", 6: "fixed64", 7: "fixed32" };

function printEnum(b: Buffer, ind: string) {
  const f = parse(b);
  console.log(`${ind}enum ${str(f.find(x => x.n === 1))} {`);
  for (const v of f.filter(x => x.n === 2)) {
    const vf = parse(v.v as Buffer);
    console.log(`${ind}  ${str(vf.find(x => x.n === 1))} = ${vf.find(x => x.n === 2)?.v ?? 0};`);
  }
  console.log(`${ind}}`);
}
function printMsg(b: Buffer, ind: string) {
  const f = parse(b);
  console.log(`${ind}message ${str(f.find(x => x.n === 1))} {`);
  for (const fld of f.filter(x => x.n === 2)) {
    const ff = parse(fld.v as Buffer);
    const label = ({ 1: "optional", 2: "required", 3: "repeated" } as any)[ff.find(x => x.n === 4)?.v as number] ?? "";
    const t = ff.find(x => x.n === 5)?.v as number;
    const tn = str(ff.find(x => x.n === 6));
    console.log(`${ind}  ${label} ${tn || TYPES[t] || t} ${str(ff.find(x => x.n === 1))} = ${ff.find(x => x.n === 3)?.v};`);
  }
  for (const e of f.filter(x => x.n === 4)) printEnum(e.v as Buffer, ind + "  ");
  for (const m of f.filter(x => x.n === 3)) printMsg(m.v as Buffer, ind + "  ");
  console.log(`${ind}}`);
}

// FileDescriptorProto starts with field 1 (name): 0x0a <len> <name>
const needle = Buffer.concat([Buffer.from([0x0a, name.length]), Buffer.from(name)]);
let at = buf.indexOf(needle);
if (at < 0) throw new Error("descriptor not found");
// Find the end: grow until parse succeeds and covers a sane region; descriptors
// are stored as a contiguous byte array, so try lengths up to 64 KiB.
for (let end = at + 64 * 1024; end > at; end--) {
  try {
    const f = parse(buf.subarray(at, end));
    if (f.every(x => x.n >= 1 && x.n <= 12) && f.some(x => x.n === 4)) {
      console.log(`// ${name} @0x${at.toString(16)} len ${end - at} package ${str(f.find(x => x.n === 2))}`);
      for (const e of f.filter(x => x.n === 5)) printEnum(e.v as Buffer, "");
      for (const m of f.filter(x => x.n === 4)) printMsg(m.v as Buffer, "");
      break;
    }
  } catch {}
}
