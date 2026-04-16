"""GitHub release update-check service.

Compares the app's bundled :data:`server.app.VERSION` against the
latest release tag on the configured GitHub repo and reports whether
an update is available.

Intentionally uses only the Python standard library (``urllib``) so
there's no extra dependency.  Results are cached in-memory for
:data:`_CACHE_TTL` seconds so page navigation doesn't hammer the
GitHub API (which has a 60-req/hour unauthenticated limit per IP).

The check is a **best-effort** network call: every exception path —
DNS failure, 404, rate-limit, malformed JSON — is swallowed and
surfaced as ``{"update_available": False, "error": "..."}``.  It never
raises into the caller, because an update check breaking the page
load would be absurd.
"""

from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
from typing import Any

from flask import current_app

#: Seconds of cache TTL for the latest-release response.  GitHub's
#: unauthenticated API is limited to 60 requests/hour, and the app's
#: pages each trigger one check on load, so we cache aggressively.
_CACHE_TTL = 60 * 60  # 1 hour

_cache: dict[str, Any] | None = None
_cache_time: float = 0


def _parse_version(tag: str) -> tuple[int, ...] | None:
    """Turn a release tag like ``v0.3.1`` into ``(0, 3, 1)``.

    Strips a leading ``v`` or ``V`` and splits on dots; any non-int
    component makes the whole parse fail, returning ``None`` — in
    which case the caller falls back to string comparison (which is
    never wrong, just less reliable for non-semver tags).
    """
    if not tag:
        return None
    stripped = tag.lstrip("vV")
    try:
        return tuple(int(p) for p in stripped.split("."))
    except ValueError:
        return None


def _is_newer(latest: str, current: str) -> bool:
    """Return True when ``latest`` strictly dominates ``current``.

    Uses tuple comparison when both parse cleanly as semver, otherwise
    a conservative string comparison (which at least catches exact
    equality and "latest is later alphabetically").
    """
    a = _parse_version(latest)
    b = _parse_version(current)
    if a is not None and b is not None:
        return a > b
    return latest.strip().lstrip("vV") != current.strip().lstrip("vV") and latest > current


def _fetch_latest_release(repo: str, token: str) -> dict[str, Any]:
    """Hit the GitHub API for ``repo``'s latest release.

    Raises:
        :class:`urllib.error.URLError` on network / HTTP errors.
        :class:`ValueError` on malformed JSON.
    """
    url = f"https://api.github.com/repos/{repo}/releases/latest"
    req = urllib.request.Request(
        url,
        headers={
            "Accept": "application/vnd.github+json",
            "User-Agent": "library-checkout-update-check",
            "X-GitHub-Api-Version": "2022-11-28",
        },
    )
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    with urllib.request.urlopen(req, timeout=6) as resp:
        return json.loads(resp.read())


def check_for_update(*, force: bool = False) -> dict[str, Any]:
    """Check whether a newer release is available on GitHub.

    Returns a dict with at minimum ``update_available: bool`` and
    ``current_version: str``.  When an update is available, also
    includes ``latest_version``, ``release_url``, ``release_notes``,
    and ``published_at``.  On any error (including "feature is
    disabled in config"), includes ``error: str`` and
    ``update_available: False``.

    Cached for :data:`_CACHE_TTL` seconds — pass ``force=True`` to
    bypass the cache (e.g. when the user clicks "Check now").
    """
    global _cache, _cache_time  # noqa: PLW0603

    from .. import VERSION  # local import to avoid a circular dep

    cfg = current_app.config
    enabled = bool(cfg.get("UPDATE_CHECK_ENABLED", True))
    if not enabled:
        return {
            "update_available": False,
            "current_version": VERSION,
            "error": "Update check is disabled",
        }

    if not force and _cache is not None and (time.monotonic() - _cache_time) < _CACHE_TTL:
        return _cache

    repo = (cfg.get("GITHUB_REPO") or "").strip()
    if not repo:
        return {
            "update_available": False,
            "current_version": VERSION,
            "error": "GITHUB_REPO is not configured",
        }

    token = (cfg.get("GITHUB_TOKEN") or "").strip()

    try:
        data = _fetch_latest_release(repo, token)
    except urllib.error.HTTPError as exc:
        # 404 on a private repo without a valid token is the most common case.
        msg = f"GitHub API returned {exc.code}"
        if exc.code == 404:
            msg += " — repo is private and needs GITHUB_TOKEN, or has no releases yet"
        result = {
            "update_available": False,
            "current_version": VERSION,
            "error": msg,
        }
        _cache = result
        _cache_time = time.monotonic()
        return result
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        result = {
            "update_available": False,
            "current_version": VERSION,
            "error": f"Network error: {exc}",
        }
        _cache = result
        _cache_time = time.monotonic()
        return result
    except (ValueError, json.JSONDecodeError) as exc:
        result = {
            "update_available": False,
            "current_version": VERSION,
            "error": f"Malformed API response: {exc}",
        }
        _cache = result
        _cache_time = time.monotonic()
        return result

    tag = data.get("tag_name") or ""
    release_url = data.get("html_url") or f"https://github.com/{repo}/releases"
    release_notes = (data.get("body") or "").strip()
    published_at = data.get("published_at") or ""
    latest_version = tag.lstrip("vV")

    result = {
        "update_available": _is_newer(tag, VERSION),
        "current_version": VERSION,
        "latest_version": latest_version,
        "release_url": release_url,
        "release_notes": release_notes[:500],  # truncate so /api response stays small
        "published_at": published_at,
    }
    _cache = result
    _cache_time = time.monotonic()
    return result


def reset_cache() -> None:
    """Clear the cached response (used by tests)."""
    global _cache, _cache_time  # noqa: PLW0603
    _cache = None
    _cache_time = 0
