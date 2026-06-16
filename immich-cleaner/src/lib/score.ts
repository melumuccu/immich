export const SCORE_DISPLAY_DIGITS = 3;

export function formatScore(score: number): string {
  return score.toFixed(SCORE_DISPLAY_DIGITS);
}

export function scoreForThreshold(score: number): number {
  return Number(formatScore(score));
}
