/**
 * zstd 批量解压桥
 *
 * 微信 4.x 的 App 消息（type 49）内容用 zstd 压缩，Python 侧没有可用库，
 * 这里借 Node 22 内置的 zlib.zstdDecompressSync 代劳。
 *
 * 协议（二进制，小端）：
 *   input : [u32 len][bytes]...
 *   output: [u32 len][bytes]...    len=0 表示该条解压失败
 *
 * 用法：node zstd_bridge.js <in.bin> <out.bin>
 */
const fs = require('fs');
const zlib = require('zlib');

const [, , inPath, outPath] = process.argv;
if (!inPath || !outPath) {
  console.error('usage: node zstd_bridge.js <in> <out>');
  process.exit(2);
}

const buf = fs.readFileSync(inPath);
const chunks = [];
let pos = 0;
while (pos + 4 <= buf.length) {
  const len = buf.readUInt32LE(pos);
  pos += 4;
  if (pos + len > buf.length) break;
  const blob = buf.subarray(pos, pos + len);
  pos += len;
  let out = Buffer.alloc(0);
  try {
    out = zlib.zstdDecompressSync(blob);
  } catch (e) {
    out = Buffer.alloc(0);
  }
  const head = Buffer.alloc(4);
  head.writeUInt32LE(out.length, 0);
  chunks.push(head, out);
}

fs.writeFileSync(outPath, Buffer.concat(chunks));
