# snitt-client

Shared Python library + thin CLI + local stdio MCP for verified Snitt.hu sheet fetch / dry-run / gated save.

Endpoints and field names come from Project mapping captures only (no invented APIs).

## Setup

```bash
cd "/home/balage/devel-magán/snitt.hu - MCP"
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev,mcp]"
# Google Sheets helper (gspread) as well:
pip install -e ".[sheets]"
# or everything: pip install -e ".[all]"
```

Packages under `src/`:

- `snitt_client` — Snitt HTTP/CLI/MCP
- `snitt_google_sheets` — thin `gspread` wrapper (optional extra)
- `snitt_anidb` — AniDB UDP client + `snitt-anidb-mcp` (stdlib; see `docs/anidb-mcp.md`)
- `snitt_crunchyroll` — unofficial Crunchyroll client + `snitt-crunchyroll-mcp` (token file; see `docs/crunchyroll-mcp.md`)

**Snitt auth** (cookie/session — **not** browser OAuth; never paste into chat):

- env `SNITT_COOKIE`, or
- first line of `~/.snitt-hu-downloader.cfg`

**Google Sheets auth** (browser OAuth preferred; never paste into chat) — see `docs/google-sheets-oauth.md`:

1. Desktop OAuth client JSON → `~/.config/snitt/google-oauth-client.json`
2. First run: `snitt-sheets-auth` (opens browser, stores refresh token at `~/.config/snitt/google-oauth-token.json`)
3. Optional fallback: service-account JSON via `GOOGLE_SHEETS_SERVICE_ACCOUNT_FILE` / `~/.config/snitt/google-service-account.json`

## Dry-run examples

```bash
# parse sheet (live GET; read-only)
snitt fetch --slug nyarido-szamitas

# dry-run műfaj plan (live GET + genres API; no POST)
snitt plan-genre --slug nyarido-szamitas --name thriller

# dry-run open tag plan
snitt plan-tag --slug grancrest-senki --name politika

# dry-run description plan (no POST)
snitt plan-description --slug dota-a-sarkany-vere --text "példa szöveg"
```

Writes are refused unless `--allow-save` is passed (and Balázs explicitly allowed the change):

```bash
# will refuse without --allow-save
snitt apply-genre --slug nyarido-szamitas --name thriller
```

## Cursor MCP (local stdio)

1. Install with MCP extras: `pip install -e ".[mcp]"`
2. Ensure session via `SNITT_COOKIE` or `~/.snitt-hu-downloader.cfg` (not in chat / not in git).
3. **Path with spaces:** Cursor `spawn` splits on spaces, so do **not** put
   `…/snitt.hu - MCP/…` directly in `command`. Prefer a space-free symlink
   (already useful on this machine):

```bash
mkdir -p /home/balage/devel-magan
ln -sfn "/home/balage/devel-magán/snitt.hu - MCP" /home/balage/devel-magan/snitt-mcp
```

Then use `docs/cursor-mcp.json.example` in `~/.cursor/mcp.json` (or project `.cursor/mcp.json`):

```json
{
  "mcpServers": {
    "snitt": {
      "command": "/home/balage/devel-magan/snitt-mcp/.venv/bin/snitt-mcp",
      "args": []
    },
    "snitt-sheets": {
      "command": "/home/balage/devel-magan/snitt-mcp/.venv/bin/snitt-sheets-mcp",
      "args": []
    },
    "snitt-anidb": {
      "command": "/home/balage/devel-magan/snitt-mcp/.venv/bin/snitt-anidb-mcp",
      "args": [],
      "env": {
        "ANIDB_USER": "PASTE_LOCAL_ONLY",
        "ANIDB_CLIENT": "snittanidb",
        "ANIDB_CLIENTVER": "1"
      }
    }
  }
}
```

Install MCP extras first: `pip install -e ".[all]"` (mcp + gspread; AniDB is stdlib).

Alternative without symlink: `bash -lc` wrapper — see `docs/cursor-mcp-bash-wrapper.json.example`.

Optional: `SNITT_COOKIE` / `GOOGLE_SHEETS_SERVICE_ACCOUNT_FILE` / AniDB ENV under each server's `env`.

4. Reload MCP / restart Cursor; tools under `snitt`, `snitt-sheets`, `snitt-anidb`, and `snitt-crunchyroll`.

### Tool names

| Tool | Role |
|------|------|
| `snitt_fetch_sheet` | GET + parse sheet |
| `snitt_resolve_tag` | open tag id from API |
| `snitt_resolve_genre` | műfaj id from API |
| `snitt_plan_add_tag` | dry-run open tag |
| `snitt_plan_add_genre` | dry-run műfaj |
| `snitt_plan_add_description` | dry-run description |
| `snitt_apply_tag` | gated POST (`allow_save=true`) |
| `snitt_apply_genre` | gated POST (`allow_save=true`) |
| `snitt_apply_description` | gated POST (`allow_save=true`) |
| `snitt_verify_sheet` | re-fetch; optional `expected_tag` |
| `snitt_list_watchings` | filmnézések list (year/type/…) |
| `snitt_series_watch_span` | series first/latest from year pages |
| `snitt_list_ratings` | értékelések: stars + review text |
| `snitt_fetch_rating` | one értékelés detail |

#### `snitt-sheets` server (`snitt-sheets-mcp`)

| Tool | Role |
|------|------|
| `sheets_list_worksheets` | tab titles (id or URL) |
| `sheets_read_records` | all rows as dicts |
| `sheets_append_rows` | gated append (`allow_write=true`) |

Typical check: Sheets `sheets_read_records` + Snitt `snitt_list_watchings` / `snitt_series_watch_span`, then compare in chat.

#### `snitt-anidb` server (`snitt-anidb-mcp`)

| Tool | Role |
|------|------|
| `anidb_session_status` | local session / rate-limit / ban (no UDP) |
| `anidb_set_password` | store website password in MCP process memory (`ok`/`ready` only) |
| `anidb_clear_credentials` | clear memory password + session |
| `anidb_lookup_anime` | `ANIME` by aid or exact name |
| `anidb_mylist_get` | bounded `MYLIST` |
| `anidb_mylist_stats` | `MYLISTSTATS` |
| `anidb_plan_mark_watched` | dry-run `MYLISTADD` preview |
| `anidb_mark_watched` | gated write (`allow_save=true`) |
| `anidb_reset_ban_latch` | clear local ban latch |

Omit `ANIDB_PASS` from `mcp.json`; call `anidb_set_password` once per MCP process. Full setup: `docs/anidb-mcp.md`.

Writes default to refuse; only pass `allow_save` / `allow_write=true` after explicit Balázs approval.

## Watch history / ratings (read-only)

```bash
# what Balázs watched in 2024 (movies)
snitt list-watchings --year 2024 --type movies

# series start/latest within scanned years (finished_at not on site)
snitt series-watch-span --slug grancrest-senki --years 2025 --type series

# personal stars (+ stars_percent=stars*10) and vélemény text when present
snitt list-ratings --is-reviewed 1
snitt fetch-rating --review-id 2317943
```

Note: `.like_count` percent on detail pages is the **community** average, not Balázs’s score.

## Tests (fixtures only; no live POST)

```bash
pytest -q
```

## Google Sheets (thin gspread layer)

```bash
snitt-sheets-auth          # first-time browser OAuth
snitt-sheets-auth --status # redacted paths only
```

```python
from snitt_google_sheets import GoogleSheetsClient

client = GoogleSheetsClient()  # OAuth token, else service-account fallback
rows = client.read_all_records("<spreadsheet-id-or-url>", "Anime")
```

Direct Sheets API reads (no CSV). Sync Snitt → sheet not wired yet. Full OAuth doc: `docs/google-sheets-oauth.md`.

## Layout

- `src/snitt_client/` — library, CLI, MCP
- `src/snitt_google_sheets/` — gspread + OAuth/SA auth + `snitt-sheets-mcp`
- `src/snitt_anidb/` — paced AniDB UDP client + `snitt-anidb-mcp`
- `tests/fixtures/` — sanitized HTML/JSON samples
- `docs/google-sheets-oauth.md` — first-run browser OAuth
- `docs/anidb-mcp.md` — AniDB credentials, registration, flood/ban, license choice
- `docs/cursor-mcp.json.example` — Cursor mcp.json (snitt + sheets + anidb + anilist + mal; space-free symlink)
- `docs/cursor-mcp-bash-wrapper.json.example` — bash `-lc` alternative
- Project store: `docs/anilist-mal-mcp-setup.md` — AniList/MAL OAuth + MCP setup (HU+EN)
