"""Local-only request guards for the public API."""

from fastapi import HTTPException, Request

# Hostnames the API answers to (ports are ignored): browsers and host tools on the
# loopback-published port, the Compose healthcheck, and the Next.js rewrite to the
# `api` service. Any other Host, such as a DNS-rebinding name, is rejected with 400.
TRUSTED_HOSTS = ("localhost", "127.0.0.1", "api")
APP_REQUEST_HEADER = "x-silicon-request"


def app_request(request: Request) -> None:
    """Require the application's custom header on state-changing and secret-bearing routes.

    A custom header forces a CORS preflight, and the API grants no CORS access, so a
    cross-site page cannot send it.
    """
    if request.headers.get(APP_REQUEST_HEADER) != "1" or request.headers.get("sec-fetch-site") == "cross-site":
        raise HTTPException(403, "Use this application to make this request")
