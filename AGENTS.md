# AGENTS.md — 工作区背景说明

本文件只描述**工作区现状与环境约定**，用于跨会话对齐，不记录某一次具体任务的执行过程。

## 1. 工作区定位

Windows 桌面 UI 自动化学习/实验工作区，基于 **Airtest** 驱动 Windows 桌面应用（当前主攻目标：**微信里的小程序窗口**），典型动作是：连接窗口句柄 → 鼠标滑动翻页 → 等待动画稳定 → 逐页截图留档。

## 2. 目录结构

```
D:\hcip\learning_project\
├─ AGENTS.md              # 本文件
├─ .venv/                 # 项目虚拟环境（uv 创建，CPython 3.12.13）
├─ Airtest/               # Airtest 官方源码 git clone（v1.4.3, commit d729c63）
├─ pic/                   # 图片资产
│  ├─ mistake/            # 人工归置的截图
│  └─ handle_<句柄>/      # 按窗口句柄分组的抓取批次
│     ├─ run01_175p/      # 批次目录命名：runNN_<页数>p（同一句柄下多批次依次递增）
│     └─ run02_100p/
├─ test.txt               # 临时草稿/参考片段（纯文本，非可执行脚本）
└─ *.py                   # 根目录下的独立自动化脚本，每个脚本自成一体
```

- `Airtest/` 是 **editable 安装源**（`pip list` 显示 airtest 1.4.3 指向 `D:\hcip\learning_project\Airtest`），改这里的代码会直接影响所有脚本运行行为；它本质上是上游源码，**不要顺手改**，确需修改前先确认是否该改上游。
- 工作区根目录是 **git 仓库**（分支 `main`），远端为 `https://github.com/yangmao42/exam_learning_helper.git`；`Airtest/` 是独立的上游 clone，已被 `.gitignore` 排除，不随本仓库上传。
- `pic/` 下的图片由人工归置，脚本运行产物请按需放入对应子目录，不要散落在根目录。
- **截图入库策略**：脚本自动产出的批次目录 `pic/handle_*/` 已在 `.gitignore` 中，**新批次默认不入库**；仓库里已存在的历史批次（`run01_175p`、`run02_100p`）保持跟踪，不会被删掉。确实需要上传某个新批次时用 `git add -f pic/handle_<句柄>/runNN_<页数>p` 强制添加。

## 3. 运行环境

- Python：`D:\hcip\learning_project\.venv\Scripts\python.exe`（Python 3.12.13，uv 管理）
- 关键依赖：`airtest 1.4.3`（本地源码）、`pywinauto 0.6.3`、`mss 6.1.0`、`pywin32 312`、`numpy 1.26.4`、`opencv-contrib-python 4.6.0.66`、`pillow 13.0.0`
- 运行方式：`& .venv\Scripts\python.exe <脚本名>.py`（在仓库根目录执行）
- 未安装：`poco`（如需 UI 树定位，需另行安装）

## 4. 目标窗口与连接方式

- Airtest 的 Windows 设备 URI 形式为 `Windows:///<hwnd>`；`Windows:///` 连整块桌面；也支持 `Windows:///?title_re=...` 按标题匹配；加 `?foreground=False` 可不抢前台。
- 目标小程序窗口的**句柄每次重开都会变**，不可硬编码长期使用。最近一次实测：句柄 `987172`，窗口标题「考试宝」，物理尺寸 **860×1578**。
- 获取句柄的两种方式：AirtestIDE 的「Windows窗口连接」面板；或用 `EnumWindows` 枚举顶层窗口标题与句柄。
- `connect_device()` 默认会把目标窗口置前并抢焦点（鼠标手势依赖前台窗口），失败时 pywintypes 报错可忽略。

## 5. DPI 与坐标约定（易踩坑）

- 本机显示缩放为 **200%**。**未声明 DPI 感知的进程**（如 PowerShell 直接调 `GetWindowRect`）会拿到被虚拟化的尺寸（430×789），而 Airtest/pywinauto 拿到的是物理像素（860×1578）。**判断窗口大小一律用 Airtest 的 `dev.get_current_resolution()`**，不要用外部 `GetWindowRect` 交叉验证。
- `touch/swipe` 传入的坐标是**相对窗口左上角**的像素，Airtest 内部再换算成屏幕绝对坐标；传 `(0.5, 0.5)` 这类 ≤1 的值则按比例解释。
- 因此固定像素坐标容易越界或落点偏移，**优先按 `get_current_resolution()` 换算**。
- `snapshot(filename=...)` 传相对路径时写入 `ST.LOG_DIR`（未设置则为当前工作目录），传绝对路径最稳妥；截图区域是整个窗口（含边框）。
- 截图默认压缩质量 `ST.SNAPSHOT_QUALITY`（默认 10，即高质量），可用 `quality=` / `max_size=` 覆盖。

## 6. 如何验证一次自动化动作真的生效

不要只看脚本有没有报错。用**相邻两帧的像素差异**判定：

- 静置不动时，两次截图差异应接近 0；
- 执行一次滑动后，差异应显著（实测该小程序一次滑动约 3.6% 像素变化）。

```python
import numpy as np, time
a = dev.snapshot().astype(np.int16); time.sleep(1.5); b = dev.snapshot().astype(np.int16)
print(np.abs(a - b).mean(), (np.abs(a - b).sum(axis=2) > 12).mean())
```

## 7. 代码约定

- 脚本放根目录，单文件自包含，直接 `python 脚本.py` 运行，不引入 AirtestIDE 工程结构。
- 中文注释与中文 `print` 输出；配置项（句柄、页数、时长、坐标、输出目录）集中在文件顶部常量区，便于调参。
- 关键动作后**必须留等待**（Airtest 的 `sleep` 或 `time.sleep`）再截图，否则容易拍到动画中间帧。
- Windows 平台的“滑动”本质是 pywinauto 的鼠标按住拖拽，`duration` / `steps` 影响手势时长与平滑度；起点终点都要落在窗口内容区内，否则手势不会作用在小程序上。
