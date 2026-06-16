import { describe, expect, it } from 'vitest';

import { buildImmichApiUrl, normalizeSmartSearchPayload } from './immich';

describe('normalizeSmartSearchPayload', () => {
  it('keeps images and sorts them by score descending', () => {
    const assets = normalizeSmartSearchPayload({
      assets: {
        items: [
          { id: 'video-1', type: 'VIDEO', score: 0.99 },
          { id: 'image-low', type: 'IMAGE', score: 0.25 },
          {
            asset: {
              id: 'image-high',
              type: 'IMAGE',
              originalFileName: 'IMG_001.JPG',
              isTrashed: false
            },
            score: 0.91
          }
        ]
      }
    });

    expect(assets.map((asset) => asset.id)).toEqual(['image-high', 'image-low']);
    expect(assets[0].originalFileName).toBe('IMG_001.JPG');
  });

  it('uses distance or search rank when Immich does not include a score field', () => {
    const distanceAssets = normalizeSmartSearchPayload({
      assets: {
        items: [
          { id: 'image-far', type: 'IMAGE', distance: 0.8 },
          { id: 'image-near', type: 'IMAGE', distance: 0.2 }
        ]
      }
    });

    expect(distanceAssets.map((asset) => asset.id)).toEqual(['image-near', 'image-far']);
    expect(distanceAssets[0].score).toBeCloseTo(0.8);
    expect(distanceAssets[1].score).toBeCloseTo(0.2);

    const rankedAssets = normalizeSmartSearchPayload({
      assets: {
        items: [
          { id: 'first', type: 'IMAGE' },
          { id: 'second', type: 'IMAGE' },
          { id: 'third', type: 'IMAGE' }
        ]
      }
    });

    expect(rankedAssets.map((asset) => asset.score)).toEqual([1, 2 / 3, 1 / 3]);
  });
});

describe('buildImmichApiUrl', () => {
  it('preserves a base path and normalizes api prefixes', () => {
    const url = buildImmichApiUrl(
      {
        immichUrl: 'http://immich.local/photos/',
        apiPrefix: '/api/'
      },
      '/assets/asset-1/thumbnail'
    );

    expect(url.toString()).toBe('http://immich.local/photos/api/assets/asset-1/thumbnail');
  });
});
