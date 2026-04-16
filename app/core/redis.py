"""Redis client helpers."""

from redis.asyncio import Redis


def build_redis_client(redis_url: str) -> Redis:
    """Create the shared Redis client."""
    return Redis.from_url(redis_url, decode_responses=True)


async def ping_redis(client: Redis) -> bool:
    """Return whether Redis is reachable."""
    try:
        return bool(await client.ping())
    except Exception:
        return False
