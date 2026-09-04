#!/usr/bin/env python3
"""单独运行智贴18系列自然位排名追踪。"""

import os
import sys

import rank_tracker_core as core

try:
    from local_secrets import (
        FEISHU_18_WEBHOOK as LOCAL_FEISHU_18_WEBHOOK,
        SPREADSHEET_18_TOKEN as LOCAL_SPREADSHEET_18_TOKEN,
        SPREADSHEET_18_URL as LOCAL_SPREADSHEET_18_URL,
    )
except ImportError:
    LOCAL_FEISHU_18_WEBHOOK = ""
    LOCAL_SPREADSHEET_18_TOKEN = ""
    LOCAL_SPREADSHEET_18_URL = ""

core.SPREADSHEET_TOKEN = os.getenv("SPREADSHEET_18_TOKEN", LOCAL_SPREADSHEET_18_TOKEN)
core.SPREADSHEET_URL = os.getenv("SPREADSHEET_18_URL", LOCAL_SPREADSHEET_18_URL)
core.FEISHU_WEBHOOK = os.getenv("FEISHU_18_WEBHOOK", LOCAL_FEISHU_18_WEBHOOK or core.FEISHU_WEBHOOK)
core.NOTIFICATION_DEFAULT_TARGET = "both"
core.NOTIFICATION_TITLE_PREFIX = "18自然位排名播报"
core.NOTIFICATION_TOP_KEYWORDS_ONLY = True
core.NOTIFICATION_KEYWORD_ZIPCODE = "90001"
core.NOTIFICATION_KEYWORD_COUNT = 3

core.PRODUCTS = [
    {
        "asin": "B0H5J2F9JL",
        "sheet_id": "0a2b37",
        "name": "智贴18PM",
        "kw_col": "B",
        "kw_start_row": 3,
        "kw_end_row": 200,
        "date_row": 1,
        "zipcode_row": 2,
        "result_start_col": "C",
        "zipcodes": ["90001", "77001", "33101"],
    },
    {
        "asin": "B0H5HXN247",
        "sheet_id": "2TNFfi",
        "name": "智贴18P",
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
    sys.argv[0] = "run_18_rank_tracker.py"
    core.main()
