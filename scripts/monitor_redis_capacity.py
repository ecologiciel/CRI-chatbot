"""Report Redis queue-safety risks without printing credentials or keys."""

import os
import sys

import redis


def assess(memory, stats, persistence, policy):
    maximum = int(memory.get("maxmemory", 0))
    used = int(memory.get("used_memory", 0))
    problems = []
    if policy != "noeviction":
        problems.append("eviction policy is unsafe")
    if maximum <= 0:
        problems.append("memory limit is missing")
    elif used * 100 >= maximum * 80:
        problems.append("memory usage is at least 80 percent")
    if int(stats.get("evicted_keys", 0)) > 0:
        problems.append("Redis reports previously evicted keys")
    if not persistence.get("aof_enabled") or persistence.get("aof_last_write_status") != "ok":
        problems.append("append-only persistence is not healthy")
    return problems


def main():
    try:
        client = redis.Redis(
            host=os.environ.get("REDIS_HOST", "redis"),
            password=os.environ["REDIS_PASSWORD"],
            decode_responses=True,
            socket_timeout=5,
            socket_connect_timeout=5,
        )
        problems = assess(
            client.info("memory"),
            client.info("stats"),
            client.info("persistence"),
            client.config_get("maxmemory-policy").get("maxmemory-policy"),
        )
    except Exception:
        print("REDIS_ALERT: monitoring unavailable", file=sys.stderr)
        return 1
    if problems:
        print("REDIS_ALERT: " + "; ".join(problems), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
