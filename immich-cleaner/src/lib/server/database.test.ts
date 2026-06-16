import { mkdtempSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';

import { afterEach, describe, expect, it } from 'vitest';

import { CleanerDatabase } from './database';

let tempDir: string | null = null;

afterEach(() => {
  if (tempDir) {
    rmSync(tempDir, { recursive: true, force: true });
    tempDir = null;
  }
});

function createDb() {
  tempDir = mkdtempSync(join(tmpdir(), 'immich-cleaner-'));
  return new CleanerDatabase(join(tempDir, 'state.sqlite3'));
}

describe('CleanerDatabase', () => {
  it('stores manual exclusions and removes them', () => {
    const db = createDb();

    db.upsertExclusion('asset-1', 'manual');
    expect(db.listExclusions(['asset-1']).get('asset-1')?.reason).toBe('manual');

    db.deleteExclusion('asset-1');
    expect(db.listExclusions(['asset-1']).has('asset-1')).toBe(false);

    db.close();
  });

  it('marks restored trashed assets as rescued exclusions', () => {
    const db = createDb();

    db.recordTrashedAssets([{ assetId: 'asset-1', query: 'blurry photo', score: 0.91 }]);
    const rescued = db.markRescuedAssets([
      {
        id: 'asset-1',
        score: 0.91,
        type: 'IMAGE',
        originalFileName: null,
        originalPath: null,
        isDeleted: false
      }
    ]);

    expect(rescued).toEqual(['asset-1']);
    expect(db.listExclusions(['asset-1']).get('asset-1')?.reason).toBe('rescued');

    db.close();
  });
});
