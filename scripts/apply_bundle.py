#!/usr/bin/env python3
"""把 ChatGPT 的 MODE=B bundle 拆成文件（仅在对方不能写 GitHub 时使用）。

bundle 格式：
    <<<FILE src/em/data/panel.py>>>
    ...完整文件...
    <<<END>>>

用法：
    python scripts/apply_bundle.py inbox/W1-R1.md --dry-run
    python scripts/apply_bundle.py inbox/W1-R1.md
"""

from __future__ import annotations

import argparse
import re
import shutil
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ALLOWED_ROOTS = {"src", "tests", "scripts", "configs"}
FILE_RE = re.compile(r"^<<<FILE\s+(.+?)>>>\s*$")
END_RE = re.compile(r"^<<<END>>>\s*$")


def parse(text: str) -> list[tuple[str, str]]:
    files: list[tuple[str, str]] = []
    current: str | None = None
    buf: list[str] = []
    for line in text.splitlines(keepends=True):
        if current is None:
            m = FILE_RE.match(line.rstrip("\r\n"))
            if m:
                current = m.group(1).strip()
                buf = []
                continue
            if END_RE.match(line.rstrip("\r\n")):
                raise SystemExit("出现未配对的 <<<END>>>")
        else:
            if FILE_RE.match(line.rstrip("\r\n")):
                raise SystemExit(f"文件 {current} 没有 <<<END>>> 就开始了下一个文件")
            if END_RE.match(line.rstrip("\r\n")):
                content = "".join(buf)
                if content.startswith("\n"):
                    content = content[1:]
                if content and not content.endswith("\n"):
                    content += "\n"
                files.append((current, content))
                current = None
                buf = []
                continue
            buf.append(line)
    if current is not None:
        raise SystemExit(f"文件 {current} 缺少 <<<END>>>（可能被截断）")
    return files


def safe_path(raw: str) -> Path:
    rel = Path(raw.replace("\\", "/"))
    if rel.is_absolute() or ".." in rel.parts:
        raise SystemExit(f"非法路径: {raw}")
    if not rel.parts or rel.parts[0] not in ALLOWED_ROOTS:
        raise SystemExit(f"不允许写到 {raw}；只允许 {sorted(ALLOWED_ROOTS)}")
    return ROOT / rel


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("bundle")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--no-backup", action="store_true")
    args = ap.parse_args()

    text = Path(args.bundle).read_text(encoding="utf-8")
    files = parse(text)
    if not files:
        raise SystemExit("没有找到任何 <<<FILE ...>>> 块")

    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    print(f"bundle: {args.bundle}")
    print(f"files : {len(files)}")
    for raw, content in files:
        target = safe_path(raw)
        exists = target.exists()
        print(f"  {'UPDATE' if exists else 'CREATE'} {target.relative_to(ROOT)}  {len(content)} chars")
        if args.dry_run:
            continue
        if exists and not args.no_backup:
            backup = ROOT / ".bundle_backup" / stamp / target.relative_to(ROOT)
            backup.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(target, backup)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
    if args.dry_run:
        print("dry-run: 没有写文件")


if __name__ == "__main__":
    main()
