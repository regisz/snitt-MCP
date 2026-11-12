# Crunchyroll thin MCP (nem hivatalos API)

HU — `snitt_crunchyroll` / `snitt-crunchyroll-mcp` setup. **Nincs hivatalos public API**; személyes, best-effort, ToS/törékenység kockázattal.

## Döntések

- Saját thin MCP (AniDB-mintára), nem az npm `@striderlabs/mcp-crunchyroll`.
- Írás **csak Crunchyrollra**. A Google Sheets a **forrás**; a **számított 5★** oszlopból megy a rating (`1s`…`5s`).
- Auth: lokális token fájl (`etp_rt` → refresh), nem jelszó a chatben / `mcp.json`-ban.
- Végignézett sorozat → csak **sorozat-szintű** watched; folyamatban → rész / playhead.

Részletes terv: Project store `internal/crunchyroll-mcp-plan.md`.

## Auth (token fájl)

1. Böngészőben jelentkezz be a Crunchyrollra.
2. DevTools → Application/Storage → Cookies → másold az **`etp_rt`** értékét (ne a chatbe).
3. Lokálisan:

```bash
cd "/home/balage/devel-magán/snitt.hu - MCP"
source .venv/bin/activate
pip install -e ".[all]"
snitt-crunchyroll login-etp-rt
# getpass kéri az etp_rt-t → ~/.config/snitt/crunchyroll.json (0600)
snitt-crunchyroll session-status
```

Opcionális bootstrap env (ideiglenes): `CRUNCHYROLL_ETP_RT` — ne commitold. Token path override: `CRUNCHYROLL_TOKEN_FILE`.

Logout: `snitt-crunchyroll logout` vagy MCP `crunchyroll_logout`.

### Cloudflare / 403 „Just a moment...”

A `www.crunchyroll.com` auth gyakran CF challenge-et ad automatikus kliensnek. A kliens **`beta-api.crunchyroll.com`**-ot használ. Az auth body kötelezően küldi a `device_id` / `device_type` mezőket (nélkülük HTTP 400 `missing_required_field`). Elsődleges grant: `etp_rt_cookie`. Ha 403/CF jön: friss cookie, ne VPN, később újra.

## Cursor `mcp.json`

Nincs secret az env-ben — a token fájlból jön:

```json
"snitt-crunchyroll": {
  "command": "/home/balage/devel-magan/snitt-mcp/.venv/bin/snitt-crunchyroll-mcp",
  "args": []
}
```

MCP reload után: `crunchyroll_session_status`, majd plan_* → allow_save írások.

## MCP toolok

| Tool | Szerep |
|------|--------|
| `crunchyroll_session_status` | helyi token státusz |
| `crunchyroll_search` | keresés |
| `crunchyroll_get_series` / `_seasons` / `_episodes` | katalógus |
| `crunchyroll_get_watchlist` | watchlist olvasás |
| `crunchyroll_plan_watchlist_add` → `crunchyroll_watchlist_add` | watchlist hozzáadás (gated) |
| `crunchyroll_plan_watchlist_remove` → `crunchyroll_watchlist_remove` | watchlist törlés (gated) |
| `crunchyroll_get_custom_lists` / `_get_custom_list_items` | saját listák |
| `crunchyroll_plan_custom_list_create` → `crunchyroll_custom_list_create` | lista létrehozás (gated) |
| `crunchyroll_plan_custom_list_add_item` → `…_add_item` | elem a listába (gated) |
| `crunchyroll_plan_custom_list_remove_item` → `…_remove_item` | elem törlés (gated) |
| `crunchyroll_plan_mark_watched` → `crunchyroll_mark_watched` | watched (gated) |
| `crunchyroll_plan_set_playhead` → `crunchyroll_set_playhead` | folyamatban (gated) |
| `crunchyroll_plan_rate_series` → `crunchyroll_rate_series` | 1–5★ (gated; sheet 5★ forrás) |
| `crunchyroll_logout` | token fájl törlés |

## Agent workflow (sheet → CR)

1. `snitt-sheets` — olvasd a sor **számított 5★** értékét (ne a nyers 10-est).
2. `crunchyroll_search` / id feloldás.
3. Kész sorozat: `plan_mark_watched(level=series)` → `mark_watched(allow_save=true)`.
4. Értékelés: `plan_rate_series(stars=<sheet 5★>)` → `rate_series(allow_save=true)`.
5. Folyamatban: episode mark és/vagy playhead — ne jelöld késznek a sorozatot.

Élő AUTH/írás csak kifejezett OK után; unit tesztek mock HTTP-t használnak.
