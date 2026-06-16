import { mkdirSync } from 'node:fs';
import { dirname } from 'node:path';
import { DatabaseSync } from 'node:sqlite';

import type { ExcludedAsset, ExclusionReason, SmartSearchAsset } from './types';

type ExclusionRow = {
  asset_id: string;
  reason: ExclusionReason;
  updated_at: string;
};

type TrashedAssetInput = {
  assetId: string;
  query: string;
  score: number;
};

export class CleanerDatabase {
  readonly db: DatabaseSync;

  constructor(readonly dbPath: string) {
    if (dbPath !== ':memory:') {
      mkdirSync(dirname(dbPath), { recursive: true });
    }
    this.db = new DatabaseSync(dbPath);
    this.db.exec('PRAGMA journal_mode = WAL');
    this.db.exec('PRAGMA foreign_keys = ON');
    this.migrate();
  }

  close(): void {
    this.db.close();
  }

  upsertExclusion(assetId: string, reason: ExclusionReason = 'manual'): ExcludedAsset {
    this.db
      .prepare(
        `
          INSERT INTO excluded_assets (asset_id, reason, updated_at)
          VALUES (?, ?, CURRENT_TIMESTAMP)
          ON CONFLICT(asset_id) DO UPDATE SET
            reason = excluded.reason,
            updated_at = CURRENT_TIMESTAMP
        `
      )
      .run(assetId, reason);

    const row = this.db
      .prepare('SELECT asset_id, reason, updated_at FROM excluded_assets WHERE asset_id = ?')
      .get(assetId) as ExclusionRow;

    return toExcludedAsset(row);
  }

  deleteExclusion(assetId: string): void {
    this.db.prepare('DELETE FROM excluded_assets WHERE asset_id = ?').run(assetId);
  }

  listExclusions(assetIds: string[]): Map<string, ExcludedAsset> {
    const rows: ExclusionRow[] = [];
    for (const chunk of chunks(unique(assetIds), 500)) {
      if (chunk.length === 0) {
        continue;
      }
      const placeholders = chunk.map(() => '?').join(', ');
      rows.push(
        ...(this.db
          .prepare(
            `
              SELECT asset_id, reason, updated_at
              FROM excluded_assets
              WHERE asset_id IN (${placeholders})
            `
          )
          .all(...chunk) as ExclusionRow[])
      );
    }

    return new Map(rows.map((row) => [row.asset_id, toExcludedAsset(row)]));
  }

  recordTrashedAssets(items: TrashedAssetInput[]): void {
    if (items.length === 0) {
      return;
    }

    this.transaction(() => {
      const statement = this.db.prepare(
        `
          INSERT INTO trashed_assets (asset_id, query, score, moved_at, restored_at)
          VALUES (?, ?, ?, CURRENT_TIMESTAMP, NULL)
          ON CONFLICT(asset_id) DO UPDATE SET
            query = excluded.query,
            score = excluded.score,
            moved_at = CURRENT_TIMESTAMP,
            restored_at = NULL
        `
      );

      for (const item of items) {
        statement.run(item.assetId, item.query, item.score);
      }
    });
  }

  markRescuedAssets(assets: SmartSearchAsset[]): string[] {
    const candidates = assets.filter((asset) => !asset.isDeleted);
    const pending = this.listPendingTrashedIds(candidates.map((asset) => asset.id));
    if (pending.length === 0) {
      return [];
    }

    this.transaction(() => {
      const excludedStatement = this.db.prepare(
        `
          INSERT INTO excluded_assets (asset_id, reason, updated_at)
          VALUES (?, 'rescued', CURRENT_TIMESTAMP)
          ON CONFLICT(asset_id) DO UPDATE SET
            reason = 'rescued',
            updated_at = CURRENT_TIMESTAMP
        `
      );
      const trashedStatement = this.db.prepare(
        `
          UPDATE trashed_assets
          SET restored_at = CURRENT_TIMESTAMP
          WHERE asset_id = ?
        `
      );

      for (const assetId of pending) {
        excludedStatement.run(assetId);
        trashedStatement.run(assetId);
      }
    });

    return pending;
  }

  private listPendingTrashedIds(assetIds: string[]): string[] {
    const rows: { asset_id: string }[] = [];
    for (const chunk of chunks(unique(assetIds), 500)) {
      if (chunk.length === 0) {
        continue;
      }
      const placeholders = chunk.map(() => '?').join(', ');
      rows.push(
        ...(this.db
          .prepare(
            `
              SELECT asset_id
              FROM trashed_assets
              WHERE restored_at IS NULL
                AND asset_id IN (${placeholders})
            `
          )
          .all(...chunk) as { asset_id: string }[])
      );
    }
    return rows.map((row) => row.asset_id);
  }

  private migrate(): void {
    this.db.exec(`
      CREATE TABLE IF NOT EXISTS excluded_assets (
        asset_id TEXT PRIMARY KEY,
        reason TEXT NOT NULL DEFAULT 'manual',
        updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
      );

      CREATE TABLE IF NOT EXISTS trashed_assets (
        asset_id TEXT PRIMARY KEY,
        query TEXT NOT NULL,
        score REAL NOT NULL,
        moved_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
        restored_at DATETIME
      );
    `);
  }

  private transaction<T>(callback: () => T): T {
    this.db.exec('BEGIN IMMEDIATE');
    try {
      const value = callback();
      this.db.exec('COMMIT');
      return value;
    } catch (error) {
      this.db.exec('ROLLBACK');
      throw error;
    }
  }
}

let singleton: CleanerDatabase | null = null;

export function getCleanerDatabase(dbPath: string): CleanerDatabase {
  if (singleton?.dbPath !== dbPath) {
    singleton?.close();
    singleton = new CleanerDatabase(dbPath);
  }
  return singleton;
}

function toExcludedAsset(row: ExclusionRow): ExcludedAsset {
  return {
    assetId: row.asset_id,
    reason: row.reason,
    updatedAt: row.updated_at
  };
}

function unique(values: string[]): string[] {
  return [...new Set(values.filter(Boolean))];
}

function chunks<T>(values: T[], size: number): T[][] {
  const result: T[][] = [];
  for (let index = 0; index < values.length; index += size) {
    result.push(values.slice(index, index + size));
  }
  return result;
}
