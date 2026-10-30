import { json } from '@sveltejs/kit';

import { jsonFailure } from '#lib/server/response';
import { clearAssetExclusion, setAssetExclusion } from '#lib/server/service';

export function PUT({ params }) {
  try {
    return json(setAssetExclusion(params.assetId));
  } catch (error) {
    return jsonFailure(error);
  }
}

export function DELETE({ params }) {
  try {
    clearAssetExclusion(params.assetId);
    return json({ ok: true });
  } catch (error) {
    return jsonFailure(error);
  }
}
