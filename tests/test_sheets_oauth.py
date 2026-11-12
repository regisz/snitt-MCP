# -*- coding: utf-8 -*-
"""Unit tests for Sheets OAuth/session helpers (no live Google / no browser)."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from snitt_google_sheets.session import (
    SheetsAuthError,
    auth_status,
    load_credentials,
    load_oauth_credentials,
    main_auth,
    run_browser_oauth,
)


def test_auth_status_redacted(tmp_path: Path) -> None:
    secrets = tmp_path / "client.json"
    token = tmp_path / "token.json"
    secrets.write_text("{}", encoding="utf-8")
    status = auth_status(token_path=token, client_secrets_path=secrets, service_account_path_arg=tmp_path / "sa.json")
    assert status["oauth_client_secrets_present"] is True
    assert status["oauth_token_present"] is False
    assert status["service_account_present"] is False
    assert "cookie" in status["snitt_auth_note"].lower() or "SNITT" in status["snitt_auth_note"]
    assert "secret" not in json.dumps(status).lower() or "client_secrets" in json.dumps(status)


def test_load_oauth_from_valid_token_file(tmp_path: Path) -> None:
    token = tmp_path / "token.json"
    fake = MagicMock()
    fake.valid = True
    with patch("snitt_google_sheets.session.UserCredentials.from_authorized_user_file", return_value=fake):
        token.write_text("{}", encoding="utf-8")
        creds = load_oauth_credentials(token_path=token, interactive=False)
    assert creds is fake


def test_load_oauth_refreshes_expired_token(tmp_path: Path) -> None:
    token = tmp_path / "token.json"
    token.write_text("{}", encoding="utf-8")
    fake = MagicMock()
    fake.valid = False
    fake.expired = True
    fake.refresh_token = "refresh-not-for-chat"
    fake.to_json.return_value = '{"token":"x","refresh_token":"y"}'
    with patch("snitt_google_sheets.session.UserCredentials.from_authorized_user_file", return_value=fake):
        with patch("snitt_google_sheets.session.Request"):
            creds = load_oauth_credentials(token_path=token, interactive=False)
    fake.refresh.assert_called_once()
    assert creds is fake
    assert token.is_file()


def test_load_credentials_falls_back_to_service_account(tmp_path: Path) -> None:
    sa = tmp_path / "sa.json"
    sa.write_text("{}", encoding="utf-8")
    fake_sa = MagicMock()
    with patch("snitt_google_sheets.session.load_oauth_credentials", return_value=None):
        with patch(
            "snitt_google_sheets.session.ServiceAccountCredentials.from_service_account_file",
            return_value=fake_sa,
        ):
            creds = load_credentials(service_account_path_arg=sa, oauth_token_path_arg=tmp_path / "missing.json")
    assert creds is fake_sa


def test_load_credentials_errors_when_nothing_configured(tmp_path: Path) -> None:
    with pytest.raises(SheetsAuthError, match="snitt-sheets-auth"):
        load_credentials(
            oauth_token_path_arg=tmp_path / "t.json",
            oauth_client_secrets_path_arg=tmp_path / "c.json",
            service_account_path_arg=tmp_path / "sa.json",
            interactive=False,
        )


def test_run_browser_oauth_uses_installed_app_flow(tmp_path: Path) -> None:
    secrets = tmp_path / "client.json"
    secrets.write_text('{"installed":{"client_id":"x","client_secret":"y"}}', encoding="utf-8")
    token = tmp_path / "token.json"
    fake_creds = MagicMock()
    fake_creds.to_json.return_value = '{"refresh_token":"rt","token":"at"}'
    fake_flow = MagicMock()
    fake_flow.run_local_server.return_value = fake_creds
    with patch("snitt_google_sheets.session.InstalledAppFlow.from_client_secrets_file", return_value=fake_flow):
        out = run_browser_oauth(client_secrets_path=secrets, token_path=token)
    assert out == token
    assert token.is_file()
    fake_flow.run_local_server.assert_called_once()
    assert fake_flow.run_local_server.call_args.kwargs.get("open_browser") is True


def test_main_auth_status_exit_zero(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    code = main_auth(["--status", "--token", str(tmp_path / "t.json"), "--client-secrets", str(tmp_path / "c.json")])
    assert code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["oauth_token_present"] is False
