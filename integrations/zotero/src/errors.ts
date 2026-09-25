export class TeXGlotIntegrationError extends Error {
  readonly code: string;
  readonly status?: number;
  readonly details?: unknown;

  constructor(code: string, message: string, status?: number, details?: unknown) {
    super(message);
    this.name = "TeXGlotIntegrationError";
    this.code = code;
    this.status = status;
    this.details = details;
  }
}

export function errorFromPayload(status: number, payload: unknown): TeXGlotIntegrationError {
  const body = payload && typeof payload === "object" ? payload as Record<string, unknown> : {};
  const detail = body.detail && typeof body.detail === "object"
    ? body.detail as Record<string, unknown>
    : {};
  const code = String(body.code ?? detail.code ?? (status === 404 ? "NOT_FOUND" : "SERVICE_ERROR"));
  const message = String(body.message ?? detail.message ?? body.detail ?? `TeXGlot 服务返回 HTTP ${status}`);
  return new TeXGlotIntegrationError(code, message, status, payload);
}
