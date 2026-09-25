import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

import pytest

from pry.payments.x402 import solana_verifier as legacy

try:
    from pry.payments.x402 import solana_transfer as new
except ModuleNotFoundError:  # characterization while the new facade is pending
    new = None  # type: ignore[assignment]

RECIPIENT = "9WzDXwBbmkg8ZTbNMqUxvQRAyrZzDsGYdLVL9zYtAWWM"
OTHER = "4Nd1mBQtrMJVYVfKf2PJy9NZUZdTAsp7D4xWLs4gDB4T"
USDC, USDT = legacy.SOLANA_USDC_MINT, legacy.SOLANA_USDT_MINT


class _RpcServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self) -> None:
        super().__init__(("127.0.0.1", 0), _RpcHandler)
        self.status, self.body, self.delay = 200, b"{}", 0.0


class _RpcHandler(BaseHTTPRequestHandler):
    def do_POST(self) -> None:
        try:
            if self.server.delay:
                time.sleep(self.server.delay)
            self.send_response(self.server.status)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(self.server.body)
        except OSError:
            pass


@pytest.fixture
def rpc() -> Any:
    server = _RpcServer()
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield server
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=1)


def _url(server: _RpcServer) -> str:
    return f"http://127.0.0.1:{server.server_port}"


def _tx(
    instructions: list[dict[str, Any]], *, slot: int | None = 1, err: Any = None
) -> dict[str, Any]:
    return {
        "slot": slot,
        "blockTime": 1,
        "meta": {"err": err, "innerInstructions": []},
        "transaction": {"message": {"instructions": instructions}},
    }


def _spl(
    amount: str = "1000000", *, mint: str = USDC, destination: str = RECIPIENT
) -> dict[str, Any]:
    return {
        "program": "splToken",
        "programId": legacy.SPL_TOKEN_PROGRAM_ID,
        "parsed": {
            "type": "transferChecked",
            "info": {
                "mint": mint,
                "destination": destination,
                "tokenAmount": {"amount": amount, "decimals": 6},
            },
        },
    }


def _native(lamports: int = 10_000_000, destination: str = RECIPIENT) -> dict[str, Any]:
    return {
        "program": "system",
        "programId": legacy.SYSTEM_PROGRAM_ID,
        "parsed": {"type": "transfer", "info": {"lamports": lamports, "destination": destination}},
    }


def _body(server: _RpcServer, value: Any) -> None:
    server.body = value if isinstance(value, bytes) else json.dumps(value).encode()


def _call(*args: Any, **kwargs: Any) -> Any:
    if new is None:
        pytest.skip("new Solana transfer facade is not present")
    return new.verify_solana_payment(*args, **kwargs)


class TestValidation:
    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        ("signature", "recipient", "amount", "asset", "needle"),
        [
            ("", RECIPIENT, 1.0, None, "missing tx signature"),
            ("sig", "", 1.0, None, "missing expected recipient"),
            ("sig", RECIPIENT, -1.0, None, "invalid"),
            ("sig", RECIPIENT, 1.0, "DOGE", "unsupported_asset"),
        ],
    )
    async def test_rejects_invalid_requests(
        self, signature: str, recipient: str, amount: float, asset: str | None, needle: str
    ) -> None:
        out = await _call(signature, recipient, amount, asset=asset)
        assert out["verified"] is False
        assert needle in out["reason"]


class TestRpc:
    @pytest.mark.asyncio
    async def test_success_selects_largest_spl_candidate(self, rpc: _RpcServer) -> None:
        _body(
            rpc,
            {"result": _tx([_spl("300000"), _spl("9000000", destination=OTHER), _spl("2000000")])},
        )
        out = await _call("sig", RECIPIENT, 1.0, rpc_url=_url(rpc))
        assert out["verified"] is True
        assert out["amount_raw"] == 2_000_000
        assert out["asset"] == "USDC"

    @pytest.mark.asyncio
    async def test_native_candidate_is_selected_when_priced(self, rpc: _RpcServer) -> None:
        _body(rpc, {"result": _tx([_spl("500000"), _native(10_000_000)])})
        out = await _call("sig", RECIPIENT, 1.0, rpc_url=_url(rpc), sol_price_usd=200.0)
        assert out["verified"] is True
        assert out["asset"] == "SOL"
        assert out["amount_raw"] == 10_000_000

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        ("status", "value", "needle"),
        [
            (503, b"{}", "rpc_http_error"),
            (200, {"error": {"code": -32000, "message": "no"}}, "rpc_error_response"),
            (200, b"{bad", "rpc_invalid_json"),
        ],
    )
    async def test_rpc_failures_are_envelopes(
        self, rpc: _RpcServer, status: int, value: Any, needle: str
    ) -> None:
        rpc.status, rpc.body = (
            status,
            value if isinstance(value, bytes) else json.dumps(value).encode(),
        )
        out = await _call("sig", RECIPIENT, 1.0, rpc_url=_url(rpc))
        assert out["verified"] is False
        assert needle in out["reason"]

    @pytest.mark.asyncio
    async def test_rpc_timeout_is_enveloped(self, rpc: _RpcServer) -> None:
        rpc.delay = legacy.SOLANA_RPC_TIMEOUT_SECONDS + 0.2
        out = await _call("sig", RECIPIENT, 1.0, rpc_url=_url(rpc))
        assert out["verified"] is False
        assert out["reason"].startswith("rpc_error:")

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "result",
        [
            [],
            {"meta": [], "slot": 1},
            {"transaction": {}, "meta": {}, "slot": "pending"},
            {"weird": ["shape"]},
        ],
    )
    async def test_malformed_results_never_raise(self, rpc: _RpcServer, result: Any) -> None:
        _body(rpc, {"result": result})
        out = await _call("sig", RECIPIENT, 1.0, rpc_url=_url(rpc))
        assert isinstance(out, dict)
        assert out["verified"] is False
        assert isinstance(out["reason"], str)
