import { getCleanerConfig } from '$lib/server/config';
import { fetchImmichOriginal } from '$lib/server/immich';
import { jsonFailure } from '$lib/server/response';
import { convertHeicToJpeg, isHeicImage } from '$lib/server/image-conversion';

export async function GET({ params }) {
  try {
    const original = await fetchImmichOriginal(getCleanerConfig(), params.assetId);
    const image = isHeicImage(original.contentType, original.body)
      ? {
          body: await convertHeicToJpeg(original.body),
          contentType: 'image/jpeg',
          cacheControl: 'private, no-cache, max-age=0',
          etag: null
        }
      : original;
    const headers = new Headers({
      'content-type': image.contentType,
      'cache-control': image.cacheControl ?? 'private, max-age=60'
    });

    if (image.etag) {
      headers.set('etag', image.etag);
    }

    return new Response(image.body, { headers });
  } catch (error) {
    return jsonFailure(error);
  }
}
