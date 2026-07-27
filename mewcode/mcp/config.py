"""MCP Server 配置加载：数据结构、${VAR} 展开、两层 YAML 合并、字段校验."""

from __future__ import annotations

import os
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

import yaml


# ---------------------------------------------------------------------------
# 数据结构
# ---------------------------------------------------------------------------


@dataclass
class MCPServerConfig:
    """单个 MCP Server 的解析后配置。

    Attributes:
        name: Server 名（YAML key），如 "github"。
        type: 传输类型，"stdio" 或 "http"。
        command: stdio 必填，命令名或路径。
        args: stdio 可选，命令行参数。
        env: stdio 可选，注入子进程的环境变量（已展开）。
        url: http 必填，端点 URL。
        headers: http 可选，注入请求的 HTTP 头（已展开）。
    """

    name: str
    type: str  # "stdio" | "http"
    command: str | None = None
    args: list[str] = field(default_factory=list)
    env: dict[str, str] = field(default_factory=dict)
    url: str | None = None
    headers: dict[str, str] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# 环境变量展开
# ---------------------------------------------------------------------------

_VAR_PATTERN = re.compile(r"\$\{(\w+)\}")


def expand_env(value: str) -> str:
    """展开字符串中的 ``${VAR}`` 环境变量引用。

    Args:
        value: 可能包含 ``${VAR}`` 的字符串。

    Returns:
        展开后的字符串。未定义的变量展开为空串并 stderr 告警；
        无 ``${}`` 的原样返回。
    """
    def _replace(match: re.Match) -> str:
        var_name = match.group(1)
        val = os.environ.get(var_name, "")
        if val == "" and var_name not in os.environ:
            print(
                f"[mcp] 环境变量 ${{{var_name}}} 未定义，已展开为空串",
                file=sys.stderr,
            )
        return val

    return _VAR_PATTERN.sub(_replace, value)


def _expand_dict_values(d: dict[str, str]) -> dict[str, str]:
    """对 dict 的每个 value 调用 expand_env()，返回新 dict。"""
    return {k: expand_env(v) for k, v in d.items()}


# ---------------------------------------------------------------------------
# YAML 文件加载与校验
# ---------------------------------------------------------------------------

_USER_CONFIG_PATH = Path.home() / ".mewcode" / "config.yaml"
_PROJECT_CONFIG_NAME = ".mewcode.yaml"


def _load_yaml_file(path: Path) -> dict | None:
    """加载单个 YAML 文件。

    Args:
        path: YAML 文件路径。

    Returns:
        解析后的 dict；文件不存在返回 None；
        格式错误时 stderr 告警并返回 None。
    """
    if not path.is_file():
        return None
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as e:
        print(
            f"[mcp] 配置文件 {path} YAML 格式错误: {e}",
            file=sys.stderr,
        )
        return None
    if data is None:
        return {}
    if not isinstance(data, dict):
        return {}
    return data


def _parse_servers(raw: dict) -> dict[str, MCPServerConfig]:
    """从 YAML 原始 dict 中提取并校验 mcp_servers 段。

    Args:
        raw: YAML 文件解析后的完整 dict。

    Returns:
        校验通过的 server 字典（key 为 server 名）。
        字段非法/缺失的 server 被跳过并 stderr 告警。
    """
    servers_section = raw.get("mcp_servers", {})
    if not isinstance(servers_section, dict):
        return {}

    result: dict[str, MCPServerConfig] = {}
    for name, value in servers_section.items():
        if not isinstance(value, dict):
            print(
                f"[mcp] Server '{name}': 配置格式错误（非 dict），跳过",
                file=sys.stderr,
            )
            continue

        server_type = value.get("type")
        if server_type not in ("stdio", "http"):
            print(
                f"[mcp] Server '{name}': type 非法或缺失 "
                f"(期望 stdio/http，实际 {server_type!r})，跳过",
                file=sys.stderr,
            )
            continue

        if server_type == "stdio":
            command = value.get("command")
            if not command:
                print(
                    f"[mcp] Server '{name}': stdio 类型缺 command 字段，跳过",
                    file=sys.stderr,
                )
                continue
            result[name] = MCPServerConfig(
                name=name,
                type="stdio",
                command=command,
                args=value.get("args", []),
                env=_expand_dict_values(value.get("env", {})),
            )

        elif server_type == "http":
            url = value.get("url")
            if not url:
                print(
                    f"[mcp] Server '{name}': http 类型缺 url 字段，跳过",
                    file=sys.stderr,
                )
                continue
            result[name] = MCPServerConfig(
                name=name,
                type="http",
                url=url,
                headers=_expand_dict_values(value.get("headers", {})),
            )

    return result


# ---------------------------------------------------------------------------
# 两层合并：主入口
# ---------------------------------------------------------------------------


def load_mcp_servers(cwd: str | None = None) -> dict[str, MCPServerConfig]:
    """加载两层 MCP 配置并合并。

    用户级：``~/.mewcode/config.yaml``
    项目级：``<cwd>/.mewcode.yaml``
    按 server 名合并，项目级同名 server 完整覆盖用户级。

    Args:
        cwd: 项目根目录。为 None 时用当前工作目录。

    Returns:
        server 名 → MCPServerConfig 的字典。无配置时返回空 dict。
    """
    project_root = Path(cwd or os.getcwd())
    project_path = project_root / _PROJECT_CONFIG_NAME

    user_raw = _load_yaml_file(_USER_CONFIG_PATH)
    project_raw = _load_yaml_file(project_path)

    user_servers = _parse_servers(user_raw or {})
    project_servers = _parse_servers(project_raw or {})

    # 项目级覆盖用户级同名 server
    merged = {**user_servers, **project_servers}
    return merged
