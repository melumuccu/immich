import { getCleanerConfig } from './config';
import { getCleanerDatabase } from './database';
import { parseTakenDateFilter } from './date-filter';
import { HttpError } from './errors';
import { searchSmartAssets, trashImmichAssets } from './immich';
import type { CleanerAsset, SearchPage, SmartSearchAsset, TrashResult } from './types';
import { scoreForThreshold } from '$lib/score';

const SEARCH_CACHE_MS = 5 * 60 * 1000;

type SearchCacheEntry = {
  expiresAt: number;
  assets: SmartSearchAsset[];
};

const searchCache = new Map<string, SearchCacheEntry>();

export async function searchCleanerAssets(input: {
  query: unknown;
  page: unknown;
  pageSize: unknown;
  includeExcluded: unknown;
  size: unknown;
  year: unknown;
  month: unknown;
}): Promise<SearchPage> {
  const config = getCleanerConfig();
  const query = parseQuery(input.query);
  const pageSize = parseInteger(input.pageSize, 100, 1, 500);
  const requestedPage = parseInteger(input.page, 1, 1, 100000);
  const searchSize = parseInteger(input.size, config.defaultSearchSize, 1, 5000);
  const dateFilter = parseTakenDateFilter({ year: input.year, month: input.month });
  const includeExcluded = Boolean(input.includeExcluded);
  const db = getCleanerDatabase(config.dbPath);
  const assets = await getSearchAssets(config, db, query, searchSize, dateFilter);
  const exclusions = db.listExclusions(assets.map((asset) => asset.id));
  const decorated = assets.map((asset): CleanerAsset => {
    const exclusion = exclusions.get(asset.id);
    return {
      ...asset,
      thumbnailUrl: `/api/proxy/thumbnail/${encodeURIComponent(asset.id)}`,
      isExcluded: Boolean(exclusion),
      exclusionReason: exclusion?.reason ?? null
    };
  });
  const visibleAssets = includeExcluded ? decorated : decorated.filter((asset) => !asset.isExcluded);
  const totalItems = visibleAssets.length;
  const totalPages = Math.max(1, Math.ceil(totalItems / pageSize));
  const page = Math.min(requestedPage, totalPages);
  const start = (page - 1) * pageSize;

  return {
    query,
    page,
    pageSize,
    totalItems,
    totalPages,
    includeExcluded,
    searchSize,
    items: visibleAssets.slice(start, start + pageSize)
  };
}

export async function trashAssetsByThreshold(input: {
  query: unknown;
  threshold: unknown;
  size: unknown;
  year: unknown;
  month: unknown;
}): Promise<TrashResult> {
  const config = getCleanerConfig();
  const query = parseQuery(input.query);
  const threshold = parseThreshold(input.threshold);
  const searchSize = parseInteger(input.size, config.defaultSearchSize, 1, 5000);
  const dateFilter = parseTakenDateFilter({ year: input.year, month: input.month });
  const db = getCleanerDatabase(config.dbPath);
  const assets = await getSearchAssets(config, db, query, searchSize, dateFilter);
  const exclusions = db.listExclusions(assets.map((asset) => asset.id));
  const meetsThreshold = (asset: SmartSearchAsset) => scoreForThreshold(asset.score) >= threshold;
  const targets = assets.filter((asset) => meetsThreshold(asset) && !asset.isDeleted && !exclusions.has(asset.id));
  const skippedExcludedCount = assets.filter((asset) => meetsThreshold(asset) && exclusions.has(asset.id)).length;
  const skippedDeletedCount = assets.filter((asset) => meetsThreshold(asset) && asset.isDeleted).length;

  await trashImmichAssets(
    config,
    targets.map((asset) => asset.id)
  );
  db.recordTrashedAssets(targets.map((asset) => ({ assetId: asset.id, query, score: asset.score })));
  invalidateSearchCache(query);

  return {
    query,
    threshold,
    movedCount: targets.length,
    skippedExcludedCount,
    skippedDeletedCount,
    ids: targets.map((asset) => asset.id)
  };
}

export async function trashAssetsByIds(input: {
  query: unknown;
  assetIds: unknown;
  size: unknown;
  year: unknown;
  month: unknown;
}): Promise<TrashResult> {
  const config = getCleanerConfig();
  const query = parseQuery(input.query);
  const assetIds = parseAssetIds(input.assetIds);
  const searchSize = parseInteger(input.size, config.defaultSearchSize, 1, 5000);
  const dateFilter = parseTakenDateFilter({ year: input.year, month: input.month });
  const db = getCleanerDatabase(config.dbPath);
  const assets = await getSearchAssets(config, db, query, searchSize, dateFilter);
  const selectedIds = new Set(assetIds);
  const selectedAssets = assets.filter((asset) => selectedIds.has(asset.id));
  const targets = selectedAssets.filter((asset) => !asset.isDeleted);
  const skippedDeletedCount = selectedAssets.length - targets.length;

  await trashImmichAssets(
    config,
    targets.map((asset) => asset.id)
  );
  db.recordTrashedAssets(targets.map((asset) => ({ assetId: asset.id, query, score: asset.score })));
  invalidateSearchCache(query);

  return {
    query,
    threshold: null,
    movedCount: targets.length,
    skippedExcludedCount: 0,
    skippedDeletedCount,
    ids: targets.map((asset) => asset.id)
  };
}

export function setAssetExclusion(assetId: string) {
  const config = getCleanerConfig();
  const db = getCleanerDatabase(config.dbPath);
  invalidateSearchCache();
  return db.upsertExclusion(assetId, 'manual');
}

export function clearAssetExclusion(assetId: string) {
  const config = getCleanerConfig();
  const db = getCleanerDatabase(config.dbPath);
  invalidateSearchCache();
  db.deleteExclusion(assetId);
}

async function getSearchAssets(
  config: ReturnType<typeof getCleanerConfig>,
  db: ReturnType<typeof getCleanerDatabase>,
  query: string,
  size: number,
  dateFilter: ReturnType<typeof parseTakenDateFilter>
): Promise<SmartSearchAsset[]> {
  const key = cacheKey(query, size, dateFilter.cacheKey);
  const cached = searchCache.get(key);
  if (cached && cached.expiresAt > Date.now()) {
    return cached.assets;
  }

  const assets = await searchSmartAssets(config, query, size, dateFilter);
  db.markRescuedAssets(assets);
  searchCache.set(key, {
    assets,
    expiresAt: Date.now() + SEARCH_CACHE_MS
  });
  return assets;
}

function invalidateSearchCache(query?: string): void {
  if (!query) {
    searchCache.clear();
    return;
  }

  for (const key of searchCache.keys()) {
    if (key.startsWith(`${query}\u0000`)) {
      searchCache.delete(key);
    }
  }
}

function cacheKey(query: string, size: number, dateFilterKey: string): string {
  return `${query}\u0000${size}\u0000${dateFilterKey}`;
}

function parseQuery(value: unknown): string {
  if (typeof value !== 'string' || !value.trim()) {
    throw new HttpError(400, 'query is required');
  }
  return value.trim();
}

function parseThreshold(value: unknown): number {
  const threshold = typeof value === 'number' ? value : Number.parseFloat(String(value ?? ''));
  if (!Number.isFinite(threshold) || threshold < 0 || threshold > 1) {
    throw new HttpError(400, 'threshold must be between 0 and 1');
  }
  return threshold;
}

function parseAssetIds(value: unknown): string[] {
  if (!Array.isArray(value)) {
    throw new HttpError(400, 'assetIds is required');
  }

  const assetIds = [
    ...new Set(value.filter((item): item is string => typeof item === 'string' && item.trim().length > 0))
  ];
  if (assetIds.length === 0) {
    throw new HttpError(400, 'assetIds is required');
  }
  return assetIds;
}

function parseInteger(value: unknown, fallback: number, min: number, max: number): number {
  const parsed = typeof value === 'number' ? value : Number.parseInt(String(value ?? ''), 10);
  if (!Number.isFinite(parsed)) {
    return fallback;
  }
  return Math.min(Math.max(Math.trunc(parsed), min), max);
}
