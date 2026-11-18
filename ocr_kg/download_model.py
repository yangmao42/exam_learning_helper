# -*- coding: utf-8 -*-
"""从 HuggingFace 镜像并行分片、断点续传下载模型权重。

为什么要自己写：
本机直连 huggingface.co 超时，只能走 hf-mirror.com；而 6.5GB 的单文件用
huggingface_hub 默认下载器容易中途断流（实测传 8MB 就断一次），
因此改成「分片 + 多线程 + 每片独立重试 + 落盘续传」，任何一片断了只重下那一片。

镜像的坑：HEAD 返回的 Content-Length 不可信（README.md 探到 20，实际 11342），
所以大小一律用 Range 探针（bytes=0-0）读 Content-Range 来定，并据此判断
服务端是否支持 Range。

运行（在仓库根目录执行）：
    & ocr_kg\\Universal-DeepSeek-OCR-2\\.venv\\Scripts\\python.exe -u ocr_kg\\download_model.py
    & ocr_kg\\Universal-DeepSeek-OCR-2\\.venv\\Scripts\\python.exe -u ocr_kg\\download_model.py <仓库ID> <输出目录>
"""

from __future__ import annotations

import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import requests

# ===================== 配置区 =====================
HF_ENDPOINT = "https://hf-mirror.com"
DEFAULT_REPO = "Dogacel/Universal-DeepSeek-OCR-2"
DEFAULT_OUT = Path(r"D:\hcip\learning_project\ocr_kg\models\Universal-DeepSeek-OCR-2")
CHUNK_SIZE = 32 * 1024 * 1024      # 每片 32MB
WORKERS = 8                        # 并行分片数
MAX_RETRY = 30                     # 单片最大重试次数
TIMEOUT = 60                       # 单次请求超时（秒）
MB = 1024 ** 2
GB = 1024 ** 3
# ===============================================


def list_files(repo: str) -> list[str]:
    """列出仓库全部文件（走镜像 API）。"""
    url = f"{HF_ENDPOINT}/api/models/{repo}"
    resp = requests.get(url, timeout=TIMEOUT)
    resp.raise_for_status()
    data = resp.json()
    files = [s["rfilename"] for s in data.get("siblings", [])]
    return sorted(f for f in files if not f.startswith("."))


def resolve_url(repo: str, filename: str) -> str:
    return f"{HF_ENDPOINT}/{repo}/resolve/main/{filename}"


def probe(url: str) -> tuple[int, bool]:
    """用 Range 探针确定 (文件总大小, 服务端是否支持 Range)。

    镜像的 HEAD 长度不可信，必须以 Content-Range 为准。
    """
    try:
        with requests.get(url, headers={"Range": "bytes=0-0"}, stream=True,
                          timeout=TIMEOUT, allow_redirects=True) as resp:
            honors = resp.status_code == 206
            total = 0
            content_range = resp.headers.get("Content-Range", "")
            if "/" in content_range:
                tail = content_range.rsplit("/", 1)[1].strip()
                if tail.isdigit():
                    total = int(tail)
            if not total:
                length = resp.headers.get("Content-Length", "")
                if length.isdigit():
                    total = int(length)
            return total, honors
    except Exception as exc:
        print(f"    [探针失败] {exc}")
        return 0, False


def stream_to_file(url: str, target: Path, total: int, start_at: int = 0) -> int:
    """整文件流式下载（可从 start_at 续传），返回最终字节数。"""
    have = target.stat().st_size if target.exists() else 0
    if total and have == total:
        return have
    if have > (total or 0):
        target.unlink()
        have = 0
    headers = {"Range": f"bytes={have}-"} if have else {}
    with requests.get(url, headers=headers, stream=True, timeout=TIMEOUT,
                      allow_redirects=True) as resp:
        resp.raise_for_status()
        mode = "ab" if have else "wb"
        with open(target, mode) as fh:
            for chunk in resp.iter_content(chunk_size=1024 * 1024):
                if chunk:
                    fh.write(chunk)
    return target.stat().st_size


def download_part(url: str, part_path: Path, start: int, end: int, total: int) -> int:
    """下载 [start, end] 区间到分片文件；已存在且大小正确则跳过。"""
    expect = end - start + 1
    if part_path.exists() and part_path.stat().st_size == expect:
        return expect

    for attempt in range(1, MAX_RETRY + 1):
        try:
            have = part_path.stat().st_size if part_path.exists() else 0
            if have > expect:
                part_path.unlink()
                have = 0
            if have == expect:
                return expect
            headers = {"Range": f"bytes={start + have}-{end}"}
            with requests.get(url, headers=headers, stream=True, timeout=TIMEOUT,
                              allow_redirects=True) as resp:
                if resp.status_code not in (200, 206):
                    raise RuntimeError(f"HTTP {resp.status_code}")
                if resp.status_code == 200:
                    # 服务端忽略 Range，直接给了整个文件：本地拼装无意义，改由整文件分支处理
                    raise RuntimeError("服务端忽略 Range")
                mode = "ab" if have else "wb"
                with open(part_path, mode) as fh:
                    for chunk in resp.iter_content(chunk_size=1024 * 1024):
                        if chunk:
                            fh.write(chunk)
            size = part_path.stat().st_size
            if size == expect:
                return size
            raise RuntimeError(f"分片大小不符 {size}/{expect}")
        except Exception as exc:
            wait = min(2 ** attempt, 60)
            print(f"    [重试 {attempt}/{MAX_RETRY}] {part_path.name}: {exc}；{wait}s 后再试",
                  flush=True)
            time.sleep(wait)
    raise RuntimeError(f"分片下载失败：{part_path}")


def download_file(repo: str, filename: str, out_dir: Path) -> None:
    url = resolve_url(repo, filename)
    target = out_dir / filename
    target.parent.mkdir(parents=True, exist_ok=True)

    total, honors = probe(url)
    if total and target.exists() and target.stat().st_size == total:
        print(f"  [已存在] {filename}（{total / MB:.1f}MB）", flush=True)
        return

    # ── 小文件 / 不支持 Range：整文件直下 ──
    if not honors or not total or total <= CHUNK_SIZE:
        for attempt in range(1, MAX_RETRY + 1):
            try:
                size = stream_to_file(url, target, total)
                if not total or size == total:
                    print(f"  [完成] {filename}（{size / MB:.1f}MB）", flush=True)
                    return
                raise RuntimeError(f"大小不符 {size}/{total}")
            except Exception as exc:
                wait = min(2 ** attempt, 60)
                print(f"  [重试 {attempt}/{MAX_RETRY}] {filename}: {exc}；{wait}s 后再试",
                      flush=True)
                time.sleep(wait)
        raise RuntimeError(f"文件下载失败：{filename}")

    # ── 大文件：分片并行 ──
    parts_dir = out_dir / "_parts" / filename.replace("/", "__")
    parts_dir.mkdir(parents=True, exist_ok=True)
    ranges = []
    idx = 0
    for off in range(0, total, CHUNK_SIZE):
        ranges.append((idx, off, min(off + CHUNK_SIZE, total) - 1))
        idx += 1

    print(f"  [分片] {filename}：{total / GB:.2f}GB / {len(ranges)} 片", flush=True)
    t0 = time.time()
    done_bytes = 0
    with ThreadPoolExecutor(max_workers=WORKERS) as pool:
        futs = {}
        for i, s, e in ranges:
            part_path = parts_dir / f"part_{i:04d}"
            futs[pool.submit(download_part, url, part_path, s, e, total)] = (i, e - s + 1)
        for fut in as_completed(futs):
            i, size = futs[fut]
            fut.result()
            done_bytes += size
            elapsed = max(time.time() - t0, 0.001)
            speed = done_bytes / MB / elapsed
            print(f"    片 {i} 完成 | {done_bytes / GB:.2f}/{total / GB:.2f}GB "
                  f"| {speed:.1f}MB/s", flush=True)

    with open(target, "wb") as out:
        for i, _, _ in ranges:
            with open(parts_dir / f"part_{i:04d}", "rb") as src:
                while True:
                    buf = src.read(8 * 1024 * 1024)
                    if not buf:
                        break
                    out.write(buf)
    assert target.stat().st_size == total, "合并后大小不符"
    for i, _, _ in ranges:
        (parts_dir / f"part_{i:04d}").unlink(missing_ok=True)
    parts_dir.rmdir()
    print(f"  [完成] {filename}（{total / GB:.2f}GB，用时 {(time.time() - t0) / 60:.1f} 分钟）",
          flush=True)


def main() -> int:
    os.environ.setdefault("HF_ENDPOINT", HF_ENDPOINT)
    repo = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_REPO
    out_dir = Path(sys.argv[2]) if len(sys.argv) > 2 else DEFAULT_OUT
    out_dir.mkdir(parents=True, exist_ok=True)

    print(f"[仓库] {repo}")
    print(f"[输出] {out_dir}")
    files = list_files(repo)
    print(f"[文件] 共 {len(files)} 个：{files}", flush=True)

    t0 = time.time()
    for f in files:
        download_file(repo, f, out_dir)
    print(f"[全部完成] 用时 {(time.time() - t0) / 60:.1f} 分钟 -> {out_dir}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
