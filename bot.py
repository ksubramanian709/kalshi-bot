"""
Kalshi Trading Bot

Uses RSA-signed requests for authentication. You need:
1. API Key ID (from Kalshi Account → APIpip freeze > requirements.txt
 Keys)
2. Private key file (.key) - downloaded when creating the API key
"""
import base64
import datetime
import uuid
from urllib.parse import urlparse

import requests
from cryptography.hazmat.backends import default_backend
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding

from config import BASE_URL, get_credentials

# Resolved at runtime based on DEMO mode
API_KEY_ID, PRIVATE_KEY_PATH = get_credentials()


def load_private_key(key_path: str):
    """Load the RSA private key from file."""
    with open(key_path, "rb") as f:
        return serialization.load_pem_private_key(
            f.read(), password=None, backend=default_backend()
        )


def create_signature(private_key, timestamp: str, method: str, path: str) -> str:
    """Create RSA-PSS SHA256 signature for the request."""
    path_without_query = path.split("?")[0]
    message = f"{timestamp}{method}{path_without_query}".encode("utf-8")
    signature = private_key.sign(
        message,
        padding.PSS(
            mgf=padding.MGF1(hashes.SHA256()),
            salt_length=padding.PSS.DIGEST_LENGTH,
        ),
        hashes.SHA256(),
    )
    return base64.b64encode(signature).decode("utf-8")


def _get_sign_path(base_url: str, path: str) -> str:
    """Get the full path for signing (includes /trade-api/v2)."""
    full_url = base_url.rstrip("/") + ("/" if not path.startswith("/") else "") + path
    return urlparse(full_url).path


def get(private_key, path: str, params: dict | None = None):
    """Authenticated GET request."""
    timestamp = str(int(datetime.datetime.now().timestamp() * 1000))
    sign_path = _get_sign_path(BASE_URL, path.split("?")[0])
    signature = create_signature(private_key, timestamp, "GET", sign_path)

    headers = {
        "KALSHI-ACCESS-KEY": API_KEY_ID,
        "KALSHI-ACCESS-SIGNATURE": signature,
        "KALSHI-ACCESS-TIMESTAMP": timestamp,
    }
    url = f"{BASE_URL.rstrip('/')}{path}"
    return requests.get(url, headers=headers, params=params)


def post(private_key, path: str, data: dict):
    """Authenticated POST request."""
    timestamp = str(int(datetime.datetime.now().timestamp() * 1000))
    sign_path = _get_sign_path(BASE_URL, path)
    signature = create_signature(private_key, timestamp, "POST", sign_path)

    headers = {
        "KALSHI-ACCESS-KEY": API_KEY_ID,
        "KALSHI-ACCESS-SIGNATURE": signature,
        "KALSHI-ACCESS-TIMESTAMP": timestamp,
        "Content-Type": "application/json",
    }
    url = f"{BASE_URL.rstrip('/')}{path}"
    return requests.post(url, headers=headers, json=data)


def delete(private_key, path: str):
    """Authenticated DELETE request."""
    timestamp = str(int(datetime.datetime.now().timestamp() * 1000))
    sign_path = _get_sign_path(BASE_URL, path)
    signature = create_signature(private_key, timestamp, "DELETE", sign_path)

    headers = {
        "KALSHI-ACCESS-KEY": API_KEY_ID,
        "KALSHI-ACCESS-SIGNATURE": signature,
        "KALSHI-ACCESS-TIMESTAMP": timestamp,
    }
    url = f"{BASE_URL.rstrip('/')}{path}"
    return requests.delete(url, headers=headers)


# --- Trading functions ---


def get_balance(private_key) -> dict:
    """Get account balance (balance is in cents)."""
    resp = get(private_key, "/portfolio/balance")
    resp.raise_for_status()
    return resp.json()


def get_markets(limit: int = 10, status: str = "open") -> dict:
    """Get markets (no auth required)."""
    resp = requests.get(
        f"{BASE_URL}/markets",
        params={"limit": limit, "status": status},
    )
    resp.raise_for_status()
    return resp.json()


def search_markets(query: str, limit: int = 50) -> list[dict]:
    """Search markets by title (paginates through API). Returns matches."""
    query = query.lower()
    matches = []
    cursor = None
    for _ in range(20):
        params = {"limit": 200, "status": "open"}
        if cursor:
            params["cursor"] = cursor
        resp = requests.get(f"{BASE_URL}/markets", params=params)
        data = resp.json()
        for m in data.get("markets", []):
            title = (m.get("title") or "") + " " + (m.get("subtitle") or "")
            if query in title.lower():
                matches.append(m)
                if len(matches) >= limit:
                    return matches
        cursor = data.get("cursor")
        if not cursor:
            break
    return matches


def place_order(
    private_key,
    ticker: str,
    side: str,  # "yes" or "no"
    action: str,  # "buy" or "sell"
    count: int = 1,
    yes_price: int | None = None,
    no_price: int | None = None,
    order_type: str = "limit",
) -> dict:
    """
    Place an order. For limit orders, provide yes_price (1-99) or no_price (1-99).
    """
    data = {
        "ticker": ticker,
        "side": side,
        "action": action,
        "count": count,
        "type": order_type,
        "client_order_id": str(uuid.uuid4()),
    }
    if yes_price is not None:
        data["yes_price"] = yes_price
    if no_price is not None:
        data["no_price"] = no_price

    resp = post(private_key, "/portfolio/orders", data)
    resp.raise_for_status()
    return resp.json()


def cancel_order(private_key, order_id: str) -> dict:
    """Cancel an open order."""
    resp = delete(private_key, f"/portfolio/orders/{order_id}")
    resp.raise_for_status()
    return resp.json()


def get_orders(private_key, limit: int = 100) -> dict:
    """Get your orders."""
    resp = get(private_key, "/portfolio/orders", params={"limit": limit})
    resp.raise_for_status()
    return resp.json()


def get_positions(private_key) -> dict:
    """Get your open positions."""
    resp = get(private_key, "/portfolio/positions")
    resp.raise_for_status()
    return resp.json()


# --- Main ---

if __name__ == "__main__":
    # Load private key
    try:
        pk = load_private_key(PRIVATE_KEY_PATH)
    except FileNotFoundError:
        print(
            f"Error: Private key file not found at '{PRIVATE_KEY_PATH}'.\n"
            "Download your .key file from Kalshi (Account → API Keys) and place it in this directory."
        )
        exit(1)

    # Test: get balance
    print("Fetching account balance...")
    balance = get_balance(pk)
    print(f"Balance: ${balance['balance'] / 100:.2f}")

    # List open markets
    print("\nOpen markets (first 3):")
    markets = get_markets(limit=3)
    for m in markets.get("markets", []):
        print(f"  {m['ticker']}: {m['title']}")
