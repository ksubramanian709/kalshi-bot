"""
Kalshi WebSocket client: global ticker stream, reconnect with backoff.

https://docs.kalshi.com/getting_started/quick_start_websockets
"""
import asyncio
import json
import os
import ssl
from collections.abc import Callable, MutableSet
from typing import Any

import certifi
import websockets
from websockets.exceptions import WebSocketException


def _as_header_list(headers: dict[str, str]) -> list[tuple[str, str]]:
    return [(k, v) for k, v in headers.items()]


def _ssl_context() -> ssl.SSLContext:
    """Use certifi CA bundle (fixes macOS python.org builds missing system certs)."""
    return ssl.create_default_context(cafile=certifi.where())

WS_URL_PROD = "wss://api.elections.kalshi.com/trade-api/ws/v2"
WS_URL_DEMO = "wss://demo-api.kalshi.co/trade-api/ws/v2"


def websocket_url() -> str:
    return os.environ.get("KALSHI_WS_URL") or (
        WS_URL_DEMO if os.environ.get("KALSHI_USE_DEMO") else WS_URL_PROD
    )


def _fresh_headers(get_headers: Callable[[], dict[str, str] | None]) -> dict[str, str]:
    h = get_headers()
    if not h:
        raise RuntimeError("WebSocket auth headers unavailable")
    return h


async def stream_tickers(
    queue: asyncio.Queue[dict[str, Any]],
    universe_tickers: MutableSet[str],
    get_headers: Callable[[], dict[str, str] | None],
    *,
    url: str | None = None,
) -> None:
    """
    Connect, subscribe to all ticker updates, enqueue msg payloads for markets in universe_tickers.
    Regenerates auth headers on each connection attempt.
    """
    ws_url = url or websocket_url()
    backoff_s = 1.0
    msg_id = 1

    while True:
        try:
            headers = _as_header_list(_fresh_headers(get_headers))
            async with websockets.connect(
                ws_url,
                additional_headers=headers,
                ssl=_ssl_context(),
                ping_interval=20,
                ping_timeout=25,
                close_timeout=5,
            ) as ws:
                backoff_s = 1.0
                sub = {
                    "id": msg_id,
                    "cmd": "subscribe",
                    "params": {"channels": ["ticker"]},
                }
                msg_id += 1
                await ws.send(json.dumps(sub))

                while True:
                    raw = await ws.recv()
                    data = json.loads(raw)
                    kind = data.get("type")
                    if kind == "ticker":
                        msg = data.get("msg") or {}
                        t = msg.get("market_ticker")
                        if t and t in universe_tickers:
                            try:
                                queue.put_nowait(msg)
                            except asyncio.QueueFull:
                                pass
                    elif kind == "error":
                        err = data.get("msg") or {}
                        print(f"[WS error] {err.get('code')}: {err.get('msg')}")
                    elif kind == "subscribed":
                        print("[WS] subscribed to ticker channel")
                    elif kind == "ok":
                        pass

        except (WebSocketException, OSError, RuntimeError, json.JSONDecodeError) as e:
            print(f"[WS] {e!s}; reconnecting in {backoff_s:.0f}s")
            await asyncio.sleep(backoff_s)
            backoff_s = min(backoff_s * 2, 60.0)
