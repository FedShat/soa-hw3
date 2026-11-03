import base64
import json
import logging

from google.protobuf.message import DecodeError
from redis.asyncio.sentinel import Sentinel
from redis.exceptions import RedisError

logger = logging.getLogger(__name__)


class FlightCache:
    def __init__(self, settings):
        addresses = [
            (host, int(port))
            for host, port in (
                address.rsplit(":", 1) for address in settings.redis_sentinels.split(",")
            )
        ]
        self.sentinel = Sentinel(
            addresses,
            socket_timeout=0.3,
            socket_connect_timeout=0.3,
        )
        self.redis = self.sentinel.master_for(settings.redis_master_name)
        self.ttl = settings.cache_ttl

    async def get(self, key, revision, message_type):
        try:
            raw = await self.redis.get(key)
            if raw:
                value = json.loads(raw)
                if value["revision"] == revision:
                    message = message_type.FromString(base64.b64decode(value["payload"]))
                    logger.info("cache hit key=%s revision=%s", key, revision)
                    return message
        except (RedisError, ValueError, KeyError, TypeError, DecodeError):
            logger.warning("cache read unavailable key=%s", key)
        logger.info("cache miss key=%s revision=%s", key, revision)
        return None

    async def set(self, key, revision, message):
        value = json.dumps(
            {
                "revision": revision,
                "payload": base64.b64encode(message.SerializeToString()).decode(),
            }
        )
        try:
            await self.redis.set(key, value, ex=self.ttl)
        except RedisError:
            logger.warning("cache write unavailable key=%s", key)

    async def invalidate(self, flight):
        day = flight.departure_time.date().isoformat()
        keys = [
            f"flight:{flight.id}",
            f"search:{flight.origin}:{flight.destination}:{day}",
            f"search:{flight.origin}:{flight.destination}:all",
        ]
        try:
            await self.redis.delete(*keys)
            logger.info("cache invalidated flight=%s", flight.id)
        except RedisError:
            logger.warning("cache invalidation deferred to revision check flight=%s", flight.id)

    async def close(self):
        await self.redis.aclose()
        for sentinel in self.sentinel.sentinels:
            await sentinel.aclose()
