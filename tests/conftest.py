import aiohttp
import pytest_asyncio
from aiohttp import web
from aiohttp.test_utils import TestServer


@pytest_asyncio.fixture
async def server_factory():
    servers = []

    async def create(handler):
        app = web.Application()
        app.router.add_route("*", "/{path:.*}", handler)
        server = TestServer(app)
        await server.start_server()
        servers.append(server)
        return str(server.make_url("/")).rstrip("/")

    yield create
    for server in servers:
        await server.close()


@pytest_asyncio.fixture
async def session():
    async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=5)) as session:
        yield session
