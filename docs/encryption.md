# Encrypted uploads

Use `/encrypt on` before sending a file. The bot sends its decryption key in a
separate private message before uploading the `.ubenc` file. Keep that message.
File contents are encrypted as chunks arrive, without a temporary upload file.
Keys are never saved in hosted files, URLs, or history metadata. Use `/encrypt off`
to return to ordinary uploads.

Download the `.ubenc` file, install UploadBot with uv, and run

```bash
uv run uploadbot-decrypt downloaded.ubenc --output original-file.zip
```

Paste the key at the hidden prompt. For automation, put it in a private text file
and pass `--key-file path/to/key.txt`. Existing output files are never replaced.
The command authenticates every frame before publishing the completed output.
It removes its temporary plaintext on failure.

Encryption protects file
contents from the upload host and people who only have the link. The host still
sees the filename and approximate size. Telegram and the bot server receive the
original file, and the key remains in your Telegram chat. This is not end-to-end
encryption between Telegram clients.

The output directory must support hard links, used to publish the authenticated
file atomically without overwriting an existing path. Decrypt to a local disk
first when using a filesystem such as FAT that does not support them.

## File format

Version 1 uses AES-256-GCM-SIV from
[cryptography](https://cryptography.io/en/latest/hazmat/primitives/aead/#cryptography.hazmat.primitives.ciphers.aead.AESGCMSIV).
Every file gets a new random 32-byte key and an 8-byte random nonce prefix.
Plaintext is divided into 512 KiB frames, with a shorter final frame. Each frame
has a 16-byte authentication tag.

The 28-byte header contains the magic `UPBOT01\0`, a big-endian 32-bit frame
size, a big-endian 64-bit plaintext size, and the nonce prefix. Each frame's
12-byte nonce combines that prefix with its big-endian 32-bit frame index.
Associated data combines the complete header with the same index. This binds
the length, ordering, and header to the authenticated contents.

Reopening a range reconstructs the same encrypted frames from the immutable
Telegram file, so failed upload parts can be retried without saving a local
copy. Memory use stays bounded by a few frames. Upload size limits include the
header and authentication tags.
