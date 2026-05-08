"""GitHub App authentication — JWT → installation token, auto-refreshed."""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Optional

import httpx
import jwt as pyjwt

GITHUB_API = "https://api.github.com"
JWT_TTL_SECONDS = 9 * 60
INSTALLATION_TTL_SECONDS = 60 * 60
REFRESH_LEAD_SECONDS = 5 * 60


@dataclass
class InstallationToken:
    token: str
    expires_at_epoch: float

    def is_fresh(self) -> bool:
        return time.time() < (self.expires_at_epoch - REFRESH_LEAD_SECONDS)


class GitHubAppAuth:
    """Builds short-lived installation tokens for a GitHub App.

    Reads ``private_pem`` and ``app_id`` once and caches the installation
    token internally, refreshing 5 minutes before expiry.
    """

    def __init__(
        self,
        app_id: str,
        installation_id: str,
        private_pem: str,
        http_client: Optional[httpx.Client] = None,
    ) -> None:
        self.app_id = str(app_id)
        self.installation_id = str(installation_id)
        self.private_pem = private_pem
        self._http = http_client or httpx.Client(timeout=15.0)
        self._cached: Optional[InstallationToken] = None

    def _build_jwt(self) -> str:
        now = int(time.time())
        payload = {
            "iat": now - 30,
            "exp": now + JWT_TTL_SECONDS,
            "iss": self.app_id,
        }
        return pyjwt.encode(payload, self.private_pem, algorithm="RS256")

    def _exchange_for_installation_token(self) -> InstallationToken:
        app_jwt = self._build_jwt()
        url = f"{GITHUB_API}/app/installations/{self.installation_id}/access_tokens"
        response = self._http.post(
            url,
            headers={
                "Authorization": f"Bearer {app_jwt}",
                "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": "2022-11-28",
            },
        )
        response.raise_for_status()
        body = response.json()
        return InstallationToken(
            token=body["token"],
            expires_at_epoch=time.time() + INSTALLATION_TTL_SECONDS,
        )

    def get_token(self) -> str:
        if self._cached is not None and self._cached.is_fresh():
            return self._cached.token
        self._cached = self._exchange_for_installation_token()
        return self._cached.token

    def headers(self) -> dict:
        return {
            "Authorization": f"token {self.get_token()}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        }
