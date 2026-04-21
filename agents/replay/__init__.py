"""Replay subpackage — feed historical / synthetic events back
through ShopAI's live pipeline to exercise learning loops
without waiting for real traffic."""
from agents.replay.order_replay import (
    OrderReplayResult,
    ReplayStats,
    replay_orders,
    replay_orders_from_file,
)

__all__ = [
    "OrderReplayResult",
    "ReplayStats",
    "replay_orders",
    "replay_orders_from_file",
]
