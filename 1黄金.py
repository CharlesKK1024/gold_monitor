from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from webdriver_manager.chrome import ChromeDriverManager
from bs4 import BeautifulSoup
import time
import re
import datetime
import sys
import os

# 配置 webdriver_manager 缓存目录为当前项目目录，避免权限问题
os.environ['WDM_LOCAL'] = '1'
os.environ['WDM_LOG_LEVEL'] = '0'

# === 用户输入 ===
# 优先从命令行参数读取，如果没有则提示用户输入
if len(sys.argv) > 2:
    x = float(sys.argv[1])
    buy_weight = float(sys.argv[2])
    print(f"使用命令行参数: 买入价={x}, 买入克数={buy_weight}")
else:
    try:
        x = float(input("请输入买入时金价（元/克）: "))
        buy_weight = float(input("请输入买入克数（克）: "))
    except (EOFError, ValueError):
        # 默认值
        x = 600.0
        buy_weight = 10.0
        print(f"使用默认值: 买入价={x}, 买入克数={buy_weight}")

# 计算买入金额 (仅用于日志显示对比)
y = x * buy_weight
print(f"对应买入金额: {y:.2f} 元")

# 设置无头浏览器
chrome_options = Options()
chrome_options.add_argument("--headless")
chrome_options.add_argument("--disable-gpu")
# 忽略证书错误
chrome_options.add_argument('--ignore-certificate-errors')
chrome_options.add_argument('--ignore-ssl-errors')

# 优先尝试使用 Selenium 内置的驱动管理（最简单，不需要联网下载）
try:
    driver = webdriver.Chrome(options=chrome_options)
except Exception:
    # 如果内置方式失败，再尝试备选方案
    from selenium.webdriver.chrome.service import Service
    from webdriver_manager.chrome import ChromeDriverManager
    driver = webdriver.Chrome(service=Service(ChromeDriverManager().install()), options=chrome_options)

# 目标页面
url = 'https://m.jr.jd.com/finance-gold/msjgold/homepage?from=fhc&ip=66.249.71.78&orderSource=6&ptag=16337378.0.1'

try:
    while True:
        driver.get(url)
        time.sleep(3)  # 等待JS渲染

        html = driver.page_source
        soup = BeautifulSoup(html, 'html.parser')

        # 提取实时金价
        all_titles = soup.find_all('span', class_='gold-price-persent-title')
        gold_price = None
        for title in all_titles:
            if '实时金价' in title.get_text():
                match = re.search(r'(\d+\.\d+)', title.get_text())
                if match:
                    gold_price = float(match.group(1))
                    break

        if gold_price:
            # 盈亏计算：(当前金价 - 买入金价) * 买入克数
            profit = (gold_price - x) * buy_weight

            # 当前时间
            now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")

            print(f"{now} 实时金价: {gold_price} 元/克，当前盈亏: {profit:.2f} 元")

            # 提醒逻辑（仅打印）
            if profit >= 40:
                msg = f"{now}\n📈 恭喜！可以卖了，赚了40元以上！\n当前盈亏: {profit:.2f} 元"
                print(msg)
            elif profit <= -30:
                msg = f"{now}\n📉 注意！已经亏了30元以上！\n当前盈亏: {profit:.2f} 元"
                print(msg)

        else:
            print("未找到实时金价")

        # 每30秒检测一次
        time.sleep(30)

except KeyboardInterrupt:
    print("已停止监控")

finally:
    driver.quit()
