import math
from types import SimpleNamespace

from aiohttp import web

from uploadbot.encryption import FRAME_SIZE, decrypt_file
from uploadbot.models import UploadOptions
from uploadbot.providers import Provider, ProviderConfig, ProviderRegistry
from uploadbot.service import UploadService


async def test_telegram_encryption_part_retry_and_local_decryption(
    server_factory, session, tmp_path, monkeypatch
):
    monkeypatch.setattr("uploadbot.providers.RETRY_DELAY", 0)
    plaintext = bytes(range(256)) * 5000
    delivered_keys = []
    closed = []
    ranges = []
    received = {}
    attempts = {}
    part_size = FRAME_SIZE + 7

    class Download:
        def __init__(self, offset):
            self.offset = offset

        async def close(self):
            closed.append(self.offset)

        async def __aiter__(self):
            for start in range(self.offset, len(plaintext), FRAME_SIZE):
                yield memoryview(plaintext)[start : start + FRAME_SIZE]

    class Client:
        def iter_download(self, media, *, offset, **kwargs):
            assert offset % FRAME_SIZE == 0
            ranges.append(offset)
            return Download(offset)

    async def key_delivery(key):
        delivered_keys.append(key)

    async def handler(request):
        assert delivered_keys  # Delivery must succeed before any publication request.
        if request.path == "/api/v1/uploads":
            form = await request.post()
            assert form["name"].endswith(".ubenc")
            return web.json_response(
                dict(
                    upload_id="pipeline",
                    part_size=part_size,
                    parts=math.ceil(int(form["size"]) / part_size),
                )
            )
        if request.path.endswith("complete"):
            assert request.headers["Max-Days"] == "3"
            return web.Response(text="https://files.example/encrypted")
        number = int(request.path.rsplit("/", 1)[-1])
        attempts[number] = attempts.get(number, 0) + 1
        data = await request.read()
        if number == 2 and attempts[number] == 1:
            return web.Response(status=503)
        received[number] = data
        return web.Response(text="ok")

    base = await server_factory(handler)
    provider = Provider(session, ProviderConfig("default", "file2share", base), 10_000_000)
    provider.single_limit = 1
    message = SimpleNamespace(
        id=1, media=object(), file=SimpleNamespace(size=len(plaintext), name="test.bin")
    )
    service = UploadService(Client(), ProviderRegistry([provider]))
    completed = await service.upload(
        message, "default", UploadOptions(3, encrypted=True), on_key=key_delivery
    )
    assert attempts == {1: 1, 2: 2, 3: 1}
    assert len(ranges) == len(closed) == 4
    body = b"".join(received[n] for n in sorted(received))
    assert len(body) == completed.result.size
    assert completed.result.encrypted
    assert completed.key == delivered_keys[0]
    incoming, output = tmp_path / "file.ubenc", tmp_path / "original"
    incoming.write_bytes(body)
    decrypt_file(incoming, output, delivered_keys[0])
    assert output.read_bytes() == plaintext
