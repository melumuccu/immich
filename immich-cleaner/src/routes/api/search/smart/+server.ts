import { json } from '@sveltejs/kit';

import { jsonFailure } from '#lib/server/response';
import { searchCleanerAssets } from '#lib/server/service';

export async function POST({ request }) {
  try {
    const body = await request.json();
    return json(
      await searchCleanerAssets({
        query: body.query,
        page: body.page,
        pageSize: body.pageSize,
        includeExcluded: body.includeExcluded,
        size: body.size,
        year: body.year,
        month: body.month
      })
    );
  } catch (error) {
    return jsonFailure(error);
  }
}
