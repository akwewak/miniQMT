"""
配置参数管理模块，集中管理所有可配置参数
优化版本：增强止盈止损配置的清晰度
"""
import os
import json
from datetime import datetime

# ======================= 系统配置 =======================
# 调试开关
DEBUG = False
DEBUG_SIMU_STOCK_DATA= False
LOG_LEVEL = "INFO"  # DEBUG, INFO, WARNING, ERROR, CRITICAL
LOG_FILE = "qmt_trading.log"
LOG_MAX_SIZE = 10 * 1024 * 1024  # 10MB
LOG_BACKUP_COUNT = 5  # 保留5个备份文件

# ======================= 功能开关 =======================
ENABLE_SIMULATION_MODE = True   # 模拟交易模式开关（True=模拟，False=实盘）
ENABLE_MONITORING = False       # 控制前端UI监控状态
ENABLE_AUTO_TRADING = False     # 自动交易总开关：控制是否执行交易决策并形成交易记录
ENABLE_ALLOW_BUY = True         # 是否允许买入操作
ENABLE_ALLOW_SELL = True        # 是否允许卖出操作

# 策略功能模块开关（独立控制）
ENABLE_DYNAMIC_STOP_PROFIT = True   # 止盈止损功能开关
ENABLE_GRID_TRADING = False         # 网格交易功能开关

# 其他功能开关
ENABLE_DATA_SYNC = True             # 是否启用数据同步
ENABLE_POSITION_MONITOR = True      # 是否启用持仓监控
ENABLE_LOG_CLEANUP = True           # 是否启用日志清理

# 注释说明：
# - 策略线程始终运行，进行信号检测和监控
# - ENABLE_AUTO_TRADING 控制是否执行检测到的交易信号
# - ENABLE_DYNAMIC_STOP_PROFIT 控制止盈止损模块
# - ENABLE_GRID_TRADING 控制网格交易模块
# - ENABLE_SIMULATION_MODE 控制交易执行方式（模拟/实盘）

# ======================= 数据配置 =======================
# 历史数据存储路径
DATA_DIR = "data"
# 数据库配置（如果使用SQLite）
DB_PATH = os.path.join(DATA_DIR, "trading.db")
# 行情数据周期
PERIODS = ["1d", "1h", "30m", "15m", "5m", "1m"]
# 默认使用的周期
DEFAULT_PERIOD = "1d"
# 历史数据初始获取天数
INITIAL_DAYS = 365
# 定时更新间隔（秒）
UPDATE_INTERVAL = 60
# 备选池股票文件路径
STOCK2BUY_FILE = os.path.join(DATA_DIR, "stock2buy.json")

# 实时数据源配置
REALTIME_DATA_CONFIG = {
    'enable_multi_source': True,
    'health_check_interval': 30,
    'source_timeout': 5,
    'max_error_count': 3,
    'preferred_sources': [
        'XtQuant',
        'Mootdx'
    ]
}


# ======================= 交易配置 =======================
# 交易账号信息（从外部文件读取，避免敏感信息硬编码）
ACCOUNT_CONFIG_FILE = "account_config.json"
QMT_PATH = r'C:/光大证券金阳光QMT实盘/userdata_mini'

def get_account_config():
    """从外部文件读取账号配置"""
    try:
        with open(ACCOUNT_CONFIG_FILE, 'r') as f:
            return json.load(f)
    except FileNotFoundError:
        # 如果配置文件不存在，返回默认空配置
        return {"account_id": "", "account_type": "STOCK"}

# 账号信息
ACCOUNT_CONFIG = get_account_config()

# ======================= 策略配置 =======================
# 仓位管理
POSITION_UNIT = 20000  # 每次买入金额
MAX_POSITION_VALUE = 50000  # 单只股票最大持仓金额
MAX_TOTAL_POSITION_RATIO = 0.95  # 最大总持仓比例（占总资金）
SIMULATION_BALANCE = 1000000 # 模拟持仓

# 买入策略
BUY_GRID_LEVELS = [1.0, 0.93, 0.86]  # 建仓价格网格（第一个是初次建仓价格比例，后面是补仓价格比例）
BUY_AMOUNT_RATIO = [0.4, 0.3, 0.3]  # 每次买入金额占单元的比例

# ======================= 止盈止损策略配置 =======================
# 统一的止损比例
STOP_LOSS_RATIO = -0.07  # 固定止损比例：成本价下跌7%触发止损

# 动态止盈配置
ENABLE_DYNAMIC_STOP_PROFIT = True  # 启用动态止盈功能
INITIAL_TAKE_PROFIT_RATIO = 0.05   # 首次止盈触发阈值：盈利5%时触发
INITIAL_TAKE_PROFIT_PULLBACK_RATIO = 0.005  # 回撤比例：0.5%（可配置）
INITIAL_TAKE_PROFIT_RATIO_PERCENTAGE = 0.6  # 首次止盈卖出比例：50%（半仓）

# 分级动态止盈设置（已触发首次止盈后的动态止盈位）
# 格式：(最高盈利比例阈值, 止盈位系数)
# 说明：当最高盈利达到阈值后，止盈位 = 最高价 × 系数
DYNAMIC_TAKE_PROFIT = [
    (0.05, 0.96),  # 最高浮盈达5%时，止盈位为最高价的96%
    (0.10, 0.93),  # 最高浮盈达10%时，止盈位为最高价的93%
    (0.15, 0.90),  # 最高浮盈达15%时，止盈位为最高价的90%
    (0.30, 0.87),  # 最高浮盈达30%时，止盈位为最高价的87%
    (0.40, 0.85)   # 最高浮盈达40%时，止盈位为最高价的85%
]

# 止盈止损优先级说明：
# 1. 止损检查优先级最高
# 2. 未触发首次止盈时：盈利5%触发首次止盈（卖出50%）
# 3. 已触发首次止盈后：使用动态止盈位进行全仓止盈
# 4. 止损价格计算：未触发首次止盈时为成本价×(1-7%)，已触发后为最高价×对应系数

# 网格交易参数
GRID_TRADING_ENABLED = True
GRID_STEP_RATIO = 0.03  # 网格步长（价格变动3%创建一个网格）
GRID_POSITION_RATIO = 0.2  # 每个网格交易的仓位比例 10%
GRID_MAX_LEVELS = 6  # 最大网格数量

# ======================= 指标配置 =======================
# MACD参数
MACD_FAST = 12
MACD_SLOW = 26
MACD_SIGNAL = 9

# 均线参数
MA_PERIODS = [10, 20, 30, 60]

# ======================= 参数配置范围 =======================
# 参数范围定义，用于前后端校验
CONFIG_PARAM_RANGES = {
    "singleBuyAmount": {"min": 1000, "max": 100000, "type": "float", "desc": "单只单次买入金额"},
    "firstProfitSell": {"min": 1.0, "max": 20.0, "type": "float", "desc": "首次止盈比例(%)"},
    "stockGainSellPencent": {"min": 1.0, "max": 100.0, "type": "float", "desc": "首次盈利平仓卖出比例(%)"},
    "stopLossBuy": {"min": 1.0, "max": 20.0, "type": "float", "desc": "补仓跌幅(%)"},
    "stockStopLoss": {"min": 1.0, "max": 20.0, "type": "float", "desc": "止损比例(%)"},
    "singleStockMaxPosition": {"min": 10000, "max": 100000, "type": "float", "desc": "单只股票最大持仓"},
    "totalMaxPosition": {"min": 50000, "max": 1000000, "type": "float", "desc": "最大总持仓"},
    "connectPort": {"min": 1, "max": 65535, "type": "int", "desc": "连接端口"}
}

# 实现参数校验函数
def validate_config_param(param_name, value):
    """验证配置参数是否在有效范围内"""
    if param_name not in CONFIG_PARAM_RANGES:
        return True, ""  # 未定义范围的参数默认通过
        
    param_range = CONFIG_PARAM_RANGES[param_name]
    param_type = param_range.get("type", "float")
    param_min = param_range.get("min")
    param_max = param_range.get("max")
    
    try:
        # 类型转换
        if param_type == "float":
            value = float(value)
        elif param_type == "int":
            value = int(value)
            
        # 范围检查
        if param_min is not None and value < param_min:
            return False, f"{param_range['desc']}不能小于{param_min}"
            
        if param_max is not None and value > param_max:
            return False, f"{param_range['desc']}不能大于{param_max}"
            
        return True, ""
    except (ValueError, TypeError):
        return False, f"{param_range['desc']}必须是{param_type}类型"

# ======================= Web服务配置 =======================
WEB_SERVER_HOST = "localhost"
WEB_SERVER_PORT = 5000
WEB_SERVER_DEBUG = True

# ======================= 日志清理配置 =======================
LOG_CLEANUP_DAYS = 30  # 保留最近30天的日志
LOG_CLEANUP_TIME = "00:00:00"  # 每天凌晨执行清理

# ======================= 功能配置 =======================
# 交易时间配置
TRADE_TIME = {
    "morning_start": "09:30:00",
    "morning_end": "11:30:00",
    "afternoon_start": "13:00:00",
    "afternoon_end": "15:00:00",
    "trade_days": [1, 2, 3, 4, 5]  # 周一至周五
}

def is_trade_time():
    """判断当前是否为交易时间"""
    if DEBUG_SIMU_STOCK_DATA or ENABLE_SIMULATION_MODE:
        return True

    now = datetime.now()
    weekday = now.weekday() + 1  # 转换为1-7表示周一至周日
    
    if weekday not in TRADE_TIME["trade_days"]:
        return False
    
    current_time = now.strftime("%H:%M:%S")
    if (TRADE_TIME["morning_start"] <= current_time <= TRADE_TIME["morning_end"]) or \
       (TRADE_TIME["afternoon_start"] <= current_time <= TRADE_TIME["afternoon_end"]):
        return True
    
    return False

# ======================= 预设股票池 =======================
# 可以在这里定义预设的股票池，也可以从外部文件加载
DEFAULT_STOCK_POOL = [
    "000001.SZ",  # 平安银行
    "600036.SH",  # 招商银行
    "000333.SZ",  # 美的集团
    "600519.SH",  # 贵州茅台
    "000858.SZ",  # 五粮液
]

STOCK_POOL_FILE = "stock_pool.json" 

def load_stock_pool(file_path=STOCK_POOL_FILE):
    """从外部文件加载股票池"""
    try:
        with open(file_path, 'r') as f:
            return json.load(f)
    except FileNotFoundError:
        return DEFAULT_STOCK_POOL

# 实际使用的股票池
STOCK_POOL = load_stock_pool()