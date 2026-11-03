set -eu
if [ ! -f /data/redis.conf ]; then
    cp /config/redis.conf /data/redis.conf
    printf '\nreplica-announce-ip %s\n' "$REDIS_HOST" >> /data/redis.conf
    if [ -n "${REDIS_INITIAL_MASTER:-}" ]; then
        printf 'replicaof %s 6379\n' "$REDIS_INITIAL_MASTER" >> /data/redis.conf
    fi
fi
exec redis-server /data/redis.conf
