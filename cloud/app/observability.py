"""
Error tracking (Sentry).

Opt-in: with SENTRY_DSN unset the SDK is never initialised and every helper
here is a no-op, so local runs, forks and the existing test path behave exactly
as they did before.

Privacy — events leave this box and land on a third party's servers, so
scrubbing is deny-by-default rather than best-effort. This process holds
Spotify OAuth tokens, a Last.fm API key and a Spotify user ID, and the DB holds
the user's full listening history:

  * local variables are NOT captured (include_local_variables=False). This is
    the big one: the SDK default is True, which would serialise every frame's
    locals — including the `track` dict (name/artist/album) and whatever a
    settings dict happens to hold. before_send cannot fix this, as it does not
    reach stack-trace frame vars.
  * request bodies and cookies are dropped outright
  * query strings are stripped from both request URLs and HTTP breadcrumbs
    (the Spotify OAuth callback carries ?code=<secret>, and every Last.fm call
    carries ?api_key=<secret> — the httpx integration would otherwise record it)
  * any key that looks like a credential or a personal detail is redacted
  * the `user` context is removed entirely

What is deliberately kept, because it is what makes an event useful at all: the
exception type and message, and the stack trace as file/function/line only.
"""

import logging
import os

logger = logging.getLogger("observability")

_DSN_ENV = "SENTRY_DSN"
_REDACTED = "[redacted]"

# Matched as a lowercase substring against every key we would serialise.
_SENSITIVE_KEY_PARTS = (
    # Credentials for this app.
    "token",
    "secret",
    "password",
    "api_key",
    "apikey",
    "authorization",
    "cookie",
    "session",
    "dsn",
    "refresh",
    # Personal data — never reported, per project policy.
    "email",
    "salary",
    "salaries",
    "placa",
    "unique_id",
    "user_id",
    "username",
    "first_name",
    "last_name",
    "full_name",
)

# Set by init_error_tracking(); guards every helper so call sites stay one-liners.
_enabled = False


def _is_sensitive(key) -> bool:
    lowered = str(key).lower()
    return any(part in lowered for part in _SENSITIVE_KEY_PARTS)


def _scrub(value, depth: int = 0):
    """Recursively redact sensitive keys in nested dicts/lists."""
    if depth > 8:  # cheap cycle/pathological-nesting guard
        return value
    if isinstance(value, dict):
        return {
            key: (_REDACTED if _is_sensitive(key) else _scrub(inner, depth + 1))
            for key, inner in value.items()
        }
    if isinstance(value, list):
        return [_scrub(item, depth + 1) for item in value]
    return value


def _strip_query(url):
    return url.split("?", 1)[0] if isinstance(url, str) and "?" in url else url


def _before_send(event, hint):
    """Last gate before an event leaves the process."""
    request = event.get("request")
    if isinstance(request, dict):
        request.pop("data", None)  # request body — never sent
        request.pop("cookies", None)
        request.pop("query_string", None)
        request["url"] = _strip_query(request.get("url"))
        headers = request.get("headers")
        if isinstance(headers, dict):
            request["headers"] = {
                key: (_REDACTED if _is_sensitive(key) else value) for key, value in headers.items()
            }

    event.pop("user", None)
    for section in ("extra", "contexts", "tags"):
        if isinstance(event.get(section), dict):
            event[section] = _scrub(event[section])
    return event


def _before_breadcrumb(crumb, hint):
    """Strip secrets from HTTP breadcrumbs recorded by the httpx integration."""
    data = crumb.get("data")
    if isinstance(data, dict):
        data["url"] = _strip_query(data.get("url"))
        data.pop("http.query", None)
        data.pop("http.fragment", None)
    return crumb


def init_error_tracking(release: str) -> bool:
    """Initialise error tracking. Returns True when it is actually on.

    Called at import time in main.py so the FastAPI/Starlette integration is in
    place before the app handles anything. Note this runs with no event loop yet,
    which is why background-task coverage is installed separately at startup via
    install_asyncio_exception_handler() rather than through AsyncioIntegration
    (that integration silently no-ops when no loop is running at init time).
    """
    global _enabled

    dsn = os.getenv(_DSN_ENV, "").strip()
    if not dsn:
        logger.warning("%s is not set — error tracking is disabled.", _DSN_ENV)
        return False

    try:
        import sentry_sdk
    except ImportError:
        logger.warning("sentry-sdk is not installed — error tracking is disabled.")
        return False

    sentry_sdk.init(
        dsn=dsn,
        release=release,
        environment=os.getenv("SENTRY_ENVIRONMENT", "").strip() or "production",
        # Privacy — see the module docstring. Both of these default the other
        # way or are merely the current default, so they are set explicitly:
        # events go to a third party and must not carry app data.
        include_local_variables=False,
        send_default_pii=False,
        max_request_body_size="never",
        before_send=_before_send,
        before_breadcrumb=_before_breadcrumb,
        # Errors only — no tracing/profiling. Keeps the free tier (5k
        # errors/month) comfortable and adds no request overhead.
        traces_sample_rate=0.0,
    )
    _enabled = True
    # WARNING rather than INFO: the app configures no INFO handler, so INFO
    # never surfaces in the container log (same reason as _log_auth_posture).
    logger.warning("Error tracking enabled (release %s).", release)
    return True


def report_exception(exc: BaseException, component: str) -> None:
    """Report an exception. No-op when tracking is disabled.

    Never raises: a telemetry failure must not take down the caller, which in
    every current call site is a recovery path.
    """
    if not _enabled:
        return
    try:
        import sentry_sdk

        with sentry_sdk.new_scope() as scope:
            scope.set_tag("component", component)
            sentry_sdk.capture_exception(exc)
    except Exception:  # pragma: no cover - telemetry must never break the caller
        logger.debug("Failed to report exception to error tracking.", exc_info=True)


def install_asyncio_exception_handler(loop) -> None:
    """Report exceptions that escape a background task.

    The asyncio analogue of an unhandled promise rejection: a task that dies
    with nobody awaiting it. Without this the loop only prints "Task exception
    was never retrieved" to stderr and the failure is invisible. Chains to the
    previous handler so existing logging behaviour is unchanged.
    """
    if not _enabled:
        return

    previous = loop.get_exception_handler()

    def handler(running_loop, context):
        exc = context.get("exception")
        if exc is not None:
            report_exception(exc, component="asyncio")
        if previous is not None:
            previous(running_loop, context)
        else:
            running_loop.default_exception_handler(context)

    loop.set_exception_handler(handler)
