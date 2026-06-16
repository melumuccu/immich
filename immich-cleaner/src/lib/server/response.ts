import { json } from '@sveltejs/kit';

import { errorMessage, HttpError } from './errors';

export function jsonFailure(error: unknown) {
  if (error instanceof HttpError) {
    return json(
      {
        message: error.message,
        detail: error.detail
      },
      { status: error.status }
    );
  }

  console.error(error);
  return json({ message: errorMessage(error) }, { status: 500 });
}
