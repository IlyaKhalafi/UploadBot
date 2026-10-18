from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from uploadbot.sources import TelegramSource
from uploadbot.transfer import CHUNK_SIZE, TransferError


class Stream:
    def __init__(self, data):
        self.data = iter(data)
        self.closed = False

    def __aiter__(self):
        return self

    async def __anext__(self):
        try:
            return next(self.data)
        except StopIteration:
            raise StopAsyncIteration from None

    async def close(self):
        self.closed = True


def source(data):
    streams = []

    def download(media, *, request_size, file_size, offset):
        assert offset % CHUNK_SIZE == 0
        stream = Stream([data[offset : offset + 3], data[offset + 3 :]])
        streams.append(stream)
        return stream

    client = Mock(iter_download=download)
    message = SimpleNamespace(
        id=1, media=object(), file=SimpleNamespace(name="video.mp4", ext=".mp4", size=len(data))
    )
    return TelegramSource(client, message), streams


async def test_ranges_are_replayable_and_closed():
    replay, streams = source(b"0123456789")
    for _ in range(2):
        async with replay.open(2, 5) as chunks:
            assert b"".join([bytes(chunk) async for chunk in chunks]) == b"23456"
    assert len(streams) == 2
    assert all(stream.closed for stream in streams)


async def test_early_consumer_exit_closes_telegram_sender():
    replay, streams = source(b"0123456789")
    with pytest.raises(RuntimeError):
        async with replay.open() as chunks:
            await anext(chunks)
            raise RuntimeError("consumer stopped")
    assert streams[0].closed


async def test_truncated_source_is_not_success():
    replay, streams = source(b"0123456789")
    replay.client.iter_download = lambda *args, **kwargs: Stream([b"01"])
    with pytest.raises(TransferError, match="complete"):
        async with replay.open() as chunks:
            _ = [chunk async for chunk in chunks]


@pytest.mark.parametrize("offset,length", [(-1, 1), (5, 10), (1, -1), (11, None)])
async def test_out_of_range_is_rejected(offset, length):
    replay, streams = source(b"0123456789")
    with pytest.raises(ValueError):
        async with replay.open(offset, length):
            pass
    assert not streams
