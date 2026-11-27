"""Tests for Redis capacity and persistence monitoring decisions."""

from monitor_redis_capacity import assess

MEMORY = {"used_memory": 79, "maxmemory": 100}
STATS = {"evicted_keys": 0}
PERSISTENCE = {"aof_enabled": 1, "aof_last_write_status": "ok"}


def test_healthy():
    assert assess(MEMORY, STATS, PERSISTENCE, "noeviction") == []


def test_rejects_unsafe_policy_and_previous_loss():
    assert len(assess(MEMORY, {"evicted_keys": 1}, PERSISTENCE, "allkeys-lru")) == 2


def test_memory_threshold_and_missing_limit():
    assert assess({"used_memory": 80, "maxmemory": 100}, STATS, PERSISTENCE, "noeviction")
    assert assess({"used_memory": 1, "maxmemory": 0}, STATS, PERSISTENCE, "noeviction")


def test_unhealthy_persistence():
    assert assess(MEMORY, STATS, {"aof_enabled": 1, "aof_last_write_status": "err"}, "noeviction")
    assert assess(MEMORY, STATS, {"aof_enabled": 0}, "noeviction")
