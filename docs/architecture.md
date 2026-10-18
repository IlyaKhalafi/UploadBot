# How streaming works

```mermaid
sequenceDiagram
    participant User
    participant Bot as UploadBot
    participant Telegram
    participant Host as Transfer server
    User->>Bot: Send a file
    Bot->>Bot: Validate size and reserve a slot
    Bot->>Host: PUT /filename (Content-Length)
    loop Until the file ends
        Bot->>Telegram: Request up to 512 KiB
        Telegram-->>Bot: File chunk
        Bot->>Host: Write chunk, await socket backpressure
    end
    Host-->>Bot: HTTP success + download URL
    Bot-->>User: Download URL
```

`Telethon.iter_download` yields bounded chunks. An asynchronous generator passes
those chunks to `aiohttp` as a request body. HTTP flow control pauses the producer
when the destination cannot accept more data. No application-level prefetch queue
or temporary file grows with file size. Socket buffers and Telegram/HTTP internal
buffers still consume memory; this is not a zero-copy implementation.

The transfer starts uploading before the Telegram download completes, removing
the separate disk-writing phase and allowing network operations to overlap.
Throughput is bounded by the slower connection, Telegram's request latency and
rate limits, cryptography, and the upload host. There is no guaranteed speedup.
The previous implementation already downloaded to disk rather than holding the
whole file in RAM; the main gains are eliminating disk I/O and blocking HTTP.

## Lifecycle and failures

The event handler claims a slot before its first transfer-related await. Each user
can run one transfer and the configured global limit bounds active jobs. When
full, new work is rejected immediately instead of entering an unbounded queue.
`/cancel` cancels the active handler. All exit paths release the slot, and the
Telegram iterator is explicitly closed to return its borrowed connection.

The upload request uses the declared file length and validates the actual source
byte count. Non-success HTTP status codes, invalid URL responses, oversized
response bodies, transport errors, and incomplete streams produce a failed
transfer rather than a success link. Redirects are rejected because streamed
bodies cannot safely be replayed. There is no automatic upload retry or resume;
send the file again after an error. A server may retain a partial upload after
cancellation or a network error, depending on its implementation.

Progress edits are throttled to at most once every four seconds per job. A deleted
status message or Telegram edit rate limit does not abort the file transfer.

## URLs sent to the bot

For the reverse direction, UploadBot passes a public HTTP(S) URL to Telegram's
external-media API. Telegram fetches the file directly. The bot host does not
download it, and cannot enforce `MAX_FILE_SIZE` on this path. Telegram and the
remote source decide supported file types, size limits, redirects, and access.
Authentication-required pages, private-network links, and URLs needing browser
cookies generally do not work. URL queries are preserved and suffix detection
uses only the path.

## Local test downloads

A receiver bound to `127.0.0.1` accepts connections only from its own machine.
The bot can upload to it, but a returned loopback URL will not open directly on a
different computer. A successful upload reply labels private-network links.

If your test server uses port `36579`, forward that port from your computer.
Replace `your-server` with the host or SSH alias you use to connect to the bot's
machine.

```bash
ssh -N -L 36579:127.0.0.1:36579 your-server
```

Keep that connection open, then open the returned `http://127.0.0.1:36579/...`
URL in your browser. Substitute the receiver's actual port in both places if it
differs. The receiver must remain running for the download to work.

For links other people can open without SSH, configure `TRANSFER_URL` with a
working public transfer.sh-compatible host. Changing the hostname in a returned
URL does not make a loopback-bound receiver publicly reachable.

## Configuration and sessions

Environment variables override the repository-local `.env`. No secrets belong
in `config.py`. A persistent Telethon session is stored separately from uploaded
files; protect it like the bot token. On shutdown the Telegram client disconnects
before the shared HTTP session closes. Uploaded file bytes never enter the
session file.
