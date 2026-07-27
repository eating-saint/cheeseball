"""MCP Client 生命周期管理：并发连接、会话缓存、退出统一关闭."""

from __future__ import annotations

import asyncio
import re
import sys
from dataclasses import dataclass
from typing import Any

from mcp import ClientSession
from mcp.client.stdio import StdioServerParameters, stdio_client
from mcp.client.streamable_http import streamablehttp_client

from mewcode.mcp.config import MCPServerConfig
from mewcode.mcp.wrapper import MCPToolWrapper

# 工具名合法字符：字母、数字、下划线、连字符
_VALID_TOOL_NAME = re.compile(r"^[A-Za-z0-9_-]+$")


@dataclass
class ServerSession:
    """Manager 对每个已连接 Server 保存的运行时状态。

    Attributes:
        config: 原始配置。
        transport_ctx: stdio_client 或 streamablehttp_client 的返回值
                       （async context manager，用于退出时 __aexit__）。
        session: 已初始化的 MCP 会话。
    """

    config: MCPServerConfig
    transport_ctx: Any  # async context manager
    session: ClientSession


class MCPClientManager:
    """管理多 MCP Server 的完整生命周期。

    负责并发连接（asyncio.gather）、30s 超时、会话缓存、失败隔离、
    退出统一关闭。
    """

    def __init__(self) -> None:
        self._sessions: dict[str, ServerSession] = {}

    # ── 连接单个 server ─────────────────────────────────────────

    async def _connect_one(
        self, server: MCPServerConfig, timeout: float
    ) -> list[MCPToolWrapper]:
        """连接单个 MCP Server，完成握手+列工具，返回 MCPToolWrapper 列表。

        任一子步骤失败触发回滚：已进入的 context manager 做 __aexit__。

        Args:
            server: Server 配置。
            timeout: 单 server 超时秒数。

        Returns:
            该 server 的所有 MCPToolWrapper。失败时返回空列表。
        """
        transport_ctx = None
        session_ctx = None

        try:
            # 1. 根据 type 创建 transport
            if server.type == "stdio":
                params = StdioServerParameters(
                    command=server.command or "",
                    args=server.args,
                    env=server.env if server.env else None,
                )
                transport_ctx = stdio_client(params)
            elif server.type == "http":
                transport_ctx = streamablehttp_client(
                    server.url or "",
                    headers=server.headers if server.headers else None,
                )
            else:
                print(
                    f"[mcp] Server '{server.name}': 未知 type {server.type!r}",
                    file=sys.stderr,
                )
                return []

            # 2. 进入 transport 上下文
            read, write = await transport_ctx.__aenter__()

            # 3. 进入 session 上下文
            session_ctx = ClientSession(read, write)
            session = await session_ctx.__aenter__()

            # 4. 握手
            await asyncio.wait_for(session.initialize(), timeout=timeout)

            # 5. 列工具
            result = await asyncio.wait_for(
                session.list_tools(), timeout=timeout
            )

            # 6. 为每个工具创建 MCPToolWrapper
            wrappers: list[MCPToolWrapper] = []
            for tool in result.tools:
                full_name = f"mcp__{server.name}__{tool.name}"
                if not _VALID_TOOL_NAME.match(full_name):
                    print(
                        f"[mcp] Server '{server.name}': 工具名 '{full_name}' "
                        f"含非法字符，跳过",
                        file=sys.stderr,
                    )
                    continue
                wrappers.append(
                    MCPToolWrapper(server.name, tool, session)
                )

            # 7. 存入会话
            self._sessions[server.name] = ServerSession(
                config=server,
                transport_ctx=transport_ctx,
                session=session,
            )

            return wrappers

        except Exception as exc:
            # 回滚：先退 session 再退 transport
            if session_ctx is not None:
                try:
                    await session_ctx.__aexit__(None, None, None)
                except Exception:
                    pass
            elif transport_ctx is not None:
                # session 未进入但 transport 已进入
                try:
                    await transport_ctx.__aexit__(None, None, None)
                except Exception:
                    pass

            msg = str(exc).rstrip(".")
            print(
                f"[mcp] Server '{server.name}': 连接失败 — {msg}",
                file=sys.stderr,
            )
            return []

    # ── 并发连接全部 server ──────────────────────────────────────

    async def connect_all(
        self,
        servers: dict[str, MCPServerConfig],
        timeout: float = 30,
    ) -> list[MCPToolWrapper]:
        """并发连接所有配置的 MCP Server。

        Args:
            servers: server 名 → 配置的字典。
            timeout: 单 server 超时秒数（默认 30s）。

        Returns:
            所有成功连接的 server 的 MCPToolWrapper 合集。
            失败的 server 被跳过并 stderr 告警。
        """
        tasks = [
            asyncio.wait_for(
                self._connect_one(s, timeout), timeout=timeout
            )
            for s in servers.values()
        ]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        all_wrappers: list[MCPToolWrapper] = []
        for server, result in zip(servers.values(), results):
            if isinstance(result, Exception):
                print(
                    f"[mcp] Server '{server.name}': {result}",
                    file=sys.stderr,
                )
            elif isinstance(result, list):
                all_wrappers.extend(result)

        return all_wrappers

    # ── 统一关闭 ─────────────────────────────────────────────────

    async def close_all(self, timeout: float = 5) -> None:
        """关闭所有已连接的 MCP 会话。

        先 __aexit__ ClientSession，再 __aexit__ transport。
        整体 5s 超时兜底，某 server 卡住不阻塞退出。

        Args:
            timeout: 关闭总超时秒数（默认 5s）。
        """
        if not self._sessions:
            return

        async def _close_one(ss: ServerSession) -> None:
            """关闭单个 server 的 session + transport。"""
            # 先关 session
            try:
                await ss.session.__aexit__(None, None, None)
            except Exception:
                pass
            # 再关 transport
            try:
                await ss.transport_ctx.__aexit__(None, None, None)
            except Exception:
                pass

        tasks = [_close_one(ss) for ss in self._sessions.values()]
        try:
            await asyncio.wait_for(
                asyncio.gather(*tasks, return_exceptions=True),
                timeout=timeout,
            )
        except asyncio.TimeoutError:
            print(
                "[mcp] 关闭 MCP 会话超时（5s），已强制退出",
                file=sys.stderr,
            )

        self._sessions.clear()

    def get_session(self, name: str) -> ClientSession | None:
        """查找已连接 server 的 session。

        Args:
            name: Server 名。

        Returns:
            ClientSession 或 None（未连接）。
        """
        ss = self._sessions.get(name)
        return ss.session if ss else None
