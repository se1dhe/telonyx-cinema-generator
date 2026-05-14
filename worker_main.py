import os
from redis import Redis
from rq import SimpleWorker

REDIS_URL = os.getenv('REDIS_URL', 'redis://localhost:6379/0')
connection = Redis.from_url(REDIS_URL)
worker = SimpleWorker(['render'], connection=connection)
worker.work()
