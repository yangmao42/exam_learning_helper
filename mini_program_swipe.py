# -*- coding: utf-8 -*-
"""
微信小程序窗口：滑动翻页 + 逐页截图

功能与参考脚本一致：
    连接窗口句柄 -> 循环滑动翻页 -> 等待页面稳定 -> 截图保存
"""
import os

from airtest.core.api import *

# --- 配置参数 ---
WINDOW_HANDLE = 987172           # 微信小程序窗口句柄（可用 AirtestIDE 的“Windows窗口连接”获取）
PAGE_COUNT = 100                 # 总共需要翻多少页
SWIPE_DURATION = 0.2             # swipe 持续时间（秒）
WAIT_SECONDS = 0.5               # 每页等待页面稳定的时间（秒）
RUN_TAG = "run02_100p"           # 本批次目录名（同一句柄下多批次依次递增）
OUTPUT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                          "pic", "handle_%d" % WINDOW_HANDLE, RUN_TAG)   # 截图保存目录
os.makedirs(OUTPUT_DIR, exist_ok=True)

# --- 连接窗口 ---
# 方式一：直接连接微信小程序窗口的句柄 (推荐)
dev = connect_device("Windows:///%d" % WINDOW_HANDLE)

# 方式二：通过窗口标题连接（如果标题比较固定），备用不启用
# connect_device("Windows:///?title_re=.*小程序.*")

# 滑动坐标（相对小程序窗口内部，起点/终点按窗口实际尺寸换算，
# 避免固定坐标落到窗口外导致滑不动）
WIDTH, HEIGHT = dev.get_current_resolution()
START_X, START_Y = int(WIDTH * 0.85), int(HEIGHT * 0.55)   # 滑动的起点
END_X, END_Y = int(WIDTH * 0.15), int(HEIGHT * 0.55)         # 滑动的终点，从右向左滑以实现“向右翻页”

print("窗口尺寸: %dx%d, 滑动: (%d,%d) -> (%d,%d)" % (
    WIDTH, HEIGHT, START_X, START_Y, END_X, END_Y))

# --- 主循环 ---
for i in range(PAGE_COUNT):
    # 1. 执行滑动翻页
    swipe((START_X, START_Y), (END_X, END_Y), duration=SWIPE_DURATION)

    # 2. 等待页面稳定 (非常重要！)
    # 给页面加载和动画留出时间，否则截图可能是模糊或未加载完的
    sleep(WAIT_SECONDS)

    # 3. 截图并保存
    filename = os.path.join(OUTPUT_DIR, "page_%d.png" % (i + 1))
    snapshot(filename=filename)
    print("已截图第 %d 页 -> %s" % (i + 1, filename))

print("截图任务完成！")
