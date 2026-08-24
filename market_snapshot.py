#!/usr/bin/env python3
"""
防窥16PM 市场自然排名快照
========================
独立于日常排名监控：
1. 第一个 sheet：统计我们 ASIN 在 3 个关键词、3 个邮编下的自然排名
2. 后面 3 个 sheet：每个关键词一个 sheet，列出 Amazon 第 1 页全部自然结果，并标黄我们自己的产品
"""

import datetime
import json
import os
import re
import time
import urllib.parse
import urllib.request

from config import FEISHU_APP_ID, FEISHU_APP_SECRET
from rank_tracker_core import AmazonRanker, FeishuTokenManager, col_letter, feishu_api

try:
    from local_secrets import (
        MARKET_SPREADSHEET_TOKEN as LOCAL_MARKET_SPREADSHEET_TOKEN,
        MARKET_SPREADSHEET_URL as LOCAL_MARKET_SPREADSHEET_URL,
    )
except ImportError:
    LOCAL_MARKET_SPREADSHEET_TOKEN = ""
    LOCAL_MARKET_SPREADSHEET_URL = ""


TARGET_ASIN = "B0D6NQ2GN5"
PRODUCT_NAME = "防窥16PM"
ZIPCODES = ["90001", "77001", "33101"]
KEYWORDS = [
    "iphone 16 pro max privacy screen protector",
    "privacy screen iphone 16 pro max",
    "iphone 16 pro max screen protector privacy",
]

MARKET_SPREADSHEET_TITLE = "防窥16PM市场自然排名快照"

# 第一次运行如果成功创建新表，会把 token/url 打印出来。
# 如果飞书创建新表权限不足，手动新建空白飞书表格后，把 token 填到这里再运行。
MARKET_SPREADSHEET_TOKEN = os.getenv("MARKET_SPREADSHEET_TOKEN", LOCAL_MARKET_SPREADSHEET_TOKEN)
MARKET_SPREADSHEET_URL = os.getenv("MARKET_SPREADSHEET_URL", LOCAL_MARKET_SPREADSHEET_URL)


def safe_sheet_title(text, max_len=30):
    title = re.sub(r"[\[\]\*?/\\\\:]", " ", text).strip()
    title = re.sub(r"\s+", " ", title)
    return title[:max_len] or "Sheet"


def create_spreadsheet(token):
    url = "https://open.feishu.cn/open-apis/sheets/v3/spreadsheets"
    resp = feishu_api("POST", url, {"title": MARKET_SPREADSHEET_TITLE}, token=token)
    data = resp.get("data", {})
    spreadsheet = data.get("spreadsheet", data)
    spreadsheet_token = (
        spreadsheet.get("spreadsheet_token")
        or spreadsheet.get("token")
        or data.get("spreadsheet_token")
        or data.get("token")
    )
    spreadsheet_url = spreadsheet.get("url") or data.get("url") or ""
    if not spreadsheet_token:
        raise RuntimeError(f"创建飞书表格成功但没有拿到 token: {json.dumps(resp, ensure_ascii=False)[:500]}")
    print(f"✅ 新飞书表格已创建: {spreadsheet_url or spreadsheet_token}")
    return spreadsheet_token, spreadsheet_url


def list_sheets(token, spreadsheet_token):
    base = f"https://open.feishu.cn/open-apis/sheets/v2/spreadsheets/{spreadsheet_token}"
    resp = feishu_api("GET", f"{base}/metainfo", token=token)
    return resp.get("data", {}).get("sheets", [])


def add_sheet(token, spreadsheet_token, title):
    base = f"https://open.feishu.cn/open-apis/sheets/v2/spreadsheets/{spreadsheet_token}"
    resp = feishu_api("POST", f"{base}/sheets_batch_update", {
        "requests": [
            {
                "addSheet": {
                    "properties": {
                        "title": title,
                        "index": 0,
                    }
                }
            }
        ]
    }, token=token)
    replies = resp.get("data", {}).get("replies", [])
    if replies:
        props = replies[0].get("addSheet", {}).get("properties", {})
        if props.get("sheetId"):
            return props["sheetId"]
    sheets = list_sheets(token, spreadsheet_token)
    for sheet in sheets:
        if sheet.get("title") == title:
            return sheet.get("sheetId")
    raise RuntimeError(f"创建 sheet 失败: {title} / {json.dumps(resp, ensure_ascii=False)[:500]}")


def get_or_create_sheet(token, spreadsheet_token, title):
    for sheet in list_sheets(token, spreadsheet_token):
        if sheet.get("title") == title:
            return sheet.get("sheetId")
    return add_sheet(token, spreadsheet_token, title)


def write_values(token, spreadsheet_token, sheet_id, start_cell, values):
    if not values:
        return
    row_count = len(values)
    col_count = max(len(row) for row in values)
    start_col = re.match(r"([A-Z]+)", start_cell).group(1)
    start_row = int(re.search(r"(\d+)", start_cell).group(1))
    start_col_idx = 0
    for ch in start_col:
        start_col_idx = start_col_idx * 26 + (ord(ch) - ord("A") + 1)
    end_col = col_letter(start_col_idx - 1 + col_count - 1)
    end_row = start_row + row_count - 1
    base = f"https://open.feishu.cn/open-apis/sheets/v2/spreadsheets/{spreadsheet_token}"
    feishu_api("PUT", f"{base}/values", {
        "valueRange": {
            "range": f"{sheet_id}!{start_cell}:{end_col}{end_row}",
            "values": values,
        }
    }, token=token)


def highlight_own_rows(token, spreadsheet_token, sheet_id, row_numbers):
    if not row_numbers:
        return
    ranges = [f"{sheet_id}!A{row}:E{row}" for row in row_numbers]
    base = f"https://open.feishu.cn/open-apis/sheets/v2/spreadsheets/{spreadsheet_token}"
    feishu_api("PUT", f"{base}/styles_batch_update", {
        "data": [
            {
                "ranges": ranges,
                "style": {"backColor": "#FFF2CC"},
            }
        ]
    }, token=token)


def extract_title(section):
    patterns = [
        r'<h2[^>]*>.*?<span[^>]*>(.*?)</span>',
        r'<span class="a-size-medium a-color-base a-text-normal">(.*?)</span>',
        r'<span class="a-size-base-plus a-color-base a-text-normal">(.*?)</span>',
    ]
    for pattern in patterns:
        match = re.search(pattern, section, flags=re.S)
        if match:
            text = re.sub(r"<.*?>", "", match.group(1))
            return re.sub(r"\s+", " ", text).strip()
    return ""


def first_page_organic_results(ranker, keyword):
    url = f"https://www.amazon.com/s?k={urllib.parse.quote(keyword)}&page=1"
    html = ranker._fetch_page(url)
    if ranker._is_blocked_page(html):
        ranker.blocked = True
        return []

    results = []
    organic_rank = 0
    sections = re.split(r'(?=data-component-type="s-search-result")', html)
    for section in sections:
        asin_match = re.search(r'data-asin="([A-Z0-9]{10})"', section)
        if not asin_match or not asin_match.group(1):
            continue
        asin = asin_match.group(1)
        is_sponsored = bool(re.search(r'Sponsored|AdHolder|s-sponsored', section[:5000]))
        if is_sponsored:
            continue
        organic_rank += 1
        results.append({
            "rank": organic_rank,
            "asin": asin,
            "title": extract_title(section),
            "is_ours": asin == TARGET_ASIN,
        })
    return results


def main():
    token_mgr = FeishuTokenManager()
    spreadsheet_token = MARKET_SPREADSHEET_TOKEN
    spreadsheet_url = MARKET_SPREADSHEET_URL
    if not spreadsheet_token:
        spreadsheet_token, spreadsheet_url = create_spreadsheet(token_mgr.token)
        print("\n请把下面两行保存到 market_snapshot.py，之后会复用这个新表：")
        print(f'MARKET_SPREADSHEET_TOKEN = "{spreadsheet_token}"')
        print(f'MARKET_SPREADSHEET_URL = "{spreadsheet_url}"')

    run_label = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
    own_sheet_id = get_or_create_sheet(token_mgr.token, spreadsheet_token, "自身自然排名")

    own_rows = [["更新时间", run_label], ["产品", PRODUCT_NAME], ["ASIN", TARGET_ASIN], []]
    own_rows.append(["关键词", "邮编", "自然排名"])

    market_snapshots = {}
    for keyword in KEYWORDS:
        market_snapshots[keyword] = {}
        for zipcode in ZIPCODES:
            print(f"查询: {keyword} / {zipcode}")
            ranker = AmazonRanker(zipcode)
            try:
                results = first_page_organic_results(ranker, keyword)
                market_snapshots[keyword][zipcode] = results
                own_rank = next((f"Page 1 · #{r['rank']}" for r in results if r["asin"] == TARGET_ASIN), "—")
                own_rows.append([keyword, zipcode, own_rank])
            finally:
                ranker.close()
            time.sleep(2)

    write_values(token_mgr.token, spreadsheet_token, own_sheet_id, "A1", own_rows)

    for keyword in KEYWORDS:
        title = safe_sheet_title(keyword)
        sheet_id = get_or_create_sheet(token_mgr.token, spreadsheet_token, title)
        rows = [
            ["关键词", keyword],
            ["更新时间", run_label],
            [],
            ["邮编", "自然位", "ASIN", "是否我们产品", "标题"],
        ]
        own_rows_to_highlight = []
        row_number = len(rows) + 1
        for zipcode in ZIPCODES:
            for result in market_snapshots[keyword][zipcode]:
                rows.append([
                    zipcode,
                    result["rank"],
                    result["asin"],
                    "是" if result["is_ours"] else "",
                    result["title"],
                ])
                if result["is_ours"]:
                    own_rows_to_highlight.append(row_number)
                row_number += 1
            rows.append(["", "", "", "", ""])
            row_number += 1
        write_values(token_mgr.token, spreadsheet_token, sheet_id, "A1", rows)
        highlight_own_rows(token_mgr.token, spreadsheet_token, sheet_id, own_rows_to_highlight)

    print("\n✅ 市场自然排名快照完成")
    print(spreadsheet_url or spreadsheet_token)


if __name__ == "__main__":
    main()
