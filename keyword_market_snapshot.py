#!/usr/bin/env python3
"""
按单个关键词抓取 Amazon 前三页独立自然竞对快照。

用法:
  python3 keyword_market_snapshot.py "iphone 18 pro screen protector"
  python3 keyword_market_snapshot.py "keyword" --pages 3 --zipcodes 90001,77001,33101
"""

import argparse
import datetime
import html
import json
import os
import re
import sys
import time
import urllib.parse

from config import FEISHU_PRIVATE_OPEN_ID, ZIPCODE
import rank_tracker_core as core
from rank_tracker_core import AmazonRanker, FeishuTokenManager, col_letter, feishu_api, send_feishu_private_card

try:
    from keyword_market_config import (
        MARKET_KEYWORD_SPREADSHEET_TOKEN as LOCAL_MARKET_KEYWORD_SPREADSHEET_TOKEN,
        MARKET_KEYWORD_SPREADSHEET_URL as LOCAL_MARKET_KEYWORD_SPREADSHEET_URL,
    )
except ImportError:
    LOCAL_MARKET_KEYWORD_SPREADSHEET_TOKEN = ""
    LOCAL_MARKET_KEYWORD_SPREADSHEET_URL = ""

DEFAULT_TARGET_ASINS = ["B0H5J2F9JL", "B0H5HXN247"]


def clean_text(value):
    value = html.unescape(value or "")
    value = re.sub(r"<.*?>", " ", value, flags=re.S)
    value = re.sub(r"\s+", " ", value)
    return value.strip()


def safe_sheet_title(text, max_len=30):
    title = re.sub(r"[\[\]\*?/\\\\:]", " ", text).strip()
    title = re.sub(r"\s+", " ", title)
    return title[:max_len] or "Sheet"


def create_spreadsheet(token, title):
    url = "https://open.feishu.cn/open-apis/sheets/v3/spreadsheets"
    resp = feishu_api("POST", url, {"title": title}, token=token)
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
    return spreadsheet_token, spreadsheet_url


def grant_user_permission(token, spreadsheet_token):
    if not FEISHU_PRIVATE_OPEN_ID:
        print("⚠ 未配置个人 open_id，新表不会自动授权给你", flush=True)
        return
    url = (
        f"https://open.feishu.cn/open-apis/drive/v1/permissions/{spreadsheet_token}/members"
        "?type=sheet&need_notification=true"
    )
    try:
        feishu_api("POST", url, {
            "member_type": "openid",
            "member_id": FEISHU_PRIVATE_OPEN_ID,
            "perm": "edit",
        }, token=token)
        print("✅ 已自动授权给你的飞书账号", flush=True)
    except Exception as e:
        print(f"⚠ 自动授权失败，请手动分享表格: {e}", flush=True)


def list_sheets(token, spreadsheet_token):
    base = f"https://open.feishu.cn/open-apis/sheets/v2/spreadsheets/{spreadsheet_token}"
    resp = feishu_api("GET", f"{base}/metainfo", token=token)
    return resp.get("data", {}).get("sheets", [])


def add_sheet(token, spreadsheet_token, title, index=0):
    base = f"https://open.feishu.cn/open-apis/sheets/v2/spreadsheets/{spreadsheet_token}"
    resp = feishu_api("POST", f"{base}/sheets_batch_update", {
        "requests": [
            {
                "addSheet": {
                    "properties": {
                        "title": title,
                        "index": index,
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
    for sheet in list_sheets(token, spreadsheet_token):
        if sheet.get("title") == title:
            return sheet.get("sheetId")
    raise RuntimeError(f"创建 sheet 失败: {title} / {json.dumps(resp, ensure_ascii=False)[:500]}")


def get_or_create_sheet(token, spreadsheet_token, title, index=0):
    for sheet in list_sheets(token, spreadsheet_token):
        if sheet.get("title") == title:
            return sheet.get("sheetId")
    return add_sheet(token, spreadsheet_token, title, index=index)


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


def style_rows(token, spreadsheet_token, sheet_id, own_rows):
    data = []
    if own_rows:
        data.append({
            "ranges": [f"{sheet_id}!A{row}:J{row}" for row in own_rows],
            "style": {"backColor": "#FFF2CC"},
        })
    if not data:
        return
    base = f"https://open.feishu.cn/open-apis/sheets/v2/spreadsheets/{spreadsheet_token}"
    feishu_api("PUT", f"{base}/styles_batch_update", {"data": data}, token=token)


def extract_title(section):
    patterns = [
        r'<h2[^>]*>.*?<span[^>]*>(.*?)</span>',
        r'<span class="a-size-medium a-color-base a-text-normal">(.*?)</span>',
        r'<span class="a-size-base-plus a-color-base a-text-normal">(.*?)</span>',
    ]
    for pattern in patterns:
        match = re.search(pattern, section, flags=re.S)
        if match:
            return clean_text(match.group(1))
    return ""


def extract_brand(title):
    """按约定取商品标题的第一个词作为品牌。"""
    first_word = re.split(r"\s+", (title or "").strip(), maxsplit=1)[0]
    return first_word.strip("[](){}<>\"'.,:;|-")


def extract_rating(section):
    patterns = [
        r'([0-5](?:\.\d)?) out of 5 stars',
        r'a-icon-alt">([0-5](?:\.\d)?)',
    ]
    for pattern in patterns:
        match = re.search(pattern, section, flags=re.I | re.S)
        if match:
            return match.group(1)
    return ""


def extract_review_count(section):
    patterns = [
        r'aria-label="([\d,]+) ratings?"',
        r'>([\d,]+)</span>\s*</a>\s*</span>\s*</div>',
        r'href="[^"]*customerReviews[^"]*"[^>]*>\s*<span[^>]*>([\d,]+)</span>',
    ]
    for pattern in patterns:
        match = re.search(pattern, section, flags=re.I | re.S)
        if match:
            return match.group(1)
    return ""


def extract_price(section):
    match = re.search(
        r'<span class="a-price"[^>]*>.*?<span class="a-offscreen">(.*?)</span>',
        section,
        flags=re.S,
    )
    if match:
        return clean_text(match.group(1))
    match = re.search(r'\$[\d,]+(?:\.\d{2})?', clean_text(section))
    return match.group(0) if match else ""


def is_real_product_card(section, asin, title):
    if not title or title.lower() == "search":
        return False
    asin_link_patterns = [
        rf'/dp/{re.escape(asin)}',
        rf'/gp/product/{re.escape(asin)}',
        rf'/sspa/click[^"]*%2Fdp%2F{re.escape(asin)}',
    ]
    return any(re.search(pattern, section, flags=re.I) for pattern in asin_link_patterns)


def is_sponsored(section):
    first_chunk = section[:7000]
    return bool(re.search(r'Sponsored|AdHolder|s-sponsored|puis-sponsored-label', first_chunk, flags=re.I))


def first_pages_organic_results(ranker, keyword, max_pages=3):
    """只返回前几页中独立商品卡片的自然结果，不包含广告或变体。"""
    results = []
    natural_rank = 0
    for page in range(1, max_pages + 1):
        url = f"https://www.amazon.com/s?k={urllib.parse.quote(keyword)}&page={page}"
        html_text = ranker._fetch_page(url)
        if ranker._is_blocked_page(html_text):
            ranker.blocked = True
            break

        page_organic_rank = 0
        sections = re.split(r'(?=data-component-type="s-search-result")', html_text)
        for section in sections:
            asin_match = re.search(r'data-asin="([A-Z0-9]{10})"', section)
            if not asin_match:
                continue
            asin = asin_match.group(1)
            title = extract_title(section)
            # data-asin + 商品标题代表独立商品卡片；不扫描卡片内部的 /dp/ 变体链接。
            if not asin or not title or title.lower() == "search" or is_sponsored(section):
                continue
            if not is_real_product_card(section, asin, title):
                continue

            natural_rank += 1
            page_organic_rank += 1
            results.append({
                "page": page,
                "page_organic_rank": page_organic_rank,
                "natural_rank": natural_rank,
                "asin": asin,
                "brand": extract_brand(title),
                "rating": extract_rating(section),
                "review_count": extract_review_count(section),
                "price": extract_price(section),
                "title": title,
            })

        if page < max_pages:
            time.sleep(4)
    return results


def send_private_notification(keyword, results_by_zipcode, target_asins, spreadsheet_url, run_label):
    """发送 90001 第一页竞品品牌与自然位通知，只发给个人 open_id。"""
    notification_zipcode = "90001"
    first_page_results = [
        result
        for result in results_by_zipcode.get(notification_zipcode, [])
        if result["page"] == 1
    ]
    first_page_results.sort(key=lambda result: result["natural_rank"])
    summary_rows = [
        f"关键词：{keyword}",
        f"邮编：{notification_zipcode}，第 1 页独立自然商品（含我方）",
    ]
    if first_page_results:
        rank_rows = ["**自然位 ｜ 品牌**"]
        for result in first_page_results:
            brand = result["brand"] or "未识别品牌"
            owner_label = "（我方）" if result["asin"] in target_asins else ""
            rank_rows.append(f"#{result['natural_rank']} ｜ {brand}{owner_label}")
        notification_content = "\n".join(summary_rows + [""] + rank_rows)
    else:
        summary_rows.append("未抓到独立自然竞品")
        notification_content = "\n".join(summary_rows)

    elements = [
        {"tag": "div", "text": {"tag": "lark_md", "content": notification_content}},
        {"tag": "hr"},
        {"tag": "note", "elements": [{"tag": "plain_text", "content": f"更新时间：{run_label}，共 {len(first_page_results)} 个独立自然商品（含我方）"}]},
    ]
    if spreadsheet_url:
        elements.append({
            "tag": "action",
            "actions": [{
                "tag": "button",
                "text": {"tag": "plain_text", "content": "打开竞品表格"},
                "type": "primary",
                "url": spreadsheet_url,
            }],
        })

    card = {
        "header": {
            "title": {"tag": "plain_text", "content": "📊 90001第一页品牌自然排名"},
            "template": "green",
        },
        "elements": elements,
    }
    # 私聊发送函数读取核心模块中的表格链接，这里临时替换为竞品表链接。
    previous_url = core.SPREADSHEET_URL
    core.SPREADSHEET_URL = spreadsheet_url
    try:
        send_feishu_private_card(card)
    finally:
        core.SPREADSHEET_URL = previous_url


def parse_args():
    parser = argparse.ArgumentParser(description="抓取单个关键词前几页独立自然位竞对快照")
    parser.add_argument("keyword", help="要搜索的 Amazon 关键词")
    parser.add_argument("--pages", type=int, default=3, help="抓取前几页自然结果，默认3")
    parser.add_argument("--zipcodes", default="90001,77001,33101", help="逗号分隔的美国邮编")
    parser.add_argument("--target-asins", default=",".join(DEFAULT_TARGET_ASINS), help="需要标黄的 ASIN，逗号分隔")
    parser.add_argument("--spreadsheet-token", default=os.getenv("MARKET_KEYWORD_SPREADSHEET_TOKEN", LOCAL_MARKET_KEYWORD_SPREADSHEET_TOKEN))
    parser.add_argument("--spreadsheet-url", default=os.getenv("MARKET_KEYWORD_SPREADSHEET_URL", LOCAL_MARKET_KEYWORD_SPREADSHEET_URL))
    return parser.parse_args()


def main():
    args = parse_args()
    keyword = args.keyword.strip()
    if not keyword:
        print("请提供关键词")
        sys.exit(1)
    pages = max(1, args.pages)

    zipcodes = [z.strip() for z in args.zipcodes.split(",") if z.strip()] or [ZIPCODE]
    target_asins = {a.strip().upper() for a in args.target_asins.split(",") if a.strip()}
    token_mgr = FeishuTokenManager()
    run_label = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")

    spreadsheet_token = args.spreadsheet_token
    spreadsheet_url = args.spreadsheet_url
    if not spreadsheet_token:
        title = f"关键词竞品前三页自然排名 - {keyword[:40]}"
        spreadsheet_token, spreadsheet_url = create_spreadsheet(token_mgr.token, title)
        grant_user_permission(token_mgr.token, spreadsheet_token)

    snapshot_sheet_id = get_or_create_sheet(token_mgr.token, spreadsheet_token, "竞对快照", index=0)
    rows = [
        ["关键词", keyword],
        ["更新时间", run_label],
        ["抓取页数", pages],
        ["邮编", ", ".join(zipcodes)],
        ["标黄ASIN", ", ".join(sorted(target_asins))],
        ["表格链接", spreadsheet_url or spreadsheet_token],
        [],
        ["邮编", "页码", "页内自然位", "自然排名", "ASIN", "品牌", "评分", "评分数量", "价格", "标题"],
    ]
    own_rows = []
    results_by_zipcode = {}

    for zipcode in zipcodes:
        print(f"查询: {keyword} / {zipcode}", flush=True)
        ranker = AmazonRanker(zipcode)
        try:
            results = first_pages_organic_results(ranker, keyword, max_pages=pages)
        finally:
            ranker.close()

        results_by_zipcode[zipcode] = results
        for result in results:
            row_number = len(rows) + 1
            rows.append([
                zipcode,
                result["page"],
                result["page_organic_rank"],
                result["natural_rank"],
                result["asin"],
                result["brand"],
                result["rating"],
                result["review_count"],
                result["price"],
                result["title"],
            ])
            if result["asin"] in target_asins:
                own_rows.append(row_number)
        rows.append(["", "", "", "", "", "", "", "", "", ""])
        time.sleep(1)

    write_values(token_mgr.token, spreadsheet_token, snapshot_sheet_id, "A1", rows)
    style_rows(token_mgr.token, spreadsheet_token, snapshot_sheet_id, own_rows)
    send_private_notification(keyword, results_by_zipcode, target_asins, spreadsheet_url or spreadsheet_token, run_label)

    print("\n✅ 关键词竞对快照完成")
    print(spreadsheet_url or spreadsheet_token)


if __name__ == "__main__":
    main()
