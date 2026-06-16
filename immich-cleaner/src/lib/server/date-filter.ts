import { HttpError } from './errors';

export type TakenDateFilter = {
  year: number | null;
  month: number | null;
  takenAfter?: string;
  takenBefore?: string;
  cacheKey: string;
};

export function parseTakenDateFilter(input: { year: unknown; month: unknown }): TakenDateFilter {
  const year = parseOptionalInteger(input.year, 'year');
  const month = parseOptionalInteger(input.month, 'month');

  if (year === null && month === null) {
    return { year: null, month: null, cacheKey: 'all' };
  }

  if (year === null) {
    throw new HttpError(400, 'year is required when month is set');
  }

  if (year < 1900 || year > 9999) {
    throw new HttpError(400, 'year must be between 1900 and 9999');
  }

  if (month !== null && (month < 1 || month > 12)) {
    throw new HttpError(400, 'month must be between 1 and 12');
  }

  const startMonth = month === null ? 0 : month - 1;
  const endYear = month === null ? year + 1 : year;
  const endMonth = month === null ? 0 : month;

  return {
    year,
    month,
    takenAfter: new Date(Date.UTC(year, startMonth, 1)).toISOString(),
    takenBefore: new Date(Date.UTC(endYear, endMonth, 1)).toISOString(),
    cacheKey: `${year}-${month ?? 'all'}`
  };
}

function parseOptionalInteger(value: unknown, key: string): number | null {
  if (value === null || value === undefined || value === '') {
    return null;
  }

  const parsed = typeof value === 'number' ? value : Number.parseInt(String(value), 10);
  if (!Number.isInteger(parsed)) {
    throw new HttpError(400, `${key} must be an integer`);
  }
  return parsed;
}
