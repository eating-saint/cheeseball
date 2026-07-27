"""配置层：YAML 加载、校验、结构化."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml


class ConfigError(Exception):
    """配置异常，携带人类可读的消息."""

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


@dataclass
class ProviderConfig:
    """单个 LLM provider 的配置."""

    protocol: str   # "anthropic" | "openai"
    model: str      # 模型名，如 "claude-sonnet-5"
    base_url: str   # API 地址
    api_key: str    # 认证密钥
    context_window: int = 0  # 0 表示未配置，运行时取协议默认值（F30-F32）


@dataclass
class AppConfig:
    """完整的应用配置."""

    default_provider: str                     # provider 名称
    providers: dict[str, ProviderConfig]      # 名称 → 配置映射


_REQUIRED_TOP_FIELDS = ("default_provider", "providers")
_REQUIRED_PROVIDER_FIELDS = ("protocol", "model", "base_url", "api_key")


def load_config(config_path: str | None = None) -> AppConfig:
    """加载并校验配置文件。

    Args:
        config_path: 配置文件路径。默认读取 ~/.mewcode/config.yaml。

    Returns:
        校验通过的 AppConfig。

    Raises:
        ConfigError: 配置不存在、格式错误或缺少必填字段。
    """
    if config_path is None:
        config_path = str(Path.home() / ".mewcode" / "config.yaml")

    path = Path(config_path)
    if not path.exists():
        raise ConfigError(f"配置文件不存在: {path}\n请在 {path} 创建 config.yaml 配置文件。")

    try:
        with path.open("r", encoding="utf-8") as f:
            raw: dict[str, Any] = yaml.safe_load(f)
    except yaml.YAMLError as e:
        raise ConfigError(f"配置文件 YAML 格式错误: {e}") from e

    if raw is None:
        raise ConfigError("配置文件为空，请填入 default_provider 和 providers 配置。")

    # 校验顶层必填字段
    for field in _REQUIRED_TOP_FIELDS:
        if field not in raw:
            raise ConfigError(f"配置文件缺少顶层必填字段 '{field}'")

    if not isinstance(raw["providers"], dict) or len(raw["providers"]) == 0:
        raise ConfigError("providers 必须是一个非空的字典")

    # 校验每个 provider
    providers: dict[str, ProviderConfig] = {}
    for name, pdata in raw["providers"].items():
        if not isinstance(pdata, dict):
            raise ConfigError(f"provider '{name}' 的配置必须是字典格式")
        for field in _REQUIRED_PROVIDER_FIELDS:
            if field not in pdata or pdata[field] is None or str(pdata[field]).strip() == "":
                raise ConfigError(f"provider '{name}' 缺少字段 '{field}'")
        providers[name] = ProviderConfig(
            protocol=str(pdata["protocol"]),
            model=str(pdata["model"]),
            base_url=str(pdata["base_url"]),
            api_key=str(pdata["api_key"]),
            context_window=int(pdata.get("context_window", 0)),
        )

    return AppConfig(
        default_provider=str(raw["default_provider"]),
        providers=providers,
    )
