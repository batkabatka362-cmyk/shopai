"""Tests for engines.churn_prediction.discount_minter +
the Phase 7 opt-in path in flow.py.

Coverage:
  1. Risk-level filter: critical/high mint, medium/low skip.
  2. Retention-action filter: win_back_offer mints; others
     skip (personal_outreach, exclusive_access, ...).
  3. Cost-tier -> percentage mapping (low=10, med=15, high=20).
  4. Custom TTL override from store config.
  5. Pattern Z recording (success + failure paths).
  6. Engine flow opt-in: no flag = no mint, flag = mint loop.
  7. Engine flow output carries minted_codes list.
  8. Mint raise inside flow doesn't break the envelope.
"""
from __future__ import annotations

from unittest.mock import patch, MagicMock

import pytest

from engines.churn_prediction.discount_minter import (
    mint_retention_code,
)


def _prediction(
    *,
    customer_id="cust1",
    risk_level="critical",
    retention_action="win_back_offer",
    estimated_cost_tier="medium",
):
    return {
        "customer_id": customer_id,
        "churn_probability": 0.85,
        "risk_level": risk_level,
        "retention_action": retention_action,
        "estimated_cost_tier": estimated_cost_tier,
        "key_factors": [],
    }


def _customer(id_="cust1"):
    return {"id": id_, "email": f"{id_}@x.example"}


class TestRiskFilter:

    def test_critical_risk_mints(self):
        with patch(
            "engines.churn_prediction.discount_minter._mint",
            return_value={
                "code": "RETAIN1", "discount_id": "gid://1",
                "ends_at": "2030-01-01", "applies_once": True,
            },
        ), patch(
            "engines.churn_prediction.discount_minter."
            "record_writeback",
        ):
            result = mint_retention_code(
                _prediction(risk_level="critical"),
                _customer(),
            )
        assert result is not None
        assert result["code"] == "RETAIN1"
        assert result["customer_id"] == "cust1"

    def test_high_risk_mints(self):
        with patch(
            "engines.churn_prediction.discount_minter._mint",
            return_value={"code": "X"},
        ), patch(
            "engines.churn_prediction.discount_minter."
            "record_writeback",
        ):
            result = mint_retention_code(
                _prediction(risk_level="high"),
                _customer(),
            )
        assert result is not None

    def test_medium_risk_skipped(self):
        """Medium risk doesn't warrant retention spend yet."""
        with patch(
            "engines.churn_prediction.discount_minter._mint",
        ) as mint_mock:
            result = mint_retention_code(
                _prediction(risk_level="medium"),
                _customer(),
            )
        assert result is None
        mint_mock.assert_not_called()

    def test_low_risk_skipped(self):
        with patch(
            "engines.churn_prediction.discount_minter._mint",
        ) as mint_mock:
            result = mint_retention_code(
                _prediction(risk_level="low"),
                _customer(),
            )
        assert result is None
        mint_mock.assert_not_called()


class TestRetentionActionFilter:

    def test_win_back_offer_mints(self):
        with patch(
            "engines.churn_prediction.discount_minter._mint",
            return_value={"code": "X"},
        ), patch(
            "engines.churn_prediction.discount_minter."
            "record_writeback",
        ):
            result = mint_retention_code(
                _prediction(retention_action="win_back_offer"),
                _customer(),
            )
        assert result is not None

    @pytest.mark.parametrize("action", [
        "personal_outreach",
        "exclusive_access",
        "loyalty_reward",
        "engagement_email",
    ])
    def test_non_mintable_actions_skip(self, action):
        with patch(
            "engines.churn_prediction.discount_minter._mint",
        ) as mint_mock:
            result = mint_retention_code(
                _prediction(retention_action=action),
                _customer(),
            )
        assert result is None
        mint_mock.assert_not_called()


class TestCostTierMapping:

    @pytest.mark.parametrize("tier,expected_pct", [
        ("low", 10.0),
        ("medium", 15.0),
        ("high", 20.0),
        ("unknown", 10.0),  # Default
    ])
    def test_cost_tier_maps_to_percentage(
        self, tier, expected_pct,
    ):
        with patch(
            "engines.churn_prediction.discount_minter._mint",
            return_value={"code": "X"},
        ) as mint_mock, patch(
            "engines.churn_prediction.discount_minter."
            "record_writeback",
        ):
            mint_retention_code(
                _prediction(estimated_cost_tier=tier),
                _customer(),
            )
        kwargs = mint_mock.call_args.kwargs
        assert kwargs["value"] == expected_pct


class TestTtlOverride:

    def test_store_override_clamped(self):
        with patch(
            "engines.churn_prediction.discount_minter._mint",
            return_value={"code": "X"},
        ) as mint_mock, patch(
            "engines.churn_prediction.discount_minter."
            "record_writeback",
        ):
            mint_retention_code(
                _prediction(),
                _customer(),
                store={"retention_code_ttl_days": 30},
            )
        assert mint_mock.call_args.kwargs["ttl_days"] == 30

    def test_invalid_override_falls_back_to_default(self):
        with patch(
            "engines.churn_prediction.discount_minter._mint",
            return_value={"code": "X"},
        ) as mint_mock, patch(
            "engines.churn_prediction.discount_minter."
            "record_writeback",
        ):
            mint_retention_code(
                _prediction(),
                _customer(),
                # 999 is out of range -> default 14
                store={"retention_code_ttl_days": 999},
            )
        assert mint_mock.call_args.kwargs["ttl_days"] == 14


class TestPatternZRecording:

    def test_success_records_writeback(self):
        with patch(
            "engines.churn_prediction.discount_minter._mint",
            return_value={"code": "X"},
        ), patch(
            "engines.churn_prediction.discount_minter."
            "record_writeback",
        ) as record_mock:
            mint_retention_code(
                _prediction(), _customer(),
            )
        record_mock.assert_called_once()
        kwargs = record_mock.call_args.kwargs
        assert kwargs["engine"] == "churn_prediction"
        assert kwargs["action_type"] == "mint_retention_code"
        assert kwargs["success"] is True

    def test_mint_failure_records_writeback(self):
        with patch(
            "engines.churn_prediction.discount_minter._mint",
            return_value=None,
        ), patch(
            "engines.churn_prediction.discount_minter."
            "record_writeback",
        ) as record_mock:
            result = mint_retention_code(
                _prediction(), _customer(),
            )
        assert result is None
        record_mock.assert_called_once()
        assert record_mock.call_args.kwargs["success"] is False
        assert (
            "mint_returned_none"
            in record_mock.call_args.kwargs["error"]
        )


class TestFlowOptIn:

    def _seed_payload(self, *, apply_codes=False):
        # Minimal customer dict that gets through the engine
        # validator + retention recommender. Real engine has
        # ~20 fields; the validator only requires `id`.
        return {
            "status": "success",
            "data": {
                "customers": [
                    {
                        "id": "cust1",
                        "email": "cust1@x.example",
                        "total_lifetime_value": 500,
                    },
                ],
                "apply_retention_codes": apply_codes,
            },
            "meta": {},
            "error": None,
        }

    def test_no_flag_no_mint(self):
        """Default: no apply_retention_codes flag = no mints."""
        from engines.churn_prediction.flow import (
            ChurnPredictionEngine,
        )
        with patch(
            "engines.churn_prediction.discount_minter."
            "mint_retention_code",
        ) as mint_mock:
            result = ChurnPredictionEngine().run(
                self._seed_payload(apply_codes=False),
            )
        mint_mock.assert_not_called()
        assert result["status"] == "success"
        assert result["data"]["minted_codes"] == []

    def test_opt_in_invokes_minter_for_each_prediction(self):
        from engines.churn_prediction.flow import (
            ChurnPredictionEngine,
        )
        with patch(
            "engines.churn_prediction.discount_minter."
            "mint_retention_code",
            return_value={
                "code": "RETAIN1",
                "discount_id": "gid://1",
                "ends_at": "2030-01-01",
                "applies_once": True,
                "customer_id": "cust1",
            },
        ) as mint_mock:
            result = ChurnPredictionEngine().run(
                self._seed_payload(apply_codes=True),
            )
        assert mint_mock.call_count >= 1
        assert result["data"]["minted_codes"]
        first_code = result["data"]["minted_codes"][0]
        assert first_code["code"] == "RETAIN1"

    def test_mint_loop_raise_doesnt_break_envelope(self):
        """A raising minter must not propagate -- the engine
        still returns its standard envelope."""
        from engines.churn_prediction.flow import (
            ChurnPredictionEngine,
        )
        with patch(
            "engines.churn_prediction.discount_minter."
            "mint_retention_code",
            side_effect=RuntimeError("router boom"),
        ):
            result = ChurnPredictionEngine().run(
                self._seed_payload(apply_codes=True),
            )
        # Engine still emits a clean envelope; minted_codes
        # is empty since every per-prediction mint raised.
        assert result["status"] == "success"
        assert result["data"]["minted_codes"] == []

    def test_estimated_cost_tier_flows_through_prediction(self):
        """The cost_tier added to predictions in this PR must
        actually appear on each prediction so the minter can
        read it."""
        from engines.churn_prediction.flow import (
            ChurnPredictionEngine,
        )
        result = ChurnPredictionEngine().run(
            self._seed_payload(apply_codes=False),
        )
        assert result["status"] == "success"
        predictions = result["data"]["predictions"]
        assert predictions
        for p in predictions:
            assert "estimated_cost_tier" in p
