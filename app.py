from flask import Flask, render_template, request, jsonify, send_from_directory
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from bs4 import BeautifulSoup
import time
import re
import datetime
import threading
import os
import requests
import json
import os
import sys

app = Flask(__name__)

# 全局变量存储状态
monitor_data = {
    "gold_price": 0.0,
    "profit": 0.0,
    "profit_with_fee": 0.0,
    "fee_amount": 0.0,
    "last_update": "尚未开始",
    "is_running": False,
    "buy_price": 600.0,
    "buy_weight": 10.0,
    "interval": 30,
    "push_all": False,  # 是否推送每一次更新
    "logs": []
}

# 固定的钉钉配置
DINGTALK_TOKEN = "bd2869ab474d047c4ef11bae1a7153580f542e716a7ae88da75a07fc1cfe3dd4"

# 数据文件路径
DATA_DIR = "data"
PRICE_DATA_FILE = os.path.join(DATA_DIR, "price_data.json")

# 手续费配置（百分比）
TRANSACTION_FEE_RATE = 0.004  # 0.4% 卖出手续费

# 确保数据目录存在
if not os.path.exists(DATA_DIR):
    os.makedirs(DATA_DIR)
    print(f"创建数据目录: {DATA_DIR}")
else:
    print(f"数据目录已存在: {DATA_DIR}")

# 监控线程
monitor_thread = None

def save_price_data(price, profit, timestamp, profit_with_fee=None, fee_amount=None):
    """保存价格数据到本地文件"""
    try:
        # 读取现有数据
        data = []
        if os.path.exists(PRICE_DATA_FILE):
            with open(PRICE_DATA_FILE, 'r', encoding='utf-8') as f:
                data = json.load(f)

        # 添加新数据
        new_entry = {
            "timestamp": timestamp,
            "price": price,
            "profit": profit,
            "profit_with_fee": profit_with_fee if profit_with_fee is not None else profit,
            "fee_amount": fee_amount if fee_amount is not None else 0,
            "datetime": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        }
        data.append(new_entry)

        # 只保留最近1000条记录
        if len(data) > 1000:
            data = data[-1000:]

        # 保存到文件
        with open(PRICE_DATA_FILE, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

        print(f"价格数据已保存: {new_entry}")
        sys.stdout.flush()  # 立即刷新输出
    except Exception as e:
        print(f"保存价格数据失败: {e}")
        sys.stdout.flush()

def send_dingtalk(msg):
    """发送钉钉提醒"""
    if not DINGTALK_TOKEN:
        return

    # 如果配置的是完整的 URL，直接使用；否则拼接 Token
    if DINGTALK_TOKEN.startswith("http"):
        url = DINGTALK_TOKEN
    else:
        url = f"https://oapi.dingtalk.com/robot/send?access_token={DINGTALK_TOKEN}"
    
    headers = {"Content-Type": "application/json"}
    payload = {
        "msgtype": "text",
        "text": {
            "content": f"【黄金监控提醒】\n{msg}"
        }
    }
    try:
        response = requests.post(url, headers=headers, data=json.dumps(payload), timeout=5)
        print(f"钉钉发送状态: {response.status_code}, 响应内容: {response.text}")
        return response.json()
    except Exception as e:
        print(f"钉钉发送失败: {e}")
        return {"errcode": -1, "errmsg": str(e)}


def get_gold_price(driver):
    url = 'https://m.jr.jd.com/finance-gold/msjgold/homepage?from=fhc&ip=66.249.71.78&orderSource=6&ptag=16337378.0.1'
    try:
        print(f"正在访问URL: {url}")
        driver.get(url)
        time.sleep(3)
        html = driver.page_source
        print(f"页面HTML长度: {len(html)}")

        if len(html) < 1000:
            print("警告: 页面HTML太短，可能加载失败")
            return None

        soup = BeautifulSoup(html, 'html.parser')
        all_titles = soup.find_all('span', class_='gold-price-persent-title')
        print(f"找到 {len(all_titles)} 个价格元素")

        for i, title in enumerate(all_titles):
            text = title.get_text()
            print(f"元素 {i}: {text}")
            if '实时金价' in text:
                match = re.search(r'(\d+\.\d+)', text)
                if match:
                    price = float(match.group(1))
                    print(f"成功提取金价: {price}")
                    return price

        print("未找到包含'实时金价'的元素")
        return None
    except Exception as e:
        print(f"抓取错误: {e}")
        import traceback
        traceback.print_exc()
    return None

def monitor_task():
    global monitor_data

    print("监控任务开始执行")
    sys.stdout.flush()

    chrome_options = Options()
    chrome_options.add_argument("--headless")
    chrome_options.add_argument("--disable-gpu")
    chrome_options.add_argument('--ignore-certificate-errors')
    chrome_options.add_argument('--ignore-ssl-errors')
    
    driver = None
    try:
        try:
            driver = webdriver.Chrome(options=chrome_options)
        except:
            from selenium.webdriver.chrome.service import Service
            from webdriver_manager.chrome import ChromeDriverManager
            driver = webdriver.Chrome(service=Service(ChromeDriverManager().install()), options=chrome_options)
        
        while monitor_data["is_running"]:
            try:
                print(f"[{datetime.datetime.now().strftime('%H:%M:%S')}] 开始抓取金价...")
                price = get_gold_price(driver)
                print(f"获取到的金价: {price}")
                # 直接减去0.8
                price = price - 0.85
                print(f"减去0.8后金价: {price}")
                if price:
                    print(f"[DEBUG] 原始价格: {price}, 四舍五入后: {round(price, 2)}, 三位精度: {round(price, 3)}")
                    # 盈亏计算：(当前金价 - 买入金价) * 买入克数
                    profit = (price - monitor_data["buy_price"]) * monitor_data["buy_weight"]

                    # 手续费计算（只有卖出手续费）
                    current_value = price * monitor_data["buy_weight"]  # 当前总价值

                    # 卖出手续费 = 卖出克数 * 实时金价 * 0.4%
                    sell_fee = current_value * TRANSACTION_FEE_RATE

                    # 扣除手续费后的实际盈利
                    profit_with_fee = profit - sell_fee

                    now = datetime.datetime.now().strftime("%H:%M:%S")

                    monitor_data["gold_price"] = price
                    monitor_data["profit"] = round(profit, 2)
                    monitor_data["profit_with_fee"] = round(profit_with_fee, 2)
                    monitor_data["fee_amount"] = round(sell_fee, 2)
                    monitor_data["last_update"] = now

                    # 保存价格数据到本地文件
                    save_price_data(price, monitor_data["profit"], now, monitor_data["profit_with_fee"], monitor_data["fee_amount"])
                    log_msg = (
                    f"🏦 金价: {price:.2f} 元/克\n"
                    f"💰 盈亏: {monitor_data['profit']} 元\n"
                    f"🕒 时间: {now}"
                     )    # log_msg = f"[{now}] 实时金价: {price} 元/克, 盈亏: {monitor_data['profit']} 元"
                    
                    print(f"准备更新日志: {log_msg}")
                    print(f"更新前日志数量: {len(monitor_data['logs'])}")
                    monitor_data["logs"].insert(0, log_msg)
                    print(f"更新后日志数量: {len(monitor_data['logs'])}")
                    print(f"当前日志内容: {monitor_data['logs']}")  
                    
                    # 提醒逻辑（使用扣除手续费后的实际盈利）
                    alert_sent = False
                    if profit_with_fee >= 40:
                        msg = f"📈 盈利提醒: 当前金价 {price:.3f}, 实际盈利 {monitor_data['profit_with_fee']} 元 (含手续费 {monitor_data['fee_amount']} 元)"
                        monitor_data["logs"].insert(0, msg)
                        print(f"发送盈利提醒: {msg}")
                        send_dingtalk(msg)
                        alert_sent = True
                        # 保持日志数量在合理范围
                        if len(monitor_data["logs"]) > 10:
                            monitor_data["logs"] = monitor_data["logs"][:10]
                    elif profit_with_fee <= -30:
                        msg = f"📉 止损提醒: 当前金价 {price:.3f}, 实际亏损 {abs(monitor_data['profit_with_fee'])} 元 (含手续费 {monitor_data['fee_amount']} 元)"
                        monitor_data["logs"].insert(0, msg)
                        print(f"发送止损提醒: {msg}")
                        send_dingtalk(msg)
                        alert_sent = True
                        # 保持日志数量在合理范围
                        if len(monitor_data["logs"]) > 10:
                            monitor_data["logs"] = monitor_data["logs"][:10]

                    # 如果开启了全部推送且没有发送特殊提醒，则推送常规更新
                    if monitor_data["push_all"] and not alert_sent:
                        send_dingtalk(log_msg)
                else:
                    msg = f"[{datetime.datetime.now().strftime('%H:%M:%S')}] 未能获取到金价"
                    print(msg)
                    monitor_data["logs"].insert(0, msg)
                    # 保持日志数量在合理范围
                    if len(monitor_data["logs"]) > 10:
                        monitor_data["logs"] = monitor_data["logs"][:10]
            except Exception as e:
                err_msg = f"抓取异常: {str(e)}"
                print(err_msg)
                monitor_data["logs"].insert(0, err_msg)
                # 保持日志数量在合理范围
                if len(monitor_data["logs"]) > 10:
                    monitor_data["logs"] = monitor_data["logs"][:10]
            
            # 等待设定的时间
            wait_time = int(monitor_data["interval"])
            print(f"等待 {wait_time} 秒后进行下一次抓取...")
            for i in range(wait_time):
                if not monitor_data["is_running"]:
                    print("监控已停止，退出等待循环")
                    break
                if i % 10 == 0:  # 每10秒打印一次
                    print(f"等待中... {i+1}/{wait_time} 秒")
                time.sleep(1)
            print("等待结束，准备下一次抓取")
                
    finally:
        if driver:
            driver.quit()

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/status')
def status():
    return jsonify(monitor_data)

@app.route('/start', methods=['POST'])
def start():
    global monitor_data, monitor_thread
    if not monitor_data["is_running"]:
        data = request.json
        monitor_data["buy_price"] = float(data.get('buy_price', 600.0))
        monitor_data["buy_weight"] = float(data.get('buy_weight', 10.0))
        monitor_data["interval"] = int(data.get('interval', 15))
        monitor_data["push_all"] = bool(data.get('push_all', False))
        monitor_data["is_running"] = True
        if not monitor_data["logs"]:
            monitor_data["logs"] = ["正在启动监控..."]
        else:
            monitor_data["logs"].insert(0, "正在启动监控...")
            monitor_data["logs"] = monitor_data["logs"][:10]
        
        monitor_thread = threading.Thread(target=monitor_task)
        monitor_thread.daemon = True
        monitor_thread.start()
        print("监控线程已启动")
        sys.stdout.flush()
        return jsonify({"status": "started"})
    return jsonify({"status": "already running"})

@app.route('/stop', methods=['POST'])
def stop():
    global monitor_data
    monitor_data["is_running"] = False
    monitor_data["logs"].insert(0, "监控已停止")
    return jsonify({"status": "stopped"})

@app.route('/update', methods=['POST'])
def update():
    global monitor_data
    data = request.json
    if 'interval' in data:
        monitor_data["interval"] = int(data['interval'])
        monitor_data["logs"].insert(0, f"监控频率已更新为 {monitor_data['interval']} 秒")
    return jsonify({"status": "updated"})

@app.route('/modules/<path:filename>')
def serve_modules(filename):
    return send_from_directory('modules', filename)

@app.route('/favicon.ico')
def favicon():
    return '', 204  # No Content

@app.route('/price_history')
def get_price_history():
    """获取历史价格数据"""
    try:
        if os.path.exists(PRICE_DATA_FILE):
            with open(PRICE_DATA_FILE, 'r', encoding='utf-8') as f:
                data = json.load(f)
            return jsonify(data)
        else:
            return jsonify([])
    except Exception as e:
        print(f"读取价格历史数据失败: {e}")
        return jsonify([])

if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=8889)
