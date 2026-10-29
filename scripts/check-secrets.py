#!/usr/bin/env python
"""扫描受版本控制文件里的疑似真实密钥。

替代 CI 里那段纯字符正则，它有两个毛病：把 `const X = c.env.X` 这类引用误报，
以及完全看不见未 checkout 的子仓库。这里做的是「按行判别」：

    - 只认赋值给疑似密钥变量的行（变量名含 SECRET/TOKEN/PASSWORD/API_KEY…）；
    - 占位符、${VAR} 插值、`<redacted>`、点号标识符一律放行；
    - 命中时只回报键名与值长度，绝不回显值本身；
    - 行尾写 `# sensitive-scan: ignore` 可单行豁免。

用法:
    python scripts/check-secrets.py            # 扫 git 跟踪的全部文件
    python scripts/check-secrets.py --staged   # 只扫暂存区（提交前）
    python scripts/check-secrets.py --audit    # 同默认，供 .githooks 包装调用

退出码：0 = 干净；1 = 有命中；2 = git 调用失败。
"""
from __future__ import annotations

import argparse
import re
import subprocess
import sys

# 变量名里出现这些词才值得看值。
# 关键词的位置不限：`SECRET_KEY`、`API_KEY`、`MY_SECRET_VALUE` 这类
# "词在中间"的命名都要覆盖——之前要求关键词紧跟在首字母之后，
# 导致 SECRET_KEY / API_KEY 整体漏检（实测踩过）。
SUSPICIOUS_KEY = re.compile(
    r"(?P<key>[A-Z][A-Z0-9_]*)"
    r"\s*(?:=|:)\s*(?P<rest>.+)$"
)
# 变量名里必须出现的关键词（位置不限）
KEY_WORD = re.compile(
    r"SECRET|TOKEN|PASSWORD|PASSWD|CREDENTIAL|API_?KEY|PRIVATE_?KEY"
)

# 与变量名无关、本身就足以判定为凭据的形态
TOKEN_PATTERNS = (
    re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH |DSA |PGP )?PRIVATE KEY-----"),
    re.compile(r"\bghp_[A-Za-z0-9]{36}\b"),
    re.compile(r"\bgithub_pat_[A-Za-z0-9_]{20,}\b"),
    re.compile(r"\bxox[baprs]-[A-Za-z0-9-]{10,}\b"),
    re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    re.compile(r"\bsk-[A-Za-z0-9]{32,}\b"),
)

# 预扫描用：先把含这些词的文件行捞出来，再逐行判别
PRE_FILTER = r"SECRET|TOKEN|PASSWORD|PASSWD|CREDENTIAL|API_?KEY|PRIVATE KEY"

IGNORE_MARKER = "sensitive-scan: ignore"

_LITERAL = re.compile(r"[A-Za-z0-9+/=_.:\-]+")
_DOTTED_IDENTIFIER = re.compile(r"[A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)+")

_PLACEHOLDER_HINTS = (
    "your_", "your-", "placeholder", "changeme", "change_me", "replace_me",
    "redacted", "example", "dummy", "sample", "todo", "fixme", "xxxx",
    "****", "secret_here", "<", ">", "${", "$(", "%s", "%(", "{{", "}}",
)

_REFERENCE_PREFIXES = (
    "process.env", "c.env", "os.environ", "self.", "settings.",
    "config.", "env.", "import.",
)

# 全大写 + 下划线的标识符（如 KAME_SIGNATURE_SECRET、ENV_LOCAL），
# 是变量名而不是密钥字面量。`SECRET_ENV = "KAME_SIGNATURE_SECRET"`
# 这种写法必须放行，否则扫描器会把自己的常量表当成凭据。
_UPPER_IDENTIFIER = re.compile(r"[A-Z][A-Z0-9_]*")


def _strip_value(value: str) -> str:
    """把赋值右侧归一化成裸值。

    剥离顺序很关键：必须**先**去掉尾部的 `;` / `,`，**再**去引号。
    反过来的话，`KEY = "abc...";` 这种带分号的写法，剥引号时尾部还有 `;`，
    引号不在首尾位置，剥不掉，后面按字面量匹配就会失败——
    于是带分号的真密钥反而漏检（实测踩过：TS 里的 `const X = "..."`）。
    """
    s = value.strip()
    s = s.rstrip(";").rstrip(",")
    s = s.strip()
    s = s.strip("\"'")
    s = s.strip()
    return s


def is_placeholder(value: str) -> bool:
    """占位符/插值/脱敏标记，放行。"""
    lowered = _strip_value(value).lower()
    return any(hint in lowered for hint in _PLACEHOLDER_HINTS)


def is_reference(value: str) -> bool:
    """变量引用（c.env.X / process.env.X / 点号标识符 / 全大写常量名），不是字面量。"""
    stripped = _strip_value(value)
    if stripped.startswith(_REFERENCE_PREFIXES):
        return True
    if _DOTTED_IDENTIFIER.fullmatch(stripped) is not None:
        return True
    # 全大写标识符：KAME_SIGNATURE_SECRET、ENV_LOCAL 这类是常量名
    if _UPPER_IDENTIFIER.fullmatch(stripped) is not None:
        return True
    return False


def looks_like_literal(value: str) -> bool:
    """去掉引号后长度足够、字符集像密钥、且不是占位符或引用。"""
    stripped = _strip_value(value)
    if len(stripped) < 16:
        return False
    if is_placeholder(stripped) or is_reference(stripped):
        return False
    return _LITERAL.fullmatch(stripped) is not None


def find_issues(path: str, lineno: int, line: str) -> list[tuple[str, str, int]]:
    """返回该行的命中项列表：(路径, 键名, 值长度)。"""
    if IGNORE_MARKER in line:
        return []

    issues: list[tuple[str, str, int]] = []
    for pattern in TOKEN_PATTERNS:
        match = pattern.search(line)
        if match:
            issues.append((path, pattern.pattern, len(match.group(0))))

    match = SUSPICIOUS_KEY.search(line)
    if match and KEY_WORD.search(match.group("key")):
        # 值可能带行尾注释，先切掉
        value = match.group("rest").split("#", 1)[0].strip()
        if looks_like_literal(value):
            issues.append((path, match.group("key"), len(value.strip("\"'"))))
    return issues


def git_grep(staged: bool) -> subprocess.CompletedProcess[str]:
    # 注意选项顺序：`--cached` 必须放在**所有选项之前**（git grep --cached -nIE PAT -- .）。
    # 放到 PATTERN 之后、或 "--" 之后，git 会把它当成 revision 名，
    # 报 "unable to resolve revision: --cached"；该错误码既不是 0 也不是 1，
    # 于是 audit() 判为"git 调用失败"返回 2——提交前的 --staged 路径因此从未真正工作过。
    cmd = ["git", "grep"]
    if staged:
        cmd.append("--cached")
    cmd += ["-nIE", PRE_FILTER, "--", "."]
    return _run(cmd)


def _run(cmd: list[str]) -> subprocess.CompletedProcess[str]:
    """执行 git 调用。抽出来是为了让"命令拼装"可被测试断言。"""
    return subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace")


def audit(staged: bool) -> int:
    result = git_grep(staged)
    if result.returncode not in (0, 1):  # 1 = 无命中，属正常
        print(f"git grep 失败：{result.stderr.strip()}", file=sys.stderr)
        return 2

    findings: list[tuple[str, str, int]] = []
    for raw in result.stdout.splitlines():
        parts = raw.split(":", 2)
        if len(parts) != 3:
            continue
        path, lineno, line = parts
        findings.extend(find_issues(path, int(lineno), line))

    if not findings:
        print("OK：未发现疑似真实密钥")
        return 0

    for path, key, size in findings:
        print(f"{path}: {key} = <已隐藏，{size} 字符>")
    print(
        f"\n发现 {len(findings)} 处疑似真实密钥。"
        f"若是占位符请改写或在该行加 `# {IGNORE_MARKER}`。",
        file=sys.stderr,
    )
    return 1


def main() -> int:
    parser = argparse.ArgumentParser(description="扫描受版本控制文件里的疑似真实密钥")
    parser.add_argument("--staged", action="store_true", help="只扫暂存区（提交前用）")
    parser.add_argument("--audit", action="store_true", help="全量审计（默认行为，保留此开关供 hook 调用）")
    args = parser.parse_args()
    return audit(staged=args.staged)


if __name__ == "__main__":
    sys.exit(main())
