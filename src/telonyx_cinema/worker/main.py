import os
import socket
import time

from redis import Redis
from rq import Worker

REDIS_URL = os.getenv('REDIS_URL', 'redis://localhost:6379/0')


def write_worker_heartbeat(redis: Redis) -> None:
    redis.hset(
        'worker:heartbeat',
        mapping={
            'status': 'starting',
            'host': socket.gethostname(),
            'updated_at': str(int(time.time())),
            'queue': 'render',
        },
    )


def main() -> None:
    redis = Redis.from_url(REDIS_URL)
    write_worker_heartbeat(redis)
    worker = Worker(['render'], connection=redis)
    worker.work(with_scheduler=True)


if __name__ == '__main__':
    main()
