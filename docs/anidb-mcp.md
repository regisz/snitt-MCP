# AniDB thin MCP + UDP client

HU / EN — setup and license choice for `snitt_anidb` / `snitt-anidb-mcp`.

## License / library choice

**Decision: own minimal UDP wrapper (MIT-compatible with this repo), not PyPI `anidb-client`.**

| Option | Notes |
|--------|--------|
| **`anidb-client` (PyPI)** | Mature, rate-limit aware, mylist helpers. **GPL-3.0-or-later**; Python **≥ 3.14.5**; pulls `pycryptodome` + `sqlalchemy`. Local `.venv` is 3.14.x so the version floor is fine, but **GPL cannot be bundled into the main package without Balázs’s explicit approval**. |
| **Owned `snitt_anidb` (chosen)** | Thin stdlib UDP + hard flood limiter + ban latch + gated `MYLISTADD`. No GPL dependency. Fits shared-lib + thin MCP pattern. |

If Balázs later approves GPL, wrapping `anidb-client` behind the same MCP surface remains possible; do not vendor its sources into this tree without that approval.

## AniDB client registration (required)

UDP `AUTH` needs a **registered** `client` / `clientver`:

1. Read [UDP API Definition](https://wiki.anidb.net/UDP_API_Definition) (protover **3**).
2. Register a new client name via the links on that page (“register it here and here”) / [UDP Clients](https://wiki.anidb.net/UDP_Clients) pointer (do **not** reuse another app’s name).
3. Name rules: lowercase `a-z` only, length **4–16** (e.g. `snittanidb`).
4. Start `clientver` at `1`; bump on each release that changes protocol behaviour.

Website password is used for AUTH. Profile “API password” is only for optional ENCRYPT — unused here.

## Credentials (password in process memory)

**Prefer: do not put the website password in `mcp.json` or `anidb.cfg`.**

Non-secret identity (ENV or file):

- `ANIDB_USER`
- `ANIDB_CLIENT` — registered client name
- `ANIDB_CLIENTVER` — integer
- `ANIDB_PROTOVER` — optional, default `3`
- `ANIDB_CONFIG_FILE` — optional path override

Password:

1. **MCP (preferred):** call tool `anidb_set_password` once per MCP process. Stored only on the shared `AniDBClient` in memory. Tool result is `{ok, ready}` only — never echoes the password. Never written to disk. Never logged by the client.
2. **CLI:** `snitt-anidb session-status` (or any `AniDBClient(interactive=True)`) prompts once with `getpass.getpass` into memory for that process.
3. **Optional fallback:** `ANIDB_PASS` / cfg `pass` still works if present, but **omit it from `mcp.json`**.

Clear with `anidb_clear_credentials` (clears memory password + session; best-effort UDP `LOGOUT`).

If AUTH tools run without a password, they fail with: *call anidb_set_password first*.

Or file `~/.config/snitt/anidb.cfg` (no password):

```ini
# ~/.config/snitt/anidb.cfg
user=YOUR_USER
client=snittanidb
clientver=1
# protover=3
# pass=  # prefer omit — use anidb_set_password / getpass instead
```

## Flood rules / ban latch

Client enforces wiki flood protection:

- After the first packets: **≥ 2 s** between datagrams
- Sustained (≥ 5 packets since idle reset): **≥ 4 s**
- **One** shared session/socket per MCP process
- On `504` / `555`, ACCESS DENIED, timeout, or unparseable reply → **ban latch** stops all further calls until `anidb_reset_ban_latch` (local clear only)

Do not retry blindly after a ban (dropped packets still count toward rate).

## Install

```bash
cd /home/balage/devel-magan/snitt-mcp   # space-free symlink
source .venv/bin/activate
pip install -e ".[all]"   # includes mcp; anidb is stdlib
```

Entry points: `snitt-anidb-mcp` (stdio MCP), `snitt-anidb` (CLI helpers).

## Cursor `mcp.json` snippet

Omit `ANIDB_PASS` — set the password in chat via `anidb_set_password` after the server starts:

```json
"snitt-anidb": {
  "command": "/home/balage/devel-magan/snitt-mcp/.venv/bin/snitt-anidb-mcp",
  "args": [],
  "env": {
    "ANIDB_USER": "PASTE_LOCAL_ONLY",
    "ANIDB_CLIENT": "snittanidb",
    "ANIDB_CLIENTVER": "1"
  }
}
```

Or omit `env` and use `~/.config/snitt/anidb.cfg` (still omit `pass`).

### How Balázs uses it in Cursor chat

1. Ensure `mcp.json` has user/client/clientver only (no password).
2. Reload MCP / restart the `snitt-anidb` server.
3. In chat: ask the agent to call `anidb_set_password` with the website password (or invoke the tool yourself). Expect `{ "ok": true, "ready": true }` — password must not appear in the tool result.
4. Then use `anidb_session_status` / lookup / mylist tools as usual (session stays in that MCP process).
5. Optional: `anidb_clear_credentials` when done (clears memory password + session).

Restarting the MCP server clears memory; set the password again.

## MCP tools

| Tool | Role |
|------|------|
| `anidb_session_status` | Local status (no UDP) |
| `anidb_set_password` | Store password in process memory (`ok`/`ready` only) |
| `anidb_clear_credentials` | Clear memory password + session |
| `anidb_lookup_anime` | `ANIME` by `aid` or exact `aname` |
| `anidb_mylist_get` | Bounded `MYLIST` |
| `anidb_mylist_stats` | `MYLISTSTATS` |
| `anidb_plan_mark_watched` | Dry-run `MYLISTADD` preview |
| `anidb_mark_watched` | Gated write (`allow_save=true`) |
| `anidb_plan_vote` | Dry-run `VOTE` preview (UI 1–10 → `value=stars*100`; default permanent) |
| `anidb_vote` | Gated `VOTE` (`allow_save=true`; `temporary=true` for Temporary Vote) |
| `anidb_reset_ban_latch` | Clear local ban latch |

Permanent Vote maps to UDP `VOTE type=1&id={aid}&value={stars*100}`. AniDB rejects permanent votes until finished airing (`363 PERMVOTE NOT ALLOWED`); use Temporary Vote in that case.

Fuzzy search is **not** implemented (UDP has no safe fuzzy search without flooding; use exact name or aid).

## Live traffic policy

Offline unit tests use `MockUdpTransport` only. Agents must **not** send authenticated UDP unless Balázs supplies credentials **and** explicitly allows the first live call.
