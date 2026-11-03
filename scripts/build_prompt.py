#!/usr/bin/env python3
"""把仓库内的角色说明 + 契约 + 任务书 + 交付协议拼成一份自包含 prompt。

用法：
    python scripts/build_prompt.py --task W1-R1
    python scripts/build_prompt.py --task W2-R1 --out prompts/generated/W2-R1.md

生成物是给 ChatGPT 直接复制粘贴的；仓库内的 docs/ 才是真源。
"""

from __future__ import annotations

import argparse
import hashlib
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DOCS = ROOT / "docs"
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from em.contracts import CONTRACT_VERSION  # noqa: E402


def read_text(path: Path) -> str:
    if not path.exists():
        raise SystemExit(f"缺少文件: {path}")
    return path.read_text(encoding="utf-8").strip()


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()[:16]


def build(task: str) -> str:
    task_path = DOCS / "tasks" / f"{task}.md"
    worker = task.split("-", 1)[0].upper()
    intro_path = DOCS / "prompts" / f"{worker}_intro.md"
    if not intro_path.exists():
        raise SystemExit(f"未知 worker: {worker}（缺 {intro_path}）")

    now = datetime.now(timezone.utc).astimezone().strftime("%Y-%m-%d %H:%M %Z")
    parts = [
        f"# {task} 自包含任务包",
        "",
        f"> 生成时间：{now}",
        f"> 仓库：https://github.com/Leo1Hugh/AI-electricity_market",
        f"> 基线 tag：contract-v1.0.0 ｜ 契约版本：{CONTRACT_VERSION}",
        f"> 本文件由 scripts/build_prompt.py 生成，真源在 docs/；冲突以仓库 main 上 tag 为准。",
        "",
        "## A. 你的角色",
        "",
        read_text(intro_path),
        "",
        "## B. 仓库规则（AGENTS.md 全文）",
        "",
        read_text(ROOT / "AGENTS.md"),
        "",
        "## C. 建模契约（docs/建模契约_v1.md 全文）",
        "",
        read_text(DOCS / "建模契约_v1.md"),
        "",
        "## D. 本次任务书（docs/tasks/" + task + ".md 全文）",
        "",
        read_text(task_path),
        "",
        "## E. 交付协议（docs/prompts/_output_protocol.md 全文）",
        "",
        read_text(DOCS / "prompts" / "_output_protocol.md"),
        "",
        "## F. 最后自检（发送前逐条打勾）",
        "",
        "- [ ] 我读的是 contract-v1.0.0，不是旧版本",
        "- [ ] 我只改了任务书允许的文件",
        "- [ ] 我没有引入未来信息、随机切分、双向插值",
        "- [ ] 我跑了任务书里的 pytest 命令，并贴了真实输出",
        "- [ ] 我的交付格式是 MODE=G 的 PR，或 MODE=B 的完整 bundle",
        "- [ ] 我写了 HANDOFF，且没有把推断写成已验证",
        "",
        "---",
        "",
        f"<!-- prompt-sha256: {hashlib.sha256(read_text(task_path).encode()).hexdigest()[:16]} -->",
    ]
    return "\n".join(parts).rstrip() + "\n"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--task", required=True, help="如 W1-R1")
    ap.add_argument("--out", default=None)
    args = ap.parse_args()

    text = build(args.task)
    out = Path(args.out) if args.out else ROOT / "prompts" / "generated" / f"{args.task}.md"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(text, encoding="utf-8")
    print(f"wrote {out}")
    print(f"chars={len(text)} lines={text.count(chr(10)) + 1}")
    print(f"sha256={hashlib.sha256(text.encode()).hexdigest()[:16]}")


if __name__ == "__main__":
    main()
