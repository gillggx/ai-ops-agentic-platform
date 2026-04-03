"""Reverse-proxy router for the OntologySimulator backend (port 8099).

HTTP:  /simulator-api/{path}  →  http://localhost:8099/{path}
WS:    /simulator-api/ws      →  ws://localhost:8099/ws
"""

import asyncio
import logging

import httpx
import websockets
from fastapi import APIRouter, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import Response

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/simulator-api", tags=["simulator-proxy"])

_SIMULATOR_ORIGIN = "http://localhost:8099"
_SIMULATOR_WS     = "ws://localhost:8099/ws"

_HOP_BY_HOP = {
    "connection", "keep-alive", "transfer-encoding",
    "te", "trailers", "upgrade", "proxy-authorization", "proxy-authenticate",
}


# ── HTTP proxy ─────────────────────────────────────────────────────────────────

async def _proxy_http(request: Request, path: str) -> Response:
    url = f"{_SIMULATOR_ORIGIN}/{path}"
    if request.url.query:
        url = f"{url}?{request.url.query}"

    headers = {
        k: v for k, v in request.headers.items()
        if k.lower() not in _HOP_BY_HOP and k.lower() != "host"
    }

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.request(
                method=request.method,
                url=url,
                headers=headers,
                content=await request.body(),
            )
    except httpx.ConnectError:
        return Response(
            content=b'{"error":"OntologySimulator (port 8099) is not running"}',
            status_code=503,
            media_type="application/json",
        )
    except Exception as exc:
        logger.error("simulator proxy error: %s", exc)
        return Response(
            content=b'{"error":"Proxy error"}',
            status_code=502,
            media_type="application/json",
        )

    resp_headers = {
        k: v for k, v in resp.headers.items()
        if k.lower() not in _HOP_BY_HOP
    }
    return Response(
        content=resp.content,
        status_code=resp.status_code,
        headers=resp_headers,
        media_type=resp.headers.get("content-type"),
    )


@router.get("/{path:path}")
async def proxy_get(path: str, request: Request) -> Response:
    return await _proxy_http(request, path)


@router.post("/{path:path}")
async def proxy_post(path: str, request: Request) -> Response:
    return await _proxy_http(request, path)


@router.put("/{path:path}")
async def proxy_put(path: str, request: Request) -> Response:
    return await _proxy_http(request, path)


@router.delete("/{path:path}")
async def proxy_delete(path: str, request: Request) -> Response:
    return await _proxy_http(request, path)


# ── WebSocket proxy ─────────────────────────────────────────────────────────────

@router.websocket("/ws")
async def proxy_ws(client_ws: WebSocket) -> None:
    await client_ws.accept()

    try:
        async with websockets.connect(_SIMULATOR_WS) as backend_ws:
            async def _forward_to_backend():
                try:
                    while True:
                        data = await client_ws.receive_bytes()
                        await backend_ws.send(data)
                except (WebSocketDisconnect, Exception):
                    pass

            async def _forward_to_client():
                try:
                    async for message in backend_ws:
                        if isinstance(message, bytes):
                            await client_ws.send_bytes(message)
                        else:
                            await client_ws.send_text(message)
                except (WebSocketDisconnect, Exception):
                    pass

            done, pending = await asyncio.wait(
                [
                    asyncio.create_task(_forward_to_backend()),
                    asyncio.create_task(_forward_to_client()),
                ],
                return_when=asyncio.FIRST_COMPLETED,
            )
            for task in pending:
                task.cancel()

    except (OSError, websockets.exceptions.WebSocketException) as exc:
        logger.warning("simulator WS proxy: backend unreachable — %s", exc)
        await client_ws.send_text(
            '{"error":"OntologySimulator (port 8099) is not running"}'
        )
        await client_ws.close()
