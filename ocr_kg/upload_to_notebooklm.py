# -*- coding: utf-8 -*-
"""把批次 Markdown 上传到 nano-NotebookLM，触发知识点抽取 + 知识图谱构建。

接口链路（上游 README / api/server.py）：
    POST /api/upload/{course_id}   multipart 上传 -> 立刻返回 {task_id}
    GET  /api/upload/status/{task_id}  轮询后台管线（切片->嵌入->KG_A->KG_B）
    POST /api/mindmap/{course_id}  取/生成知识图谱（mindmap 树）

运行（在仓库根目录执行）：
    & ocr_kg\\nano-NotebookLM\\.venv\\Scripts\\python.exe ocr_kg\\upload_to_notebooklm.py <md目录> [课程ID]
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

import requests

# ===================== 配置区 =====================
BASE_URL = "http://127.0.0.1:8000"
COURSE_ID = "考试宝错题"
POLL_INTERVAL = 10          # 轮询间隔（秒）
TIMEOUT = 30                # 单次请求超时（秒）
# 建图提示语：抽取知识点 + 建关联，不诱导模型编造答案/解析
KG_PROMPT = (
    "本文档包含若干考试错题，绝大多数只有题干和选项；少数题带 App 标注的「正确答案：X」，"
    "那是题库给出的真实答案，可用来判断该题究竟在考什么，但不要为没有标注的题推测答案，也不要编造解析。"
    "请抽取每道题考查的知识点，并建立知识点之间的关联（前置/对比/同属/应用场景）。"
    "知识点粒度控制在“学科概念”级别（如“Transformer 自注意力机制”“DeepSpeed ZeRO 显存优化”"
    "“RoCEv2 拥塞控制”“混合精度训练 BF16/FP16”），"
    "避免抽取过细的公式符号或过粗的章节标题。"
)
# ================================================


def upload(course_id: str, files: list[Path]) -> str:
    """上传所有批次文件，返回 task_id。"""
    handles = []
    try:
        for f in files:
            handles.append(open(f, "rb"))
        payload = [("files", (f.name, h, "text/markdown")) for f, h in zip(files, handles)]
        resp = requests.post(
            f"{BASE_URL}/api/upload/{course_id}",
            files=payload,
            params={"engine": "pymupdf", "lang": "ch"},
            timeout=TIMEOUT,
        )
        if resp.status_code >= 400:
            print(f"[错误] 上传失败 HTTP {resp.status_code}: {resp.text[:300]}")
            sys.exit(1)
        return resp.json()["task_id"]
    finally:
        for h in handles:
            h.close()


def wait_task(task_id: str) -> bool:
    """轮询后台管线直到完成，返回是否成功。

    上游状态接口返回的是 stages 字典（extracting/chunking/embedding/
    kg_stage_a/kg_stage_b 各自带 progress），不是单个 stage/percent 字段，
    这里按真实结构打印进度。
    """
    while True:
        resp = requests.get(f"{BASE_URL}/api/upload/status/{task_id}", timeout=TIMEOUT)
        if resp.status_code >= 400:
            print(f"[错误] 查询状态失败 HTTP {resp.status_code}")
            return False
        state = resp.json()
        status = state.get("status", "")
        stages = state.get("stages") or {}
        if stages:
            parts = []
            for name, info in stages.items():
                info = info or {}
                detail = info.get("detail")
                text = f"{name}={info.get('progress', 0)}%"
                if detail:
                    text += f"({detail})"
                parts.append(text)
            print(f"    [{status}] " + "  ".join(parts))
        else:
            print(f"    [{status}]")
        if status in ("done", "completed", "success"):
            result = state.get("result") or {}
            if result:
                print(f"[结果] 文件 {result.get('files')} 个，切片 {result.get('chunks')} 块，"
                      f"知识图谱节点 {result.get('kg_nodes')} 个，"
                      f"耗时 {result.get('duration_ms', 0) / 1000:.1f}s")
            return True
        if status in ("error", "failed"):
            print(f"[失败] {state.get('error')}（阶段：{state.get('error_stage')}）")
            return False
        time.sleep(POLL_INTERVAL)


def show_mindmap(course_id: str) -> None:
    """取知识图谱，打印节点/边数量。"""
    resp = requests.post(f"{BASE_URL}/api/mindmap/{course_id}", json={"query": KG_PROMPT},
                         timeout=300)
    if resp.status_code >= 400:
        print(f"[提示] 取知识图谱失败 HTTP {resp.status_code}: {resp.text[:200]}")
        return
    data = resp.json()
    nodes = data.get("nodes") or data.get("tree") or []
    print(f"[图谱] 根节点数：{len(nodes)}")
    if isinstance(nodes, list):
        for n in nodes[:12]:
            label = n.get("label") or n.get("name") or n.get("id")
            children = n.get("children") or []
            print(f"    - {label}" + (f"（{len(children)} 个子节点）" if children else ""))


def main() -> int:
    src = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(
        r"D:\hcip\learning_project\ocr_kg\ocr_batches\run01_175p")
    course_id = sys.argv[2] if len(sys.argv) > 2 else COURSE_ID

    files = sorted([p for p in src.glob("*.md") if p.is_file()])
    if not files:
        print(f"[错误] 没有找到 .md 文件：{src}")
        return 1

    print(f"[课程] {course_id}")
    print(f"[上传] {len(files)} 个批次文件 -> {BASE_URL}")
    task_id = upload(course_id, files)
    print(f"[任务] task_id={task_id}，开始轮询…")

    ok = wait_task(task_id)
    if not ok:
        return 1

    print("[建图] 拉取知识图谱…")
    show_mindmap(course_id)
    return 0


if __name__ == "__main__":
    sys.exit(main())
