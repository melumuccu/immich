import { describe, expect, it } from 'vitest';

import { formatScore, scoreForThreshold } from './score';

describe('score display threshold', () => {
  it('uses the same rounded value for display and threshold comparison', () => {
    const score = 0.9989999;

    expect(formatScore(score)).toBe('0.999');
    expect(scoreForThreshold(score)).toBe(0.999);
    expect(scoreForThreshold(score) >= 0.999).toBe(true);
  });
});
