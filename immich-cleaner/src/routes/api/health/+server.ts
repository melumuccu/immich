import { json } from '@sveltejs/kit';

import { getPublicConfig } from '$lib/server/config';

export function GET() {
  return json({
    ok: true,
    configured: getPublicConfig().configured
  });
}
