import { describe, expect, it } from 'vitest';

import { isHeicImage } from './image-conversion';

describe('isHeicImage', () => {
  it('detects HEIC by content type', () => {
    expect(isHeicImage('image/heic', new Uint8Array())).toBe(true);
    expect(isHeicImage('image/heif; charset=binary', new Uint8Array())).toBe(true);
  });

  it('detects HEIC by the HEIF ftyp brand', () => {
    expect(isHeicImage('application/octet-stream', makeFtypBuffer('heic'))).toBe(true);
    expect(isHeicImage('image/jpeg', makeFtypBuffer('mif1', 'heic'))).toBe(true);
  });

  it('ignores non-HEIF images', () => {
    expect(isHeicImage('image/jpeg', new Uint8Array([0xff, 0xd8, 0xff]))).toBe(false);
    expect(isHeicImage('application/octet-stream', makeFtypBuffer('avif'))).toBe(false);
    expect(isHeicImage('image/avif', makeFtypBuffer('avif', 'mif1'))).toBe(false);
  });
});

function makeFtypBuffer(majorBrand: string, compatibleBrand = majorBrand): Uint8Array {
  const bytes = new Uint8Array(24);
  writeAscii(bytes, 4, 'ftyp');
  writeAscii(bytes, 8, majorBrand);
  writeAscii(bytes, 16, compatibleBrand);
  return bytes;
}

function writeAscii(bytes: Uint8Array, offset: number, value: string): void {
  for (let index = 0; index < value.length; index += 1) {
    bytes[offset + index] = value.charCodeAt(index);
  }
}
