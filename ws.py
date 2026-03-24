import asyncio, json, time, base64, os
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding
import websockets

API_KEY = os.environ["KALSHI_API_KEY_ID"]
KEY_PATH = os.environ["KALSHI_PRIVATE_KEY_PATH"]

with open(KEY_PATH, "rb") as f:
    private_key = serialization.load_pem_private_key(f.read(), password=None)

ts = str(int(time.time() * 1000))
msg = ts + "GET" + "/trade-api/ws/v2"

sig = private_key.sign(
    msg.encode(),
    padding.PSS(
        mgf=padding.MGF1(hashes.SHA256()),
        salt_length=padding.PSS.DIGEST_LENGTH,
    ),
    hashes.SHA256(),
)
sig_b64 = base64.b64encode(sig).decode()

headers = {
    "KALSHI-ACCESS-KEY": API_KEY,
    "KALSHI-ACCESS-SIGNATURE": sig_b64,
    "KALSHI-ACCESS-TIMESTAMP": ts,
}

async def main():
    async with websockets.connect(
        "wss://demo-api.kalshi.co/trade-api/ws/v2",
        additional_headers=headers,
    ) as ws:
        print("connected")

        await ws.send(json.dumps({
            "id": 1,
            "cmd": "subscribe",
            "params": {"channels": ["ticker"]}
        }))

        async for m in ws:
            print(m)

asyncio.run(main())
