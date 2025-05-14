# -*- coding: utf-8 -*-

"""
Web服务模块，提供RESTful API接口与前端交互
"""
import os
import time
import json
import threading
from datetime import datetime
from flask import Flask, request, jsonify, send_from_directory, make_response, Response, stream_with_context
from flask_cors import CORS
import pandas as pd

import config
from logger import get_logger
from data_manager import get_data_manager
from indicator_calculator import get_indicator_calculator
from position_manager import get_position_manager
from trading_executor import get_trading_executor
from strategy import get_trading_strategy
import utils


# 获取logger
logger = get_logger("web_server")
webpage_dir = 'web1.0'

# 创建Flask应用
app = Flask(__name__, static_folder=webpage_dir, static_url_path='')

# 允许跨域请求
CORS(app)

# 获取各个模块的实例
data_manager = get_data_manager()
indicator_calculator = get_indicator_calculator()
position_manager = get_position_manager()
trading_executor = get_trading_executor()
trading_strategy = get_trading_strategy()

# 实时推送的数据
realtime_data = {
    'positions': {},
    'latest_prices': {},
    'trading_signals': {},
    'account_info': {},
    'positions_all': []  # Add new field for all positions data
}

# 实时推送线程
push_thread = None
stop_push_flag = False

@app.route('/')
def index():
    """Serve the index.html file"""
    return send_from_directory(os.path.join(os.path.dirname(__file__), webpage_dir), 'index.html')

@app.route('/<path:filename>')
def serve_static(filename):
    """Serve static files from the 'web' directory"""
    return send_from_directory(os.path.join(os.path.dirname(__file__), webpage_dir), filename)

@app.route('/api/connection/status', methods=['GET'])
def connection_status():
    """返回API连接状态"""
    try:
        # 检查 qmt_trader 的连接状态
        is_connected = False
        if hasattr(position_manager, 'qmt_trader') and position_manager.qmt_trader:
            if hasattr(position_manager.qmt_trader, 'xt_trader') and position_manager.qmt_trader.xt_trader:
                if hasattr(position_manager.qmt_trader.xt_trader, 'is_connected'):
                    is_connected = position_manager.qmt_trader.xt_trader.is_connected()
                else:
                    # 尝试其他检查方式
                    is_connected = True  # 假设已连接，实际应根据具体情况修改
        
        return jsonify({
            'status': 'success',
            'connected': bool(is_connected),  # 确保返回布尔值
            'timestamp': datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        })
    except Exception as e:
        logger.error(f"检查API连接状态时出错: {str(e)}")
        return jsonify({
            'status': 'error',
            'connected': False,
            'message': f"检查API连接状态时出错: {str(e)}",
            'timestamp': datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        })

@app.route('/api/status', methods=['GET'])
def get_status():
    """获取系统状态"""
    try:
        # 从 position_manager 获取账户信息
        account_info = position_manager.get_account_info() or {}
        
        # 如果没有账户信息，使用默认值
        if not account_info:
            account_info = {
                'account_id': '--',
                'account_type': '--',
                'available': 0.0,
                'frozen_cash': 0.0,
                'market_value': 0.0,
                'total_asset': 0.0,
                'timestamp': datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            }
            
        # 格式化为前端期望的结构
        account_data = {
            'id': account_info.get('account_id', '--'),
            'availableBalance': account_info.get('available', 0.0),
            'maxHoldingValue': account_info.get('market_value', 0.0),
            'totalAssets': account_info.get('total_asset', 0.0),
            'timestamp': account_info.get('timestamp', datetime.now().strftime('%Y-%m-%d %H:%M:%S'))
        }
        
        # 判断监控状态
        strategy_monitoring = (
            trading_strategy.strategy_thread is not None and 
            trading_strategy.strategy_thread.is_alive()
        )
        position_monitoring = (
            position_manager.monitor_thread is not None and
            position_manager.monitor_thread.is_alive()
        )
        is_monitoring = strategy_monitoring or position_monitoring

        return jsonify({
            'status': 'success',
            'isMonitoring': is_monitoring,
            'account': account_data,
            'timestamp': datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        })
    except Exception as e:
        logger.error(f"获取系统状态时出错: {str(e)}")
        return jsonify({
            'status': 'error',
            'message': f"获取系统状态时出错: {str(e)}"
        }), 500

@app.route('/api/positions', methods=['GET'])
def get_positions():
    """获取持仓信息"""
    try:
        positions = trading_executor.get_stock_positions()
        positions_df = pd.DataFrame(positions)
        
        # 计算持仓指标
        metrics = utils.calculate_position_metrics(positions_df)
        
        # 更新实时数据
        for pos in positions:
            stock_code = pos['stock_code']
            realtime_data['positions'][stock_code] = pos
        
        # 获取所有持仓数据
        positions_all_df = position_manager.get_all_positions_with_all_fields()
        realtime_data['positions_all'] = positions_all_df.to_dict('records')
        
        response = make_response(jsonify({
            'status': 'success',
            'data': {
                'positions': positions,
                'metrics': metrics,
                'positions_all': realtime_data['positions_all']
            }
        }))
        response.headers['Content-Type'] = 'application/json; charset=utf-8'
        return response
    except Exception as e:
        logger.error(f"获取持仓信息时出错: {str(e)}")
        return jsonify({
            'status': 'error',
            'message': f"获取持仓信息时出错: {str(e)}"
        }), 500

@app.route('/api/trade-records', methods=['GET'])
def get_trade_records():
    """获取交易记录"""
    try:
        # 从交易执行器获取交易记录
        trades_df = trading_executor.get_trades()
        
        # 如果没有交易记录，返回空列表
        if trades_df.empty:
            return jsonify({'status': 'success', 'data': []})
        
        # Format 'trade_time' to 'YYYY-MM-DD'
        if 'trade_time' in trades_df.columns:
            trades_df['trade_time'] = pd.to_datetime(trades_df['trade_time']).dt.strftime('%Y-%m-%d')
        
        # Replace NaN with None (which will become null in JSON)
        trades_df = trades_df.replace({pd.NA: None, float('nan'): None})
        
        # 将 DataFrame 转换为 JSON 格式
        trade_records = trades_df.to_dict(orient='records')
        
        response = make_response(jsonify({

            'status': 'success',
            'data': trade_records
        }))        
        response.headers['Content-Type'] = 'application/json; charset=utf-8'
        return response
    except Exception as e:
        logger.error(f"获取交易记录时出错: {str(e)}")
        return jsonify({'status': 'error', 'message': f"获取交易记录时出错: {str(e)}"}), 500

# 添加SSE接口
@app.route('/api/sse', methods=['GET'])
def sse():
    """提供Server-Sent Events流"""
    def event_stream():
        prev_data = None
        while True:
            try:
                # 获取最新数据
                account_info = position_manager.get_account_info() or {}
                current_data = {
                    'timestamp': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                    'holdings_count': len(realtime_data['positions_all']),
                    'account_info': {
                        'available': account_info.get('available', 0),
                        'market_value': account_info.get('market_value', 0),
                        'total_asset': account_info.get('total_asset', 0)
                    }
                }
                
                # 只在数据变化时发送更新
                if current_data != prev_data:
                    yield f"data: {json.dumps(current_data)}\n\n"
                    prev_data = current_data
            except Exception as e:
                logger.error(f"SSE流生成数据时出错: {str(e)}")
                yield f"data: {json.dumps({'error': str(e)})}\n\n"
            
            time.sleep(2)  # 每2秒检查一次
    
    return Response(stream_with_context(event_stream()), 
                   mimetype="text/event-stream",
                   headers={"Cache-Control": "no-cache",
                            "X-Accel-Buffering": "no"})

# 修改get_positions_all函数，添加数据版本号
@app.route('/api/positions-all', methods=['GET'])
def get_positions_all():
    """获取所有持仓信息（包括所有字段）"""
    try:
        positions_all_df = position_manager.get_all_positions_with_all_fields()
        
        # 计算数据版本号（使用时间戳）
        data_version = int(time.time())
        
        # 处理NaN值
        positions_all_df = positions_all_df.replace({pd.NA: None, float('nan'): None})
        
        # 转换为JSON可序列化的格式
        positions_all = positions_all_df.to_dict('records')
        
        # 更新实时数据
        realtime_data['positions_all'] = positions_all
        
        response = make_response(jsonify({
            'status': 'success',
            'data': positions_all,
            'data_version': data_version  # 添加版本号
        }))
        response.headers['Content-Type'] = 'application/json; charset=utf-8'
        return response
    except Exception as e:
        logger.error(f"获取所有持仓信息（所有字段）时出错: {str(e)}")
        return jsonify({
            'status': 'error',
            'message': f"获取所有持仓信息（所有字段）时出错: {str(e)}"
        }), 500

def push_realtime_data():
    """推送实时数据的线程函数"""
    global stop_push_flag
    
    while not stop_push_flag:
        try:
            # 只在交易时间更新数据
            if config.is_trade_time():
                # 更新所有持仓的最新价格
                position_manager.update_all_positions_price()
                
                # 获取所有持仓数据
                positions_all_df = position_manager.get_all_positions_with_all_fields()
                
                # 处理NaN值
                positions_all_df = positions_all_df.replace({pd.NA: None, float('nan'): None})
                
                # 更新实时数据
                realtime_data['positions_all'] = positions_all_df.to_dict('records')
            
            # 休眠间隔
            time.sleep(3)
        except Exception as e:
            logger.error(f"推送实时数据时出错: {str(e)}")
            time.sleep(3)  # 出错后休眠


def start_push_thread():
    """启动实时推送线程"""
    global push_thread
    global stop_push_flag
    
    if push_thread is None or not push_thread.is_alive():
        stop_push_flag = False
        push_thread = threading.Thread(target=push_realtime_data)
        push_thread.daemon = True
        push_thread.start()
        logger.info("实时推送线程已启动")
    else:
        logger.warning("实时推送线程已在运行")

def start_web_server():
    """启动Web服务器"""
    start_push_thread()
    app.run(host=config.WEB_SERVER_HOST, port=config.WEB_SERVER_PORT, debug=config.WEB_SERVER_DEBUG, use_reloader=False)

if __name__ == '__main__':
     start_web_server()
