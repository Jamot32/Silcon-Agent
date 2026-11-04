import type { NextRequest } from "next/server";

// The /api rewrite reaches the API as Host "api", so the browser-facing Host is checked here:
// a DNS-rebinding page on another name resolving to loopback must not reach the API.
const LOCAL_HOST = /^(localhost|127\.0\.0\.1)(:\d{1,5})?$/i;

export function proxy(request: NextRequest): Response | undefined {
  if (!LOCAL_HOST.test(request.headers.get("host") ?? "")) {
    return Response.json({ detail: "Invalid host header" }, { status: 400 });
  }
}

export const config = {
  matcher: "/api/:path*",
};
