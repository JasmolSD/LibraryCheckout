"""Tests for the GitHub release update-check service.

All network calls are patched out — these tests never hit the real
GitHub API, so they're safe to run in CI regardless of rate limits or
network state.
"""

from __future__ import annotations

import json
import urllib.error
from io import BytesIO
from unittest.mock import MagicMock, patch

import pytest

from server.app import VERSION
from server.app.services import update_check


@pytest.fixture(autouse=True)
def _clear_cache():
    """Every test starts with an empty update-check cache."""
    update_check.reset_cache()
    yield
    update_check.reset_cache()


@pytest.fixture
def enable_update_check(client):
    """Turn the update check on for this test with a known repo."""
    with patch.dict(
        client.application.config,
        {
            "UPDATE_CHECK_ENABLED": True,
            "GITHUB_REPO": "JasmolSD/LibraryCheckout",
            "GITHUB_TOKEN": "",
        },
        clear=False,
    ):
        yield


def _mock_github_response(payload: dict) -> MagicMock:
    """Build a context-manager mock shaped like ``urllib.request.urlopen``."""
    mock = MagicMock()
    mock.__enter__ = lambda self: self
    mock.__exit__ = MagicMock(return_value=False)
    mock.read.return_value = json.dumps(payload).encode()
    return mock


# ── Version comparison helper ────────────────────────────────────────────────


class TestVersionCompare:
    def test_semver_newer(self):
        assert update_check._is_newer("v0.2.0", "0.1.0") is True

    def test_semver_older(self):
        assert update_check._is_newer("v0.1.0", "0.2.0") is False

    def test_semver_equal(self):
        assert update_check._is_newer("v0.2.0", "0.2.0") is False

    def test_v_prefix_optional(self):
        assert update_check._is_newer("0.2.0", "0.1.0") is True
        assert update_check._is_newer("v0.2.0", "v0.1.0") is True

    def test_patch_bump(self):
        assert update_check._is_newer("v0.1.1", "0.1.0") is True

    def test_minor_bump(self):
        assert update_check._is_newer("v0.2.0", "0.1.5") is True

    def test_major_bump(self):
        assert update_check._is_newer("v1.0.0", "0.9.9") is True

    def test_non_semver_strings_fallback(self):
        # Unparseable → falls back to string compare; same string = not newer
        assert update_check._is_newer("weird", "weird") is False


# ── Disabled / unconfigured short-circuits ───────────────────────────────────


class TestDisabledPaths:
    def test_disabled_flag_returns_noop(self, client):
        with patch.dict(client.application.config, {"UPDATE_CHECK_ENABLED": False}, clear=False):
            result = update_check.check_for_update()
            assert result["update_available"] is False
            assert "disabled" in result["error"].lower()
            assert result["current_version"] == VERSION

    def test_no_repo_configured_returns_noop(self, client):
        with patch.dict(
            client.application.config,
            {"UPDATE_CHECK_ENABLED": True, "GITHUB_REPO": ""},
            clear=False,
        ):
            result = update_check.check_for_update()
            assert result["update_available"] is False
            assert "not configured" in result["error"].lower()


# ── Happy path: API returns a newer / same / older release ─────────────────


class TestUpdateAvailable:
    def test_newer_release_flags_update(self, client, enable_update_check):
        payload = {
            "tag_name": "v99.0.0",
            "html_url": "https://github.com/JasmolSD/LibraryCheckout/releases/tag/v99.0.0",
            "body": "Big release",
            "published_at": "2026-04-15T00:00:00Z",
        }
        with patch(
            "server.app.services.update_check.urllib.request.urlopen",
            return_value=_mock_github_response(payload),
        ):
            result = update_check.check_for_update()
        assert result["update_available"] is True
        assert result["latest_version"] == "99.0.0"
        assert result["current_version"] == VERSION
        assert "99.0.0" in result["release_url"]
        assert result["release_notes"] == "Big release"

    def test_same_version_no_update(self, client, enable_update_check):
        payload = {
            "tag_name": f"v{VERSION}",
            "html_url": "https://github.com/x/x/releases/tag/v" + VERSION,
            "body": "",
            "published_at": "",
        }
        with patch(
            "server.app.services.update_check.urllib.request.urlopen",
            return_value=_mock_github_response(payload),
        ):
            result = update_check.check_for_update()
        assert result["update_available"] is False
        assert result["latest_version"] == VERSION

    def test_older_release_no_update(self, client, enable_update_check):
        payload = {
            "tag_name": "v0.0.1",
            "html_url": "https://github.com/x/x/releases/tag/v0.0.1",
            "body": "",
            "published_at": "",
        }
        with patch(
            "server.app.services.update_check.urllib.request.urlopen",
            return_value=_mock_github_response(payload),
        ):
            result = update_check.check_for_update()
        assert result["update_available"] is False

    def test_release_notes_truncated_to_500(self, client, enable_update_check):
        long_notes = "x" * 2000
        payload = {
            "tag_name": "v99.0.0",
            "html_url": "https://github.com/x/x/releases/tag/v99.0.0",
            "body": long_notes,
            "published_at": "",
        }
        with patch(
            "server.app.services.update_check.urllib.request.urlopen",
            return_value=_mock_github_response(payload),
        ):
            result = update_check.check_for_update()
        assert len(result["release_notes"]) == 500


# ── Network / auth error paths ───────────────────────────────────────────────


class TestErrorHandling:
    def test_404_returns_informative_error(self, client, enable_update_check):
        from email.message import Message

        err = urllib.error.HTTPError(
            url="https://api.github.com/...",
            code=404,
            msg="Not Found",
            hdrs=Message(),
            fp=BytesIO(b""),
        )
        with patch(
            "server.app.services.update_check.urllib.request.urlopen",
            side_effect=err,
        ):
            result = update_check.check_for_update()
        assert result["update_available"] is False
        assert "404" in result["error"]
        assert "private" in result["error"].lower()

    def test_network_error_swallowed(self, client, enable_update_check):
        with patch(
            "server.app.services.update_check.urllib.request.urlopen",
            side_effect=urllib.error.URLError("name resolution failed"),
        ):
            result = update_check.check_for_update()
        assert result["update_available"] is False
        assert "Network error" in result["error"]

    def test_malformed_json_swallowed(self, client, enable_update_check):
        mock = MagicMock()
        mock.__enter__ = lambda self: self
        mock.__exit__ = MagicMock(return_value=False)
        mock.read.return_value = b"{not valid json"
        with patch(
            "server.app.services.update_check.urllib.request.urlopen",
            return_value=mock,
        ):
            result = update_check.check_for_update()
        assert result["update_available"] is False
        assert "Malformed" in result["error"]


# ── Auth header is sent when GITHUB_TOKEN is set ────────────────────────────


class TestPrivateRepoAuth:
    def test_token_passed_as_bearer_header(self, client):
        with patch.dict(
            client.application.config,
            {
                "UPDATE_CHECK_ENABLED": True,
                "GITHUB_REPO": "private/repo",
                "GITHUB_TOKEN": "ghp_fake_token_12345",
            },
            clear=False,
        ):
            payload = {
                "tag_name": "v99.0.0",
                "html_url": "https://github.com/private/repo/releases/tag/v99.0.0",
                "body": "",
                "published_at": "",
            }
            with patch(
                "server.app.services.update_check.urllib.request.urlopen",
                return_value=_mock_github_response(payload),
            ) as mock_urlopen:
                update_check.check_for_update()
                # First positional arg to urlopen is the Request object
                req = mock_urlopen.call_args[0][0]
                auth_header = req.get_header("Authorization")
                assert auth_header == "Bearer ghp_fake_token_12345"

    def test_no_token_means_no_auth_header(self, client, enable_update_check):
        payload = {
            "tag_name": "v0.0.1",
            "html_url": "https://github.com/x/x",
            "body": "",
            "published_at": "",
        }
        with patch(
            "server.app.services.update_check.urllib.request.urlopen",
            return_value=_mock_github_response(payload),
        ) as mock_urlopen:
            update_check.check_for_update()
            req = mock_urlopen.call_args[0][0]
            assert req.get_header("Authorization") is None


# ── Caching ──────────────────────────────────────────────────────────────────


class TestCaching:
    def test_second_call_hits_cache_not_network(self, client, enable_update_check):
        payload = {
            "tag_name": "v0.0.1",
            "html_url": "https://github.com/x/x",
            "body": "",
            "published_at": "",
        }
        with patch(
            "server.app.services.update_check.urllib.request.urlopen",
            return_value=_mock_github_response(payload),
        ) as mock_urlopen:
            update_check.check_for_update()
            update_check.check_for_update()
            update_check.check_for_update()
            assert mock_urlopen.call_count == 1

    def test_force_bypasses_cache(self, client, enable_update_check):
        payload = {
            "tag_name": "v0.0.1",
            "html_url": "https://github.com/x/x",
            "body": "",
            "published_at": "",
        }
        with patch(
            "server.app.services.update_check.urllib.request.urlopen",
            return_value=_mock_github_response(payload),
        ) as mock_urlopen:
            update_check.check_for_update()
            update_check.check_for_update(force=True)
            assert mock_urlopen.call_count == 2


# ── /api/update-check route ──────────────────────────────────────────────────


class TestRoute:
    def test_route_returns_json(self, client, enable_update_check):
        payload = {
            "tag_name": "v0.0.1",
            "html_url": "https://github.com/x/x",
            "body": "",
            "published_at": "",
        }
        with patch(
            "server.app.services.update_check.urllib.request.urlopen",
            return_value=_mock_github_response(payload),
        ):
            r = client.get("/api/update-check")
        assert r.status_code == 200
        data = r.get_json()
        assert "update_available" in data
        assert "current_version" in data

    def test_route_refresh_param_bypasses_cache(self, client, enable_update_check):
        payload = {
            "tag_name": "v0.0.1",
            "html_url": "https://github.com/x/x",
            "body": "",
            "published_at": "",
        }
        with patch(
            "server.app.services.update_check.urllib.request.urlopen",
            return_value=_mock_github_response(payload),
        ) as mock_urlopen:
            client.get("/api/update-check")
            client.get("/api/update-check?refresh=1")
            assert mock_urlopen.call_count == 2
