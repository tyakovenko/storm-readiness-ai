const ERROR_MESSAGES = {
  model_quota_exhausted: "The AI model has reached its usage limit. Please try again later. Dashboard data is still available.",
  model_unavailable: "The AI model is unavailable right now. Please try again later. Dashboard data is still available.",
  model_timeout: "The AI model took too long to respond. Please try again.",
};

export const DEFAULT_CHAT_ERROR = "Something went wrong getting that answer. Please try again in a moment.";

export async function chatErrorMessage(response) {
  try {
    const body = await response.json();
    const detail = body?.detail;
    const codes = [body?.error, detail?.error, detail?.code, detail];
    const code = codes.find((value) => typeof value === "string" && Object.hasOwn(ERROR_MESSAGES, value));
    if (code) return ERROR_MESSAGES[code];
  } catch {
    // Keep malformed or non-JSON error responses on the same safe fallback.
  }
  return DEFAULT_CHAT_ERROR;
}
