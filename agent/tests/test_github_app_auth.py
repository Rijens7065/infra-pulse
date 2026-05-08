"""Tests for GitHub App auth — JWT generation and token caching."""

from __future__ import annotations

import time
from unittest.mock import MagicMock

import httpx
import jwt as pyjwt
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

from agent.actions.github_app_auth import (
    GitHubAppAuth,
    InstallationToken,
    JWT_TTL_SECONDS,
    REFRESH_LEAD_SECONDS,
)


@pytest.fixture(scope="module")
def rsa_keypair():
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    private_pem = key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    ).decode("utf-8")
    public_pem = key.public_key().public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    ).decode("utf-8")
    return private_pem, public_pem


def _stub_client(token_value: str = "ghs_test_token") -> tuple[httpx.Client, list]:
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append({"method": request.method, "url": str(request.url),
                      "auth": request.headers.get("authorization", "")})
        return httpx.Response(201, json={"token": token_value, "expires_at": "2026-12-31T00:00:00Z"})

    return httpx.Client(transport=httpx.MockTransport(handler)), calls


def test_jwt_is_signed_with_rs256_and_carries_app_id(rsa_keypair):
    private_pem, public_pem = rsa_keypair
    client, _ = _stub_client()
    auth = GitHubAppAuth(
        app_id="12345",
        installation_id="67890",
        private_pem=private_pem,
        http_client=client,
    )
    encoded = auth._build_jwt()
    decoded = pyjwt.decode(encoded, public_pem, algorithms=["RS256"])
    assert decoded["iss"] == "12345"
    now = int(time.time())
    assert decoded["exp"] > now
    assert decoded["exp"] - decoded["iat"] <= JWT_TTL_SECONDS + 60


def test_get_token_caches_and_reuses(rsa_keypair):
    private_pem, _ = rsa_keypair
    client, calls = _stub_client()
    auth = GitHubAppAuth(
        app_id="12345",
        installation_id="67890",
        private_pem=private_pem,
        http_client=client,
    )

    t1 = auth.get_token()
    t2 = auth.get_token()
    assert t1 == t2
    assert len(calls) == 1


def test_get_token_refreshes_when_stale(rsa_keypair):
    private_pem, _ = rsa_keypair
    client, calls = _stub_client()
    auth = GitHubAppAuth(
        app_id="12345",
        installation_id="67890",
        private_pem=private_pem,
        http_client=client,
    )
    # Force-cache an expired token
    auth._cached = InstallationToken(token="old", expires_at_epoch=time.time() - 10)
    t = auth.get_token()
    assert t != "old"
    assert len(calls) == 1


def test_installation_token_is_fresh_window():
    fresh = InstallationToken(token="x", expires_at_epoch=time.time() + REFRESH_LEAD_SECONDS + 60)
    stale = InstallationToken(token="x", expires_at_epoch=time.time() + REFRESH_LEAD_SECONDS - 10)
    assert fresh.is_fresh() is True
    assert stale.is_fresh() is False


def test_headers_include_token_and_api_version(rsa_keypair):
    private_pem, _ = rsa_keypair
    client, _ = _stub_client(token_value="ghs_xyz")
    auth = GitHubAppAuth(
        app_id="12345",
        installation_id="67890",
        private_pem=private_pem,
        http_client=client,
    )
    headers = auth.headers()
    assert headers["Authorization"] == "token ghs_xyz"
    assert headers["X-GitHub-Api-Version"] == "2022-11-28"
