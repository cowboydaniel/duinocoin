"""Lightweight client for retrieving Duino Coin wallet information."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Optional

import requests

from .state import WalletData


class WalletClientError(Exception):
    """Base error for wallet client failures."""


class WalletAuthError(WalletClientError):
    """Raised when credentials are missing or invalid."""


@dataclass
class WalletCredentials:
    """Credentials required to talk to the wallet API."""

    username: str
    token: str | None = None


class WalletClient:
    """Perform authenticated queries against the Duino Coin API."""

    def __init__(
        self,
        server: str = "server.duinocoin.com",
        port: Optional[int] = None,
        session: Optional[requests.Session] = None,
    ) -> None:
        host = server.removeprefix("https://").removeprefix("http://").rstrip("/")
        if port:
            host = f"{host}:{port}"
        self.base_url = f"https://{host}"
        self.session = session or requests.Session()

    def fetch_wallet(self, credentials: WalletCredentials) -> WalletData:
        """Fetch wallet balances and stats."""
        if not credentials.username:
            raise WalletAuthError("Wallet username is missing")

        url = f"{self.base_url}/users/{credentials.username}"
        headers = {}
        if credentials.token:
            headers["Authorization"] = f"Bearer {credentials.token}"

        response = self.session.get(url, timeout=10, headers=headers)
        response.raise_for_status()
        payload = response.json()

        if payload.get("success") is False:
            message = payload.get("message") or "Unknown error from wallet API"
            if "auth" in message.lower():
                raise WalletAuthError(message)
            raise WalletClientError(message)

        result = payload.get("result", {})
        balance_info = result.get("balance", {})
        balance, pending, last_payout = self._parse_balance_info(balance_info)

        if not last_payout:
            last_payout = self._extract_last_payout(result.get("transactions"))

        return WalletData(
            username=result.get("username") or credentials.username,
            balance=balance,
            pending_rewards=pending,
            last_payout=last_payout,
        )

    @staticmethod
    def _parse_balance_info(balance_info: Any) -> tuple[float, float, Optional[str]]:
        balance = 0.0
        pending = 0.0
        last_payout: Optional[str] = None

        if isinstance(balance_info, dict):
            balance = float(balance_info.get("balance") or balance_info.get("ducoBalance") or 0.0)
            pending = float(
                balance_info.get("pending")
                or balance_info.get("pendingRewards")
                or balance_info.get("pending_rewards")
                or 0.0
            )
            last_payout = balance_info.get("lastPayout") or balance_info.get("last_payout")
        else:
            try:
                balance = float(balance_info)
            except (TypeError, ValueError):
                balance = 0.0

        return balance, pending, last_payout

    @staticmethod
    def _extract_last_payout(transactions: Any) -> Optional[str]:
        if not isinstance(transactions, list):
            return None

        for tx in transactions:
            if not isinstance(tx, dict):
                continue
            if tx.get("type", "").lower() in {"payout", "mining"}:
                return tx.get("datetime") or tx.get("timestamp")
        return None
