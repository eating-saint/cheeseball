"""第 3 层：规则引擎。

加载三层 YAML 规则文件，按优先级合并，提供 ToolName(pattern) 格式的
精确匹配和 glob 匹配。同时负责"永久允许"时的规则写入。
"""

from __future__ import annotations

import fnmatch
import sys
from pathlib import Path

import yaml

from cheeseball.permission.types import Rule


class RuleEngine:
    """加载三层 YAML 规则，按优先级匹配。

    优先级（从高到低）：session > local > project > user
    """

    def __init__(self, project_root: str, user_home: str) -> None:
        self._session_rules: list[Rule] = []
        self._local_rules: list[Rule] = []
        self._project_rules: list[Rule] = []
        self._user_rules: list[Rule] = []

        project_dir = Path(project_root)
        user_dir = Path(user_home)

        self._local_path = project_dir / ".cheeseball" / "permissions.local.yaml"
        self._project_path = project_dir / ".cheeseball" / "permissions.yaml"
        self._user_path = user_dir / ".cheeseball" / "permissions.yaml"

        self._load_files()

    # ── 公开方法 ──────────────────────────────────────────────────

    def match(self, tool_name: str, primary_arg: str) -> Rule | None:
        """按优先级查找第一个命中的规则。

        Args:
            tool_name: 工具名, e.g. "Bash", "WriteFile"
            primary_arg: 第一个关键参数值, e.g. "git status", "src/main.py"

        Returns:
            第一个命中的 Rule，未命中返回 None。
        """
        for source in (self._session_rules, self._local_rules,
                       self._project_rules, self._user_rules):
            rule = self._match_in_list(source, tool_name, primary_arg)
            if rule is not None:
                return rule
        return None

    def add_session_rule(self, rule: Rule) -> None:
        """添加会话级临时规则（内存，不写文件）。

        插入到会话规则列表头部，保证最高优先级。
        """
        # 去重：已有同 tool + 同 pattern 的不重复添加
        for existing in self._session_rules:
            if existing.tool == rule.tool and existing.pattern == rule.pattern:
                return
        self._session_rules.insert(0, rule)

    def write_local_rule(self, rule: Rule) -> None:
        """追加规则到本地 YAML 文件并重新加载。

        去重：已有同 tool + 同 pattern 的规则不重复写入。
        """
        # 确保目录存在
        self._local_path.parent.mkdir(parents=True, exist_ok=True)

        # 读取已有规则
        existing_rules: list[dict] = []
        if self._local_path.exists():
            try:
                data = yaml.safe_load(self._local_path.read_text(encoding="utf-8"))
                if data and isinstance(data.get("rules"), list):
                    existing_rules = data["rules"]
            except yaml.YAMLError:
                existing_rules = []

        # 去重检查
        for existing in existing_rules:
            if (isinstance(existing, dict)
                    and existing.get("tool") == rule.tool
                    and existing.get("pattern") == rule.pattern):
                # 已存在，无需写入
                self._local_rules.insert(0, Rule(
                    tool=rule.tool,
                    pattern=rule.pattern,
                    result=rule.result,
                    source="local",
                ))
                return

        # 追加新规则
        existing_rules.append({
            "tool": rule.tool,
            "pattern": rule.pattern,
            "result": rule.result,
        })

        yaml_data = {"rules": existing_rules}
        self._local_path.write_text(
            yaml.dump(yaml_data, allow_unicode=True, default_flow_style=False,
                      sort_keys=False),
            encoding="utf-8",
        )

        # 重新加载本地规则
        self._local_rules = self._load_yaml(self._local_path, "local")

    # ── 内部方法 ──────────────────────────────────────────────────

    def _load_files(self) -> None:
        """加载三层 YAML 规则文件。"""
        self._user_rules = self._load_yaml(self._user_path, "user")
        self._project_rules = self._load_yaml(self._project_path, "project")
        self._local_rules = self._load_yaml(self._local_path, "local")

    @staticmethod
    def _load_yaml(path: Path, source: str) -> list[Rule]:
        """从 YAML 文件加载规则列表。

        Args:
            path: YAML 文件路径。
            source: 规则来源标识 ("user" | "project" | "local")。

        Returns:
            Rule 列表。文件不存在或解析失败返回 []。
        """
        if not path.exists():
            return []

        try:
            data = yaml.safe_load(path.read_text(encoding="utf-8"))
        except yaml.YAMLError as exc:
            print(
                f"[WARNING] 解析权限规则文件失败: {path} — {exc}",
                file=sys.stderr,
            )
            return []
        except Exception as exc:
            print(
                f"[WARNING] 读取权限规则文件失败: {path} — {exc}",
                file=sys.stderr,
            )
            return []

        if not data or not isinstance(data.get("rules"), list):
            return []

        rules: list[Rule] = []
        for entry in data["rules"]:
            if not isinstance(entry, dict):
                continue
            tool = entry.get("tool")
            pattern = entry.get("pattern")
            result = entry.get("result")
            if tool and pattern and result:
                rules.append(Rule(
                    tool=str(tool),
                    pattern=str(pattern),
                    result=str(result),
                    source=source,
                ))
        return rules

    @staticmethod
    def _match_in_list(
        rules: list[Rule], tool_name: str, primary_arg: str
    ) -> Rule | None:
        """在单个规则列表中查找匹配项。

        同一列表中多条规则命中时：精确匹配（无 * 通配符）优先于 glob 匹配。

        Args:
            rules: 规则列表。
            tool_name: 工具名。
            primary_arg: 参数值。

        Returns:
            命中的 Rule，按精确度优先；未命中返回 None。
        """
        best: Rule | None = None
        best_exact = False

        for rule in rules:
            if rule.tool != tool_name:
                continue
            if not fnmatch.fnmatch(primary_arg, rule.pattern):
                continue

            # 判断是否为精确匹配（pattern 不含 * ? [ 等通配符）
            is_exact = not any(ch in rule.pattern for ch in "*?[")

            if is_exact and not best_exact:
                # 精确匹配 > glob（含 None）
                best = rule
                best_exact = True
            elif is_exact and best_exact:
                # 同为精确匹配，取较早的（后面的即使也是精确，但不会比前面的更好）
                # 保持现有 best
                pass
            elif not is_exact and best is None:
                # 首次命中（glob 匹配），记录
                best = rule
            # else: glob 匹配但已有结果（精确或 glob），忽略

        return best
