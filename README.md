# exam_learning_helper

基于 [Airtest](https://github.com/AirtestProject/Airtest) 的 Windows 桌面自动化小工具：连接微信小程序窗口句柄，循环滑动翻页并逐页截图留档，用于考试/学习类小程序的内容采集与离线复习。

## 目录结构

```
.
├─ AGENTS.md                  # 工作区背景与环境约定（含踩坑记录）
├─ mini_program_swipe.py      # 主脚本：连接窗口 -> 滑动翻页 -> 截图
├─ requirements.txt           # Python 依赖
├─ test.txt                   # 早期参考片段
└─ pic/                       # 截图产物
   ├─ mistake/                # 人工归置的截图
   └─ handle_<窗口句柄>/      # 按句柄分组的抓取批次
      ├─ run01_175p/          # 批次目录：runNN_<页数>p
      └─ run02_100p/
```

## 环境准备

```powershell
# 1) 创建虚拟环境（推荐 uv）
uv venv --python 3.12 .venv
# 或：python -m venv .venv

# 2) 安装依赖
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

## 使用

编辑 [mini_program_swipe.py](mini_program_swipe.py) 顶部配置区：

```python
WINDOW_HANDLE = 987172           # 小程序窗口句柄（每次重开都会变）
PAGE_COUNT = 100                 # 翻页次数
SWIPE_DURATION = 0.2             # swipe 持续时间（秒）
WAIT_SECONDS = 0.5               # 每页等待页面稳定的时间（秒）
RUN_TAG = "run02_100p"           # 本批次目录名
```

运行：

```powershell
.\.venv\Scripts\python.exe mini_program_swipe.py
```

截图自动写入 `pic/handle_<窗口句柄>/<RUN_TAG>/`，命名为 `page_1.png ... page_N.png`。

## 获取窗口句柄

两种方式：

1. AirtestIDE → 「Windows窗口连接」面板，直接读取句柄号；
2. 用 `EnumWindows` 枚举顶层窗口标题与句柄，例如本项目目标小程序窗口标题为「考试宝」。

## 常见问题

- **窗口尺寸判断**：本机显示缩放 200%，未声明 DPI 感知的进程（如 PowerShell 的 `GetWindowRect`）会拿到被虚拟化的尺寸；请统一用 Airtest 的 `dev.get_current_resolution()`。
- **滑动不生效**：滑动坐标是**窗口相对像素**，起点终点必须落在窗口内容区内，脚本已按窗口尺寸比例换算。
- **截图糊/半张图**：关键动作后要留等待（`WAIT_SECONDS`），否则容易拍到动画中间帧。
- **验证动作是否真的生效**：比较相邻两帧的像素差异——静置时应接近 0，滑动后应显著变化。

## 许可证

MIT
