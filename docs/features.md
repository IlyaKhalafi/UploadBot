# Commands and providers

All commands work in private chats. Preferences persist across restarts and apply
to future uploads. An album occupies one existing transfer slot and uploads its
files sequentially. Cancelling it preserves links for files already completed.

| Command | Purpose |
| --- | --- |
| `/files [text]` | Show the latest ten active uploads, optionally matching a filename |
| `/link ID` | Retrieve a link using the short ID from history |
| `/delete ID` | Delete the remote file when its host supports deletion |
| `/provider [name]` | Inspect or change your selected provider |
| `/provider auto` | Explicitly allow fallback across configured providers |
| `/expiry [1-14]` | Request retention in days for new File2Share uploads |
| `/encrypt [on\|off]` | Inspect or change encryption for new uploads |
| `/cancel` | Stop the current transfer or remaining album files |

Completed uploads include Download, Share, Copy link, and Delete buttons where
supported. Copy link sends the plain URL for Telegram's long-press copy action.
Share opens Telegram's recipient chooser. Cancel appears during a transfer.
Buttons check ownership again when clicked.

History is private to each Telegram user and keeps up to 1,000 records per user
for 30 days. Expired and deleted files are hidden from active history. Removing
history metadata does not delete the remote file. File2Share expiry is an estimate;
its host controls availability. WebDAV and generic PUT hosts control their own
expiry, so `/expiry` does not promise automatic deletion on those hosts.

## Additional providers

`TRANSFER_URL` configures the provider named `default`. It uses File2Share's API
for the official File2Share hostname and raw PUT for custom hosts. Additional
profiles come from `UPLOAD_PROVIDERS`, a JSON array in `.env`.

```dotenv
UPLOAD_PROVIDERS='[{"name":"vault","kind":"webdav","url":"https://dav.example/uploads","public_url":"https://files.example/uploads","headers":{"Authorization":"Bearer replace-me"}}]'
```

The WebDAV directory must already exist and permit PUT and DELETE. Public URLs
must map to the same objects, without a login, for recipients to download them.
Without `public_url`, the bot returns the WebDAV URL, which may require login.
Each object gets a random prefix to avoid filename collisions. No directory
listing or separate web server is created by UploadBot.

Use `kind` of `put` for a host accepting raw PUT at `/<filename>` and returning a
URL in `X-Direct-Url` or a plain response body. A same-origin `X-Delete-Url` or
`X-Url-Delete` enables remote deletion. Use `file2share` only for an endpoint
implementing its numbered-part API too. Credentials require HTTPS except for
deliberate loopback tests. Redirects are rejected, and profile credentials are
never forwarded to another provider.

Select `/provider vault` to upload there exclusively. The default is `default`;
fallback happens only after `/provider auto`. In auto mode, hosts are tried in
configuration order using the same encryption settings. Choosing auto authorizes
sending the file to another configured host after a failure.

## Retries and progress

Temporary connection failures and HTTP 408, 425, 429, and 5xx responses are retried
up to three times with backoff. Large File2Share uploads preserve confirmed parts
and replay only the failed range from Telegram. Generic PUT retries start the
whole file again. WebDAV retries reuse the same object URL.

Retries do not survive a bot restart. File2Share has no documented abort endpoint,
so interrupted part sessions remain subject to host cleanup. A lost response to
its non-repeatable completion call can leave a published file without a recovered
link. The bot reports uncertainty and stops fallback in that case. Plain PUT
hosts can also retain incomplete or duplicate uploads after a lost response.

Progress shows average useful bytes per second and an estimated remaining time,
updated at most every four seconds. Retries do not make the percentage go
backwards. These figures include time spent retrying and are estimates rather
than measurements of the host's internal processing.
