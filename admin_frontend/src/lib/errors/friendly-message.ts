/** Map an unknown thrown/rejected value to user-readable copy for error surfaces. */
export function friendlyErrorMessage(error: unknown): string {
  if (error instanceof Error && error.message.trim()) {
    return error.message;
  }
  if (typeof error === 'string' && error.trim()) {
    return error;
  }
  return 'Something went wrong. Please try again.';
}
