# 考试宝错题知识图谱：纯 CPU 部署手册（工作区适配版）

> 原方案：《DeepSeek-OCR 2 + nano-NotebookLM（纯 CPU 路径）》。
> 本文件是**结合本工作区实测环境**改写后的落地版本：原教程的每一步都在本机跑过，
> 差异点集中在「虚拟环境」「网络镜像」「LLM 后端」「OCR 参数」四处。

---

## 0. 本机基线（实测，非估算）

| 项 | 实测值 | 对方案的影响 |
|---|---|---|
| CPU | i5-12450H，8 核 12 线程，**无 AVX-512** | 无 bf16 硬件加速；fp16 靠软件模拟，速度以实测为准 |
| 内存 | 15.7 GB（提交上限 35.7 GB） | OCR 权重 fp16 常驻约 6.3 GB；**若再跑本地 7B LLM 会很吃紧** |
| 磁盘 | D 盘剩余 154.8 GB | 权重 + 依赖约 10 GB，放 D 盘充裕 |
| GPU | 无（`nvidia-smi` 不存在） | 纯 CPU 路径是唯一选择 |
| Python | uv 托管 CPython **3.12.13**（与项目 `.venv` 同基座） | 与工作区版本完全对齐，无需另下解释器 |
| 工具链 | uv 0.11.2、git 2.47.1；**无 conda、无 docker、无 ollama** | 教程的 conda 步骤替换为 uv |
| 网络 | `github.com` 直连被重置；`huggingface.co` 超时；`hf-mirror.com` / `pypi.org` / `download.pytorch.org` 正常 | clone 与权重下载必须走镜像 |

## 1. 与原教程的关键差异（务必按本文件执行）

| # | 原教程 | 本工作区做法 | 原因 |
|---|---|---|---|
| 1 | `conda create -n deepseek-ocr2 python=3.12.9` | `uv venv --python 3.12.13`（每个工具独立 venv） | 本机无 conda；工作区统一用 uv + 3.12.13 |
| 2 | OCR 与 nano-NotebookLM 各装一套 | **两个独立 venv**，均不复用项目 `.venv` | 项目 `.venv` 锁着 airtest + numpy 1.26.4，混入 torch/transformers 有破坏风险 |
| 3 | `git clone https://github.com/...` | `git clone https://ghfast.top/https://github.com/...` | 直连 github.com 被中间设备重置 |
| 4 | 模型从 huggingface.co 拉 | `HF_ENDPOINT=https://hf-mirror.com` + 自研分片下载器 | 直连 HF 超时；6.5GB 单流下载实测频繁断流 |
| 5 | `pip install -r requirements.txt`（torch 默认轮子） | 追加 `--index-url https://download.pytorch.org/whl/cpu` | 装纯 CPU 轮子，避免 CUDA 依赖与磁盘膨胀 |
| 6 | Ollama + 本地 Qwen2.5 7B | **改用外部大模型 API**（`OPENAI_BASE_URL`/`OPENAI_MODEL`/`OPENAI_API_KEY`） | 用户明确不用 Ollama；省掉约 5GB 内存占用与本地推理延迟 |
| 7 | `LOCAL_LLM_BASE_URL` 指向 Ollama | 同上，改用 `OPENAI_*` 三件套 | `LOCAL_LLM_*` 是「本地 OpenAI 兼容服务」专用，外部 API 走 `OPENAI_*` |
| 8 | `uv venv && source .venv/bin/activate` | `uv venv`（Python 3.12.13）+ 直接用绝对路径调 `python.exe` | Windows 无 `source`；工作区约定用绝对路径调解释器 |
| 9 | 装 `.[mineru]` 可选 | **不装** | OCR 已由 DeepSeek-OCR 独立完成，nano-NotebookLM 只吃 Markdown，省 3–5GB |
| 10 | `MINERU_DEVICE_MODE=cpu` | 不设置 | mineru 未安装，该变量无意义 |
| 11 | 提示词 `<\|grounding\|>Convert the document to markdown.` | 改用 `Free OCR.` + **关闭 crop_mode** | 实测 250s/页 → **35–66s/页**，输出还是结构化 Markdown（见第 6 节） |
| 12 | `from_pretrained` 默认参数 | 显式 `torch_dtype=float16` + `low_cpu_mem_usage=True` | 默认按 float32 载入，3.2B 参数要 12.6GB，撑爆提交额度（OSError 1455） |

## 2. 目录结构

```
D:\hcip\learning_project\
├─ .venv/                          # 项目原有 venv（airtest，本方案不碰）
├─ pic\handle_987172\run01_175p\   # 考试宝截图 175 张
└─ ocr_kg/                         # 本方案新增（本地部署区）
   ├─ .gitignore                   # 屏蔽两个 clone 目录与产物
   ├─ DEPLOY_OCR_KG.md             # ← 本文件
   ├─ download_model.py            # 分片并行 + 断点续传的模型下载器
   ├─ batch_ocr.py                 # 整目录批量 OCR → Markdown（含界面噪声清洗）
   ├─ clean_ocr_out.py             # 对已生成的 md 二次清洗（清洗规则升级后补跑用）
   ├─ bench_ocr.py                 # 提示词 / crop_mode 四组对照基准（换机器可复测）
   ├─ build_md_batches.py          # 逐页 md → 批次 md（每 20 页一份）
   ├─ upload_to_notebooklm.py      # 上传批次 → 触发抽取 + 建图
   ├─ models\Universal-DeepSeek-OCR-2\   # OCR 权重（6.3GB）
   ├─ ocr_out\run01_175p\         # 逐页 OCR 结果
   │  ├─ page_N.md                # 每页一个 Markdown
   │  ├─ _skip\page_175.md        # 非题目页（统计页），隔离不入库
   │  └─ ..\run01_175p_preclean_backup\   # 二次清洗前的原始 md 备份
   ├─ ocr_batches\run01_175p\     # 批次 Markdown（9 个）
   ├─ Universal-DeepSeek-OCR-2\    # 上游 clone（不入库）
   │  └─ .venv\                    # OCR 依赖（torch 2.6.0+cpu）
   └─ nano-NotebookLM\             # 上游 clone（不入库）
      ├─ .env                      # 后端配置（含 API Key，不入库）
      └─ .venv\                    # NLM 依赖（torch 2.15.0+cpu）
```

## 3. 部署步骤（已在本机执行）

### 3.1 克隆两个仓库（走镜像）

```powershell
git -c http.sslBackend=openssl clone --depth 1 https://ghfast.top/https://github.com/Dogacel/Universal-DeepSeek-OCR-2.git ocr_kg\Universal-DeepSeek-OCR-2
git -c http.sslBackend=openssl clone --depth 1 https://ghfast.top/https://github.com/ArthurYangX/nano-NotebookLM.git ocr_kg\nano-NotebookLM
# 仓库级固定 openssl 后端（沿用工作区约定）
git -C ocr_kg\Universal-DeepSeek-OCR-2 config http.sslBackend openssl
git -C ocr_kg\nano-NotebookLM config http.sslBackend openssl
```

### 3.2 建虚拟环境（uv + 3.12.13，不动项目 .venv）

```powershell
# OCR 侧
cd ocr_kg\Universal-DeepSeek-OCR-2
uv venv --python 3.12.13
uv pip install --python .venv\Scripts\python.exe `
  --index-url https://download.pytorch.org/whl/cpu `
  --extra-index-url https://pypi.org/simple `
  -r requirements.txt
uv pip install --python .venv\Scripts\python.exe accelerate   # 低内存加载路径

# nano-NotebookLM 侧
cd ..\nano-NotebookLM
uv venv --python 3.12.13
uv pip install --python .venv\Scripts\python.exe `
  --index-url https://download.pytorch.org/whl/cpu `
  --extra-index-url https://pypi.org/simple `
  -e ".[test]"
```

装完的版本（实测）：OCR 侧 `torch 2.6.0+cpu / transformers 4.46.3 / accelerate 1.16.0`；
NLM 侧 `torch 2.15.0+cpu / transformers 5.23.0 / sentence-transformers 6.3.0 / faiss-cpu 1.16.0`。
两个 venv 各约 1.1–1.3 GB。

> 提示：`uv pip install` 后面接 `| Select-Object -Last N` 会提前掐断管道，
> 令 uv 以退出码 1 收场（但其实已装完）。别加管道，或改用 `-q`。

### 3.3 下载 OCR 权重（6.3GB，分片续传）

```powershell
& ocr_kg\Universal-DeepSeek-OCR-2\.venv\Scripts\python.exe -u ocr_kg\download_model.py
```

自研下载器的原因：镜像的 HEAD 返回的 `Content-Length` 不可信（README.md 探到 20，
实际 11342），且 6.5GB 单流传输实测传 8MB 就断一次。下载器改为
`Range 探针定长 → 32MB 分片 × 8 并行 → 每片独立重试 → 分片落盘续传 → 最后合并`，
实测聚合速度 4–9MB/s，6.31GB 用时 52.7 分钟。

### 3.4 配置 LLM 后端（**外部 API，不用 Ollama**）

编辑 `ocr_kg/nano-NotebookLM\.env`：

```ini
OPENAI_API_KEY=sk-REPLACE_WITH_YOUR_ASCII_API_KEY
OPENAI_BASE_URL=https://api.minimax.cn/v1           # 或任意 OpenAI 兼容网关
OPENAI_MODEL=MiniMax-M3.1-Flash
DEFAULT_BACKEND=openai

# 本工作区不装 Ollama，这组留空
LOCAL_LLM_BASE_URL=
LOCAL_LLM_MODEL=

EMBEDDING_MODE=local
HF_ENDPOINT=https://hf-mirror.com                # MiniLM 首次下载走镜像
```

要点：

- **API Key 必须是纯 ASCII**。填含中文的占位串时，httpx 构造 `Authorization` 请求头会抛
  `UnicodeEncodeError: 'ascii' codec can't encode characters in position 10-15`，
  上游 `except` 把它吞成一行 warning，看起来像网络挂了，其实只是 Key 的锅。
  本机实测：用纯 ASCII 的假 Key 能收到 DeepSeek 的 401，说明**外部 API 网络完全可达**。
- `.env` 只是**首启引导**。服务起来后 `artifacts/providers.json` 成为运行时真源，
  之后改供应商请用 UI 的 Settings 面板（或删掉 `providers.json` 重启以重新引导）。
- 换供应商只改 `OPENAI_BASE_URL` / `OPENAI_MODEL` / `OPENAI_API_KEY` 三行；
  任何暴露 `/v1/chat/completions` 的服务都能直接用，无需改代码。
- 嵌入模型默认本地 MiniLM（470MB，多语种含中文）；首次使用时自动下载，
  靠 `HF_ENDPOINT` 走镜像。也可切 `openai_large`（text-embedding-3-large）或 `bge_m3`。

> **本机最终生效的配置**：MiniMax provider 是通过 **Settings 面板**加进去的，
> 所以它落在 `artifacts/providers.json`（provider id `1`，`default_backend_id: "1"`，
> key 以 `literal:` 形式内联），而不是 `.env`。
> 已把 `.env` 的引导配置同步成 MiniMax，这样即使删掉 `providers.json` 重启，
> 首启引导也会落到同一个可用供应商上。
>
> 排查该 provider：`Invoke-RestMethod -Method Post http://127.0.0.1:8000/api/providers/1/test`
> 注意这个探测接口**超时只有 5 秒**，MiniMax 首次调用有冷启动，容易误报 TimeoutError，
> 重试一次即可（本机首测超时、重试 883ms 成功）。

### 3.5 启动服务

```powershell
$env:HF_ENDPOINT='https://hf-mirror.com'
cd ocr_kg\nano-NotebookLM
& .venv\Scripts\python.exe api\server.py       # http://127.0.0.1:8000
```

## 4. 端到端用法

```powershell
# ① 批量 OCR：截图 -> 逐页 Markdown（可断点续跑）
& ocr_kg\Universal-DeepSeek-OCR-2\.venv\Scripts\python.exe -u ocr_kg\batch_ocr.py `
  pic\handle_987172\run01_175p ocr_kg\ocr_out\run01_175p
#   先试 3 页：末尾加 --limit 3

# ①-b 二次清洗（清洗规则升级后补跑；幂等，可重复执行）
& .venv\Scripts\python.exe ocr_kg\clean_ocr_out.py ocr_kg\ocr_out\run01_175p
#   先看效果不加写入：末尾加 --dry-run

# ② 合并成批次（每 20 页一份，约 20 道题）
& ocr_kg\nano-NotebookLM\.venv\Scripts\python.exe ocr_kg\build_md_batches.py `
  ocr_kg\ocr_out\run01_175p ocr_kg\ocr_batches\run01_175p

# ③ 上传 + 触发知识点抽取与建图
& ocr_kg\nano-NotebookLM\.venv\Scripts\python.exe ocr_kg\upload_to_notebooklm.py `
  ocr_kg\ocr_batches\run01_175p "考试宝错题"
```

上传接口链路：`POST /api/upload/{course_id}` → 返回 `task_id` →
轮询 `GET /api/upload/status/{task_id}`（切片→嵌入→KG_A→KG_B）→
`POST /api/mindmap/{course_id}` 取知识图谱。

OCR 侧的配置集中在 `batch_ocr.py` 顶部常量区：
`PROMPT` / `BASE_SIZE` / `IMAGE_SIZE` / `CROP_MODE` / `TEST_COMPRESS` / `DTYPE` /
`BATCH_DIR` / `OUTPUT_DIR`，以及噪声清洗用的 `UI_NOISE_PATTERNS`（整行噪声）/
`INLINE_NOISE_TOKENS`（行内按钮文案）/ `DROP_SECTIONS`（整段丢弃的章节）。

## 5. 验证清单（实测结果）

| 步骤 | 验证方式 | 实测结果 |
|---|---|---|
| 1 | `GET /api/health` | `{"ok":true,"version":"0.2.0"}` ✅ |
| 2 | `GET /api/status` | `available_backends:["openai-main"]`，base_url/model 已按 `.env` 引导 ✅ |
| 3 | 服务启动日志 | `EMBEDDING_MODE=local: loading paraphrase-multilingual-MiniLM-L12-v2`，走 hf-mirror 下载 ✅ |
| 4 | mineru | 未安装，日志提示 `mineru-api CLI missing`，自动跳过 ✅（符合预期） |
| 5 | OCR 权重 | 6.31GB / 203 分片，实测 4–9MB/s，完整落盘 ✅ |
| 6 | OCR 冒烟（5 张错题截图） | 5/5 成功，题干选项齐全，公式裁剪图保留 ✅ |
| 7 | OCR 真实批次（3 页） | 题干 + 选项完整，界面噪声被清洗 ✅ |
| 8 | 上传链路（冒烟） | 上传 1 份 md → 切片 3 块 → FAISS 3/3 命中 → BM25 建好 → `upload.done` ✅ |
| 9 | 外部 API 可达 | 用纯 ASCII 假 Key 直连 api.deepseek.com，返回 401（说明网络/协议都对，只差真 Key）✅ |
| 10 | 知识图谱节点 | **已验证**：MiniMax 后端下 9 个批次 → 123 切片 → **160 个图谱节点 / 259 条边**，耗时 192.6s ✅ |
| 11 | **全量 175 页 OCR** | 175/175 成功，0 失败，总耗时 292.4 分钟 ✅ |
| 12 | 界面噪声清洗 | 行级 + 行内 + 章节级三级清洗后，`提交答案`/`全选`/`AI 深度` 等残留 **全部归零** ✅ |
| 13 | 批次合成 | 174 道题 → 9 个批次 md（每 20 页一份，共 53.6KB）✅ |
| 14 | 检索问答（graphrag） | 提问「分布式训练和显存优化考了哪些知识点」→ `path=graphrag`，模型 `MiniMax-M3.1-Flash`，21.1s 给出带引用的答案 ✅ |

> 冒烟测试留下的课程数据在 `ocr_kg/nano-NotebookLM/artifacts/courses/冒烟测试/`，
> 可用 `Invoke-RestMethod http://127.0.0.1:8000/api/courses` 查看。

### 5.1 本批次 OCR 结果统计（175 页实测）

| 项 | 数值 |
|---|---|
| 截图页数 | 175（`pic\handle_987172\run01_175p`） |
| OCR 成功 / 失败 | **175 / 0** |
| 总耗时 | 292.4 分钟（单页异常 6915s，剔除后均值 61.1s/页） |
| 题干完整率 | 174/174（`page_175` 是「我的错题成绩」统计页，非题目，已隔离到 `_skip/`） |
| 题型分布 | 多选 51 · 其他 48 · 判断 26 · 填空 26 · 单选 23 |
| 带「正确答案」标注 | 3 页（App 只在已作答题目上展示答案） |
| 批次合成 | 9 个文件（8×20 页 + 1×14 页），共 53.6KB |

### 5.2 知识图谱构建结果（实测）

| 项 | 数值 |
|---|---|
| LLM 后端 | MiniMax `https://api.minimax.cn/v1` + `MiniMax-M3.1-Flash` |
| 上传文件 / 切片 | 9 个 md → **123 个切片**（FAISS + BM25 双索引） |
| 图谱节点 | **160 个** = 9 个批次根节点 + 36 个主题 + 113 个叶子概念 |
| 图谱边 | **259 条** = `part-of` 204 + `example-of` 27 + `depends-on` 19 + `related` 9 |
| 建图耗时 | 192.6s（Stage A 主题 → Stage B 叶子概念，两阶段） |
| 典型主题 | 大模型训练体系 / ZeRO-R内存优化 / CANN异构计算架构 / 混合精度训练 / 自注意力机制 / KV Cache推理阶段 / MindFormers使用方式 / 集合通信模式 |
| 检索问答 | `path=graphrag`（走的是图谱检索，不是纯向量 RAG），带来源引用 |

图谱文件：`ocr_kg/nano-NotebookLM/artifacts/courses/考试宝错题/knowledge_graph.json`（3.8MB）。

## 6. 性能实测（本机 i5-12450H，纯 CPU）

### 6.1 OCR 提示词 / crop_mode 四组对照

同一张图（`pic/mistake/page_5.png`），模型只加载一次：

| 配置 | 提示词 | crop_mode | 耗时 | 输出 |
|---|---|---|---|---|
| A | `<\|grounding\|>Convert the document to markdown.` | True | 约 250s | 纯文本 + LaTeX 公式，界面文案夹杂在正文行之间 |
| B | `Convert the document to markdown.` | True | **344s** | 纯文本，**公式丢失** |
| C | `Convert the document to markdown.` | False | **66s** | 结构化 Markdown（`### 题目` / `#### 单选` / 选项列表） |
| D | `Free OCR.` | False | **41s** | 同上，最快 |

结论：**`crop_mode=False` 是最大提速点（3.8 倍）**。crop 模式会对局部再切一遍图过视觉编码器，
纯 CPU 下这个代价极高；关闭后模型把整页一次性转成结构化 Markdown，对知识点抽取反而更友好
（题干、选项边界清晰）。最终采用配置 **D**。

实测批量速度（真实考试题截图）：**25–115s/页**，取决于该页文字量。
175 页全量实测：总耗时 **292.4 分钟**，其中 page_137 单页异常卡了 **6915s（1.9 小时）**，
剔除该异常页后均值 **61.1s/页**（填空题页只有 1–2 行文字，约 25s；长题干页约 90–115s）。
教程给的「10–15 秒/张」是 GPU 口径，本机不要按那个估算。

> page_137 那 6915 秒不是模型问题（该页本身只有两行文字），疑似系统休眠/电源策略降频。
> 批量作业是**断点续跑**的，中断后重跑同一条命令即可，已生成的页会跳过。

复测方法（换机器后建议重跑一次）：

```powershell
& ocr_kg\Universal-DeepSeek-OCR-2\.venv\Scripts\python.exe -u ocr_kg\bench_ocr.py
```

它会加载一次模型，依次跑 A/B/C/D 四组配置，打印各自耗时与输出样例。

### 6.2 其他环节

| 环节 | 实测 |
|---|---|
| OCR 权重下载 | 4–9MB/s（8 线程分片），6.31GB 用时 52.7 分钟（含多次断流重试） |
| 模型加载 | 约 40–60s（从磁盘读 6.3GB 并按 fp16 载入） |
| MiniLM 嵌入 | 本机 CPU，首批约 1–2 秒/百块 |
| 切片 + 建索引 | 3 块文本约 3 秒（不含 LLM 调用） |
| 知识图谱抽取 | 由外部 API 决定，与本机无关 |

### 6.3 内存要点

- fp16 权重常驻 **6.3GB**，这是本机纯 CPU 跑该模型的**下限**。
- float32 需要 12.6GB；而且生成速度反而更慢——fp16 的访存量只有一半。
  这颗 CPU 无 AVX-512，fp16 是软件模拟，但访存瓶颈下仍比 fp32 省时间。
- 跑 OCR 前先关掉 nano-NotebookLM 服务，能多腾约 1GB 提交额度。
- 页面文件本机已是 20GB（`D:\pagefile.sys`），不是瓶颈；真正的瓶颈是
  `from_pretrained` 默认按 float32 载入（见第 1 节第 12 行）。

## 7. 踩坑记录（本次实际踩到的）

| 现象 | 根因 | 处理 |
|---|---|---|
| `git clone` 报 `Recv failure: Connection was reset` | 本机直连 github.com 被中间设备重置 | 走 `ghfast.top` 前缀镜像 + `-c http.sslBackend=openssl` |
| HF 权重传到 8MB 就断 | 镜像单流大文件不稳 | 自研分片下载器：Range 探针定长 + 32MB×8 并行 + 每片独立重试 + 落盘续传 |
| 镜像 HEAD 的 `Content-Length` 不可信 | 小文件 HEAD 返回 20（实际 11342） | 一律用 `Range: bytes=0-0` 读 `Content-Range` 定长 |
| `OSError 1455 页面文件太小` | `from_pretrained` 默认 float32，3.2B 参数要 12.6GB > 可用提交 10.1GB | 显式 `torch_dtype=float16` + `low_cpu_mem_usage=True`，并装 `accelerate` |
| KG 抽取报 `'ascii' codec can't encode characters` | API Key 里的中文进了 `Authorization` 请求头，httpx 按 ASCII 编码 | Key 必须纯 ASCII；占位符也用 ASCII |
| 上游 `infer` 找不到 `.md` | 它写的是 `result.mmd` | 批量脚本按 `.mmd` 找 |
| 公式图片丢失 | 删临时目录时把 `images/` 一起删了 | 每页保留 `<页码>_images/`，并改写链接 |
| OCR 把「立即开通/分享/0/902」当正文 | 截图含 App 界面 | 三级清洗：行级白名单 + 行内按钮文案剔除 + 章节级丢弃 |
| 按钮文案粘在正文行尾（`全选 提交答案`） | 它不独占一行，行级白名单抓不到 | 新增 `INLINE_NOISE_TOKENS` 行内剔除；剔空或只剩选项字母则整行丢弃 |
| 清洗规则升级后旧 md 不干净 | 旧页是旧规则洗的，OCR 又很贵不能重跑 | `clean_ocr_out.py` 幂等二次清洗（先备份再覆盖），不用重跑 OCR |
| `AI 深度` 被误当成噪声误删题目 | 「深度学习」是本批次的常见词 | 噪声标签改成**整行锚定**匹配 `^ai\s*深度$`，不再用「包含即命中」 |
| 某一页耗时 6915s（1.9 小时） | 疑似系统休眠/电源降频，非模型问题 | 批量断点续跑，重跑同命令即可；速度统计看均值而非单页 |
| `uv pip install ... | Select-Object -Last N` 退出码 1 | 管道提前关闭导致 uv 收到断管 | 别加管道，或用 `-q`；实际已装完 |
| 手册里的 `1MB` 写法在 f-string 里报错 | `1MB` 不是合法字面量 | 用常量 `MB = 1024**2` |

## 8. 已知限制

1. **无本地 LLM**：本方案不含本地大模型，知识点抽取质量完全取决于你选的外部 API 模型。
   小模型（如 3B）抽出的知识点粒度会明显变粗。
2. **错题自演化不可用**：没有「哪题做错」的标记信号，nano-NotebookLM 的 exam-prep
   闭环跑不起来。方案价值集中在「知识点抽取 + 知识图谱 + 可编辑修正」。
3. **题干极短难定位**：「下列说法正确的是」这类题干只能靠选项补充信号，建图后建议人工补标注。
4. **fp16 on CPU 是软件模拟**：这台 CPU 无 AVX-512/AMX，fp16 运算会先转 fp32；
   换 float32 内存翻倍到约 13GB，本机 15.7GB 装不下 OCR + 其他服务，**不推荐**。
5. **nano-NotebookLM 首次启动会下载 MiniLM**（470MB），需保证 `HF_ENDPOINT` 已设置，
   否则直连 huggingface.co 会卡住。
6. **仓库 `.env` 含 Key**：`ocr_kg/nano-NotebookLM/` 已在 `ocr_kg/.gitignore` 中屏蔽，不会入库。
7. **界面噪声只能「清洗」不能「根除」**：截图里的 App 元素五花八门，
   当前规则是保守白名单 + 结构规则（三级：行级 / 行内 / 章节级），
   遇到没见过的噪声需往 `batch_ocr.py` 的
   `UI_NOISE_PATTERNS` / `INLINE_NOISE_TOKENS` / `DROP_SECTIONS` 里补，
   补完用 `clean_ocr_out.py` 二次清洗，**不必重跑 OCR**。
8. **公式处理**：无 crop 模式下公式可能以 LaTeX 形式出现，也可能整体丢失；
   知识点抽取层面影响有限，但若某科大量涉及公式，可对重点页面单开 crop 模式重跑。
9. **非题目页需人工隔离**：本批次最后一页是「我的错题成绩」统计页，不是题目，
   已移到 `ocr_out/run01_175p/_skip/page_175.md`，不入库建图。
   以后每批 OCR 后建议先扫一眼有没有这类页面。

## 9. 全链路已验证

第 10 项（上传 → 建图 → 出现知识点节点）**已用 MiniMax 后端跑通**：
9 个批次 → 123 切片 → 160 个图谱节点 / 259 条边，耗时 192.6s，
检索问答走 `path=graphrag` 并给出带来源引用的答案。详见第 5.2 节。

接下来可以直接用 UI：http://127.0.0.1:8000 ，切到「考试宝错题」课程，
打开 **Mindmap** 就能看到并手动编辑图谱；**Assistant** 里可以提问。

## 10. 常用命令速查

```powershell
# 启动 NLM 服务
cd D:\hcip\learning_project\ocr_kg\nano-NotebookLM
$env:HF_ENDPOINT='https://hf-mirror.com'
& .venv\Scripts\python.exe api\server.py

# 健康检查 / 状态 / provider 连通性
Invoke-RestMethod http://127.0.0.1:8000/api/health
Invoke-RestMethod http://127.0.0.1:8000/api/status
Invoke-RestMethod -Method Post http://127.0.0.1:8000/api/providers/openai-main/test

# 查看已建课程
Invoke-RestMethod http://127.0.0.1:8000/api/courses

# 断点续跑 OCR（已存在的页会跳过）
& ocr_kg\Universal-DeepSeek-OCR-2\.venv\Scripts\python.exe -u ocr_kg\batch_ocr.py `
  pic\handle_987172\run01_175p ocr_kg\ocr_out\run01_175p

# 二次清洗（清洗规则改了就跑一遍，不用重跑 OCR）
& .venv\Scripts\python.exe ocr_kg\clean_ocr_out.py ocr_kg\ocr_out\run01_175p
& .venv\Scripts\python.exe ocr_kg\clean_ocr_out.py ocr_kg\ocr_out\run01_175p --dry-run

# 合成批次 + 上传建图
& ocr_kg\nano-NotebookLM\.venv\Scripts\python.exe ocr_kg\build_md_batches.py `
  ocr_kg\ocr_out\run01_175p ocr_kg\ocr_batches\run01_175p
& ocr_kg\nano-NotebookLM\.venv\Scripts\python.exe ocr_kg\upload_to_notebooklm.py `
  ocr_kg\ocr_batches\run01_175p "考试宝错题"
```
