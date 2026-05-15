import os

from redis import Redis
from rq import Worker

REDIS_URL = os.getenv('REDIS_URL', 'redis://localhost:6379/0')


def main() -> None:
    redis = Redis.from_url(REDIS_URL)
    worker = Worker(['render'], connection=redis)
    worker.work(with_scheduler=True)


if __name__ == '__main__':
    main()
