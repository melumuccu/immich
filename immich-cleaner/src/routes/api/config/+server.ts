import { json } from '@sveltejs/kit';

import { getPublicConfig } from '#lib/server/config';

export function GET() {
  return json(getPublicConfig());
}
