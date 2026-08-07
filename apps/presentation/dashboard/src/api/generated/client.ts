/**
 * Generated LoopX v1 openapi-fetch wrapper. Do not edit.
 * OpenAPI-SHA256: acffb305774095fe7133fab21bd3c9e1f9b80ef3128a231cfb95b5b2e4942aa8
 */
import createClient, { type Middleware } from "openapi-fetch";
import type { paths } from "./schema";

export const LOOPX_CONTROL_SESSION_HEADER = "X-LoopX-Control-Session" as const;

export interface LoopXClientOptions {
  baseUrl?: string;
}

export function ifNoneMatch(etag: string | null | undefined): HeadersInit {
  return etag ? { "If-None-Match": etag } : {};
}

export function createLoopXApiClient(options: LoopXClientOptions = {}) {
  let controlSessionId: string | null = null;
  const controlSessionMiddleware: Middleware = {
    async onRequest({ request }) {
      if (controlSessionId) {
        request.headers.set(LOOPX_CONTROL_SESSION_HEADER, controlSessionId);
      } else {
        request.headers.delete(LOOPX_CONTROL_SESSION_HEADER);
      }
      return request;
    },
  };
  const client = createClient<paths>({ baseUrl: options.baseUrl ?? "" });
  client.use(controlSessionMiddleware);
  return {
    client,
    setControlSession(value: string | null) {
      controlSessionId = value;
    },
  };
}

export type LoopXApiClient = ReturnType<typeof createLoopXApiClient>;
