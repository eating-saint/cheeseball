"""第 6 章核心：权限引擎，串联五层递进判断。

工具调用请求
  → L1 黑名单（硬拦截，不可绕过）
  → L2 路径沙箱（超出项目目录即拒）
  → L3 规则引擎（三层 YAML 规则，allow/deny）
  → L4 权限模式（兜底裁决）
  → L5 人在回路（ASK 时暂停 Loop，等用户决定）
  → 放行 / 拒绝
"""

from __future__ import annotations

from cheeseball.permission.blacklist import Blacklist
from cheeseball.permission.modes import (
    MODE_FALLBACK,
    Mode,
    ToolCategory,
    cycle_mode,
    get_fallback,
)
from cheeseball.permission.rules import RuleEngine
from cheeseball.permission.sandbox import PathSandbox
from cheeseball.permission.types import CheckResult, Rule, Verdict


class PermissionEngine:
    """串联五层，对外提供统一的 check() 入口。"""

    def __init__(self, project_root: str, user_home: str) -> None:
        self.blacklist = Blacklist()
        self.sandbox = PathSandbox(project_root)
        self.rules = RuleEngine(project_root, user_home)
        self.mode: Mode = Mode.DEFAULT

    # ── 核心判定 ──────────────────────────────────────────────────

    def check(
        self,
        tool_name: str,
        arguments: dict,
        tool_category: ToolCategory,
    ) -> CheckResult:
        """串联五层，返回判定结果。

        Args:
            tool_name: 工具名, e.g. "run_command", "write_file".
            arguments: 工具调用参数字典, e.g. {"command": "git status"}.
            tool_category: 工具类别（READONLY / FILE_WRITE / COMMAND）。

        Returns:
            CheckResult(verdict, reason).
        """
        # ── bypassPermissions 快速路径 ──
        if self.mode == Mode.BYPASS_PERMISSIONS:
            # 仅 L1 黑名单生效
            if tool_name == "run_command" and "command" in arguments:
                blocked, reason = self.blacklist.check(
                    str(arguments["command"])
                )
                if blocked:
                    return CheckResult(Verdict.DENY, reason)
            return CheckResult(Verdict.ALLOW, "")

        # ── L1: 黑名单（仅 run_command）──
        if tool_name == "run_command" and "command" in arguments:
            blocked, reason = self.blacklist.check(str(arguments["command"]))
            if blocked:
                return CheckResult(Verdict.DENY, reason)

        # ── L2: 路径沙箱（仅含 path 参数的工具）──
        if "path" in arguments:
            allowed, reason = self.sandbox.validate(str(arguments["path"]))
            if not allowed:
                return CheckResult(Verdict.DENY, reason)

        # ── L3: 规则引擎 ──
        primary_arg = (
            str(arguments.get("command", ""))
            if "command" in arguments
            else str(arguments.get("path", ""))
        )
        rule = self.rules.match(tool_name, primary_arg)
        if rule is not None:
            if rule.result == "allow":
                return CheckResult(
                    Verdict.ALLOW,
                    f"RULE: {rule.tool}({rule.pattern})",
                )
            else:
                return CheckResult(
                    Verdict.DENY,
                    f"RULE: {rule.tool}({rule.pattern})",
                )

        # ── L4: 模式兜底 ──
        verdict = get_fallback(self.mode, tool_category)
        return CheckResult(
            verdict,
            f"{self.mode.value} 模式下 {tool_category.value} 类兜底裁决",
        )

    # ── 模式切换 ──────────────────────────────────────────────────

    def switch_mode(self, mode: Mode) -> None:
        """直接设置权限模式。"""
        self.mode = mode

    def switch_mode_cycle(self, direction: int) -> Mode:
        """循环切换模式（direction: +1 下一档, -1 上一档）。

        Returns:
            切换后的新模式。
        """
        self.mode = cycle_mode(self.mode, direction)
        return self.mode

    # ── 永久规则 ──────────────────────────────────────────────────

    def add_permanent_rule(self, tool_name: str, primary_arg: str) -> None:
        """选「永久允许」时调用：创建规则并写入本地 YAML，同时加入会话规则。

        写入的规则是精确匹配（无通配符）。

        Args:
            tool_name: 工具名。
            primary_arg: 参数值（精确匹配）。
        """
        rule = Rule(
            tool=tool_name,
            pattern=primary_arg,
            result="allow",
            source="local",
        )
        # 先写入文件（持久化），再写入会话（当前会话立即生效）
        self.rules.write_local_rule(rule)
        session_rule = Rule(
            tool=tool_name,
            pattern=primary_arg,
            result="allow",
            source="session",
        )
        self.rules.add_session_rule(session_rule)
