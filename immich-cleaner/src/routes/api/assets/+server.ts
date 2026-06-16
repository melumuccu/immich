import { json } from '@sveltejs/kit';

import { jsonFailure } from '$lib/server/response';
import { trashAssetsByIds, trashAssetsByThreshold } from '$lib/server/service';

export async function PUT({ request }) {
  try {
    const body = await request.json();
    if (Array.isArray(body.assetIds)) {
      return json(
        await trashAssetsByIds({
          query: body.query,
          assetIds: body.assetIds,
          size: body.size,
          year: body.year,
          month: body.month
        })
      );
    }

    return json(
      await trashAssetsByThreshold({
        query: body.query,
        threshold: body.threshold,
        size: body.size,
        year: body.year,
        month: body.month
      })
    );
  } catch (error) {
    return jsonFailure(error);
  }
}
