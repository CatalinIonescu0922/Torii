import redis

# Check if redis supports connection_pool kwarg
print(redis.Redis(connection_pool=redis.ConnectionPool.from_url("redis://localhost:6379/0")))
