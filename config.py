"""
Amazon 自然位排名追踪 — 配置模板
=================================
只改 "你需要改的部分"，其他不要动。
改完后把这个文件重命名为 config.py，然后运行 rank_to_feishu.py。
"""

import os

try:
    from local_secrets import (
        FEISHU_APP_ID as LOCAL_FEISHU_APP_ID,
        FEISHU_APP_SECRET as LOCAL_FEISHU_APP_SECRET,
        FEISHU_WEBHOOK as LOCAL_FEISHU_WEBHOOK,
        FEISHU_PRIVATE_OPEN_ID as LOCAL_FEISHU_PRIVATE_OPEN_ID,
        SPREADSHEET_TOKEN as LOCAL_SPREADSHEET_TOKEN,
        SPREADSHEET_URL as LOCAL_SPREADSHEET_URL,
    )
except ImportError:
    LOCAL_FEISHU_APP_ID = ""
    LOCAL_FEISHU_APP_SECRET = ""
    LOCAL_FEISHU_WEBHOOK = ""
    LOCAL_FEISHU_PRIVATE_OPEN_ID = ""
    LOCAL_SPREADSHEET_TOKEN = ""
    LOCAL_SPREADSHEET_URL = ""

# ╔══════════════════════════════════════════════════╗
# ║          === 你需要改的部分 ===                    ║
# ╚══════════════════════════════════════════════════╝

# ------ 飞书凭证 ------
# 在 https://open.feishu.cn/app 创建自建应用，拿到这两个值
# 应用需要开通权限：sheets:spreadsheet（读写电子表格）
FEISHU_APP_ID = os.getenv("FEISHU_APP_ID", LOCAL_FEISHU_APP_ID)
FEISHU_APP_SECRET = os.getenv("FEISHU_APP_SECRET", LOCAL_FEISHU_APP_SECRET)

# 飞书电子表格 token（打开表格，URL 里 /sheets/ 后面那串）
# 例如 URL 是 https://xxx.feishu.cn/sheets/PNKSslCFThKrPJtzs89cFHGVnQc
# 则 token 是 PNKSslCFThKrPJtzs89cFHGVnQc
SPREADSHEET_TOKEN = os.getenv("SPREADSHEET_TOKEN", LOCAL_SPREADSHEET_TOKEN)
SPREADSHEET_URL = os.getenv("SPREADSHEET_URL", LOCAL_SPREADSHEET_URL)

# 飞书群机器人 webhook（群设置 → 群机器人 → 添加自定义机器人 → 拿到 webhook URL）
FEISHU_WEBHOOK = os.getenv("FEISHU_WEBHOOK", LOCAL_FEISHU_WEBHOOK)
FEISHU_PRIVATE_OPEN_ID = os.getenv("FEISHU_PRIVATE_OPEN_ID", LOCAL_FEISHU_PRIVATE_OPEN_ID)

# ------ 产品配置 ------
# 每个产品是一个 dict，对应飞书表格里的一个 sheet tab
#
# 字段说明：
#   asin         - Amazon ASIN（B0开头的10位码）
#   sheet_id     - 飞书 sheet tab 的 ID（打开表格，切到对应 tab，URL 里 #gid= 后面的值）
#                  或者用飞书 API 获取：GET /sheets/v2/spreadsheets/{token}/sheets
#   name         - 产品名（显示用，也用于 --sheet 参数指定跑哪个）
#   kw_col       - 关键词所在列（"A" 或 "B" 等）
#   kw_start_row - 关键词开始的行号（跳过表头）
#   kw_end_row   - 关键词结束的行号（多写几行没关系，尾部空行会自动去掉）
#   date_row     - 日期所在行号（默认 1）
#   zipcode_row  - 邮编所在行号（默认 2）
#   result_start_col - 排名结果从哪一列开始写（关键词在 B 列时，建议 C）
#   zipcodes     - 多个邮编会在同一个 sheet 里横向写入多列
#   max_pages    - 最多搜索几页 Amazon 结果（默认 7，词多的产品可以设 10）
#
# 示例（替换成你自己的）：
PRODUCTS = [
    {
        "asin": "B0D6NQ2GN5",
        "sheet_id": "8eb70a",
        "name": "防窥16PM",
        "kw_col": "B",
        "kw_start_row": 3,
        "kw_end_row": 200,
        "date_row": 1,
        "zipcode_row": 2,
        "result_start_col": "C",
        "zipcodes": ["90001", "77001", "33101"],
        # "max_pages": 10,  # 可选，默认 7
    },
    {
        "asin": "B0CXD2PNQL",
        "sheet_id": "37jVM4",
        "name": "智贴14PM",
        "kw_col": "B",
        "kw_start_row": 3,
        "kw_end_row": 200,
        "date_row": 1,
        "zipcode_row": 2,
        "result_start_col": "C",
        "zipcodes": ["90001", "77001", "33101"],
    },
    {
        "asin": "B0CB5TLRBR",
        "sheet_id": "aeJTFD",
        "name": "智贴15P",
        "kw_col": "B",
        "kw_start_row": 3,
        "kw_end_row": 200,
        "date_row": 1,
        "zipcode_row": 2,
        "result_start_col": "C",
        "zipcodes": ["90001", "77001", "33101"],
    },
]

# ------ 搜索设置 ------
# 美国邮编，影响 Amazon 搜索结果的本地化（不同州价格/库存不同）
# 94203 = 加州Sacramento，大部分产品都有库存
ZIPCODE = "94203"

# ╔══════════════════════════════════════════════════╗
# ║        === 以下通常不需要改 ===                    ║
# ╚══════════════════════════════════════════════════╝

# 每页搜索后等待秒数（太快会被封）
DELAY_BETWEEN_KEYWORDS = 8   # 实际会随机 ±1 秒
DELAY_BETWEEN_PAGES = 4

# 默认搜索页数
MAX_PAGES = 5

# 连续失败多少次后跳过该产品剩余关键词
MAX_CONSECUTIVE_FAILURES = 10

# 覆盖率低于此值时触发补查（0.85 = 85%）
MIN_COVERAGE_RATE = 0.85

# 脚本整体超时（分钟），留余量给 GitHub Actions 的 180 分钟上限
SCRIPT_TIMEOUT_MINUTES = 150
