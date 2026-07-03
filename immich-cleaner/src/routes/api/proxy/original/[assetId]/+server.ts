import { getCleanerConfig } from '$lib/server/config';
import { fetchImmichOriginal } from '$lib/server/immich';
import { jsonFailure } from '$lib/server/response';

export async function GET({ params }) {
  try {
    const original = await fetchImmichOriginal(getCleanerConfig(), params.assetId);
    const headers = new Headers({
      'content-type': original.contentType,
      'cache-control': original.cacheControl ?? 'private, max-age=60'
    });

    if (original.etag) {
      headers.set('etag', original.etag);
    }

    return new Response(original.body, { headers });
  } catch (error) {
    return jsonFailure(error);
  }
}
