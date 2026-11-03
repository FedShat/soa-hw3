from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine


def database(url: str):
    engine = create_async_engine(url, pool_pre_ping=True, pool_size=10, max_overflow=20)
    return engine, async_sessionmaker(engine, expire_on_commit=False)
