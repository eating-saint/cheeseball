"""上下文管理的 16 个硬编码常量（F36）。单一事实来源，所有模块从此处引用。"""

# ── 第 1 层：工具结果预防性压缩阈值 ──────────────────────────
# F1: 单条工具结果超过此字节数即触发落盘+预览替换
SINGLE_RESULT_THRESHOLD: int = 50_000

# F2: 同一 RoleTool 消息内未被替换的结果聚合后不得超过此字节数
MESSAGE_AGGREGATE_LIMIT: int = 200_000

# ── 第 2 层：摘要触发阈值计算的安全边距 ──────────────────────
# F7: LLM 摘要本身输出预留空间（摘要响应上限）
SUMMARY_OUTPUT_RESERVE: int = 20_000

# F7: 自动触发摘要时在 context_window 基础上额外留出的安全边距
AUTO_SAFETY_MARGIN: int = 13_000

# F23: 手动 /compact 预检查的安全边距（比自动更激进，只留 3K）
MANUAL_SAFETY_MARGIN: int = 3_000

# ── 近期原文保留参数 ──────────────────────────────────────────
# F11: 摘要后保留的近期原文 token 下界
RECENT_TOKEN_FLOOR: int = 10_000

# F11: 摘要后保留的近期原文消息条数下界
RECENT_COUNT_FLOOR: int = 5

# F16: 恢复段展示的最近读取文件数量上限
MAX_RECENT_FILES: int = 5

# F16: 单个文件快照在恢复段中的 token 预算（用于字符截断）
FILE_SNAPSHOT_TOKEN_CAP: int = 5_000

# ── 熔断器 ────────────────────────────────────────────────────
# F28: 自动摘要连续失败次数阈值，达到后熔断
CIRCUIT_BREAKER_THRESHOLD: int = 3

# ── PTL 紧急压缩重试策略 ──────────────────────────────────────
# F27: 直接丢弃组重试次数上限（每次丢 1 组）
PTL_DIRECT_RETRY_MAX: int = 3

# F27: 比例丢弃步长（丢弃 ceil(剩余组数 × 0.2) 组）
PTL_RATIO_DROP_STEP: float = 0.2

# ── Token 估算 ────────────────────────────────────────────────
# F13: 增量字符数 ÷ 每 token 字符数 = 增量 token 数
ESTIMATE_CHARS_PER_TOKEN: float = 3.5

# ── 预览体格式化 ──────────────────────────────────────────────
# F3: 工具结果预览头部字节数上限
PREVIEW_HEAD_BYTE_CAP: int = 2048

# F3: 工具结果预览头部行数上限
PREVIEW_HEAD_LINE_CAP: int = 20

# ── 会话目录 ──────────────────────────────────────────────────
# F35: 工作目录下的会话存储目录
SESSION_DIR_NAME: str = ".cheeseball/sessions"

# F3: 工具结果落盘子目录名
TOOL_RESULTS_SUBDIR: str = "tool-results"
