"""Privacy redactor tests."""
from __future__ import annotations

import unittest

from core.system import privacy_redactor as pr


class TestDefaults(unittest.TestCase):
    def setUp(self) -> None:
        self.r = pr.PrivacyRedactor()

    def test_email_domain_preserved(self) -> None:
        cleaned, n = self.r.redact("contact alice@example.com please")
        self.assertIn("[EMAIL:example.com]", cleaned)
        self.assertGreaterEqual(n, 1)

    def test_phone_redacted(self) -> None:
        cleaned, n = self.r.redact("call +1 415 555 1234 now")
        self.assertIn("[PHONE]", cleaned)

    def test_card_keeps_last_4(self) -> None:
        cleaned, _ = self.r.redact("paid with 4111-1111-1111-1234")
        self.assertIn("[CARD:****1234]", cleaned)

    def test_ssn_redacted(self) -> None:
        cleaned, _ = self.r.redact("ssn: 123-45-6789 here")
        self.assertIn("[SSN]", cleaned)

    def test_ipv4_redacted(self) -> None:
        cleaned, _ = self.r.redact("from 192.168.1.1")
        self.assertIn("[IP]", cleaned)

    def test_iban_redacted(self) -> None:
        cleaned, _ = self.r.redact(
            "account DE89 3704 0044 0532 0130 00",
        )
        self.assertIn("[IBAN]", cleaned)

    def test_clean_text_unchanged(self) -> None:
        cleaned, n = self.r.redact("just a simple sentence")
        self.assertEqual(cleaned, "just a simple sentence")
        self.assertEqual(n, 0)

    def test_empty_input(self) -> None:
        cleaned, n = self.r.redact("")
        self.assertEqual(cleaned, "")
        self.assertEqual(n, 0)


class TestRedactDict(unittest.TestCase):
    def setUp(self) -> None:
        self.r = pr.PrivacyRedactor()

    def test_nested_dict_redacted(self) -> None:
        payload = {
            "customer": "alice@example.com",
            "meta": {
                "phone": "+1 415 555 1234",
                "tags": ["vip", "email: bob@ex.com"],
            },
        }
        cleaned = self.r.redact_dict(payload)
        self.assertIn("[EMAIL:example.com]", cleaned["customer"])
        self.assertIn("[PHONE]", cleaned["meta"]["phone"])
        self.assertTrue(
            any("[EMAIL:ex.com]" in t for t in cleaned["meta"]["tags"]),
        )

    def test_non_string_leaves_untouched(self) -> None:
        payload = {"count": 42, "ok": True, "ratio": 0.5}
        self.assertEqual(self.r.redact_dict(payload), payload)

    def test_tuple_preserved(self) -> None:
        payload = ("hello", "bob@x.com")
        out = self.r.redact_dict(payload)
        self.assertIsInstance(out, tuple)
        self.assertIn("[EMAIL:x.com]", out[1])


class TestCustomPattern(unittest.TestCase):
    def test_register_custom_string_replacement(self) -> None:
        r = pr.PrivacyRedactor()
        r.register_pattern(
            "license", r"\bLIC-\d{6}\b", replacer="[LICENSE]",
        )
        cleaned, _ = r.redact("vehicle LIC-123456 registered")
        self.assertIn("[LICENSE]", cleaned)

    def test_register_custom_callable_replacement(self) -> None:
        r = pr.PrivacyRedactor()
        r.register_pattern(
            "order_id", r"\bORD-\d+\b",
            replacer=lambda m: f"[ORDER:{m.group(0)[-3:]}]",
        )
        cleaned, _ = r.redact("processing ORD-98765")
        self.assertIn("[ORDER:765]", cleaned)

    def test_invalid_regex_raises(self) -> None:
        r = pr.PrivacyRedactor()
        with self.assertRaises(ValueError):
            r.register_pattern("bad", r"[unclosed")

    def test_deregister_removes(self) -> None:
        r = pr.PrivacyRedactor()
        self.assertTrue(r.deregister("email"))
        cleaned, _ = r.redact("alice@example.com")
        self.assertNotIn("[EMAIL", cleaned)


class TestStats(unittest.TestCase):
    def test_counts_accumulated(self) -> None:
        r = pr.PrivacyRedactor()
        r.redact("a@b.com and c@d.com")
        r.redact("e@f.com")
        stats = r.stats()
        self.assertGreaterEqual(stats["counts"].get("email", 0), 3)
        self.assertGreaterEqual(stats["total_redacted"], 3)

    def test_reset_counts(self) -> None:
        r = pr.PrivacyRedactor()
        r.redact("a@b.com")
        r.reset_counts()
        self.assertEqual(r.stats()["total_redacted"], 0)


if __name__ == "__main__":
    unittest.main()
