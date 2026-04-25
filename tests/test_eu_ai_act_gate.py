"""Tests for execution.compliance.eu_ai_act_gate (Wave A-4)."""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from execution.compliance.eu_ai_act_gate import (
    C2PAManifest,
    Creative,
    EUAIActGate,
    GateVerdict,
    get_eu_ai_gate,
    reset_eu_ai_gate_for_tests,
)


def _gate(tmp, **kw):
    defaults = dict(
        vault_decisions_dir=Path(tmp) / "vault",
        now_fn=lambda: 1_700_000_000.0,
    )
    defaults.update(kw)
    return EUAIActGate(**defaults)


def _creative(**kw):
    defaults = dict(
        asset_id="ad_abc",
        media_kind="video",
        c2pa=C2PAManifest(
            creator="ShopAI",
            generator_model="veo-3.1",
            created_at_iso="2026-04-20T10:00:00Z",
            ai_generated=True,
        ),
        disclosure_text="This ad is AI-generated.",
        target_markets=("US",),
    )
    defaults.update(kw)
    return Creative(**defaults)


class TestRegionDetection(unittest.TestCase):
    def test_blank_markets_not_eu(self):
        self.assertFalse(
            EUAIActGate.is_eu_target(()),
        )

    def test_us_only_not_eu(self):
        self.assertFalse(
            EUAIActGate.is_eu_target(("US",)),
        )

    def test_de_is_eu(self):
        self.assertTrue(
            EUAIActGate.is_eu_target(("DE",)),
        )

    def test_lowercase_tolerated(self):
        self.assertTrue(
            EUAIActGate.is_eu_target(("de",)),
        )

    def test_mixed_markets(self):
        self.assertTrue(
            EUAIActGate.is_eu_target(
                ("US", "FR", "CA"),
            ),
        )

    def test_generic_eu_tag(self):
        self.assertTrue(
            EUAIActGate.is_eu_target(("EU",)),
        )


class TestDisclosure(unittest.TestCase):
    def test_english(self):
        self.assertTrue(
            EUAIActGate.validate_disclosure(
                "This is AI-generated content.",
            ),
        )

    def test_german(self):
        self.assertTrue(
            EUAIActGate.validate_disclosure(
                "Dieses Bild wurde mit Künstliche "
                "Intelligenz erstellt.",
            ),
        )

    def test_empty(self):
        self.assertFalse(
            EUAIActGate.validate_disclosure(""),
        )

    def test_too_short(self):
        self.assertFalse(
            EUAIActGate.validate_disclosure("AI"),
        )

    def test_no_token(self):
        self.assertFalse(
            EUAIActGate.validate_disclosure(
                "Nice product photo here",
            ),
        )


class TestC2PAValidation(unittest.TestCase):
    def test_missing_manifest(self):
        ok, note = EUAIActGate.validate_c2pa(None)
        self.assertFalse(ok)
        self.assertIn("missing", note)

    def test_not_ai_flag(self):
        c2pa = C2PAManifest(
            creator="x", generator_model="x",
            created_at_iso="2026",
            ai_generated=False,
        )
        ok, note = EUAIActGate.validate_c2pa(c2pa)
        self.assertFalse(ok)
        self.assertIn("ai_generated=false", note)

    def test_missing_model(self):
        c2pa = C2PAManifest(
            creator="x", generator_model="",
            created_at_iso="2026",
            ai_generated=True,
        )
        ok, note = EUAIActGate.validate_c2pa(c2pa)
        self.assertFalse(ok)
        self.assertIn("generator_model", note)

    def test_complete_ok(self):
        c2pa = C2PAManifest(
            creator="x", generator_model="veo-3",
            created_at_iso="2026-04-20",
            ai_generated=True,
        )
        ok, _ = EUAIActGate.validate_c2pa(c2pa)
        self.assertTrue(ok)


class TestMediaHashVerify(unittest.TestCase):
    def test_no_hash_passes(self):
        c2pa = C2PAManifest(
            creator="x", generator_model="y",
            created_at_iso="2026",
            ai_generated=True,
            media_hash="",
        )
        self.assertTrue(
            EUAIActGate.verify_media_hash(c2pa, b"abc"),
        )

    def test_no_sample_passes(self):
        c2pa = C2PAManifest(
            creator="x", generator_model="y",
            created_at_iso="2026",
            ai_generated=True,
            media_hash="deadbeef",
        )
        self.assertTrue(
            EUAIActGate.verify_media_hash(c2pa, b""),
        )

    def test_matching_hash(self):
        import hashlib
        sample = b"test content"
        h = hashlib.sha256(sample).hexdigest()
        c2pa = C2PAManifest(
            creator="x", generator_model="y",
            created_at_iso="2026",
            ai_generated=True,
            media_hash=h,
        )
        self.assertTrue(
            EUAIActGate.verify_media_hash(c2pa, sample),
        )

    def test_mismatched_hash(self):
        c2pa = C2PAManifest(
            creator="x", generator_model="y",
            created_at_iso="2026",
            ai_generated=True,
            media_hash="00" * 32,
        )
        self.assertFalse(
            EUAIActGate.verify_media_hash(
                c2pa, b"real content",
            ),
        )


class TestGateVerify(unittest.TestCase):
    def test_compliant_eu_passes(self):
        with tempfile.TemporaryDirectory() as tmp:
            g = _gate(tmp)
            v = g.verify(
                _creative(target_markets=("FR",)),
            )
            self.assertEqual(v.decision, "pass")
            self.assertTrue(v.eu_targeted)
            self.assertTrue(v.audit_path)
            self.assertTrue(
                Path(v.audit_path).exists(),
            )

    def test_eu_missing_c2pa_blocked(self):
        with tempfile.TemporaryDirectory() as tmp:
            g = _gate(tmp)
            v = g.verify(
                _creative(
                    c2pa=None,
                    target_markets=("DE",),
                ),
            )
            self.assertEqual(v.decision, "block")
            self.assertIn("c2pa manifest", v.reason)

    def test_eu_missing_disclosure_blocked(self):
        with tempfile.TemporaryDirectory() as tmp:
            g = _gate(tmp)
            v = g.verify(
                _creative(
                    disclosure_text="",
                    target_markets=("IT",),
                ),
            )
            self.assertEqual(v.decision, "block")
            self.assertTrue(
                any("disclosure" in m for m in v.missing),
            )

    def test_non_eu_advisory_when_missing(self):
        with tempfile.TemporaryDirectory() as tmp:
            g = _gate(tmp)
            v = g.verify(
                _creative(
                    c2pa=None,
                    target_markets=("US",),
                ),
            )
            self.assertEqual(v.decision, "advisory")
            self.assertFalse(v.eu_targeted)

    def test_required_for_all_markets(self):
        with tempfile.TemporaryDirectory() as tmp:
            g = _gate(
                tmp, required_for_all_markets=True,
            )
            v = g.verify(
                _creative(
                    c2pa=None,
                    target_markets=("US",),
                ),
            )
            self.assertEqual(v.decision, "block")

    def test_media_hash_tampered_blocked_eu(self):
        with tempfile.TemporaryDirectory() as tmp:
            g = _gate(tmp)
            c2pa = C2PAManifest(
                creator="x", generator_model="y",
                created_at_iso="2026",
                ai_generated=True,
                media_hash="00" * 32,
            )
            v = g.verify(
                _creative(
                    c2pa=c2pa,
                    media_bytes_sample=b"different",
                    target_markets=("FR",),
                ),
            )
            self.assertEqual(v.decision, "block")
            self.assertTrue(
                any("mismatch" in m for m in v.missing),
            )

    def test_audit_file_contents(self):
        with tempfile.TemporaryDirectory() as tmp:
            g = _gate(tmp)
            v = g.verify(_creative(target_markets=("ES",)))
            text = Path(v.audit_path).read_text()
            self.assertIn("ad_abc", text)
            self.assertIn("pass", text)
            self.assertIn("veo-3.1", text)

    def test_non_creative_type_raises(self):
        with tempfile.TemporaryDirectory() as tmp:
            g = _gate(tmp)
            with self.assertRaises(TypeError):
                g.verify({"asset_id": "x"})

    def test_stats_increments(self):
        with tempfile.TemporaryDirectory() as tmp:
            g = _gate(tmp)
            g.verify(_creative(target_markets=("FR",)))
            g.verify(
                _creative(
                    c2pa=None, target_markets=("FR",),
                ),
            )
            s = g.stats()
            self.assertEqual(s["passed"], 1)
            self.assertEqual(s["blocked"], 1)

    def test_asset_id_sanitized_in_filename(self):
        with tempfile.TemporaryDirectory() as tmp:
            g = _gate(tmp)
            v = g.verify(
                _creative(
                    asset_id="bad/../id",
                    target_markets=("FR",),
                ),
            )
            p = Path(v.audit_path)
            self.assertNotIn("/", p.name[len("2026"):])
            self.assertTrue(p.exists())


class TestSingleton(unittest.TestCase):
    def test_singleton(self):
        reset_eu_ai_gate_for_tests()
        try:
            a = get_eu_ai_gate()
            b = get_eu_ai_gate()
            self.assertIs(a, b)
        finally:
            reset_eu_ai_gate_for_tests()


class TestDicts(unittest.TestCase):
    def test_creative_dict(self):
        d = _creative().as_dict()
        self.assertIn("c2pa", d)

    def test_verdict_dict(self):
        v = GateVerdict(
            asset_id="x", decision="pass",
            reason="ok", eu_targeted=False,
        )
        self.assertIn("decision", v.as_dict())


if __name__ == "__main__":
    unittest.main()
