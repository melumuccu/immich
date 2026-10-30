import { getCleanerConfig } from '#lib/server/config';
import { fetchImmichThumbnail } from '#lib/server/immich';
import { jsonFailure } from '#lib/server/response';

export async function GET({ params, url }) {
  try {
    const thumbnail = await fetchImmichThumbnail(getCleanerConfig(), params.assetId, url.searchParams);
    const headers = new Headers({
      'content-type': thumbnail.contentType,
      'cache-control': thumbnail.cacheControl ?? 'public, max-age=60'
    });

    if (thumbnail.etag) {
      headers.set('etag', thumbnail.etag);
    }

    return new Response(thumbnail.body, { headers });
  } catch (error) {
    return jsonFailure(error);
  }
}
