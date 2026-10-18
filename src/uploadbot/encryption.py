"""Seekable authenticated encryption with a fresh key for every uploaded file."""

import argparse
import base64
import getpass
import math
import os
import struct
import tempfile
from collections.abc import AsyncIterator, Sequence
from contextlib import aclosing, asynccontextmanager
from pathlib import Path

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCMSIV

from uploadbot.errors import TransferError
from uploadbot.http import Chunk
from uploadbot.sources import ReplaySource

FRAME_SIZE = 512 * 1024
HEADER = struct.Struct(">8sIQ8s")
MAGIC = b"UPBOT01\x00"


class EncryptedSource:
    encrypted = True

    def __init__(self, source: ReplaySource):
        if source.encrypted or not 0 < source.size <= FRAME_SIZE * (2**32 - 1):
            raise ValueError("Invalid plaintext source")
        self.source = source
        self.filename = source.filename[:170] + ".ubenc"
        self._key = AESGCMSIV.generate_key(bit_length=256)
        self._prefix = os.urandom(8)
        self.header = HEADER.pack(MAGIC, FRAME_SIZE, source.size, self._prefix)
        self.frames = math.ceil(source.size / FRAME_SIZE)
        self.size = HEADER.size + source.size + 16 * self.frames

    @property
    def key_text(self) -> str:
        return base64.urlsafe_b64encode(self._key).decode("ascii")

    @asynccontextmanager
    async def open(self, offset: int = 0, length: int | None = None):
        remaining = self.size - offset if length is None else length
        if offset < 0 or remaining < 0 or offset + remaining > self.size:
            raise ValueError("Requested range is outside the encrypted file")

        async def encoded() -> AsyncIterator[Chunk]:
            nonlocal remaining
            position = offset
            if position < HEADER.size and remaining:
                piece = self.header[position : position + remaining]
                yield piece
                remaining -= len(piece)
                position += len(piece)
            if not remaining:
                return
            frame = (position - HEADER.size) // (FRAME_SIZE + 16)
            skip = (position - HEADER.size) % (FRAME_SIZE + 16)
            cipher = AESGCMSIV(self._key)
            # Open one contiguous Telegram range. Only the first frame can be partial.
            plain_offset = frame * FRAME_SIZE
            final_position = position + remaining - 1 - HEADER.size
            final_frame = min(final_position // (FRAME_SIZE + 16), self.frames - 1)
            plain_end = min((final_frame + 1) * FRAME_SIZE, self.source.size)
            async with self.source.open(plain_offset, plain_end - plain_offset) as chunks:
                buffer = bytearray()
                async for chunk in chunks:
                    buffer.extend(chunk)
                    while remaining:
                        count = min(FRAME_SIZE, self.source.size - frame * FRAME_SIZE)
                        if len(buffer) < count:
                            break
                        number = frame.to_bytes(4, "big")
                        encrypted = cipher.encrypt(
                            self._prefix + number, bytes(buffer[:count]), self.header + number
                        )
                        del buffer[:count]
                        piece = encrypted[skip : skip + remaining]
                        remaining -= len(piece)
                        yield piece
                        skip = 0
                        frame += 1
                    if not remaining:
                        return
            raise TransferError("The plaintext source ended before encryption finished.")

        async with aclosing(encoded()) as chunks:
            yield chunks


def decrypt_file(source: Path, output: Path, key_text: str) -> None:
    """Publish the plaintext only after every frame has authenticated successfully."""
    if os.path.lexists(output):
        raise FileExistsError("The output path already exists")
    try:
        key = base64.b64decode(key_text.strip(), altchars=b"-_", validate=True)
        if len(key) != 32:
            raise ValueError
    except (ValueError, UnicodeError):
        raise ValueError("The decryption key must encode exactly 32 bytes") from None
    temporary: Path | None = None
    try:
        with source.open("rb") as incoming:
            header = incoming.read(HEADER.size)
            if len(header) != HEADER.size:
                raise ValueError("The encrypted file has a truncated header")
            magic, frame_size, size, prefix = HEADER.unpack(header)
            if (
                magic != MAGIC
                or frame_size != FRAME_SIZE
                or not 0 < size <= FRAME_SIZE * (2**32 - 1)
            ):
                raise ValueError("Unsupported encrypted file format")
            cipher = AESGCMSIV(key)
            with tempfile.NamedTemporaryFile(
                dir=output.parent, prefix=".uploadbot-", delete=False
            ) as outgoing:
                temporary = Path(outgoing.name)
                for frame in range(math.ceil(size / FRAME_SIZE)):
                    count = min(FRAME_SIZE, size - frame * FRAME_SIZE) + 16
                    encrypted = incoming.read(count)
                    if len(encrypted) != count:
                        raise ValueError("The encrypted file is truncated")
                    number = frame.to_bytes(4, "big")
                    outgoing.write(cipher.decrypt(prefix + number, encrypted, header + number))
                if incoming.read(1):
                    raise ValueError("The encrypted file has unexpected trailing data")
                outgoing.flush()
                os.fsync(outgoing.fileno())
            # Atomic, no overwrite, including symlinks created during decryption.
            os.link(temporary, output)
    except InvalidTag:
        raise ValueError("The key is incorrect or the encrypted file was modified") from None
    finally:
        if temporary:
            temporary.unlink(missing_ok=True)


def main(argv: Sequence[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Decrypt an UploadBot .ubenc file")
    parser.add_argument("input", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--key-file", type=Path, help="read the key from a private text file")
    args = parser.parse_args(argv)
    try:
        key = (
            args.key_file.read_text().strip()
            if args.key_file
            else getpass.getpass("Decryption key ")
        )
        decrypt_file(args.input, args.output, key)
    except (ValueError, OSError) as exc:
        parser.exit(1, f"Decryption failed. {exc}\n")
