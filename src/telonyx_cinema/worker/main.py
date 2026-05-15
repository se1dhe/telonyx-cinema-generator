import os
import socket
import time

from redis import Redis
from redis.exceptions import RedisError
from rq import Worker

REDIS_URL = os.getenv('REDIS_URL', 'redis://localhost:6379/0')
REDIS_WAIT_SECONDS = int(os.getenv('REDIS_WAIT_SECONDS', '120'))


def wait_for_redis() -> Redis:
    deadline = time.time() + REDIS_WAIT_SECONDS
    last_error: Exception | None = None

    while time.time() < deadline:
        try:
            redis = Redis.from_url(REDIS_URL)
            redis.ping()
            return redis
        except RedisError as error:
            last_error = error
            print(f'Redis is not ready yet: {error}', flush=True)
            time.sleep(3)

    raise RuntimeError(f'Redis did not become ready after {REDIS_WAIT_SECONDS}s: {last_error}')


def write_worker_heartbeat(redis: Redis, status: str = 'starting') -> None:
    redis.hset(
        'worker:heartbeat',
        mapping={
            'status': status,
            'host': socket.gethostname(),
            'updated_at': str(int(time.time())),
            'queue': 'render',
        },
    )


def main() -> None:
    redis = wait_for_redis()
    write_worker_heartbeat(redis, 'starting')
    worker = Worker(['render'], connection=redis)
    write_worker_heartbeat(redis, 'idle')
    worker.work(with_scheduler=True)


if __name__ == '__main__':
    main()
