#!/usr/bin/env python3
"""运行新建的 18P/17P 自然位排名追踪表。"""

import os
import sys

import rank_tracker_core as core

try:
    from local_secrets import (
        FEISHU_18_WEBHOOK as LOCAL_FEISHU_18_WEBHOOK,
        SPREADSHEET_NEW_TOKEN as LOCAL_SPREADSHEET_NEW_TOKEN,
        SPREADSHEET_NEW_URL as LOCAL_SPREADSHEET_NEW_URL,
    )
except ImportError:
    LOCAL_FEISHU_18_WEBHOOK = ""
    LOCAL_SPREADSHEET_NEW_TOKEN = ""
    LOCAL_SPREADSHEET_NEW_URL = ""

core.SPREADSHEET_TOKEN = os.getenv("SPREADSHEET_NEW_TOKEN", LOCAL_SPREADSHEET_NEW_TOKEN)
core.SPREADSHEET_URL = os.getenv("SPREADSHEET_NEW_URL", LOCAL_SPREADSHEET_NEW_URL)
core.FEISHU_WEBHOOK = os.getenv("FEISHU_18_WEBHOOK", LOCAL_FEISHU_18_WEBHOOK or core.FEISHU_WEBHOOK)
core.NOTIFICATION_DEFAULT_TARGET = "both"
core.NOTIFICATION_TITLE_PREFIX = "新18P/17P自然位排名播报"
core.NOTIFICATION_TOP_KEYWORDS_ONLY = True
core.NOTIFICATION_KEYWORD_ZIPCODE = "90001"
core.NOTIFICATION_KEYWORD_COUNT = 3
core.RANK_COLOR_MODE = "first_page_top10"

core.PRODUCTS = [
    {
        "asin": "B0H5HXN247",
        "sheet_id": "c8a69f",
        "name": "B0H5HXN247",
        "kw_col": "B",
        "kw_start_row": 3,
        "kw_end_row": 200,
        "date_row": 1,
        "zipcode_row": 2,
        "result_start_col": "C",
        "zipcodes": ["90001", "77001", "33101"],
    },
    {
        "asin": "B0FF4J8LFC",
        "sheet_id": "30Yf4c",
        "name": "B0FF4J8LFC",
        "kw_col": "B",
        "kw_start_row": 3,
        "kw_end_row": 200,
        "date_row": 1,
        "zipcode_row": 2,
        "result_start_col": "C",
        "zipcodes": ["90001", "77001", "33101"],
    },
]


if __name__ == "__main__":
    sys.argv[0] = "run_new_17_18_rank_tracker.py"
    core.main()
