"""Verify full-memory behaviour only against the disposable Redis fixture."""

import os
import secrets

import redis

if os.environ.get("REDIS_FIXTURE_HOST") != "codex-redis-eviction-test":
    raise RuntimeError("Refusing to run outside the Redis fixture")

client = redis.Redis(
    host="codex-redis-eviction-test",
    password="fixture-password",
    socket_timeout=5,
    decode_responses=True,
)
assert client.config_get("maxmemory-policy")["maxmemory-policy"] == "noeviction"
client.set("fixture:accepted-job", b"accepted")
failed = False
for index in range(200):
    try:
        client.set(f"fixture:payload:{index}", secrets.token_bytes(65536))
    except redis.exceptions.OutOfMemoryError:
        failed = True
        break
assert failed, "Fixture did not reach its memory limit"
assert client.get("fixture:accepted-job") == "accepted"
assert client.info("stats")["evicted_keys"] == 0
print("REDIS_NOEVICTION_SATURATION_OK", flush=True)
