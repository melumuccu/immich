import { getCleanerConfig } from '#lib/server/config';
import { fetchImmichOriginal, fetchImmichThumbnail, type AssetImageResponse } from '#lib/server/immich';
import { jsonFailure } from '#lib/server/response';
import { convertHeicToJpeg, isHeicImage } from '#lib/server/image-conversion';

export async function GET({ params }) {
  try {
    const config = getCleanerConfig();
    const original = await fetchImmichOriginal(config, params.assetId);
    const image = await prepareOriginalForBrowser(original, async (error) => {
      console.warn(
        `HEIC original conversion failed; using Immich preview fallback for ${params.assetId}: ${errorMessage(error)}`
      );
      return {
        ...(await fetchImmichThumbnail(config, params.assetId, new URLSearchParams({ size: 'preview' }))),
        cacheControl: 'private, no-cache, max-age=0',
        etag: null
      };
    });
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

function errorMessage(error: unknown): string {
  return error instanceof Error ? error.message : String(error);
}

async function prepareOriginalForBrowser(
  original: AssetImageResponse,
  fallback: (error: unknown) => Promise<AssetImageResponse>
): Promise<AssetImageResponse> {
  if (!isHeicImage(original.contentType, original.body)) {
    return original;
  }

  try {
    return {
      body: await convertHeicToJpeg(original.body),
      contentType: 'image/jpeg',
      cacheControl: 'private, no-cache, max-age=0',
      etag: null
    };
  } catch (error) {
    return fallback(error);
  }
}
