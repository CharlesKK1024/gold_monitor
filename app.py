from flask import Flask, render_template, request, jsonify
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

app = Flask(__name__)

# 全局变量存储状态
monitor_data = {
    "gold_price": 0.0,
    "profit": 0.0,
    "last_update": "尚未开始",
    "is_running": False,
    "buy_price": 600.0,
    "buy_weight": 10.0,
    "interval": 30,
    "dingtalk_token": "",
    "push_all": False,  # 是否推送每一次更新
    "logs": []
}

# 监控线程
monitor_thread = None

def send_dingtalk(msg):
    """发送钉钉提醒"""
    token_or_url = monitor_data["dingtalk_token"]
    if not token_or_url:
        return
    
    # 如果用户输入的是完整的 URL，直接使用；否则拼接 Token
    if token_or_url.startswith("http"):
        url = token_or_url
    else:
        url = f"https://oapi.dingtalk.com/robot/send?access_token={token_or_url}"
    
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

@app.route('/test_dingtalk', methods=['POST'])
def test_dingtalk():
    global monitor_data
    data = request.json
    temp_token = data.get('dingtalk_token', '')
    if temp_token:
        # 临时保存用于测试
        old_token = monitor_data["dingtalk_token"]
        monitor_data["dingtalk_token"] = temp_token
        res = send_dingtalk("这是一条测试通知，看到此消息说明您的钉钉配置正确。")
        monitor_data["dingtalk_token"] = old_token
        return jsonify(res)
    return jsonify({"errcode": 400, "errmsg": "未提供 Token 或 URL"})

def get_gold_price(driver):
    url = 'https://m.jr.jd.com/finance-gold/msjgold/homepage?from=fhc&ip=66.249.71.78&orderSource=6&ptag=16337378.0.1'
    try:
        driver.get(url)
        time.sleep(3)
        html = driver.page_source
        soup = BeautifulSoup(html, 'html.parser')
        all_titles = soup.find_all('span', class_='gold-price-persent-title')
        for title in all_titles:
            if '实时金价' in title.get_text():
                match = re.search(r'(\d+\.\d+)', title.get_text())
                if match:
                    return float(match.group(1))
    except Exception as e:
        print(f"抓取错误: {e}")
    return None

def monitor_task():
    global monitor_data
    
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
                if price:
                    # 盈亏计算：(当前金价 - 买入金价) * 买入克数
                    profit = (price - monitor_data["buy_price"]) * monitor_data["buy_weight"]
                    now = datetime.datetime.now().strftime("%H:%M:%S")
                    
                    monitor_data["gold_price"] = price
                    monitor_data["profit"] = round(profit, 2)
                    monitor_data["last_update"] = now
                    
                    log_msg = f"[{now}] 实时金价: {price} 元/克, 盈亏: {monitor_data['profit']} 元"
                    print(log_msg)
                    monitor_data["logs"].insert(0, log_msg)
                    monitor_data["logs"] = monitor_data["logs"][:10]
                    
                    # 如果开启了全部推送，则每一次抓取都推送
                    if monitor_data["push_all"]:
                        send_dingtalk(log_msg)
                    
                    # 提醒逻辑
                    if profit >= 40:
                        msg = f"📈 盈利提醒: 当前金价 {price}, 盈亏 {monitor_data['profit']} 元"
                        monitor_data["logs"].insert(0, msg)
                        print(f"发送盈利提醒: {msg}")
                        send_dingtalk(msg)
                    elif profit <= -30:
                        msg = f"📉 止损提醒: 当前金价 {price}, 盈亏 {monitor_data['profit']} 元"
                        monitor_data["logs"].insert(0, msg)
                        print(f"发送止损提醒: {msg}")
                        send_dingtalk(msg)
                else:
                    msg = f"[{datetime.datetime.now().strftime('%H:%M:%S')}] 未能获取到金价"
                    print(msg)
                    monitor_data["logs"].insert(0, msg)
            except Exception as e:
                err_msg = f"抓取异常: {str(e)}"
                print(err_msg)
                monitor_data["logs"].insert(0, err_msg)
            
            # 等待设定的时间
            wait_time = int(monitor_data["interval"])
            for _ in range(wait_time):
                if not monitor_data["is_running"]:
                    break
                time.sleep(1)
                
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
        monitor_data["interval"] = int(data.get('interval', 30))
        monitor_data["dingtalk_token"] = data.get('dingtalk_token', '')
        monitor_data["push_all"] = bool(data.get('push_all', False))
        monitor_data["is_running"] = True
        monitor_data["logs"] = ["正在启动监控..."]
        
        monitor_thread = threading.Thread(target=monitor_task)
        monitor_thread.daemon = True
        monitor_thread.start()
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

if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=8123)
