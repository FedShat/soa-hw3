set -eu
if [ ! -f /data/sentinel.conf ]; then
    cp /config/sentinel.conf /data/sentinel.conf
    printf '\nsentinel announce-ip %s\n' "$SENTINEL_HOST" >> /data/sentinel.conf
fi
exec redis-server /data/sentinel.conf --sentinel
