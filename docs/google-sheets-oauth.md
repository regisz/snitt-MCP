# Google Sheets browser OAuth (snitt-sheets)

Direct Sheets API via `gspread` — **no CSV export**. Refresh token stays on disk; never paste secrets into chat.

**Snitt.hu auth is separate:** cookie / `SNITT_COOKIE` / `~/.snitt-hu-downloader.cfg` — **not** browser OAuth.

## One-time Google Cloud setup

1. Google Cloud Console → create (or reuse) a project.
2. Enable **Google Sheets API**.
3. **APIs & Services → Credentials → Create credentials → OAuth client ID**.
4. Application type: **Desktop app**.
5. Download the JSON → save as:

```text
~/.config/snitt/google-oauth-client.json
```

(or set `GOOGLE_SHEETS_OAUTH_CLIENT_SECRETS` to that path)

6. OAuth consent screen: add your Google account as a test user if the app is in Testing.

## First login (Balázs)

```bash
cd "/home/balage/devel-magán/snitt.hu - MCP"   # or: cd /home/balage/devel-magan/snitt-mcp
source .venv/bin/activate
pip install -e ".[sheets]"
snitt-sheets-auth
```

- Default browser opens → sign in → allow Sheets access.
- Token written to `~/.config/snitt/google-oauth-token.json` (mode 600 when possible).
- Check without browser: `snitt-sheets-auth --status`

Optional paths:

```bash
snitt-sheets-auth --client-secrets /path/to/client.json --token /path/to/token.json
```

## Runtime (MCP / library)

`GoogleSheetsClient` / `snitt-sheets-mcp` load credentials in this order:

1. OAuth user token (`GOOGLE_SHEETS_OAUTH_TOKEN` or `~/.config/snitt/google-oauth-token.json`), refresh if expired
2. Optional service-account fallback (`GOOGLE_SHEETS_SERVICE_ACCOUNT_FILE` or `~/.config/snitt/google-service-account.json`)

MCP does **not** open a browser; run `snitt-sheets-auth` first if the token is missing.

## Cursor

See `docs/cursor-mcp.json.example` (`snitt` + `snitt-sheets`). After first auth, reload MCP.
