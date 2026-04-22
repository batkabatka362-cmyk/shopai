"""URL safety (SSRF defence) tests.

Blocks the newly-shipped /api/launch → MediaStep → vision
path from reaching internal-network addresses via caller-
supplied gallery_urls.
"""
from __future__ import annotations

import unittest
from unittest.mock import patch

from core.system.url_safety import is_safe_public_url


class _FakeSockAddr:
    """socket.getaddrinfo-shaped tuple list constructor."""

    @staticmethod
    def v4(ip: str):
        return (2, 1, 6, "", (ip, 0))

    @staticmethod
    def v6(ip: str):
        return (10, 1, 6, "", (ip, 0, 0, 0))


class TestLiteralIPs(unittest.TestCase):
    def test_public_ipv4_allowed(self):
        self.assertTrue(
            is_safe_public_url("https://8.8.8.8/foo"),
        )

    def test_loopback_blocked(self):
        self.assertFalse(
            is_safe_public_url("https://127.0.0.1/"),
        )
        self.assertFalse(
            is_safe_public_url("https://127.10.0.1/"),
        )

    def test_link_local_blocked(self):
        self.assertFalse(
            is_safe_public_url(
                "https://169.254.169.254/latest/meta-data/",
            ),
        )

    def test_rfc1918_blocked(self):
        for ip in (
            "10.0.0.1", "172.16.0.1", "192.168.1.1",
        ):
            self.assertFalse(
                is_safe_public_url(f"https://{ip}/x"),
                msg=f"{ip} should be rejected",
            )

    def test_unspecified_blocked(self):
        self.assertFalse(
            is_safe_public_url("https://0.0.0.0/"),
        )

    def test_ipv6_loopback_blocked(self):
        self.assertFalse(
            is_safe_public_url("https://[::1]/"),
        )

    def test_ipv6_private_blocked(self):
        self.assertFalse(
            is_safe_public_url("https://[fc00::1]/"),
        )

    def test_ipv6_link_local_blocked(self):
        self.assertFalse(
            is_safe_public_url("https://[fe80::1]/"),
        )


class TestSchemes(unittest.TestCase):
    def test_http_blocked(self):
        with patch(
            "socket.getaddrinfo",
            return_value=[_FakeSockAddr.v4("8.8.8.8")],
        ):
            self.assertFalse(
                is_safe_public_url(
                    "http://example.com/img.jpg",
                ),
            )

    def test_file_blocked(self):
        self.assertFalse(
            is_safe_public_url("file:///etc/passwd"),
        )

    def test_ftp_blocked(self):
        self.assertFalse(
            is_safe_public_url("ftp://example.com/x"),
        )

    def test_gopher_blocked(self):
        self.assertFalse(
            is_safe_public_url("gopher://evil.com/x"),
        )


class TestDNSResolution(unittest.TestCase):
    def test_public_hostname_allowed(self):
        with patch(
            "socket.getaddrinfo",
            return_value=[_FakeSockAddr.v4("8.8.8.8")],
        ):
            self.assertTrue(
                is_safe_public_url(
                    "https://example.com/img.jpg",
                ),
            )

    def test_hostname_resolving_to_private_blocked(self):
        """An attacker-controlled DNS entry returning a
        private IP must be rejected."""
        with patch(
            "socket.getaddrinfo",
            return_value=[_FakeSockAddr.v4("192.168.1.1")],
        ):
            self.assertFalse(
                is_safe_public_url(
                    "https://evil.com/x",
                ),
            )

    def test_hostname_resolving_to_loopback_blocked(self):
        with patch(
            "socket.getaddrinfo",
            return_value=[_FakeSockAddr.v4("127.0.0.1")],
        ):
            self.assertFalse(
                is_safe_public_url(
                    "https://localhost-alias.com/",
                ),
            )

    def test_mixed_public_and_private_blocked(self):
        """If even ONE resolved address is private, reject —
        closes partial-match DNS rebinding tricks."""
        with patch(
            "socket.getaddrinfo",
            return_value=[
                _FakeSockAddr.v4("8.8.8.8"),
                _FakeSockAddr.v4("10.0.0.1"),
            ],
        ):
            self.assertFalse(
                is_safe_public_url(
                    "https://mixed.example/x",
                ),
            )

    def test_unresolvable_blocked(self):
        import socket

        with patch(
            "socket.getaddrinfo",
            side_effect=socket.gaierror("no dns"),
        ):
            self.assertFalse(
                is_safe_public_url(
                    "https://does-not-exist.invalid/",
                ),
            )


class TestMalformed(unittest.TestCase):
    def test_empty_blocked(self):
        self.assertFalse(is_safe_public_url(""))

    def test_non_string_blocked(self):
        self.assertFalse(is_safe_public_url(None))  # type: ignore[arg-type]
        self.assertFalse(is_safe_public_url(42))  # type: ignore[arg-type]

    def test_no_host_blocked(self):
        self.assertFalse(is_safe_public_url("https:///path"))


class TestVisionWiring(unittest.TestCase):
    """vision._download must consult is_safe_public_url
    before making any request."""

    def test_download_refuses_metadata_url(self):
        from core.adapters.image import vision

        # Patch urllib.request.urlopen to fail loudly if
        # called — we should never reach it for an unsafe URL.
        with patch(
            "urllib.request.urlopen",
            side_effect=AssertionError(
                "urlopen must not be called for unsafe URL",
            ),
        ):
            result = vision._download(
                "http://169.254.169.254/",
            )
        self.assertEqual(result, b"")

    def test_download_refuses_rfc1918(self):
        from core.adapters.image import vision

        with patch(
            "urllib.request.urlopen",
            side_effect=AssertionError(
                "urlopen must not be called for unsafe URL",
            ),
        ):
            result = vision._download(
                "https://10.0.0.1/img.jpg",
            )
        self.assertEqual(result, b"")

    def test_download_refuses_loopback(self):
        from core.adapters.image import vision

        with patch(
            "urllib.request.urlopen",
            side_effect=AssertionError(
                "urlopen must not be called for unsafe URL",
            ),
        ):
            result = vision._download("http://127.0.0.1/x")
        self.assertEqual(result, b"")

    def test_download_refuses_http_public(self):
        """Even public IPs served over http:// are rejected —
        https-only to close plaintext-redirect attacks."""
        from core.adapters.image import vision

        with patch(
            "urllib.request.urlopen",
            side_effect=AssertionError(
                "urlopen must not be called for http:// URL",
            ),
        ):
            result = vision._download(
                "http://example.com/img.jpg",
            )
        self.assertEqual(result, b"")


if __name__ == "__main__":
    unittest.main()
