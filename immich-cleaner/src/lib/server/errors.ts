export class HttpError extends Error {
  constructor(
    public readonly status: number,
    message: string,
    public readonly detail?: string
  ) {
    super(message);
    this.name = 'HttpError';
  }
}

export class ImmichRequestError extends HttpError {
  constructor(
    public readonly method: string,
    public readonly url: string,
    status: number,
    detail: string
  ) {
    super(status, `Immich request failed: ${method} ${url} -> ${status}`, detail);
    this.name = 'ImmichRequestError';
  }
}

export function errorMessage(error: unknown): string {
  if (error instanceof Error) {
    return error.message;
  }
  return 'Unknown error';
}
