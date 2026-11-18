# -*- coding: utf-8 -*-
"""把逐页 OCR 结果合并成「批次 Markdown」，供 nano-NotebookLM 建图。

原教程建议：不要把所有题塞进一个巨大文件，按知识点主题或错题批次分文件，
每个文件 20—50 道题。本脚本按「页数」折算：考试宝一页约 1 道题，
所以默认每 20 页合成一个批次文件。

运行（在仓库根目录执行）：
    & ocr_kg\\nano-NotebookLM\\.venv\\Scripts\\python.exe ocr_kg\\build_md_batches.py <逐页md目录> <输出目录>
    & ocr_kg\\nano-NotebookLM\\.venv\\Scripts\\python.exe ocr_kg\\build_md_batches.py <逐页md目录> <输出目录> --per-file 15
"""

from __future__ import annotations

import shutil
import sys
from pathlib import Path

# ===================== 配置区 =====================
# 每个批次文件包含的页数（考试宝一页约 1 道题 -> 20 页约 20 道题）
PAGES_PER_FILE = 20
# 批次文件之间加分隔线
SEPARATOR = "\n\n---\n\n"
# ===============================================


def page_key(path: Path) -> tuple:
    """按自然序排序（page_2 排在 page_10 前）。"""
    return [int(t) if t.isdigit() else t
            for t in path.stem.replace("-", "_").split("_")]


def main() -> int:
    src = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(
        r"D:\hcip\learning_project\ocr_kg\ocr_out\run01_175p")
    dst = Path(sys.argv[2]) if len(sys.argv) > 2 else Path(
        r"D:\hcip\learning_project\ocr_kg\ocr_batches\run01_175p")
    per_file = PAGES_PER_FILE
    if "--per-file" in sys.argv:
        per_file = int(sys.argv[sys.argv.index("--per-file") + 1])

    dst.mkdir(parents=True, exist_ok=True)
    pages = sorted([p for p in src.glob("*.md") if p.is_file()], key=page_key)
    if not pages:
        print(f"[错误] 没有找到 .md 文件：{src}")
        return 1

    print(f"[输入] {src} 共 {len(pages)} 页")
    print(f"[输出] {dst}，每文件 {per_file} 页")

    batch_no = 0
    for i in range(0, len(pages), per_file):
        chunk = pages[i:i + per_file]
        batch_no += 1
        out = dst / f"batch_{batch_no:03d}.md"
        blocks = []
        for p in chunk:
            text = p.read_text(encoding="utf-8").strip()
            if text:
                blocks.append(f"<!-- 来源截图：{p.stem} -->\n{text}")
            # 公式裁剪图目录一并复制，链接名保持 <页码>_images/xxx.jpg 不变
            img_dir = p.parent / f"{p.stem}_images"
            if img_dir.is_dir():
                target_img = dst / img_dir.name
                if target_img.exists():
                    shutil.rmtree(target_img, ignore_errors=True)
                shutil.copytree(img_dir, target_img)
        out.write_text(SEPARATOR.join(blocks) + "\n", encoding="utf-8")
        print(f"  [批次 {batch_no}] {out.name}：{len(chunk)} 页，"
              f"{out.stat().st_size / 1024:.1f}KB")

    print(f"[完成] 共 {batch_no} 个批次文件")
    return 0


if __name__ == "__main__":
    sys.exit(main())
