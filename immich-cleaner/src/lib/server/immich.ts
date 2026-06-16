import type { CleanerConfig } from './config';
import type { TakenDateFilter } from './date-filter';
import { ImmichRequestError } from './errors';
import type { SmartSearchAsset } from './types';

type JsonRecord = Record<string, unknown>;

export type ThumbnailResponse = {
  body: ArrayBuffer;
  contentType: string;
  cacheControl: string | null;
  etag: string | null;
};

export async function searchSmartAssets(
  config: CleanerConfig,
  query: string,
  size: number,
  dateFilter: TakenDateFilter
) {
  const payload = await requestImmichJson(config, 'POST', config.searchSmartPath, {
    query,
    size,
    type: 'IMAGE',
    ...(dateFilter.takenAfter ? { takenAfter: dateFilter.takenAfter } : {}),
    ...(dateFilter.takenBefore ? { takenBefore: dateFilter.takenBefore } : {}),
    withExif: true
  });

  return normalizeSmartSearchPayload(payload);
}

export async function trashImmichAssets(config: CleanerConfig, assetIds: string[]) {
  if (assetIds.length === 0) {
    return;
  }

  const payload =
    config.trashMethod === 'DELETE'
      ? { ids: assetIds, force: config.trashForce }
      : { ids: assetIds, isDeleted: true };

  await requestImmichJson(config, config.trashMethod, config.trashPath, payload);
}

export async function fetchImmichThumbnail(
  config: CleanerConfig,
  assetId: string,
  params: URLSearchParams
): Promise<ThumbnailResponse> {
  const url = buildImmichApiUrl(config, `${config.assetsPath}/${encodeURIComponent(assetId)}/thumbnail`);
  for (const [key, value] of params) {
    url.searchParams.set(key, value);
  }

  const response = await fetch(url, {
    headers: {
      Accept: '*/*',
      'x-api-key': config.immichApiKey
    }
  });

  if (!response.ok) {
    throw new ImmichRequestError('GET', url.toString(), response.status, await response.text());
  }

  return {
    body: await response.arrayBuffer(),
    contentType: response.headers.get('content-type') ?? 'image/jpeg',
    cacheControl: response.headers.get('cache-control'),
    etag: response.headers.get('etag')
  };
}

export function normalizeSmartSearchPayload(payload: unknown): SmartSearchAsset[] {
  const items = getSearchItems(payload);
  return items
    .map((item, index) => normalizeSmartSearchItem(item, index, items.length))
    .filter((asset): asset is SmartSearchAsset => Boolean(asset))
    .filter((asset) => asset.type === 'IMAGE')
    .sort((left, right) => right.score - left.score);
}

export function buildImmichApiUrl(config: Pick<CleanerConfig, 'immichUrl' | 'apiPrefix'>, path: string): URL {
  const baseUrl = new URL(`${config.immichUrl.replace(/\/+$/, '')}/`);
  const apiPrefix = config.apiPrefix.replace(/^\/+|\/+$/g, '');
  return new URL(`${apiPrefix}/${path.replace(/^\/+/, '')}`, baseUrl);
}

async function requestImmichJson(
  config: CleanerConfig,
  method: string,
  path: string,
  jsonBody: unknown
): Promise<unknown> {
  const url = buildImmichApiUrl(config, path);
  const response = await fetch(url, {
    method,
    headers: {
      Accept: 'application/json',
      'Content-Type': 'application/json',
      'x-api-key': config.immichApiKey
    },
    body: JSON.stringify(jsonBody)
  });

  if (!response.ok) {
    throw new ImmichRequestError(method, url.toString(), response.status, await response.text());
  }

  if (response.status === 204) {
    return null;
  }

  const text = await response.text();
  return text ? JSON.parse(text) : null;
}

function getSearchItems(payload: unknown): unknown[] {
  const root = asRecord(payload);
  const assets = asRecord(root?.assets);
  const candidates = [
    assets?.items,
    root?.items,
    root?.results,
    Array.isArray(payload) ? payload : undefined
  ];

  for (const candidate of candidates) {
    if (Array.isArray(candidate)) {
      return candidate;
    }
  }

  return [];
}

function normalizeSmartSearchItem(item: unknown, index: number, total: number): SmartSearchAsset | null {
  const itemRecord = asRecord(item);
  if (!itemRecord) {
    return null;
  }

  const assetRecord = asRecord(itemRecord.asset) ?? itemRecord;
  const id = toText(assetRecord.id ?? itemRecord.assetId ?? itemRecord.id);
  if (!id) {
    return null;
  }

  const type = toText(assetRecord.type ?? assetRecord.assetType ?? itemRecord.type ?? itemRecord.assetType)
    ?.toUpperCase()
    .trim();

  return {
    id,
    score: readSearchScore(itemRecord, assetRecord, index, total),
    type: type || 'UNKNOWN',
    originalFileName: toText(assetRecord.originalFileName ?? itemRecord.originalFileName),
    originalPath: toText(assetRecord.originalPath ?? itemRecord.originalPath),
    isDeleted: Boolean(
      assetRecord.isDeleted ??
        itemRecord.isDeleted ??
        assetRecord.isTrashed ??
        itemRecord.isTrashed ??
        assetRecord.deletedAt ??
        itemRecord.deletedAt
    )
  };
}

function readSearchScore(itemRecord: JsonRecord, assetRecord: JsonRecord, index: number, total: number): number {
  const directScore = toScore(
    itemRecord.score ??
      assetRecord.score ??
      itemRecord.similarity ??
      assetRecord.similarity ??
      itemRecord.similarityScore ??
      assetRecord.similarityScore
  );
  if (directScore !== null) {
    return clampScore(directScore);
  }

  const distance = toScore(itemRecord.distance ?? assetRecord.distance);
  if (distance !== null) {
    return clampScore(1 - distance);
  }

  return total <= 0 ? 0 : clampScore((total - index) / total);
}

function asRecord(value: unknown): JsonRecord | null {
  return value && typeof value === 'object' && !Array.isArray(value) ? (value as JsonRecord) : null;
}

function toText(value: unknown): string | null {
  if (typeof value === 'string' && value.trim()) {
    return value;
  }
  if (typeof value === 'number' && Number.isFinite(value)) {
    return String(value);
  }
  return null;
}

function toScore(value: unknown): number | null {
  if (typeof value === 'number' && Number.isFinite(value)) {
    return value;
  }
  if (typeof value === 'string') {
    const parsed = Number.parseFloat(value);
    return Number.isFinite(parsed) ? parsed : null;
  }
  return null;
}

function clampScore(value: number): number {
  return Math.min(Math.max(value, 0), 1);
}
