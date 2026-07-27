"""MewCode 程序入口：参数解析 → 加载配置 → 启动 TUI（ch03 装配工具系统，ch08 上下文管理，ch09 记忆与持久化）."""

from __future__ import annotations

import argparse
import logging
import os
import sys
import threading
from pathlib import Path

from mewcode.agent.runner import Agent
from mewcode.config.loader import ConfigError, load_config
from mewcode.context.config import resolve_context_window
from mewcode.context.manager import ContextManager
from mewcode.core.conversation import Conversation
from mewcode.instruction.loader import load_instructions
from mewcode.memory.manager import MemoryManager
from mewcode.provider import create_provider
from mewcode.session import new_session_id
from mewcode.session.archiver import SessionArchiver
from mewcode.session.scanner import cleanup_expired
from mewcode.tool import new_default_registry

logger = logging.getLogger(__name__)


def main() -> None:
    """MewCode 主函数。

    1. 解析 --provider 命令行参数
    2. 加载 ~/.mewcode/config.yaml
    3. 创建对应 Provider
    4. 创建 Conversation
    5. 创建 ToolRegistry（注册全部 6 个核心工具）
    6. 创建 Agent（持有 provider + registry）
    7. 启动 Textual TUI
    """
    parser = argparse.ArgumentParser(
        prog="mewcode",
        description="命令行 AI 助手，支持多 LLM 后端流式对话与工具调用",
    )
    parser.add_argument(
        "--provider",
        type=str,
        default=None,
        help="指定使用的 LLM 后端（覆盖配置文件中的 default_provider）",
    )
    args = parser.parse_args()

    # 1. 加载配置
    try:
        config = load_config()
    except ConfigError as e:
        print(f"配置错误: {e.message}", file=sys.stderr)
        sys.exit(1)
    except Exception as e:
        print(f"加载配置失败: {e}", file=sys.stderr)
        sys.exit(1)

    # 2. 确定 provider 名称
    provider_name = args.provider or config.default_provider

    # 3. 查找 provider 配置
    provider_config = config.providers.get(provider_name)
    if provider_config is None:
        available = ", ".join(config.providers.keys())
        print(
            f"错误: 未找到 provider '{provider_name}'。"
            f"可用的 provider: {available}",
            file=sys.stderr,
        )
        sys.exit(1)

    # 4. 创建 provider
    try:
        provider = create_provider(provider_config)
    except ValueError as e:
        print(f"错误: {e}", file=sys.stderr)
        sys.exit(1)

    # 5. 创建对话管理
    conversation = Conversation(provider)

    # 6. 创建工具注册中心（工作目录 = 启动 mewcode 时的当前目录）
    cwd = os.getcwd()
    registry = new_default_registry(cwd)

    # 7. 加载 MCP 配置
    from mewcode.mcp.config import load_mcp_servers

    mcp_servers = load_mcp_servers(cwd)

    # 8. [ch09] 加载项目指令（F1-F8, F34-①）
    instructions_result = load_instructions(Path.cwd())
    instructions = instructions_result.text
    logger.info(
        "指令加载: %d 层, %d 字节, %d @include, %d 警告",
        len(instructions_result.loaded_layers),
        instructions_result.total_bytes,
        instructions_result.include_count,
        len(instructions_result.warnings),
    )

    # 9. [ch09] 初始化记忆管理器（F34-②）
    memory_mgr = MemoryManager(
        project_memory_dir=Path.cwd() / ".mewcode" / "memory",
        user_memory_dir=Path.home() / ".mewcode" / "memory",
    )
    memory_mgr.ensure_dirs()
    memories = memory_mgr.load_index()
    logger.info("记忆索引加载: %d 字符", len(memories))

    # 10. [ch09] 后台过期会话清理（F22, F34-③）
    sessions_root = Path.cwd() / ".mewcode" / "sessions"
    threading.Thread(
        target=lambda: cleanup_expired(sessions_root),
        daemon=True,
    ).start()

    # 11. [ch09] Session ID 新格式 + 目录结构（F9-F10）
    session_id = new_session_id()
    session_dir = Path.cwd() / ".mewcode" / "sessions" / session_id
    tool_results_dir = session_dir / "tool-results"
    os.makedirs(tool_results_dir, exist_ok=True)

    # 12. [ch09] 创建 archiver
    jsonl_path = session_dir / "conversation.jsonl"
    archiver = SessionArchiver(jsonl_path)

    # 13. 重新创建 Conversation（注入 archiver）
    conversation = Conversation(provider, archiver=archiver)

    # 14. 创建上下文管理器（ch08: F34, F35）
    window = resolve_context_window(provider_config)
    context_mgr = ContextManager(window, session_id, session_dir, provider, registry)

    # 15. 创建 Agent（注入 context_mgr）
    agent = Agent(provider, registry, context_mgr=context_mgr)

    # 15½. 自动修复 Textual/Rich 上游库的已知 bug
    from mewcode.install_patches import ensure_patches

    ensure_patches()

    # 15¾. [ch10] 初始化命令注册中心
    from mewcode.cmd import CommandRegistry, CommandDef, CommandKind
    from mewcode.cmd.handlers.help import cmd_help, set_registry
    from mewcode.cmd.handlers.status import cmd_status
    from mewcode.cmd.handlers.memory import cmd_memory
    from mewcode.cmd.handlers.permission import cmd_permission
    from mewcode.cmd.handlers.session import cmd_session
    from mewcode.cmd.handlers.exit import cmd_exit
    from mewcode.cmd.handlers.plan import cmd_plan
    from mewcode.cmd.handlers.do import cmd_do
    from mewcode.cmd.handlers.compact import cmd_compact
    from mewcode.cmd.handlers.resume import cmd_resume
    from mewcode.cmd.handlers.clear import cmd_clear
    from mewcode.cmd.handlers.review import cmd_review

    cmd_registry = CommandRegistry()

    # 注册 12 条命令
    cmd_registry.register(CommandDef(
        name="exit", kind=CommandKind.UI, description="退出应用",
        handler=cmd_exit, usage="/exit",
    ))
    cmd_registry.register(CommandDef(
        name="plan", kind=CommandKind.UI, description="进入计划模式",
        handler=cmd_plan, usage="/plan",
    ))
    cmd_registry.register(CommandDef(
        name="do", kind=CommandKind.PROMPT, description="执行计划",
        handler=cmd_do, usage="/do [指令]",
    ))
    cmd_registry.register(CommandDef(
        name="compact", kind=CommandKind.UI, description="压缩上下文",
        handler=cmd_compact, usage="/compact",
    ))
    cmd_registry.register(CommandDef(
        name="resume", kind=CommandKind.UI, description="恢复历史会话",
        handler=cmd_resume, usage="/resume",
    ))
    cmd_registry.register(CommandDef(
        name="clear", kind=CommandKind.UI, description="清空对话并开启新会话",
        handler=cmd_clear, usage="/clear",
    ))
    cmd_registry.register(CommandDef(
        name="help", kind=CommandKind.LOCAL, description="显示命令帮助",
        handler=cmd_help, usage="/help [命令名]", aliases=("h",),
    ))
    cmd_registry.register(CommandDef(
        name="status", kind=CommandKind.LOCAL, description="显示运行状态",
        handler=cmd_status, usage="/status",
    ))
    cmd_registry.register(CommandDef(
        name="memory", kind=CommandKind.LOCAL, description="列出已加载的记忆条目",
        handler=cmd_memory, usage="/memory",
    ))
    cmd_registry.register(CommandDef(
        name="permission", kind=CommandKind.LOCAL, description="查看当前权限模式",
        handler=cmd_permission, usage="/permission",
    ))
    cmd_registry.register(CommandDef(
        name="session", kind=CommandKind.LOCAL, description="查看当前会话信息",
        handler=cmd_session, usage="/session",
    ))
    cmd_registry.register(CommandDef(
        name="review", kind=CommandKind.PROMPT, description="代码审查",
        handler=cmd_review, usage="/review",
    ))

    # 注入 registry 到 /help handler
    set_registry(cmd_registry)

    # 启动期冲突检测（N1, N4）
    conflicts = cmd_registry.validate()
    if conflicts:
        for c in conflicts:
            print(f"命令冲突: {c}", file=sys.stderr)
        sys.exit(1)

    # 16. 启动 TUI（延迟导入避免 Textual 影响启动错误信息）
    from mewcode.ui.app import MewCodeApp

    try:
        app = MewCodeApp(
            agent, conversation, registry=registry,
            mcp_servers=mcp_servers, context_mgr=context_mgr,
            instructions=instructions,
            memories=memories,
            memory_manager=memory_mgr,
            session_archiver=archiver,
            cmd_registry=cmd_registry,
        )
        app.run()
    except KeyboardInterrupt:
        # Ctrl+C 正常退出
        pass


if __name__ == "__main__":
    main()
