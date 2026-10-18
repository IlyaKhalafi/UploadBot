import os

import pytest
from test_providers import MemorySource

from uploadbot.encryption import FRAME_SIZE, HEADER, EncryptedSource, decrypt_file


async def collect(source, offset=0, length=None):
    async with source.open(offset, length) as chunks:
        return b"".join([bytes(chunk) async for chunk in chunks])


@pytest.mark.parametrize(
    "size", [1, FRAME_SIZE - 1, FRAME_SIZE, FRAME_SIZE + 1, FRAME_SIZE * 2 + 7]
)
async def test_encryption_round_trip_and_replay_ranges(size, tmp_path):
    data = os.urandom(size)
    source = MemorySource(data)
    encrypted = EncryptedSource(source)
    body = await collect(encrypted)
    assert len(body) == encrypted.size
    assert body == await collect(encrypted)
    for offset, count in [(0, 5), (HEADER.size - 2, 6), (HEADER.size, 10), (len(body) - 1, 1)]:
        count = min(count, len(body) - offset)
        assert await collect(encrypted, offset, count) == body[offset : offset + count]
    if size > FRAME_SIZE:
        offset = HEADER.size + FRAME_SIZE + 12
        assert await collect(encrypted, offset, 20) == body[offset : offset + 20]
    assert all(count is None or count <= size for _, count in source.ranges)
    incoming = tmp_path / "file.ubenc"
    incoming.write_bytes(body)
    output = tmp_path / "plain"
    decrypt_file(incoming, output, encrypted.key_text)
    assert output.read_bytes() == data
    assert output.stat().st_mode & 0o777 == 0o600


@pytest.mark.parametrize("damage", ["ciphertext", "header", "truncated", "trailing", "wrong-key"])
async def test_tampering_never_publishes_partial_plaintext(damage, tmp_path):
    source = EncryptedSource(MemorySource(os.urandom(FRAME_SIZE + 4)))
    body = bytearray(await collect(source))
    key = source.key_text
    if damage == "ciphertext":
        body[-1] ^= 1
    elif damage == "header":
        body[25] ^= 1
    elif damage == "truncated":
        del body[-1]
    elif damage == "trailing":
        body += b"x"
    else:
        key = EncryptedSource(MemorySource()).key_text
    incoming, output = tmp_path / "encrypted", tmp_path / "plain"
    incoming.write_bytes(body)
    with pytest.raises(ValueError):
        decrypt_file(incoming, output, key)
    assert not output.exists()
    assert list(tmp_path.iterdir()) == [incoming]


async def test_never_overwrite_an_existing_destination(tmp_path):
    source = EncryptedSource(MemorySource())
    incoming, output = tmp_path / "encrypted", tmp_path / "plain"
    incoming.write_bytes(await collect(source))
    output.write_text("keep me")
    with pytest.raises(FileExistsError):
        decrypt_file(incoming, output, source.key_text)
    assert output.read_text() == "keep me"


async def test_fresh_keys_per_upload_and_invalid_ranges():
    one, two = EncryptedSource(MemorySource()), EncryptedSource(MemorySource())
    assert one.key_text != two.key_text
    assert await collect(one) != await collect(two)
    with pytest.raises(ValueError):
        await collect(one, -1)
    assert await collect(one, one.size, 0) == b""
