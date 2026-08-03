from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import Resource, build

from .accounts import AccountProfile

# youtube.force-ssl grants read/write access to the account's YouTube data
# (needed later for videos.update in M5) over an SSL-only endpoint.
SCOPES = ["https://www.googleapis.com/auth/youtube.force-ssl"]

logger = logging.getLogger(__name__)


class AuthError(Exception):
    """Raised when OAuth2 authentication fails or required files are missing."""


def get_credentials(account: AccountProfile) -> Credentials:
    client_secret_path = Path(account.client_secret_file)
    token_path = Path(account.token_file)

    creds: Optional[Credentials] = None
    if token_path.is_file():
        creds = Credentials.from_authorized_user_file(str(token_path), SCOPES)

    if creds and creds.valid:
        return creds

    if creds and creds.expired and creds.refresh_token:
        logger.info("Access token expired, refreshing...")
        creds.refresh(Request())
        _save_token(creds, token_path)
        return creds

    if not client_secret_path.is_file():
        raise AuthError(
            f"OAuth client secret file not found: {client_secret_path}. "
            "Create an OAuth client (type: Desktop app) in Google Cloud Console, "
            "enable the YouTube Data API v3, and download the JSON to this path."
        )

    logger.info("No valid token found, starting OAuth2 consent flow...")
    flow = InstalledAppFlow.from_client_secrets_file(str(client_secret_path), SCOPES)
    creds = flow.run_local_server(port=0)
    _save_token(creds, token_path)
    return creds


def _save_token(creds: Credentials, token_path: Path) -> None:
    token_path.parent.mkdir(parents=True, exist_ok=True)
    token_path.write_text(creds.to_json(), encoding="utf-8")
    logger.info("Token saved to %s", token_path)


def get_authenticated_service(account: AccountProfile) -> Resource:
    creds = get_credentials(account)
    return build("youtube", "v3", credentials=creds)
