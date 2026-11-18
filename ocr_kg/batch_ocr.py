# -*- coding: utf-8 -*-
"""考试宝错题截图 -> Markdown（DeepSeek-OCR 2 Universal，纯 CPU 批量版）

上游仓库（Dogacel/Universal-DeepSeek-OCR-2）只给了单张示例 sample_cpu.py，
本脚本按本工作区约定改写为「整目录批量 + 断点续跑 + 中文日志」。

运行方式（在仓库根目录执行）：
    & ocr_kg\\Universal-DeepSeek-OCR-2\\.venv\\Scripts\\python.exe ocr_kg\\batch_ocr.py
    & ocr_kg\\Universal-DeepSeek-OCR-2\\.venv\\Scripts\\python.exe ocr_kg\\batch_ocr.py <截图目录> <输出目录>

要点：
- 模型权重走 HuggingFace 镜像：本机直连 huggingface.co 会超时，HF_ENDPOINT 必须指向 hf-mirror。
- 纯 CPU 推理，fp16 权重常驻约 6.5GB；i5-12450H 无 AVX-512，float32 会更慢且内存翻倍。
- 已生成同名 .md 的截图会被跳过，中断后重跑即可续跑。
"""

from __future__ import annotations

import os
import re
import shutil
import sys
import time
from pathlib import Path

# ===================== 配置区（集中调参）=====================
# HuggingFace 镜像：本机直连 huggingface.co 超时，必须走镜像
HF_ENDPOINT = "https://hf-mirror.com"
# 本地权重目录（由 ocr_kg\download_model.py 下载）；不存在时回退到仓库 ID 走镜像
MODEL_DIR = Path(r"D:\hcip\learning_project\ocr_kg\models\Universal-DeepSeek-OCR-2")
MODEL_NAME = "Dogacel/Universal-DeepSeek-OCR-2"
# 官方推荐提示词：转 Markdown 并带 grounding
# 实测（i5-12450H 纯 CPU）：grounding + crop_mode=True 约 250s/页且输出带定位标记；
# 关闭 crop_mode 后快 4~6 倍，且输出是结构化 Markdown，故采用下面这组。
PROMPT = "<image>\nFree OCR. "
BASE_SIZE = 1024
IMAGE_SIZE = 768
CROP_MODE = False
TEST_COMPRESS = True
# 纯 CPU 下的精度档位：fp16 最省内存；float32 约占 13GB，本机 15.7GB 内存吃紧
DTYPE = "float16"
# 默认批次：考试宝 175 页批次
BATCH_DIR = Path(r"D:\hcip\learning_project\pic\handle_987172\run01_175p")
# Markdown 输出目录
OUTPUT_DIR = Path(r"D:\hcip\learning_project\ocr_kg\ocr_out\run01_175p")
# 参与 OCR 的图片后缀
IMAGE_SUFFIXES = (".png", ".jpg", ".jpeg", ".bmp", ".webp")
# App 界面的固定文案：OCR 会把它们当成正文抽出来，污染知识点抽取。
# 每条都是「整行匹配」，先剥掉 Markdown 的标题/列表符号再做匹配，避免误删题干。
UI_NOISE_PATTERNS = (
    r"腾讯workbuddy",
    r"workbuddy",
    r"注册免费领积分",
    r"答题\s*背题\s*语音",
    r"开通会员.*",
    r"立即开通",
    r"精编题库",
    r"易错题",
    r"精背题",
    r"精简题",
    r"分享",
    r"收藏",
    r"已做题",
    r"^ai\s*深度$",             # 「AI 深度」标签（必须整行匹配：题目里常有「深度学习」）
    r"^a1\s*深度$",             # 同上，OCR 偶尔把 AI 认成 A1
    r"^请输入答案\.{0,3}$",     # 填空题的输入框占位符
    r"^请填写答案\.{0,3}$",
    r"^输入[:：]?$",
    r"^移除$",                  # 「取消收藏」按钮
    r"^标签$",                  # 题干下方的标签 chip
    r"^科普$",                  # 同上的「科普」chip
    r"^答对[:：]\s*\d+$",       # 答题统计计数器
    r"^答错[:：]\s*\d+$",
    r"^\d+$",                   # 纯数字行（0/175 之类的计数器）
    r"注册",
    r"登录",
    r"\d+\s*/\s*\d+",          # 页码计数器 2/902、0/902
)
# 行内界面按钮文案：不会独占一行，而是粘在题干/选项行尾（如「全选 提交答案」）。
# 这些词要从行内剔除；剔完若整行只剩标点或一个孤零零的选项字母，则整行丢弃。
INLINE_NOISE_TOKENS = (
    r"\[?\s*提交答案\s*\]?",
    r"\[?\s*一起纠错\s*\]?",
    r"\[?\s*全选\s*\]?",
    r"\[?\s*下一题\s*\]?",
    r"\[?\s*上一题\s*\]?",
    r"\[?\s*查看原图\s*\]?",
    r"\[?\s*收起\s*\]?",
)
# 行首复选框，如「- [ ]」「- [x]」
CHECKBOX_RE = re.compile(r"^\s*[-*+]?\s*\[[\s xX✓√]?\]\s*")
# 剔完只剩一个选项字母（如「- B 提交答案」→「B」），正文已丢失，整行丢弃
DANGLING_OPTION_RE = re.compile(r"^[A-Da-d]$")
# 判定一行是否还剩下有效内容（中文/字母/数字）
HAS_CONTENT_RE = re.compile(r"[0-9A-Za-z\u4e00-\u9fff]")
# 题型标记要保留（对 LLM 判断题型有用），单独列出避免被上面的规则误删
KEEP_PATTERNS = (r"单选", r"多选", r"判断", r"填空", r"简答", r"作文", r"完形填空")
# 整段丢弃的界面章节（标题文字）
DROP_SECTIONS = ("按钮", "分页", "图例", "导航", "底部栏", "顶部栏", "工具栏",
                 "练习情况", "练习量", "错题成绩")
# 这些标题只丢标题本身，内容保留
STRIP_HEADING_ONLY = ("图片中的文字", "图中文字", "答案框")
# 行内选项（- A. xxx / - A: xxx），用来判断「选项」章节是否重复
INLINE_OPTION_RE = re.compile(r"^[-*+]?\s*[A-Da-d][\.、:：）)]\s*\S")
# ============================================================


def _strip_markup(line: str) -> str:
    """剥掉 Markdown 的标题/列表/强调符号，只留正文。"""
    text = line.strip()
    text = re.sub(r"^[#>\-\*\+]+\s*", "", text)
    text = re.sub(r"[*_`]+", "", text)
    text = text.replace("\\", "")
    return re.sub(r"\s+", " ", text).strip()


def _drop_section(head: str, body: list[str], has_inline_options: bool) -> bool:
    """判断某个 Markdown 章节是否整段丢弃。"""
    norm = _strip_markup(head).lower()
    if any(k in norm for k in DROP_SECTIONS):
        return True
    if norm.startswith("选项") and has_inline_options:
        # 正文里已有行内选项（A. / A: / A、），这一段是重复块，丢掉
        return True
    return False


def _strip_inline_ui_tokens(line: str) -> str:
    """剔除行内的界面按钮文案（「全选 提交答案」这类粘在正文行尾的噪声）。"""
    text = CHECKBOX_RE.sub("", line)
    for pat in INLINE_NOISE_TOKENS:
        text = re.sub(pat, " ", text)
    return text


def clean_ocr_text(text: str) -> tuple[str, int]:
    """剔除 App 界面噪声，返回 (清洗后文本, 删除行数)。

    三级处理：
    1) 行级——白名单整行匹配（先剥 Markdown 标记），题型标记显式保留；
    2) 行内——剔除粘在正文行尾的按钮文案，剔空则整行丢弃；
    3) 章节级——按 Markdown 标题分块，丢弃「按钮/分页/图例」等界面章节、
       与行内选项重复的「选项」章节，以及清洗后已空的章节。
    """
    lines = text.splitlines()

    # ── 1) 行级过滤 ──
    kept_lines: list[str] = []
    dropped = 0
    for raw in lines:
        norm = _strip_markup(raw)
        if not norm:
            kept_lines.append(raw)
            continue
        is_keep = any(re.search(p, norm, re.IGNORECASE) for p in KEEP_PATTERNS)
        if not is_keep and any(re.search(p, norm, re.IGNORECASE) for p in UI_NOISE_PATTERNS):
            dropped += 1
            continue

        # ── 2) 行内界面文案剔除 ──
        cleaned = _strip_inline_ui_tokens(raw)
        norm2 = _strip_markup(cleaned)
        if not norm2 or not HAS_CONTENT_RE.search(norm2):
            dropped += 1
            continue
        if DANGLING_OPTION_RE.match(norm2):
            # 只剩一个选项字母，说明这行原本是按钮行，正文没识别出来
            dropped += 1
            continue
        kept_lines.append(cleaned)

    has_inline_options = any(INLINE_OPTION_RE.match(l.strip()) for l in kept_lines)

    # ── 3) 章节级过滤 ──
    out: list[str] = []
    head: str | None = None
    body: list[str] = []

    def flush() -> None:
        nonlocal head, body, dropped
        if head is None:
            return
        if _drop_section(head, body, has_inline_options) or not any(x.strip() for x in body):
            dropped += len([x for x in body if x.strip()])
        else:
            out.append(head)
            out.extend(body)
        head, body = None, []

    for line in kept_lines:
        if re.match(r"^\s*#{1,6}\s+", line):
            flush()
            head = line
            # 标题本身若命中「只保留内容」的规则，则不输出标题
            norm = _strip_markup(head).lower()
            if any(k in norm for k in STRIP_HEADING_ONLY):
                head = None
            continue
        if head is None:
            out.append(line)
        else:
            body.append(line)
    flush()

    result = "\n".join(out)
    result = re.sub(r"(?:\n\s*---\s*){2,}", "\n\n", result)
    result = re.sub(r"\n{3,}", "\n\n", result).strip()
    return result, dropped


def collect_images(batch_dir: Path) -> list[Path]:
    """按文件名自然序收集截图（page_2 排在 page_10 前面）。"""
    files = [p for p in batch_dir.iterdir()
             if p.is_file() and p.suffix.lower() in IMAGE_SUFFIXES]
    return sorted(files, key=lambda p: [int(t) if t.isdigit() else t
                                        for t in p.stem.replace("-", "_").split("_")])


def load_model():
    """加载 tokenizer 与模型到 CPU。

    优先用本地权重目录（已下载好），避免每次去镜像校验；
    本地目录不存在时回退到 HuggingFace 仓库 ID（需 HF_ENDPOINT 指向镜像）。
    """
    import torch
    from transformers import AutoModel, AutoTokenizer

    # 12 逻辑核 / 8 物理核，按物理核数给 torch 线程，避免超线程抢资源
    torch.set_num_threads(max(1, (os.cpu_count() or 8) - 4))

    source = str(MODEL_DIR) if MODEL_DIR.is_dir() else MODEL_NAME
    dtype = getattr(torch, DTYPE)
    print(f"[模型] 加载 {source}（CPU / {DTYPE}）……")
    t0 = time.time()
    tokenizer = AutoTokenizer.from_pretrained(source, trust_remote_code=True)
    # 必须显式指定 torch_dtype：transformers 默认按 float32 载入，
    # 3.2B 参数就是 12.6GB，直接把本机提交额度撑爆（OSError 1455 页面文件太小）。
    # 指定 fp16 后峰值内存减半，低内存加载路径逐片灌入，不再先展开 fp32。
    model = AutoModel.from_pretrained(
        source,
        trust_remote_code=True,
        use_safetensors=True,
        torch_dtype=dtype,
        low_cpu_mem_usage=True,
    )
    model = model.eval().to("cpu").to(dtype)
    print(f"[模型] 就绪，耗时 {time.time() - t0:.1f}s")
    return tokenizer, model


def run_one(model, tokenizer, image_path: Path, out_dir: Path) -> Path | None:
    """对单张截图做 OCR，返回生成的 Markdown 路径（失败返回 None）。

    上游 infer 把 Markdown 写到 result.mmd，其中的公式是裁剪图片引用
    （![](images/0.jpg)），所以图片目录要跟着页码一起保留，并把链接改成
    <页码>_images/xxx.jpg，避免多页之间互相覆盖。
    """
    tmp_dir = out_dir / "_raw" / image_path.stem
    if tmp_dir.exists():
        shutil.rmtree(tmp_dir, ignore_errors=True)
    tmp_dir.mkdir(parents=True, exist_ok=True)

    res = model.infer(
        tokenizer,
        prompt=PROMPT,
        image_file=str(image_path),
        output_path=str(tmp_dir),
        base_size=BASE_SIZE,
        image_size=IMAGE_SIZE,
        crop_mode=CROP_MODE,
        save_results=True,
        test_compress=TEST_COMPRESS,
    )

    # 上游 infer 落盘的是 result.mmd（不是 .md）
    produced = sorted(tmp_dir.rglob("*.mmd")) or sorted(tmp_dir.rglob("*.md"))
    md_path = out_dir / f"{image_path.stem}.md"

    if produced:
        text = produced[0].read_text(encoding="utf-8", errors="ignore")
        text, dropped = clean_ocr_text(text)
        img_dir = produced[0].parent / "images"
        if img_dir.is_dir() and any(img_dir.iterdir()):
            keep = out_dir / f"{image_path.stem}_images"
            if keep.exists():
                shutil.rmtree(keep, ignore_errors=True)
            shutil.copytree(img_dir, keep)
            text = text.replace("![](images/", f"![]({keep.name}/")
        md_path.write_text(text, encoding="utf-8")
        if dropped:
            print(f"      （清洗掉 {dropped} 行界面噪声）")
    elif isinstance(res, str) and res.strip():
        text, dropped = clean_ocr_text(res)
        md_path.write_text(text, encoding="utf-8")
    else:
        shutil.rmtree(tmp_dir, ignore_errors=True)
        return None

    shutil.rmtree(tmp_dir, ignore_errors=True)
    return md_path


def main() -> int:
    os.environ.setdefault("HF_ENDPOINT", HF_ENDPOINT)

    batch_dir = Path(sys.argv[1]) if len(sys.argv) > 1 else BATCH_DIR
    out_dir = Path(sys.argv[2]) if len(sys.argv) > 2 else OUTPUT_DIR
    limit = 0
    if "--limit" in sys.argv:
        limit = int(sys.argv[sys.argv.index("--limit") + 1])
    out_dir.mkdir(parents=True, exist_ok=True)

    if not batch_dir.is_dir():
        print(f"[错误] 截图目录不存在：{batch_dir}")
        return 1

    images = collect_images(batch_dir)
    if limit:
        images = images[:limit]
    print(f"[输入] {batch_dir} 共 {len(images)} 张截图")
    print(f"[输出] {out_dir}")

    tokenizer, model = load_model()

    done = 0
    skipped = 0
    failed = 0
    t_start = time.time()
    for idx, img in enumerate(images, 1):
        md_path = out_dir / f"{img.stem}.md"
        if md_path.exists() and md_path.stat().st_size > 0:
            skipped += 1
            continue

        t0 = time.time()
        try:
            produced = run_one(model, tokenizer, img, out_dir)
        except Exception as exc:  # 单张失败不中断整批
            produced = None
            print(f"[失败] {img.name}: {exc}")
        dt = time.time() - t0

        if produced is None:
            failed += 1
            print(f"[{idx}/{len(images)}] {img.name} 失败，用时 {dt:.1f}s")
        else:
            done += 1
            total = time.time() - t_start
            avg = total / max(done + failed, 1)
            print(f"[{idx}/{len(images)}] {img.name} -> {produced.name}，"
                  f"用时 {dt:.1f}s，均值 {avg:.1f}s")

    print(f"[完成] 新生成 {done} 张，跳过 {skipped} 张，失败 {failed} 张，"
          f"总耗时 {(time.time() - t_start) / 60:.1f} 分钟")
    return 0


if __name__ == "__main__":
    sys.exit(main())
