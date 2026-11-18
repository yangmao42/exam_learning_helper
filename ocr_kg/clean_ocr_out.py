# -*- coding: utf-8 -*-
"""对已生成的 OCR Markdown 二次清洗（补跑界面噪声剔除）

背景：batch_ocr.py 的清洗规则在迭代过程中升级过（新增「行内按钮文案剔除」），
但已生成的 .md 是用旧规则洗的，题行尾仍粘着「全选 提交答案」这类 App 按钮文案。
OCR 本身很贵（纯 CPU 约 60~90s/页），所以不重跑 OCR，直接用新规则再洗一遍。

运行方式（在仓库根目录执行）：
    & .venv\\Scripts\\python.exe ocr_kg\\clean_ocr_out.py
    & .venv\\Scripts\\python.exe ocr_kg\\clean_ocr_out.py <md目录> --dry-run

要点：
- 只读项目 .venv 即可，本脚本不加载 torch（清洗逻辑在 batch_ocr.py 里是纯文本函数）。
- 首次运行会先把原始 .md 备份到 <md目录的同级>_preclean_backup/，再原地覆盖。
- 清洗规则是幂等的：重复跑同一个文件不会再变。
"""

from __future__ import annotations

import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from batch_ocr import clean_ocr_text  # noqa: E402

# 默认处理目录
DEFAULT_DIR = Path(r"D:\hcip\learning_project\ocr_kg\ocr_out\run01_175p")
# 备份目录（原始 md 的保险）
BACKUP_SUFFIX = "_preclean_backup"
# 复检用的残留噪声关键词
CHECK_TOKENS = ("提交答案", "全选", "一起纠错", "AI 深度", "AI深度", "A1 深度",
                "分享", "收起", "详解", "查看原图", "立即开通", "开通会员")


def backup_once(md_dir: Path) -> Path | None:
    """把原始 md 备份一份（只备份一次，已存在则跳过）。"""
    bak = md_dir.parent / (md_dir.name + BACKUP_SUFFIX)
    if bak.exists():
        return bak
    bak.mkdir(parents=True, exist_ok=True)
    for f in md_dir.glob("*.md"):
        shutil.copy2(f, bak / f.name)
    return bak


def main() -> int:
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    dry = "--dry-run" in sys.argv
    md_dir = Path(args[0]) if args else DEFAULT_DIR

    if not md_dir.is_dir():
        print(f"[错误] 目录不存在：{md_dir}")
        return 1

    files = sorted(md_dir.glob("*.md"))
    if not files:
        print(f"[提示] {md_dir} 下没有 .md 文件")
        return 0

    # 先备份原始 md，再原地覆盖（备份只做一次）
    bak = None if dry else backup_once(md_dir)

    changed = 0
    total_dropped = 0
    before_hits: dict[str, int] = {}
    after_hits: dict[str, int] = {}

    for f in files:
        raw = f.read_text(encoding="utf-8", errors="ignore")
        for tok in CHECK_TOKENS:
            if tok in raw:
                before_hits[tok] = before_hits.get(tok, 0) + 1

        cleaned, dropped = clean_ocr_text(raw)
        total_dropped += dropped
        for tok in CHECK_TOKENS:
            if tok in cleaned:
                after_hits[tok] = after_hits.get(tok, 0) + 1

        if cleaned != raw:
            changed += 1
            if not dry:
                f.write_text(cleaned, encoding="utf-8")

    print(f"[处理] 目录 {md_dir}")
    print(f"[文件] 共 {len(files)} 个 md，发生变化的 {changed} 个"
          f"{'（dry-run，未写回）' if dry else ''}")
    print(f"[丢弃] 累计剔除噪声行 {total_dropped} 行")
    print("[残留噪声复检]  清洗前 -> 清洗后")
    for tok in CHECK_TOKENS:
        b, a = before_hits.get(tok, 0), after_hits.get(tok, 0)
        if b or a:
            flag = "  <-- 仍有残留" if a else ""
            print(f"    {tok:<10} {b:>4} -> {a:<4}{flag}")

    if not dry:
        print(f"[备份] 原始 md 已备份到 {bak}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
