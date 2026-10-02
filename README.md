# cheeseball

命令行 AI 助手，支持多 LLM 后端流式对话与工具调用。基于 [Textual](https://textual.textualize.io/) TUI、`httpx` 与 `mcp`，内置文件读写/搜索/命令执行等工具。

## 快速开始

### 1. 安装

```bash
git clone https://github.com/eating-saint/cheeseball.git
cd cheeseball
pip install -e .          # 自动安装 textual / httpx / mcp / pyyaml / rich
```

> 需要 Python ≥ 3.10。

### 2. 配置 API Key

在用户主目录创建配置文件（程序默认从这里读取）：

| 平台 | 路径 |
|---|---|
| Windows | `C:\Users\<你>\.cheeseball\config.yaml` |
| macOS / Linux | `~/.cheeseball/config.yaml` |

以仓库里的模板为起点：

```bash
mkdir -p ~/.cheeseball
cp config.example.yaml ~/.cheeseball/config.yaml
```

然后编辑它，把 `api_key` 换成你自己的 Key（例如 DeepSeek 的 `sk-...`）。

### 3. 运行

```bash
cheeseball
```

## 配置说明

`~/.cheeseball/config.yaml` 结构：

```yaml
default_provider: deepseek-ant          # 默认使用的 provider
providers:
  deepseek:
    protocol: openai                    # openai 或 anthropic
    model: deepseek-chat
    base_url: https://api.deepseek.com
    api_key: "你的 Key"
  deepseek-ant:
    protocol: anthropic
    model: deepseek-chat
    base_url: https://api.deepseek.com/anthropic
    api_key: "你的 Key"
```

字段说明：

- `default_provider`：默认使用的 provider 名称
- `protocol`：`openai` 或 `anthropic`
- `model`：模型名
- `base_url`：API 地址
- `api_key`：认证密钥
- `context_window`（可选）：上下文窗口大小，不填则取协议默认值

## 可选：MCP 工具

在项目目录放置 `.cheeseball.yaml` 可注册 MCP server。示例（GitHub MCP，需要 `GITHUB_TOKEN` 环境变量）：

```yaml
mcp_servers:
  github:
    type: stdio
    command: npx
    args: ["-y", "@modelcontextprotocol/server-github"]
    env:
      GITHUB_PERSONAL_ACCESS_TOKEN: ${GITHUB_TOKEN}
```

## License

MIT
