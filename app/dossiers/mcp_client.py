"""Client minimal du serveur MCP admin.jin.fr/mcp (HTTP « streamable », sans état).

Le bot s'authentifie avec son jeton de service et transmet l'e-mail de la personne qui
lui écrit (X-Acting-User) : le serveur applique les droits de cette personne.
"""

import json
import logging
import time
from dataclasses import dataclass
from typing import Any

import httpx

from app.config import get_settings

logger = logging.getLogger(__name__)

_TOOLS_TTL_SECONDS = 300
_tools_cache: dict[str, tuple[float, list[dict[str, Any]], str]] = {}


class McpError(RuntimeError):
    """Erreur de protocole ou de transport (pas une erreur métier d'un tool)."""


@dataclass
class ToolResult:
    is_error: bool
    text: str
    data: Any = None


class AdminMcpClient:
    def __init__(self, acting_user: str, base_url: str | None = None, token: str | None = None, timeout: float = 25.0):
        settings = get_settings()
        self.acting_user = acting_user
        self.url = (base_url or settings.admin_jin_url).rstrip("/") + "/mcp"
        self.token = token or settings.admin_jin_bot_token
        self.timeout = timeout
        self._id = 0

    def _rpc(self, method: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        if not self.token:
            raise McpError("ADMIN_JIN_BOT_TOKEN n'est pas configuré.")
        self._id += 1
        response = httpx.post(
            self.url,
            headers={
                "authorization": f"Bearer {self.token}",
                "x-acting-user": self.acting_user,
                "content-type": "application/json",
                "accept": "application/json, text/event-stream",
            },
            json={"jsonrpc": "2.0", "id": self._id, "method": method, "params": params or {}},
            timeout=self.timeout,
        )
        if response.status_code >= 400:
            raise McpError(f"{method} : HTTP {response.status_code} {response.text[:300]}")
        body = response.json()
        if "error" in body:
            raise McpError(f"{method} : {body['error'].get('message', body['error'])}")
        return body.get("result") or {}

    def describe(self) -> tuple[list[dict[str, Any]], str]:
        """Tools visibles pour cette personne et instructions du serveur (en cache)."""
        cached = _tools_cache.get(self.acting_user)
        if cached and time.time() - cached[0] < _TOOLS_TTL_SECONDS:
            return cached[1], cached[2]
        init = self._rpc(
            "initialize",
            {"protocolVersion": "2025-06-18", "capabilities": {}, "clientInfo": {"name": "jinbot", "version": "1"}},
        )
        tools = self._rpc("tools/list").get("tools", [])
        instructions = init.get("instructions", "")
        _tools_cache[self.acting_user] = (time.time(), tools, instructions)
        return tools, instructions

    def call_tool(self, name: str, arguments: dict[str, Any]) -> ToolResult:
        result = self._rpc("tools/call", {"name": name, "arguments": arguments})
        text = "\n".join(c.get("text", "") for c in result.get("content", []) if c.get("type") == "text")
        data = result.get("structuredContent")
        if data is None:
            try:
                data = json.loads(text)
            except (ValueError, TypeError):
                data = None
        logger.info("mcp_tool_called", extra={"tool": name, "is_error": bool(result.get("isError"))})
        return ToolResult(is_error=bool(result.get("isError")), text=text, data=data)
