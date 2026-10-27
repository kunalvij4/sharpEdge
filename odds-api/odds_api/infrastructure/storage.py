from odds_api.infrastructure.repository import SqlRepository


def create_repository(settings, clock=None):
    options = dict(
        clock=clock,
        collected_ttl=settings.collected_ttl,
        source_ttl=settings.source_ttl,
        propline_collected_ttl=settings.propline_collected_ttl,
    )
    if settings.storage_backend == "redis":
        from odds_api.infrastructure.redis_repository import RedisRepository

        if not settings.redis_url.get_secret_value():
            raise RuntimeError("Set REDIS_URL for Redis storage")
        return RedisRepository(
            settings.redis_url.get_secret_value(), settings.leagues, prefix=settings.redis_prefix, **options
        )
    return SqlRepository(settings.database_url, settings.leagues, settings.snapshot_retention_days, **options)


def collector_lease(repository, key=911712349):
    from odds_api.infrastructure.lease import CollectorLease

    if isinstance(repository, SqlRepository):
        return CollectorLease(repository.engine, key)
    return RedisLease(repository, key)


class RedisLease:
    def __init__(self, repository, key):
        self.lock = repository.client.lock(
            repository.key("lease:" + str(key)), timeout=120, blocking=False, thread_local=False
        )

    def __enter__(self):
        if not self.lock.acquire():
            raise RuntimeError("Another collector owns this Redis namespace")
        return self

    def ping(self):
        self.lock.extend(120, replace_ttl=True)

    def __exit__(self, *_):
        self.lock.release()
