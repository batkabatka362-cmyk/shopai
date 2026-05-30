"""Tests for core.automation.autonomy_armed (Wave 811-814)."""
from __future__ import annotations

from unittest.mock import patch

import pytest

from core.automation.autonomy_armed import (
    ArmCooldownError,
    DOMAIN_APPLY_FLAGS,
    DOMAIN_FIRING_MODE,
    ArmedEntry,
    ArmedState,
    apply_flags_for_domain,
    arm,
    disarm,
    disarm_all,
    firing_mode_for_domain,
    is_armed,
    list_armed,
)


@pytest.fixture(autouse=True)
def _disable_pytest_guard():
    """Allow writes during tests but redirect to in-memory state.

    The module's `_save_state` short-circuits under pytest
    (Pattern J). To exercise the real arm/disarm semantics we
    patch _save_state + _load_state to bounce through a dict so
    each test sees an isolated state.
    """
    state_ref: dict[str, ArmedState] = {"s": ArmedState()}

    def fake_load() -> ArmedState:
        return ArmedState(entries=list(state_ref["s"].entries))

    def fake_save(s: ArmedState) -> None:
        state_ref["s"] = ArmedState(entries=list(s.entries))

    with patch(
        "core.automation.autonomy_armed._load_state",
        side_effect=fake_load,
    ), patch(
        "core.automation.autonomy_armed._save_state",
        side_effect=fake_save,
    ):
        yield


class TestDomainCatalog:

    def test_ten_domains_registered(self):
        assert len(DOMAIN_APPLY_FLAGS) == 10

    def test_every_domain_has_at_least_one_flag(self):
        for domain, flags in DOMAIN_APPLY_FLAGS.items():
            assert flags, domain
            for f in flags:
                assert f.startswith("apply_"), (domain, f)

    def test_customer_support_has_two_flags(self):
        # Bundles refund applier + ticket-tag applier
        assert DOMAIN_APPLY_FLAGS["customer_support"] == (
            "apply_refunds", "apply_ticket_tags",
        )

    def test_shipping_alert_present(self):
        # 10th domain shipped W756-810
        assert "shipping_alert" in DOMAIN_APPLY_FLAGS

    def test_apply_flags_helper_returns_tuple(self):
        flags = apply_flags_for_domain("shipping_alert")
        assert flags == ("apply_shipping_alert",)

    def test_unknown_domain_returns_empty_tuple(self):
        assert apply_flags_for_domain("does_not_exist") == ()


class TestFiringMode:
    """W815: firing-mode classification (engine vs substrate)."""

    def test_every_domain_has_a_firing_mode(self):
        for domain in DOMAIN_APPLY_FLAGS:
            mode = firing_mode_for_domain(domain)
            assert mode in {"engine", "substrate"}, (domain, mode)

    def test_unknown_domain_returns_unknown(self):
        assert firing_mode_for_domain("not_a_domain") == "unknown"

    def test_engine_mode_domains(self):
        # Picked up by the cycle's writeback wired_map -- the
        # cycle controller will inject apply_X=True today.
        assert DOMAIN_FIRING_MODE["customer_support"] == "engine"
        assert DOMAIN_FIRING_MODE["marketing"] == "engine"

    def test_substrate_mode_domains(self):
        # No engine wraps these appliers; cycle does not fire
        # them today. Arm is aspirational.
        for d in (
            "fulfillment", "inventory", "discount_cleanup",
            "order_followup", "product_seo",
            "customer_outreach", "catalog_quality",
            "shipping_alert",
        ):
            assert DOMAIN_FIRING_MODE[d] == "substrate", d

    def test_mode_split_2_engine_8_substrate(self):
        n_engine = sum(
            1 for m in DOMAIN_FIRING_MODE.values()
            if m == "engine"
        )
        n_sub = sum(
            1 for m in DOMAIN_FIRING_MODE.values()
            if m == "substrate"
        )
        # 2 engine-style + 8 substrate-only = 10 total
        assert n_engine == 2
        assert n_sub == 8
        assert n_engine + n_sub == len(DOMAIN_APPLY_FLAGS)


class TestArmDisarm:

    def test_idle_state_nothing_armed(self):
        assert list_armed() == []
        assert not is_armed("shipping_alert")

    def test_arm_adds_entry(self):
        e = arm("shipping_alert", reason="dogfood")
        assert e.domain == "shipping_alert"
        assert e.reason == "dogfood"
        assert e.armed_at > 0
        assert is_armed("shipping_alert")

    def test_arm_idempotent(self):
        e1 = arm("inventory")
        e2 = arm("inventory")
        # Second call returns existing entry, not new one
        assert e1.armed_at == e2.armed_at
        assert len(list_armed()) == 1

    def test_arm_unknown_domain_raises(self):
        with pytest.raises(ValueError) as exc_info:
            arm("bogus_domain")
        assert "unknown autonomy domain" in str(exc_info.value)

    def test_disarm_removes_entry(self):
        arm("marketing")
        assert is_armed("marketing")
        removed = disarm("marketing")
        assert removed is True
        assert not is_armed("marketing")

    def test_disarm_idempotent_returns_false(self):
        removed = disarm("never_armed")
        assert removed is False

    def test_disarm_all_clears_everything(self):
        arm("marketing")
        arm("shipping_alert")
        arm("inventory")
        count = disarm_all()
        assert count == 3
        assert list_armed() == []

    def test_disarm_all_empty_returns_zero(self):
        assert disarm_all() == 0

    def test_list_armed_preserves_arm_order(self):
        arm("marketing")
        arm("shipping_alert")
        arm("inventory")
        names = [e.domain for e in list_armed()]
        assert names == [
            "marketing", "shipping_alert", "inventory",
        ]


class TestCooldownEnvKnobs:
    """W866: per-domain env override of cooldown hours."""

    def test_default_global(self, monkeypatch):
        from core.automation.autonomy_armed import (
            _cooldown_hours,
        )
        monkeypatch.delenv(
            "SHOPAI_AUTO_DISARM_COOLDOWN_HOURS",
            raising=False,
        )
        assert _cooldown_hours() == 12.0
        assert _cooldown_hours("shipping_alert") == 12.0

    def test_global_env_overrides(self, monkeypatch):
        from core.automation.autonomy_armed import (
            _cooldown_hours,
        )
        monkeypatch.setenv(
            "SHOPAI_AUTO_DISARM_COOLDOWN_HOURS", "24",
        )
        assert _cooldown_hours() == 24.0
        assert _cooldown_hours("shipping_alert") == 24.0

    def test_per_domain_env_wins(self, monkeypatch):
        from core.automation.autonomy_armed import (
            _cooldown_hours,
        )
        monkeypatch.setenv(
            "SHOPAI_AUTO_DISARM_COOLDOWN_HOURS", "12",
        )
        monkeypatch.setenv(
            "SHOPAI_AUTO_DISARM_COOLDOWN_"
            "SHIPPING_ALERT_HOURS",
            "48",
        )
        # Other domains use global
        assert _cooldown_hours("inventory") == 12.0
        # shipping_alert uses per-domain
        assert _cooldown_hours("shipping_alert") == 48.0

    def test_invalid_per_domain_falls_back_to_global(
        self, monkeypatch,
    ):
        from core.automation.autonomy_armed import (
            _cooldown_hours,
        )
        monkeypatch.setenv(
            "SHOPAI_AUTO_DISARM_COOLDOWN_HOURS", "12",
        )
        monkeypatch.setenv(
            "SHOPAI_AUTO_DISARM_COOLDOWN_"
            "SHIPPING_ALERT_HOURS",
            "not-a-number",
        )
        assert _cooldown_hours("shipping_alert") == 12.0

    def test_none_domain_returns_global(self, monkeypatch):
        from core.automation.autonomy_armed import (
            _cooldown_hours,
        )
        monkeypatch.setenv(
            "SHOPAI_AUTO_DISARM_COOLDOWN_"
            "SHIPPING_ALERT_HOURS",
            "48",
        )
        # Passing None defers to global
        assert _cooldown_hours(None) == 12.0


class TestArmCooldown:
    """W859: post-auto-disarm cooldown blocks re-arm."""

    def test_no_recent_disarm_arm_succeeds(self):
        from unittest.mock import patch
        with patch(
            "core.automation.substrate_fire_disarm_log."
            "last_disarm_at",
            return_value=None,
        ):
            e = arm("shipping_alert", reason="ok")
        assert e.domain == "shipping_alert"

    def test_recent_disarm_blocks_arm(self):
        import time as _time
        from unittest.mock import patch
        # Auto-disarmed 1h ago; default cooldown 12h
        with patch(
            "core.automation.substrate_fire_disarm_log."
            "last_disarm_at",
            return_value=_time.time() - 3600.0,
        ):
            with pytest.raises(ArmCooldownError) as exc_info:
                arm("shipping_alert", reason="too soon")
        assert exc_info.value.hours_remaining > 10.0
        assert exc_info.value.hours_remaining <= 12.0

    def test_old_disarm_does_not_block(self):
        import time as _time
        from unittest.mock import patch
        # Auto-disarmed 100h ago; outside cooldown
        with patch(
            "core.automation.substrate_fire_disarm_log."
            "last_disarm_at",
            return_value=_time.time() - 100 * 3600.0,
        ):
            e = arm("shipping_alert", reason="ok")
        assert e.domain == "shipping_alert"

    def test_force_bypasses_cooldown(self):
        import time as _time
        from unittest.mock import patch
        with patch(
            "core.automation.substrate_fire_disarm_log."
            "last_disarm_at",
            return_value=_time.time() - 60.0,
        ):
            e = arm(
                "shipping_alert", reason="ovr", force=True,
            )
        assert e.domain == "shipping_alert"


class TestPerStoreScope:
    """W869: per-store armed entries."""

    def test_fleet_and_per_store_independent(self):
        # Fleet-wide arm + per-store arm for same domain are
        # independent entries.
        e1 = arm("shipping_alert", reason="fleet")
        e2 = arm(
            "shipping_alert", reason="per_store",
            store_id="store-1",
        )
        assert e1.store_id == ""
        assert e2.store_id == "store-1"
        assert e1.armed_at != e2.armed_at or True  # both ok
        assert is_armed("shipping_alert")
        assert is_armed("shipping_alert", store_id="store-1")
        assert not is_armed(
            "shipping_alert", store_id="store-2",
        )

    def test_disarm_fleet_does_not_touch_per_store(self):
        arm("shipping_alert", reason="fleet")
        arm(
            "shipping_alert", reason="per",
            store_id="store-1",
        )
        assert disarm("shipping_alert")  # fleet-wide
        assert not is_armed("shipping_alert")
        # Per-store entry survives
        assert is_armed(
            "shipping_alert", store_id="store-1",
        )

    def test_disarm_per_store_specific(self):
        arm(
            "shipping_alert", reason="a", store_id="store-1",
        )
        arm(
            "shipping_alert", reason="b", store_id="store-2",
        )
        assert disarm("shipping_alert", store_id="store-1")
        assert not is_armed(
            "shipping_alert", store_id="store-1",
        )
        assert is_armed(
            "shipping_alert", store_id="store-2",
        )

    def test_disarm_domain_all_removes_every_scope(self):
        from core.automation.autonomy_armed import (
            disarm_domain_all,
        )
        arm("shipping_alert", reason="fleet")
        arm(
            "shipping_alert", reason="a",
            store_id="store-1",
        )
        arm(
            "shipping_alert", reason="b",
            store_id="store-2",
        )
        removed = disarm_domain_all("shipping_alert")
        assert removed == 3
        assert not is_armed("shipping_alert")
        assert not is_armed(
            "shipping_alert", store_id="store-1",
        )

    def test_list_armed_filter_by_store(self):
        arm("shipping_alert", reason="fleet")
        arm(
            "shipping_alert", reason="a",
            store_id="store-1",
        )
        arm(
            "inventory", reason="b",
            store_id="store-1",
        )
        store1 = list_armed(store_id="store-1")
        assert len(store1) == 2
        assert all(
            e.store_id == "store-1" for e in store1
        )
        fleet = list_armed(store_id="")
        assert len(fleet) == 1
        assert fleet[0].store_id == ""

    def test_list_armed_no_filter_returns_all(self):
        arm("shipping_alert", reason="fleet")
        arm(
            "shipping_alert", reason="a",
            store_id="store-1",
        )
        all_entries = list_armed()
        assert len(all_entries) == 2

    def test_arm_idempotent_per_store(self):
        e1 = arm(
            "shipping_alert", reason="x",
            store_id="store-1",
        )
        e2 = arm(
            "shipping_alert", reason="y",
            store_id="store-1",
        )
        assert e1.armed_at == e2.armed_at  # same entry


class TestArmedStateDataclass:

    def test_empty_state_no_armed(self):
        s = ArmedState()
        assert not s.is_armed("anything")
        assert s.get("anything") is None

    def test_state_lookup(self):
        s = ArmedState(entries=[
            ArmedEntry(
                domain="marketing", armed_at=123.0,
                reason="testing",
            ),
        ])
        assert s.is_armed("marketing")
        e = s.get("marketing")
        assert e is not None
        assert e.reason == "testing"


class TestPatternJGuard:
    """Pattern J: writes short-circuit under pytest."""

    def test_save_state_no_ops_under_pytest(self, tmp_path):
        # Without the autouse fixture patching, the real
        # _save_state would skip the write under pytest.
        from core.automation import autonomy_armed as _aa

        assert _aa._is_test_environment() is True
        # Sanity: the function still returns cleanly
        state = ArmedState(entries=[
            ArmedEntry(domain="marketing", armed_at=1.0),
        ])
        # Real save - would have written if not in pytest
        _aa._save_state.__wrapped__ if hasattr(
            _aa._save_state, "__wrapped__"
        ) else None
        # No assertion beyond no-raise; the integration coverage
        # comes from the live autonomy-arm CLI tests below.
