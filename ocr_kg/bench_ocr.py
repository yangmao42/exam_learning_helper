# -*- coding: utf-8 -*-
"""OCR 速度/质量基准：比较 prompt 与 crop_mode 组合在纯 CPU 下的耗时。

换机器 / 换模型后可复测，用于重新确定 batch_ocr.py 里的 PROMPT 与 CROP_MODE。
用法（仓库根目录）：
    & ocr_kg\\Universal-DeepSeek-OCR-2\\.venv\\Scripts\\python.exe -u ocr_kg\\bench_ocr.py
"""
import re
import sys
import time
from pathlib import Path

import torch
from transformers import AutoModel, AutoTokenizer

MODEL_DIR = r"D:\hcip\learning_project\ocr_kg\models\Universal-DeepSeek-OCR-2"
IMAGE = Path(r"D:\hcip\learning_project\pic\mistake\page_5.png")
OUT = Path(r"D:\hcip\learning_project\ocr_kg\bench_out")

CONFIGS = [
    ("A 原方案 grounding+crop", "<image>\n<|grounding|>Convert the document to markdown. ", True),
    ("B 无grounding+crop", "<image>\nConvert the document to markdown. ", True),
    ("C 无grounding+无crop", "<image>\nConvert the document to markdown. ", False),
    ("D FreeOCR+无crop", "<image>\nFree OCR. ", False),
]


def main() -> None:
    torch.set_num_threads(8)
    OUT.mkdir(parents=True, exist_ok=True)
    print("加载模型…", flush=True)
    t0 = time.time()
    tok = AutoTokenizer.from_pretrained(MODEL_DIR, trust_remote_code=True)
    model = AutoModel.from_pretrained(
        MODEL_DIR, trust_remote_code=True, use_safetensors=True,
        torch_dtype=torch.float16, low_cpu_mem_usage=True,
    ).eval().to("cpu")
    print(f"加载耗时 {time.time() - t0:.1f}s", flush=True)

    for name, prompt, crop in CONFIGS:
        d = OUT / re.sub(r"[^\w]", "_", name)
        d.mkdir(parents=True, exist_ok=True)
        t0 = time.time()
        try:
            model.infer(
                tok, prompt=prompt, image_file=str(IMAGE), output_path=str(d),
                base_size=1024, image_size=768, crop_mode=crop,
                save_results=True, test_compress=True,
            )
        except Exception as exc:
            print(f"{name}: 失败 {exc}", flush=True)
            continue
        dt = time.time() - t0
        md = d / "result.mmd"
        text = md.read_text(encoding="utf-8") if md.exists() else ""
        print(f"\n===== {name} | {dt:.1f}s | 输出 {len(text)} 字符 =====")
        print(text[:600].replace("\n", " ⏎ "))
        print(flush=True)


if __name__ == "__main__":
    sys.exit(main())
