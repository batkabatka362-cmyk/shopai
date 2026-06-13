"""Tests for engines._clusters."""
from __future__ import annotations

from engines._clusters import (
    list_clusters,
    get_cluster,
    cluster_for_engine,
    unassigned_domain_engines,
)


class TestRegistry:

    def test_ten_clusters(self):
        clusters = list_clusters()
        assert len(clusters) == 10
        # Ensure no duplicates
        names = [c.name for c in clusters]
        assert len(set(names)) == len(names)

    def test_every_cluster_has_kpi(self):
        for c in list_clusters():
            assert c.kpi, f"Cluster {c.name} missing KPI"
            assert c.description, f"Cluster {c.name} missing description"
            assert c.members, f"Cluster {c.name} has no members"

    def test_get_cluster_by_name(self):
        c = get_cluster("pricing")
        assert c is not None
        assert c.name == "pricing"
        assert "pricing" in c.members
        assert "dynamic_pricing" in c.members

    def test_get_cluster_missing(self):
        assert get_cluster("nonexistent-cluster") is None


class TestEngineLookup:

    def test_cluster_for_known_engine(self):
        c = cluster_for_engine("loyalty")
        assert c is not None
        assert c.name == "retention"

    def test_cluster_for_pricing_engine(self):
        c = cluster_for_engine("dynamic_pricing")
        assert c is not None
        assert c.name == "pricing"

    def test_cluster_for_unassigned_engine(self):
        # global_brain is orchestrator-level, not in a cluster
        assert cluster_for_engine("global_brain") is None

    def test_cluster_for_unknown_engine(self):
        assert cluster_for_engine("does_not_exist_xyz") is None


class TestUniqueness:

    def test_no_engine_in_multiple_clusters(self):
        """Each engine should belong to exactly ONE cluster.
        Multi-cluster membership would break single-step
        delegation -- whose captain owns the engine?"""
        seen: dict[str, str] = {}
        for c in list_clusters():
            for member in c.members:
                if member in seen:
                    raise AssertionError(
                        f"Engine '{member}' appears in both "
                        f"'{seen[member]}' and '{c.name}' clusters"
                    )
                seen[member] = c.name


class TestCIInvariants:

    def test_no_unassigned_domain_engines(self):
        """Every domain engine MUST belong to a cluster.
        Engines that legitimately don't (orchestrator-level
        utilities) are in the _ORCHESTRATOR_UTILITIES
        allow-list inside engines/_clusters.py.

        If this test fails, EITHER:
          - Add the engine to a cluster (most likely), OR
          - Add it to _ORCHESTRATOR_UTILITIES with a comment
            explaining why it's orchestrator-level"""
        unassigned = unassigned_domain_engines()
        assert not unassigned, (
            f"Unassigned domain engines: {sorted(unassigned)}. "
            f"Add each to a cluster in engines/_clusters.py OR "
            f"to _ORCHESTRATOR_UTILITIES if it's orchestrator-"
            f"level."
        )


class TestBalance:

    def test_no_cluster_too_large(self):
        """Captain mandate floor: a captain should be able to
        reason about its members. >25 members suggests the
        cluster needs splitting."""
        for c in list_clusters():
            assert len(c.members) <= 25, (
                f"Cluster '{c.name}' has {len(c.members)} "
                f"members -- too many for one captain to "
                f"manage. Consider splitting."
            )

    def test_no_cluster_too_small(self):
        """A cluster with 1-2 members might not justify a
        captain. The minimum useful cluster size is 3."""
        for c in list_clusters():
            assert len(c.members) >= 3, (
                f"Cluster '{c.name}' has only {len(c.members)} "
                f"member(s). Either merge with a sibling cluster "
                f"or add more members."
            )
