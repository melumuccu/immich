import { describe, expect, it } from 'vitest';

import { parseTakenDateFilter } from './date-filter';

describe('parseTakenDateFilter', () => {
  it('returns an empty filter when year and month are cleared', () => {
    expect(parseTakenDateFilter({ year: null, month: null })).toEqual({
      year: null,
      month: null,
      cacheKey: 'all'
    });
  });

  it('builds a month date range', () => {
    expect(parseTakenDateFilter({ year: '2026', month: '5' })).toEqual({
      year: 2026,
      month: 5,
      takenAfter: '2026-05-01T00:00:00.000Z',
      takenBefore: '2026-06-01T00:00:00.000Z',
      cacheKey: '2026-5'
    });
  });

  it('builds a full year date range when month is cleared', () => {
    expect(parseTakenDateFilter({ year: 2026, month: '' })).toEqual({
      year: 2026,
      month: null,
      takenAfter: '2026-01-01T00:00:00.000Z',
      takenBefore: '2027-01-01T00:00:00.000Z',
      cacheKey: '2026-all'
    });
  });
});
