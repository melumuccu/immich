import { env } from '$env/dynamic/private';

export const DEFAULT_KEYWORD_PRESETS = [
  'screenshot',
  'document',
  'blurry photo',
  'too dark'
] as const;

export type CleanerConfig = {
  immichUrl: string;
  immichApiKey: string;
  apiPrefix: string;
  dbPath: string;
  searchSmartPath: string;
  assetsPath: string;
  trashPath: string;
  trashMethod: 'DELETE' | 'PUT' | 'PATCH';
  trashForce: boolean;
  defaultSearchSize: number;
};

type EnvSource = Record<string, string | undefined>;

const DEFAULT_DB_PATH = '/app/data/immich-cleaner.sqlite3';

export function getCleanerConfig(envSource: EnvSource = env): CleanerConfig {
  const immichUrl = readRequired(envSource, 'IMMICH_URL').replace(/\/+$/, '');
  const immichApiKey = readRequired(envSource, 'IMMICH_API_KEY');
  const trashMethod = readText(envSource, 'IMMICH_CLEANER_TRASH_METHOD', 'DELETE').toUpperCase();

  if (!['DELETE', 'PUT', 'PATCH'].includes(trashMethod)) {
    throw new Error('IMMICH_CLEANER_TRASH_METHOD must be DELETE, PUT, or PATCH');
  }

  return {
    immichUrl,
    immichApiKey,
    apiPrefix: normalizeApiPrefix(readText(envSource, 'IMMICH_API_PREFIX', '/api')),
    dbPath: readText(envSource, 'IMMICH_CLEANER_DB_PATH', DEFAULT_DB_PATH),
    searchSmartPath: readText(envSource, 'IMMICH_CLEANER_SEARCH_SMART_PATH', 'search/smart'),
    assetsPath: readText(envSource, 'IMMICH_CLEANER_ASSETS_PATH', 'assets'),
    trashPath: readText(envSource, 'IMMICH_CLEANER_TRASH_PATH', 'assets'),
    trashMethod: trashMethod as CleanerConfig['trashMethod'],
    trashForce: readBoolean(envSource, 'IMMICH_CLEANER_TRASH_FORCE', false),
    defaultSearchSize: readInteger(envSource, 'IMMICH_CLEANER_SEARCH_SIZE', 1000, 1, 5000)
  };
}

export function getPublicConfig(envSource: EnvSource = env) {
  return {
    configured: Boolean(envSource.IMMICH_URL && envSource.IMMICH_API_KEY),
    presets: DEFAULT_KEYWORD_PRESETS,
    defaultSearchSize: readInteger(envSource, 'IMMICH_CLEANER_SEARCH_SIZE', 1000, 1, 5000),
    trashMethod: readText(envSource, 'IMMICH_CLEANER_TRASH_METHOD', 'DELETE').toUpperCase()
  };
}

function readRequired(envSource: EnvSource, key: string): string {
  const value = envSource[key]?.trim();
  if (!value) {
    throw new Error(`${key} is required`);
  }
  return value;
}

function readText(envSource: EnvSource, key: string, fallback: string): string {
  const value = envSource[key]?.trim();
  return value || fallback;
}

function readBoolean(envSource: EnvSource, key: string, fallback: boolean): boolean {
  const value = envSource[key]?.trim().toLowerCase();
  if (!value) {
    return fallback;
  }
  return ['1', 'true', 'yes', 'on'].includes(value);
}

function readInteger(
  envSource: EnvSource,
  key: string,
  fallback: number,
  min: number,
  max: number
): number {
  const value = Number.parseInt(envSource[key] ?? '', 10);
  if (!Number.isFinite(value)) {
    return fallback;
  }
  return Math.min(Math.max(value, min), max);
}

function normalizeApiPrefix(value: string): string {
  const normalized = value.trim().replace(/^\/+|\/+$/g, '');
  return normalized || 'api';
}
