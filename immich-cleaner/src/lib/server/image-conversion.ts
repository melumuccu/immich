import { spawn } from 'node:child_process';

const HEIF_BRANDS = new Set([
  'heic',
  'heix',
  'hevc',
  'hevx',
  'heim',
  'heis',
  'hevm',
  'hevs'
]);

export function isHeicImage(contentType: string, body: ArrayBuffer | Uint8Array): boolean {
  const normalizedContentType = contentType.toLowerCase().split(';', 1)[0]?.trim();
  if (normalizedContentType === 'image/heic' || normalizedContentType === 'image/heif') {
    return true;
  }

  const bytes = toUint8Array(body);
  if (bytes.byteLength < 12) {
    return false;
  }

  const boxType = textDecoder.decode(bytes.subarray(4, 8));
  if (boxType !== 'ftyp') {
    return false;
  }

  const majorBrand = textDecoder.decode(bytes.subarray(8, 12));
  if (HEIF_BRANDS.has(majorBrand)) {
    return true;
  }

  for (let offset = 16; offset + 4 <= Math.min(bytes.byteLength, 64); offset += 4) {
    const brand = textDecoder.decode(bytes.subarray(offset, offset + 4));
    if (HEIF_BRANDS.has(brand)) {
      return true;
    }
  }

  return false;
}

export async function convertHeicToJpeg(body: ArrayBuffer | Uint8Array): Promise<ArrayBuffer> {
  const output = await runImageMagickConvert(toUint8Array(body));
  return toArrayBuffer(output);
}

const textDecoder = new TextDecoder('ascii');

function toUint8Array(body: ArrayBuffer | Uint8Array): Uint8Array {
  if (body instanceof Uint8Array) {
    return body;
  }
  return new Uint8Array(body);
}

function toArrayBuffer(body: ArrayBuffer | Uint8Array): ArrayBuffer {
  if (body instanceof ArrayBuffer) {
    return body;
  }
  return body.buffer.slice(body.byteOffset, body.byteOffset + body.byteLength) as ArrayBuffer;
}

function runImageMagickConvert(input: Uint8Array): Promise<Buffer> {
  return new Promise((resolve, reject) => {
    const child = spawn('convert', ['heic:-', '-auto-orient', '-quality', '92', 'jpg:-'], {
      stdio: ['pipe', 'pipe', 'pipe']
    });
    const stdoutChunks: Buffer[] = [];
    const stderrChunks: Buffer[] = [];

    child.stdout.on('data', (chunk: Buffer) => {
      stdoutChunks.push(chunk);
    });
    child.stderr.on('data', (chunk: Buffer) => {
      stderrChunks.push(chunk);
    });
    child.on('error', (error) => {
      reject(new Error(`ImageMagick convert を起動できません: ${error.message}`));
    });
    child.on('close', (code) => {
      if (code === 0) {
        resolve(Buffer.concat(stdoutChunks));
        return;
      }

      const stderr = Buffer.concat(stderrChunks).toString('utf8').trim();
      reject(new Error(`ImageMagick convert failed (${code ?? 'unknown'}): ${stderr}`));
    });

    child.stdin.end(input);
  });
}
