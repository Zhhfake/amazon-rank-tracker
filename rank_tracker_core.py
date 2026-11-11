Warning: truncated output (original token count: 15932)
Total output lines: 1534

#!/usr/bin/env python3
"""
Amazon 自然位排名追踪 — 核心逻辑
==================================
这个文件不需要改。所有配置都在 config.py 里。

用法:
  python rank_to_feishu.py                    # 跑所有产品
  python rank_to_feishu.py --sheet "产品A"     # 只跑指定产品
  python rank_to_feishu.py --check-only       # 检查今天是否已跑（供云端判断）
  python rank_to_feishu.py --notify-only      # 只发飞书日报（不查排名）
  python rank_to_feishu.py --color-all        # 给所有历史数据补上色
  python rank_to_feishu.py --limit 50         # 最多查50个新词（配合断点续传分段跑）
  python rank_to_feishu.py --skip-if-recent 55 # 55分钟内跑过则跳过（给云端定时用）
"""

import urllib.request, urllib.parse, urllib.error, re, time, json, sys, datetime, os, signal, traceback, random

# 导入配置（用户只需要改 config.py）
try:
    from config import *
except ImportError:
    print("❌ 找不到 config.py！请先复制 config_template.py 为 config.py 并填入你的配置。")
    sys.exit(1)

_script_start_time = time.time()

# ====== 飞书 API 工具 ======

def feishu_api(method, url, data=None, token=None, retries=3):
    """调用飞书 API，带重试和限频处理"""
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    body = json.dumps(data).encode() if data else None
    for attempt in range(retries):
        req = urllib.request.Request(url, data=body, headers=headers, method=method)
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                return json.loads(resp.read())
        except urllib.error.HTTPError as e:
            error_body = e.read().decode("utf-8", errors="replace")
            if e.code == 429 and attempt < retries - 1:
                wait = 3 * (attempt + 1)
                print(f"  ⏳ 飞书限频，{wait}秒后重试...", flush=True)
                time.sleep(wait)
                continue
            print(f"  飞书API错误: {e.code} {e.reason}", flush=True)
            print(f"  请求: {method} {url}", flush=True)
            if data:
                print(f"  请求体: {json.dumps(data, ensure_ascii=False)[:500]}", flush=True)
            print(f"  响应: {error_body[:500]}", flush=True)
            raise
        except Exception as e:
            if attempt < retries - 1:
                print(f"  ⏳ 请求超时/异常，重试中... ({e})", flush=True)
                time.sleep(2)
                continue
            raise


class FeishuTokenManager:
    """自动管理飞书 token，过期前自动刷新"""
    def __init__(self):
        self._token = None
        self._expire_at = 0

    @property
    def token(self):
        if time.time() >= self._expire_at - 300:
            self._refresh()
        return self._token

    def _refresh(self):
        resp = feishu_api("POST", "https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal",
                          {"app_id": FEISHU_APP_ID, "app_secret": FEISHU_APP_SECRET})
        self._token = resp["tenant_access_token"]
        self._expire_at = time.time() + resp.get("expire", 7200)
        print("  🔑 飞书 token 已刷新")


# ====== 表格工具函数 ======

def col_letter(idx):
    """0-based index -> Excel 列字母 (0=A, 25=Z, 26=AA)"""
    result = ""
    n = idx + 1
    while n > 0:
        n -= 1
        result = chr(n % 26 + ord('A')) + result
        n //= 26
    return result


def col_index(letter):
    """Excel 列字母 -> 0-based index (A=0, Z=25, AA=26)"""
    result = 0
    for ch in str(letter).strip().upper():
        if not ('A' <= ch <= 'Z'):
            continue
        result = result * 26 + (ord(ch) - ord('A') + 1)
    return max(result - 1, 0)


def _is_date_value(v):
    """判断单元格值是否是日期（序列号或 M/D 字符串）"""
    if isinstance(v, str) and re.match(r'^\d{1,2}/\d{1,2}(?:\s+\d{1,2}:\d{2})?$', v.strip()):
        return True
    if isinstance(v, str) and re.match(r'^\d{1,2}/\d{1,2}-\d{5}$', v):
        return True
    if isinstance(v, (int, float)) and v > 40000:
        return True
    return False


def _parse_run_label_datetime(value, now=None):
    """解析表头里的 'M/D HH:MM' 批次时间。"""
    if not value:
        return None
    text = str(value).strip()
    m = re.match(r'^(\d{1,2})/(\d{1,2})\s+(\d{1,2}):(\d{2})$', text)
    if not m:
        return None
    now = now or datetime.datetime.now()
    month, day, hour, minute = map(int, m.groups())
    try:
        dt = datetime.datetime(now.year, month, day, hour, minute)
    except ValueError:
        return None
    if dt - now > datetime.timedelta(days=180):
        dt = dt.replace(year=dt.year - 1)
    return dt


def latest_sheet_run_time(token, config):
    """读取一个产品表里最近一次带时间的批次表头。"""
    sheet_id = config["sheet_id"]
    date_row = config.get("date_row", 1)
    min_col_idx = col_index(config.get("result_start_col", "A"))
    base = f"https://open.feishu.cn/open-apis/sheets/v2/spreadsheets/{SPREADSHEET_TOKEN}"
    resp = feishu_api("GET", f"{base}/values/{sheet_id}!A{date_row}:ZZ{date_row}", token=token)
    row = resp["data"]["valueRange"].get("values", [[]])[0]
    now = datetime.datetime.now()
    latest = None
    for value in row[min_col_idx:]:
        dt = _parse_run_label_datetime(value, now)
        if dt and (latest is None or dt > latest):
            latest = dt
    return latest


def should_skip_recent_run(token, minutes):
    """云端高频触发时，避免短时间内重复写入。"""
    latest_times = []
    for config in PRODUCTS:
        try:
            latest = latest_sheet_run_time(token, config)
            if latest:
                latest_times.append(latest)
        except Exception as e:
            print(f"  ⚠ 检查最近运行时间失败 {config.get('name')}: {e}", flush=True)
    if not latest_times:
        return False

    latest = max(latest_times)
    age_minutes = (datetime.datetime.now() - latest).total_seconds() / 60
    print(f"最近一次表格写入: {latest.strftime('%m/%d %H:%M')}，距今 {age_minutes:.0f} 分钟", flush=True)
    if age_minutes < minutes:
        print(f"✅ {minutes} 分钟内已经跑过，本次云端触发跳过，避免重复写表。", flush=True)
        return True
    return False


def find_next_date_column(token, sheet_id, date_row=2, min_col_idx=0, header_label=None):
    """找到日期行应该写入的列（0-based index）。
    从右往左找连续日期块的末尾，跳过孤立的远端日期。"""
    base = f"https://open.feishu.cn/open-apis/sheets/v2/spreadsheets/{SPREADSHEET_TOKEN}"
    resp = feishu_api("GET", f"{base}/values/{sheet_id}!A{date_row}:ZZ{date_row}", token=token)
    row = resp["data"]["valueRange"]["values"][0]

    today = datetime.date.today()
    today_str = f"{today.month}/{today.day}"
    target_label = header_label or today_str
    epoch = datetime.date(1899, 12, 30)
    today_serial = (today - epoch).days

    # 先检查今天的日期是否已存在
    for i, v in enumerate(row):
        if v is None:
            continue
        if isinstance(v, str) and v == target_label:
            if i >= min_col_idx:
                print(f"  ⚠ {target_label} 已存在于列 {col_letter(i)}, 将续传补充数据")
                return i, today_str
        if not header_label and isinstance(v, (int, float)) and int(v) == today_serial:
            if i >= min_col_idx:
                print(f"  ⚠ 今天的日期已存在于列 {col_letter(i)}, 将续传补充数据")
                return i, today_str

    # 从右往左找连续日期块的末尾
    for i in range(len(row) - 1, -1, -1):
        if row[i] is None or row[i] == "":
            continue
        if not _is_date_value(row[i]):
            continue
        has_neighbor = False
        for offset in range(1, 3):
            ni = i - offset
            if ni >= 0 and row[ni] is not None and _is_date_value(row[ni]):
                has_neighbor = True
                break
        if has_neighbor:
            target = max(i + 1, min_col_idx)
            print(f"  📍 最后连续日期在列 {col_letter(i)}, 新数据写入列 {col_letter(target)}")
            return target, today_str
        else:
            print(f"  ⚠ 跳过孤立日期: 列{col_letter(i)}={row[i]}")

    # 兜底：找第一个空列
    for i, v in enumerate(row):
        if i < min_col_idx:
            continue
        if v is None or v == "":
            return i, today_str
    return max(len(row), min_col_idx), today_str


def find_next_zipcode_column(token, sheet_id, date_row, zipcode_row, zipcode, min_col_idx=0,
                             date_label=None, reuse_existing=True):
    """找到某次运行的邮编列，表头为日期/时间行 + 邮编行。"""
    base = f"https://open.feishu.cn/open-apis/sheets/v2/spreadsheets/{SPREADSHEET_TOKEN}"
    today = datetime.date.today()
    today_str = date_label or f"{today.month}/{today.day}"
    zip_label = str(zipcode)
    legacy_label = f"{today_str}-{zip_label}"

    resp = feishu_api("GET", f"{base}/values/{sheet_id}!A{date_row}:ZZ{zipcode_row}", token=token)
    rows = resp["data"]["valueRange"].get("values", [])
    date_values = rows[0] if rows else []
    zip_values = rows[zipcode_row - date_row] if len(rows) > zipcode_row - date_row else []
    width = max(len(date_values), len(zip_values))
    effective_dates = []
    current_date = None
    for i in range(width):
        raw_date = date_values[i] if i < len(date_values) else None
        if raw_date not in (None, ""):
            current_date = raw_date
        effective_dates.append(current_date)

    if reuse_existing:
        for i in range(min_col_idx, width):
            date_val = effective_dates[i] if i < len(effective_dates) else None
            zip_val = zip_values[i] if i < len(zip_values) else None
            if str(date_val or "").strip() == today_str and str(zip_val or "").strip() == zip_label:
                print(f"  ⚠ {today_str}/{zip_label} 已存在于列 {col_letter(i)}, 将续传补充数据")
                return i, today_str
            if str(zip_val or "").strip() == legacy_label:
                print(f"  ⚠ 发现旧表头 {legacy_label} 在列 {col_letter(i)}, 将转换为双行表头")
                return i, today_str

    for i in range(min_col_idx, width):
        date_val = date_values[i] if i < len(date_values) else None
        zip_val = zip_values[i] if i < len(zip_values) else None
        if (date_val is None or date_val == "") and (zip_val is None or zip_val == ""):
            return i, today_str

    return max(width, min_col_idx), today_str


def find_latest_zipcode_column(token, sheet_id, date_row, zipcode_row, zipcode, min_col_idx=0):
    """找到最右侧一列同邮编数据，用于日报读取最新一次运行。"""
    base = f"https://open.feishu.cn/open-apis/sheets/v2/spreadsheets/{SPREADSHEET_TOKEN}"
    resp = feishu_api("GET", f"{base}/values/{sheet_id}!A{date_row}:ZZ{zipcode_row}", token=token)
    rows = resp["data"]["valueRange"].get("values", [])
    zip_values = rows[zipcode_row - date_row] if len(rows) > zipcode_row - date_row else []
    legacy_pattern = re.compile(r'^\d{1,2}/\d{1,2}(?: \d{2}:\d{2})?-' + re.escape(str(zipcode)) + r'$')
    for i in range(len(zip_values) - 1, min_col_idx - 1, -1):
        zip_val = str(zip_values[i] if zip_values[i] is not None else "").strip()
        if zip_val == str(zipcode) or legacy_pattern.match(zip_val):
            return i
    return None


def merge_date_header(token, sheet_id, date_row, start_col_idx, end_col_idx):
    """合并同一天多个邮编上方的日期单元格。失败不影响排名数据。"""
    if end_col_idx <= start_col_idx:
        return
    base = f"https://open.feishu.cn/open-apis/sheets/v2/spreadsheets/{SPREADSHEET_TOKEN}"
    start_col = col_letter(start_col_idx)
    end_col = col_letter(end_col_idx)
    try:
        feishu_api("POST", f"{base}/merge_cells", {
            "range": f"{sheet_id}!{start_col}{date_row}:{end_col}{date_row}",
            "mergeType": "MERGE_ALL",
        }, token=token)
        print(f"  ✅ 已合并日期表头: {start_col}{date_row}:{end_col}{date_row}")
    except Exception as e:
        print(f"  ⚠ 日期表头合并失败（不影响数据）: {e}")


def find_previous_zipcode_column(token, sheet_id, today_col_idx, date_row, zipcode_row, zipcode, min_col_idx=0):
    """找到当前列左侧最近一个相同邮编的历史列。"""
    base = f"https://open.feishu.cn/open-apis/sheets/v2/spreadsheets/{SPREADSHEET_TOKEN}"
    resp = feishu_api("GET", f"{base}/values/{sheet_id}!A{date_row}:ZZ{zipcode_row}", token=token)
    rows = resp["data"]["valueRange"].get("values", [])
    date_values = rows[0] if rows else []
    zip_values = rows[zipcode_row - date_row] if len(rows) > zipcode_row - date_row else []
    legacy_pattern = re.compile(r'^\d{1,2}/\d{1,2}-' + re.escape(str(zipcode)) + r'$')
    width = max(len(date_values), len(zip_values), today_col_idx + 1)
    effective_dates = []
    current_date = None
    for i in range(width):
        raw_date = date_values[i] if i < len(date_values) else None
        if raw_date not in (None, ""):
            current_date = raw_date
        effective_dates.append(current_date)
    current_col_date = effective_dates[today_col_idx] if today_col_idx < len(effective_dates) else None

    for i in range(today_col_idx - 1, min_col_idx - 1, -1):
        zip_val = str(zip_values[i] if i < len(zip_values) and zip_values[i] is not None else "").strip()
        date_val = effective_dates[i] if i < len(effective_dates) else None
        is_same_zip = zip_val == str(zipcode) or legacy_pattern.match(zip_val)
        is_previous_date = str(date_val or "").strip() != str(current_col_date or "").strip()
        if is_same_zip and is_previous_date:
            return i
    return None


def read_existing_column(token, sheet_id, col, start_row, end_row):
    """读取今天列已有的数据，用于断点续传"""
    base = f"https://open.feishu.cn/open-apis/sheets/v2/spreadsheets/{SPREADSHEET_TOKEN}"
    try:
        resp = feishu_api("GET", f"{base}/values/{sheet_id}!{col}{start_row}:{col}{end_row}", token=token)
        return resp["data"]["valueRange"].get("values", [])
    except:
        return []


def read_column_data(token, sheet_id, col_idx, start_row, end_row):
    """读取指定列的排名数据"""
    if col_idx < 0:
        return []
    base = f"https://open.feishu.cn/open-apis/sheets/v2/spreadsheets/{SPREADSHEET_TOKEN}"
    cl = col_letter(col_idx)
    try:
        resp = feishu_api("GET", f"{base}/values/{sheet_id}!{cl}{start_row}:{cl}{end_row}", token=token)
        return resp["data"]["valueRange"].get("values", [])
    except:
        return []


# ====== Amazon 排名查询 (Playwright) ======

class AmazonRanker:
    def __init__(self, zipcode=ZIPCODE):
        from playwright.sync_api import sync_playwright
        self.zipcode = zipcode
        self.consecutive_failures = 0
        self.blocked = False
        self._recovery_attempted = False
        self._pw = sync_playwright().start()
        self._browser = None
        self._context = None
        self._page = None
        self._init_browser()

    def _init_browser(self):
        """启动浏览器并设置地址"""
        if self._context:
            try: self._context.close()
            except: pass
        if self._browser:
            try: self._browser.close()
            except: pass

        self._browser = self._pw.chromium.launch(headless=True)
        self._context = self._browser.new_context(
            user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/136.0.0.0 Safari/537.36",
            viewport={"width": 1440, "height": 900},
            locale="en-US",
            timezone_id="America/Los_Angeles",
        )
        self._context.route("**/*.{png,jpg,jpeg,gif,webp,svg,woff,woff2,ttf}", lambda route: route.abort())
        self._page = self._context.new_page()

        try:
            self._page.goto("https://www.amazon.com/?mr_donotredirect", wait_until="domcontentloaded", timeout=30000)
            time.sleep(2)
            self._page.evaluate("""
                async (zipcode) => {
                    await fetch('https://www.amazon.com/portal-migration/hz/glow/address-change?actionSource=glow', {
                        method: 'POST',
                        headers: {'Content-Type': 'application/x-www-form-urlencoded'},
                        body: 'locationType=LOCATION_INPUT&storeContext=sporting-goods&deviceType=web&pageType=Detail&actionSource=glow&almBrandId=undefined&zipCode=' + zipcode
                    });
                }
            """, self.zipcode)
            time.sleep(1)
            print("  🌐 浏览器已启动，邮编已设置", flush=True)
        except Exception as e:
            print(f"  ⚠ 浏览器初始化警告: {e}", flush=True)

    def _is_blocked_page(self, html):
        """检测 Amazon 反爬页面"""
        block_signals = [
            "To discuss automated access to Amazon data",
            "api-services-support@amazon.com",
            "Sorry, we just need to make sure you're not a robot",
            "Type the characters you see in this image",
            "Enter the characters you see below",
        ]
        return any(s in html for s in block_signals)

    def _fetch_page(self, url, max_retries=3):
        """用 Playwright 加载页面，带重试"""
        for attempt in range(max_retries):
            try:
                resp = self._page.goto(url, wait_until="domcontentloaded", timeout=30000)
                if resp and resp.status == 503:
                    if attempt == max_retries - 1:
                        self.consecutive_failures += 1
                        raise Exception("503 Service Unavailable")
                    wait = [30, 90, 180][min(attempt, 2)]
                    print(f"    503, {wait}秒后重试 ({attempt+1}/{max_retries})...", flush=True)
                    time.sleep(wait)
                    if attempt >= 1:
                        self._init_browser()
                    continue
                try:
                    self._page.wait_for_selector('[data-component-type="s-search-result"]', timeout=8000)
                except:
                    pass
                html = self._page.content()
                self.consecutive_failures = 0
                return html
            except Exception as e:
                if attempt == max_retries - 1:
                    self.consecutive_failures += 1
                    raise
                wait = [10, 30][min(attempt, 1)]
                print(f"    加载异常: {e}, {wait}秒后重试...", flush=True)
                time.sleep(wait)
                try:
                    self._init_browser()
                except:
                    pass

    def reset_for_product(self):
        """每个产品开始时重置状态"""
        self.consecutive_failures = 0
        self.blocked = False
        self._recovery_attempted = False

    def close(self):
        """关闭浏览器"""
        try:
            if self._context: self._context.close()
            if self._browser: self._browser.close()
            if self._pw: self._pw.stop()
        except:
            pass

    def find_rank(self, keyword, target_asin, max_pages=MAX_PAGES):
        """搜索关键词，只返回独立商品卡片中的目标 ASIN 自然位。"""
        return self.find_ranks(keyword, [target_asin], max_pages=max_pages).get(target_asin, "—")

    def find_ranks(self, keyword, target_asins, max_pages=MAX_PAGES):
        """搜索关键词，一次返回多个目标 ASIN 的…5932 tokens truncated…fig["sheet_id"]
    kw_col = config["kw_col"]
    start_row = config["kw_start_row"]
    end_row = config["kw_end_row"]
    date_row = config.get("date_row", 2)
    zipcode_row = config.get("zipcode_row", date_row + 1)
    result_start_col = config.get("result_start_col", "A")
    product_max_pages = config.get("max_pages", MAX_PAGES)

    print(f"\n{'='*50}")
    print(f"处理: {config['name']} 多ASIN 邮编 {zipcode} ({len(tracked_asins)}个ASIN)")
    print(f"{'='*50}")

    base = f"https://open.feishu.cn/open-apis/sheets/v2/spreadsheets/{SPREADSHEET_TOKEN}"
    resp = feishu_api("GET", f"{base}/values/{sheet_id}!{kw_col}{start_row}:{kw_col}{end_row}", token=token_mgr.token)
    rows = resp["data"]["valueRange"]["values"]
    while rows and (not rows[-1] or rows[-1][0] is None):
        rows.pop()

    keywords = [(r[0].strip() if r and r[0] else None) for r in rows]
    total = sum(1 for k in keywords if k)
    print(f"  关键词数量: {total}, 搜索页数: {product_max_pages}")

    columns = []
    next_col_idx = None
    for tracked in tracked_asins:
        label = f"{zipcode}-{tracked['name']}"
        if next_col_idx is None:
            col_idx, today_label = find_next_zipcode_column(
                token_mgr.token,
                sheet_id,
                date_row,
                zipcode_row,
                label,
                col_index(result_start_col),
                run_label,
                config.get("reuse_existing", True),
            )
            next_col_idx = col_idx + 1
        elif config.get("reuse_existing", True):
            col_idx, today_label = find_next_zipcode_column(
                token_mgr.token,
                sheet_id,
                date_row,
                zipcode_row,
                label,
                next_col_idx,
                run_label,
                True,
            )
            next_col_idx = col_idx + 1
        else:
            col_idx = next_col_idx
            today_label = run_label
            next_col_idx += 1
        columns.append({"tracked": tracked, "label": label, "col_idx": col_idx, "col": col_letter(col_idx)})

    start_col_idx = min(c["col_idx"] for c in columns)
    end_col_idx = max(c["col_idx"] for c in columns)
    print(f"  写入列: {col_letter(start_col_idx)}:{col_letter(end_col_idx)} (日期: {run_label})")

    existing_by_asin = {}
    values_by_asin = {c["tracked"]["asin"]: [] for c in columns}
    for c in columns:
        existing_by_asin[c["tracked"]["asin"]] = read_existing_column(
            token_mgr.token, sheet_id, c["col"], start_row, start_row - 1 + len(keywords)
        )

    ranker.reset_for_product()
    kw_limit = getattr(sys.modules[__name__], '_keyword_limit', None)
    target_asins = [c["tracked"]["asin"] for c in columns]
    done = 0
    new_queried = 0
    skipped_count = 0
    print("  开始查询排名... (同关键词一次搜索多个ASIN)")

    for i, kw in enumerate(keywords):
        if not kw:
            for asin in target_asins:
                values_by_asin[asin].append([None])
            continue

        existing_complete = True
        for asin in target_asins:
            existing = existing_by_asin[asin]
            if not (i < len(existing) and existing[i] and existing[i][0] and str(existing[i][0]).startswith("Page")):
                existing_complete = False
                break
        if existing_complete:
            for asin in target_asins:
                values_by_asin[asin].append([existing_by_asin[asin][i][0]])
            done += 1
            skipped_count += 1
            continue

        if kw_limit and new_queried >= kw_limit:
            for asin in target_asins:
                values_by_asin[asin].append(["—"])
            done += 1
            continue

        ranks = ranker.find_ranks(kw, target_asins, max_pages=product_max_pages)
        for asin in target_asins:
            values_by_asin[asin].append([ranks.get(asin, "—")])
        done += 1
        new_queried += 1
        if done % 10 == 0:
            skipped = " (被封后跳过)" if ranker.blocked else ""
            print(f"    进度: {done}/{total}{skipped}")
        if not ranker.blocked:
            time.sleep(DELAY_BETWEEN_KEYWORDS + random.uniform(-1, 1))

    if skipped_count:
        print(f"  ♻️ 续传: 复用了 {skipped_count} 个已有关键词结果，实际新查 {done - skipped_count} 个关键词")

    write_url = f"{base}/values"
    for c in columns:
        col = c["col"]
        asin = c["tracked"]["asin"]
        values = values_by_asin[asin]
        feishu_api("PUT", write_url, {
            "valueRange": {"range": f"{sheet_id}!{col}{date_row}:{col}{zipcode_row}", "values": [[run_label], [c["label"]]]}
        }, token=token_mgr.token)
        data_end_row = start_row - 1 + len(values)
        feishu_api("PUT", write_url, {
            "valueRange": {"range": f"{sheet_id}!{col}{start_row}:{col}{data_end_row}", "values": values}
        }, token=token_mgr.token)
        apply_rank_colors(
            token_mgr.token,
            sheet_id,
            c["col_idx"],
            start_row,
            values,
            date_row,
            zipcode_row,
            c["label"],
            col_index(result_start_col),
        )

    found_primary = sum(1 for v in values_by_asin[target_asins[0]] if v[0] and v[0] != "—")
    print(f"  ✅ 写入完成! {len(columns)}列，主ASIN找到 {found_primary}/{total}")
    return found_primary, total


def notify_only():
    """只读取飞书已有数据，按产品和邮编生成日报并发通知"""
    print("📊 仅发送通知模式...")
    token_mgr = FeishuTokenManager()
    summary = {}

    for config in PRODUCTS:
        name = config["name"]
        sheet_id = config["sheet_id"]
        date_row = config.get("date_row", 1)
        zipcode_row = config.get("zipcode_row", date_row + 1)
        start_row = config["kw_start_row"]
        end_row = config["kw_end_row"]
        min_col_idx = col_index(config.get("result_start_col", "A"))
        try:
            kw_col = config["kw_col"]
            base_kw = f"https://open.feishu.cn/open-apis/sheets/v2/spreadsheets/{SPREADSHEET_TOKEN}"
            kw_resp = feishu_api("GET", f"{base_kw}/values/{sheet_id}!{kw_col}{start_row}:{kw_col}{end_row}", token=token_mgr.token)
            kw_rows = kw_resp["data"]["valueRange"].get("values", [])
            total = sum(1 for r in kw_rows if r and r[0] and str(r[0]).strip())

            zip_summary = []
            tracked_asins = config.get("track_asins")
            primary_name = tracked_asins[0].get("name") if tracked_asins else None
            for zipcode in config.get("zipcodes") or [config.get("zipcode", ZIPCODE)]:
                lookup_label = f"{zipcode}-{primary_name}" if primary_name else zipcode
                today_col_idx = find_latest_zipcode_column(
                    token_mgr.token, sheet_id, date_row, zipcode_row, lookup_label, min_col_idx
                )
                if today_col_idx is None:
                    zip_summary.append({"zipcode": zipcode, "found": 0, "total": total})
                    continue
                existing = read_existing_column(
                    token_mgr.token, sheet_id, col_letter(today_col_idx), start_row, end_row
                )
                found = sum(1 for r in existing if r and r[0] and str(r[0]).startswith("Page"))
                zip_summary.append({"zipcode": zipcode, "found": found, "total": total})

            summary[name] = {"zipcodes": zip_summary}
        except Exception as e:
            print(f"  ❌ {name}: {e}")
            summary[name] = str(e)

    send_feishu_notification(summary, globals().get("NOTIFICATION_DEFAULT_TARGET", "private"))


def check_only():
    """检查今天是否已有数据"""
    print("🔍 检查本地今天是否跑过...", flush=True)
    token_mgr = FeishuTokenManager()
    today = datetime.date.today()
    today_str = f"{today.month}/{today.day}"
    epoch = datetime.date(1899, 12, 30)
    today_serial = (today - epoch).days

    for config in PRODUCTS:
        name = config["name"]
        sheet_id = config["sheet_id"]
        date_row = config.get("date_row", 2)
        try:
            today_col_idx, _ = find_next_date_column(token_mgr.token, sheet_id, date_row)
            base = f"https://open.feishu.cn/open-apis/sheets/v2/spreadsheets/{SPREADSHEET_TOKEN}"
            resp = feishu_api("GET", f"{base}/values/{sheet_id}!{col_letter(today_col_idx)}{date_row}:{col_letter(today_col_idx)}{date_row}", token=token_mgr.token)
            date_val = resp["data"]["valueRange"]["values"][0][0] if resp["data"]["valueRange"].get("values") else None
            if date_val:
                if (isinstance(date_val, str) and date_val == today_str) or \
                   (isinstance(date_val, (int, float)) and int(date_val) == today_serial):
                    print(f"  ✅ {name} 有今天的数据，本地已经跑了", flush=True)
                    sys.exit(0)
        except Exception as e:
            print(f"  ⚠ {name}: 检查异常 ({e})", flush=True)

    print("\n❌ 所有产品都没有今天的数据，本地没跑", flush=True)
    sys.exit(1)


def color_all_sheets():
    """给所有 sheet 的所有历史日期列回溯上色"""
    print("🎨 全量上色模式...", flush=True)
    token_mgr = FeishuTokenManager()
    base = f"https://open.feishu.cn/open-apis/sheets/v2/spreadsheets/{SPREADSHEET_TOKEN}"

    for config in PRODUCTS:
        name = config["name"]
        sheet_id = config["sheet_id"]
        date_row = config.get("date_row", 2)
        start_row = config["kw_start_row"]

        print(f"\n{'='*50}\n上色: {name}", flush=True)

        resp = feishu_api("GET", f"{base}/values/{sheet_id}!A{date_row}:ZZ{date_row}", token=token_mgr.token)
        date_row_data = resp["data"]["valueRange"]["values"][0]

        date_cols = [i for i, v in enumerate(date_row_data) if v is not None and _is_date_value(v)]

        if not date_cols:
            print(f"  只有{len(date_cols)}列日期数据，跳过", flush=True)
            continue

        print(f"  找到 {len(date_cols)} 列日期数据", flush=True)

        first_col = col_letter(date_cols[0])
        last_col = col_letter(date_cols[-1])
        end_row = config["kw_end_row"]
        resp = feishu_api("GET", f"{base}/values/{sheet_id}!{first_col}{start_row}:{last_col}{end_row}", token=token_mgr.token)
        all_data = resp["data"]["valueRange"].get("values", [])

        for col_pos in range(len(date_cols)):
            today_abs = date_cols[col_pos]
            today_rel = today_abs - date_cols[0]
            col = col_letter(today_abs)

            green_rows, yellow_rows, red_rows, white_rows = [], [], [], []

            for row_i in range(len(all_data)):
                t_val = all_data[row_i][today_rel] if today_rel < len(all_data[row_i]) else None
                t_rank = parse_rank(t_val)
                row_num = start_row + row_i
                bucket = _rank_color_bucket(t_rank, t_val)
                if bucket == "green":
                    green_rows.append(row_num)
                elif bucket == "yellow":
                    yellow_rows.append(row_num)
                elif bucket == "red":
                    red_rows.append(row_num)
                else:
                    white_rows.append(row_num)

            data = []
            if green_rows:
                data.append({"ranges": _merge_consecutive_rows(green_rows, sheet_id, col), "style": {"backColor": "#D5F5E3"}})
            if yellow_rows:
                data.append({"ranges": _merge_consecutive_rows(yellow_rows, sheet_id, col), "style": {"backColor": "#FCF3CF"}})
            if red_rows:
                data.append({"ranges": _merge_consecutive_rows(red_rows, sheet_id, col), "style": {"backColor": "#FADBD8"}})
            if white_rows:
                data.append({"ranges": _merge_consecutive_rows(white_rows, sheet_id, col), "style": {"backColor": "#FFFFFF"}})

            if data:
                try:
                    feishu_api("PUT", f"{base}/styles_batch_update", {"data": data}, token=token_mgr.token)
                except Exception as e:
                    print(f"    列{col}上色失败: {e}", flush=True)

            done_cols = col_pos + 1
            if done_cols % 5 == 0 or done_cols == len(date_cols):
                print(f"  进度: {done_cols}/{len(date_cols)} 列", flush=True)
            time.sleep(0.3)

        print(f"  ✅ {name} 完成", flush=True)

    print("\n🎨 全量上色完成!", flush=True)


def main():
    if len(sys.argv) > 1 and sys.argv[1] == "--check-only":
        check_only()
        return
    if len(sys.argv) > 1 and sys.argv[1] == "--color-all":
        color_all_sheets()
        return
    if len(sys.argv) > 1 and sys.argv[1] == "--notify-only":
        notify_only()
        return

    target_asin = sys.argv[1] if len(sys.argv) > 1 and not sys.argv[1].startswith("--") else None
    target_sheet = None
    keyword_limit = None
    skip_if_recent_minutes = None
    notify_target = globals().get("NOTIFICATION_DEFAULT_TARGET", "private")
    args = sys.argv[1:]
    if "--sheet" in args:
        idx = args.index("--sheet")
        target_sheet = args[idx + 1]
        target_asin = None
    if "--limit" in args:
        idx = args.index("--limit")
        keyword_limit = int(args[idx + 1])
    if "--skip-if-recent" in args:
        idx = args.index("--skip-if-recent")
        skip_if_recent_minutes = int(args[idx + 1])
    if "--notify" in args:
        idx = args.index("--notify")
        notify_target = args[idx + 1]
        if notify_target not in ("group", "private", "both", "none"):
            print("未知通知方式，请使用: group / private / both / none")
            sys.exit(1)

    run_label = f"{datetime.date.today().month}/{datetime.date.today().day} {datetime.datetime.now().strftime('%H:%M')}"
    expanded_products = []
    for product in PRODUCTS:
        zipcodes = product.get("zipcodes") or [product.get("zipcode", ZIPCODE)]
        for zipcode in zipcodes:
            item = dict(product)
            item["zipcode"] = zipcode
            item["run_label"] = run_label
            item["reuse_existing"] = False
            if not item.get("track_asins"):
                item["tracked_name"] = item.get("name", item["asin"])
                item["zipcode_label"] = zipcode
            expanded_products.append(item)

    all_asins = set(p["asin"] for p in expanded_products)
    all_names = [p["name"] for p in PRODUCTS]
    if target_asin and target_asin not in all_asins:
        print(f"未知 ASIN: {target_asin}\n已配置的 ASIN: {', '.join(sorted(all_asins))}")
        sys.exit(1)
    if target_sheet and target_sheet not in all_names:
        print(f"未知 sheet: {target_sheet}\n已配置的: {', '.join(all_names)}")
        sys.exit(1)

    sys.modules[__name__]._keyword_limit = keyword_limit

    print("初始化飞书连接...")
    token_mgr = FeishuTokenManager()
    if skip_if_recent_minutes and should_skip_recent_run(token_mgr.token, skip_if_recent_minutes):
        return
    print(f"本次运行批次: {run_label}")
    print("准备就绪!\n")

    if target_sheet:
        products_to_run = [p for p in expanded_products if p["name"] == target_sheet]
    elif target_asin:
        products_to_run = [p for p in expanded_products if p["asin"] == target_asin]
    else:
        products_to_run = list(expanded_products)

    _terminating = [False]
    def _on_sigterm(signum, frame):
        print(f"\n  ⚠ 收到终止信号，当前产品完成后将保存数据并退出...", flush=True)
        _terminating[0] = True
    signal.signal(signal.SIGTERM, _on_sigterm)

    results = {}
    sheet_columns = {}
    merge_groups = {}
    zipcode_order = []
    products_by_zipcode = {}
    for config in products_to_run:
        zipcode = config.get("zipcode", ZIPCODE)
        if zipcode not in products_by_zipcode:
            zipcode_order.append(zipcode)
            products_by_zipcode[zipcode] = []
        products_by_zipcode[zipcode].append(config)

    for zipcode in zipcode_order:
        ranker = None
        try:
            print(f"初始化浏览器（邮编 {zipcode}）...")
            ranker = AmazonRanker(zipcode)
            for config in products_by_zipcode[zipcode]:
                if _terminating[0]:
                    print(f"\n  ⏹ 收到终止信号，跳过 {config['name']}...")
                    break
                try:
                    if config.get("track_asins"):
                        found, found_total_keywords = process_product_multi_asin(config, token_mgr, ranker)
                    else:
                        found, found_total_keywords = process_product(config, token_mgr, ranker)
                    result_name = f"{config['name']}-{config.get('zipcode', ZIPCODE)}"
                    results[result_name] = {"found": found, "total": found_total_keywords, "config": config}
                    date_row = config.get("date_row", 2)
                    zipcode_row = config.get("zipcode_row", date_row + 1)
                    lookup_label = config.get("zipcode", ZIPCODE)
                    if config.get("track_asins"):
                        lookup_label = f"{lookup_label}-{config['track_asins'][0]['name']}"
                    today_col_idx, _ = find_next_zipcode_column(
                        token_mgr.token,
                        config["sheet_id"],
                        date_row,
                        zipcode_row,
                        lookup_label,
                        col_index(config.get("result_start_col", "A")),
                        config.get("run_label"),
                        True,
                    )
                    sheet_columns[result_name] = today_col_idx
                    merge_key = (config["sheet_id"], date_row)
                    merge_groups.setdefault(merge_key, []).append(today_col_idx)
                except Exception as e:
                    print(f"  ❌ 出错: {e}")
                    traceback.print_exc()
                    result_name = f"{config['name']}-{config.get('zipcode', ZIPCODE)}"
                    results[result_name] = str(e)
        except Exception as e:
            print(f"  ❌ 邮编 {zipcode} 浏览器初始化失败: {e}")
            traceback.print_exc()
            for config in products_by_zipcode[zipcode]:
                result_name = f"{config['name']}-{config.get('zipcode', ZIPCODE)}"
                results[result_name] = str(e)
        finally:
            if ranker:
                ranker.close()

    # 汇总
    print(f"\n{'='*50}\n汇总:")
    for name, info in results.items():
        if isinstance(info, str):
            print(f"  {name}: 错误 - {info}")
        else:
            print(f"  {name}: {info['found']}/{info['total']}")

    for (sheet_id, date_row), cols in merge_groups.items():
        if cols:
            merge_date_header(token_mgr.token, sheet_id, date_row, min(cols), max(cols))

    is_partial = target_asin or target_sheet
    should_notify = notify_target != "none" and (not is_partial or notify_target in ("private", "both"))
    if should_notify:
        print("\n生成对比报告...")
        summary = {}
        for name, info in results.items():
            if isinstance(info, str):
                summary[name] = info
            else:
                comp = None
                if name in sheet_columns:
                    try:
                        comp = compare_with_yesterday(token_mgr.token, info["config"], sheet_columns[name])
                    except Exception as e:
                        print(f"  对比失败 {name}: {e}")
                summary[name] = {"found": info["found"], "total": info["total"], "compare": comp}
        send_feishu_notification(summary, notify_target)


if __name__ == "__main__":
    main()
