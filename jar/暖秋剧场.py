"""
@header({
  searchable: 1,
  filterable: 1,
  quickSearch: 1,
  title: '晚秋剧场',
  lang: 'hipy'
})
"""
# -*- coding: utf-8 -*-
# !/usr/bin/env python3
"""
晚秋剧场 (暖秋剧场) TVBox 爬虫 —— 兼容 FongMi / T3 与 WebHomeTV / T4 及默影视
================================================================================
站点: https://www.yundongmudibana.com/  (MacCMS 系 + eWave(yun009) 模板)

【v2 更新 —— 二级分类 & 多条件筛选】
1. home_content 动态解析每个一级分类下的「二级分类子栏目」(/yubjc/14.html 等),
   作为 filters 第一组下拉返回;
2. 支持 地区/年份/语言/排序 多条件叠加, 拼成 /yubjc/{cid}/area/大陆/year/2024.html;
3. category_content 兼容 extend 传 dict / JSON串 / 旧版筛选URL / 纯数字子分类id;
4. 自测新增 [4c][4d] 用例验证二级分类与 extend 筛选。

【站点结构分析结论】(全部经真实抓包确认)
1. 首页 /            -> 多区块 vod 卡片列表
2. 顶部分类 /yubjc/{cid}.html   首页导航: 4=电影 5=电视剧 6=综艺 7=动漫 8=短剧
3. 二级分类 /yubjc/{子cid}.html  如 14=动作片; 另有 /yubjc/4/area/大陆.html 等
4. 分类翻页 /yubjc/{cid}/page/{n}.html (总页数写在页码区, e.g. 1/2824)
5. 详情页 /yunsxs/{id}.html  含海报(lazy: data-original)、简介、播放线路 tab、剧集列表
6. 播放页 /vshow/{id}/{sid}/{eid}.html
7. 播放地址: 播放页内 JS 变量 player_aaaa.url <-- 直接就是 m3u8, 无需第三方解析!
8. 搜索 /search.html?wd={kw}  结果复用 ranking-item 结构
9. 搜索翻页 /search/{kw}/page/{n}.html
"""

import sys
import json
import time
import gzip
import re
import html as html_mod
import urllib.parse
import urllib.request
import urllib.error

# ============================================================================
# 一、全局配置
# ============================================================================
BASE_HOST = "https://www.yundongmudibana.com"

UA = ("Mozilla/5.0 (Linux; Android 13; SM-S9180) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/120.0.0.0 Mobile Safari/537.36")

TIMEOUT = 12        # 单次请求超时(秒)
RETRY = 2           # 失败重试次数
CACHE_TTL = 300     # 内存缓存 TTL
_CACHE = {}

IMG_TIMEOUT = 20    # 图片请求超时
PLAY_TIMEOUT = 25   # 播放页解析超时

PAGE_LIMIT = 12     # 每页条数
PREFETCH_N = 8      # 列表返回后后台预取图片数量(0=关闭)

PROXY_M3U8 = False  # m3u8 是否走本地代理
PLAY_URL_BACKUP_PARSE = ""   # 加密线路备用解析前缀(留空=直链优先)

DEBUG = False       # 调试开关

# 首页导航兜底分类
DEFAULT_CLASSES = [
    {"type_id": "/yubjc/4.html", "type_name": "电影"},
    {"type_id": "/yubjc/5.html", "type_name": "电视剧"},
    {"type_id": "/yubjc/6.html", "type_name": "综艺"},
    {"type_id": "/yubjc/7.html", "type_name": "动漫"},
    {"type_id": "/yubjc/8.html", "type_name": "短剧"},
]

# ============================================================================
# 二、基础工具: HTTP / 缓存 / HTML 清洗
# ============================================================================
def _log(*args):
    if DEBUG:
        try:
            sys.stderr.write("[wanqiu] " + " ".join(str(a) for a in args) + "\n")
        except Exception:
            pass


def _cache_get(key):
    item = _CACHE.get(key)
    if not item:
        return None
    expire, value = item
    if expire < time.time():
        _CACHE.pop(key, None)
        return None
    return value


def _cache_set(key, value, ttl=CACHE_TTL):
    _CACHE[key] = (time.time() + ttl, value)


def fetch(url, referer=None, ttl=CACHE_TTL, use_cache=True, binary=False, timeout=None):
    """统一 HTTP GET: 超时 + gzip + 重试 + 内存缓存。返回 str/bytes, 失败返回 ''/b''。"""
    if not url:
        return b"" if binary else ""
    if url.startswith("/"):
        url = BASE_HOST + url
    if not url.startswith("http"):
        return b"" if binary else ""

    _timeout = timeout if timeout else TIMEOUT
    cache_key = ("B:" if binary else "T:") + url
    if use_cache:
        hit = _cache_get(cache_key)
        if hit is not None:
            _log("cache hit:", url)
            return hit

    # URL 中文必须百分号编码
    url = urllib.parse.quote(url, safe=":/?&=#%+$,")

    headers = {
        "User-Agent": UA,
        "Accept": "*/*",
        "Accept-Language": "zh-CN,zh;q=0.9",
        "Accept-Encoding": "gzip, deflate",
    }
    headers["Referer"] = referer if referer else BASE_HOST + "/"

    last_err = None
    for attempt in range(RETRY + 1):
        try:
            req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req, timeout=_timeout) as resp:
                raw = resp.read()
                enc = (resp.headers.get("Content-Encoding") or "").lower()
                if "gzip" in enc:
                    raw = gzip.decompress(raw)
                elif "deflate" in enc:
                    try:
                        import zlib
                        raw = zlib.decompress(raw, -zlib.MAX_WBITS)
                    except Exception:
                        pass
                result = raw if binary else _decode(raw)
                if use_cache:
                    _cache_set(cache_key, result, ttl)
                return result
        except urllib.error.HTTPError as e:
            last_err = e
            if 400 <= e.code < 500:
                _log("HTTP %s (no-retry): %s" % (e.code, url))
                break
            _log("HTTP %s retry %d: %s" % (e.code, attempt, url))
        except Exception as e:
            last_err = e
            _log("ERR retry %d: %s -> %s" % (attempt, e, url))
        if attempt < RETRY:
            time.sleep(0.4 * (attempt + 1))

    _log("FAILED:", url, last_err)
    return b"" if binary else ""


def _decode(raw):
    for enc in ("utf-8", "gbk", "gb18030"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", "ignore")


def _fix_url(u):
    if not u:
        return ""
    u = html_mod.unescape(u.strip())
    if u.startswith("//"):
        return "https:" + u
    if u.startswith("/"):
        return BASE_HOST + u
    return u


def _strip(s):
    if not s:
        return ""
    s = re.sub(r"<[^>]+>", "", s)
    s = html_mod.unescape(s)
    return re.sub(r"\s+", " ", s).strip()

# ----------------------------------------------------------------------------
# 图片磁盘缓存 / 预取 / 本地代理
# ----------------------------------------------------------------------------
def _img_cache_dir():
    import os
    for d in ("/storage/emulated/0/TVBox/py/.imgcache",
              "/sdcard/TVBox/py/.imgcache",
              "/tmp/wanqiu_imgcache"):
        try:
            if not os.path.isdir(d):
                os.makedirs(d, exist_ok=True)
            testf = os.path.join(d, ".wtest")
            with open(testf, "w") as f:
                f.write("1")
            os.remove(testf)
            return d
        except Exception:
            continue
    return ""


USE_IMG_PROXY = True


def _proxy_pic(pic):
    if not pic:
        return ""
    pic = _fix_url(pic)
    if not USE_IMG_PROXY or not pic.startswith("http"):
        return pic
    try:
        q = urllib.parse.quote(pic, safe="")
        return "http://127.0.0.1:9978/proxy?do=py&type=img&url=" + q
    except Exception:
        return pic


def _probe_log(msg):
    try:
        import os
        d = _img_cache_dir()
        if not d:
            return
        with open(os.path.join(d, "_probe.log"), "a", encoding="utf-8") as f:
            f.write("%s %s\n" % (time.strftime("%H:%M:%S"), msg))
    except Exception:
        pass


def _disk_cached(url):
    try:
        import os
        import hashlib
        d = _img_cache_dir()
        if not d:
            return False
        h = hashlib.md5(url.encode("utf-8")).hexdigest()
        for e in (".jpg", ".jpeg", ".png", ".webp", ".gif"):
            if os.path.exists(os.path.join(d, h + e)):
                return True
    except Exception:
        pass
    return False


def _save_disk(url, data):
    try:
        import os
        import hashlib
        d = _img_cache_dir()
        if not d or not data:
            return
        h = hashlib.md5(url.encode("utf-8")).hexdigest()
        ext = ".jpg"
        for e in (".png", ".webp", ".jpeg", ".gif"):
            if e in url.lower():
                ext = e
                break
        with open(os.path.join(d, h + ext), "wb") as f:
            f.write(data)
    except Exception:
        pass


def _prefetch_images(pics, n=None):
    if not USE_IMG_PROXY:
        return
    n = PREFETCH_N if n is None else n
    if n <= 0 or not pics:
        return
    todo = []
    for p in pics[:n]:
        p = _fix_url(p)
        if p.startswith("http") and not _disk_cached(p):
            todo.append(p)
    if not todo:
        return

    def _worker(urls):
        for u in urls:
            try:
                data = fetch(u, referer=BASE_HOST + "/", use_cache=False,
                             binary=True, timeout=IMG_TIMEOUT)
                if data:
                    _save_disk(u, data)
                    _probe_log("prefetch ok %s (%d bytes)" % (u[-40:], len(data)))
            except Exception:
                pass

    try:
        import threading
        t = threading.Thread(target=_worker, args=(todo,))
        t.daemon = True
        t.start()
    except Exception:
        pass

# ============================================================================
# 三、HTML 区块解析
# ============================================================================
def _parse_cards(block):
    """
    eWave 列表卡片:
    <li class="col-xs-4 ..."> <div class="pic"><a href="/yunsxs/699334.html" title="...">
      <div class="img-wrapper lazyload" data-original="...jpg"></div>
      <span class="fed-list-score">7.6</span><span class="vtitle">正片</span></a></div>
      <div class="name"><h3><a title="...">名</a></h3><p class="item-status">内详</p></div></li>
    """
    videos = []
    seen = set()
    for li in re.findall(r"<li[^>]*>(.*?)</li>", block, re.S):
        m = re.search(r'href="(/yunsxs/(\d+)\.html)"', li)
        if not m:
            continue
        vid = m.group(2)
        if vid in seen:
            continue
        title = ""
        mt = re.search(r'title="([^"]*)"', li)
        if mt:
            title = html_mod.unescape(mt.group(1)).strip()
        if not title:
            mh3 = re.search(r"<h3[^>]*>(.*?)</h3>", li, re.S)
            if mh3:
                title = _strip(mh3.group(1))
        if not title:
            continue
        pic = ""
        for pat in (r'data-original="([^"]+)"',
                    r'data-background="([^"]+)"',
                    r'data-src="([^"]+)"',
                    r'src="([^"]+\.(?:jpg|jpeg|png|webp)[^"]*)"'):
            mp = re.search(pat, li)
            if mp and "load.png" not in mp.group(1):
                pic = _fix_url(mp.group(1))
                break
        note = ""
        mv = re.search(r'class="vtitle[^"]*"[^>]*>(.*?)</span>', li, re.S)
        if mv:
            note = _strip(mv.group(1))
        if not note:
            ms = re.search(r'class="item-status[^"]*"[^>]*>(.*?)</p>', li, re.S)
            if ms:
                note = _strip(ms.group(1))
        seen.add(vid)
        videos.append({
            "vod_id": vid,
            "vod_name": title,
            "vod_pic": _proxy_pic(pic),
            "vod_remarks": note,
        })
    return videos


def _parse_ranking_cards(block):
    """排行榜/搜索结果卡片 (<li class="ranking-item">)。"""
    videos = []
    seen = set()
    for li in re.findall(r'<li[^>]*class="ranking-item"[^>]*>(.*?)</li>', block, re.S):
        m = re.search(r'href="(/yunsxs/(\d+)\.html)"', li)
        if not m:
            continue
        vid = m.group(2)
        if vid in seen:
            continue
        title = ""
        mt = re.search(r'title="([^"]*)"', li)
        if mt:
            title = html_mod.unescape(mt.group(1)).strip()
        if not title:
            mh = re.search(r"<h4[^>]*>(.*?)</h4>", li, re.S)
            if mh:
                title = _strip(mh.group(1))
        if not title:
            continue
        pic = ""
        mp = re.search(r'data-original="([^"]+)"', li)
        if mp:
            pic = _fix_url(mp.group(1))
        note = ""
        mn = re.search(r'<p[^>]*>(.*?)</p>', li, re.S)
        if mn:
            note = _strip(mn.group(1))
        seen.add(vid)
        videos.append({
            "vod_id": vid,
            "vod_name": title,
            "vod_pic": _proxy_pic(pic),
            "vod_remarks": note,
        })
    return videos


def _merged_cards(block):
    out = []
    seen = set()
    for v in _parse_cards(block) + _parse_ranking_cards(block):
        if v["vod_id"] in seen:
            continue
        seen.add(v["vod_id"])
        out.append(v)
    return out

# ============================================================================
# 三点五、二级分类 & 筛选 (v2 新增)
# ============================================================================
# 允许参与多条件叠加的维度 (对应站点 URL 段 /yubjc/{cid}/{key}/{val}.html)
_FILTER_KEYS = ("class", "area", "year", "lang", "by")
# dt 文本 -> extend key 映射
_NAME2KEY = {
    "分类": "class", "类型": "class", "剧情": "class",
    "地区": "area",
    "年份": "year", "年代": "year",
    "语言": "lang",
    "排序": "by", "时间": "by", "人气": "by",
}


def _parse_sub_classes(html_text, parent_cid):
    """
    解析分类页里的「二级分类子栏目」。
    实测形态: /yubjc/14.html (动作片) 等, 出现在页面顶部的 tab / swiper 区域。
    返回: [{"type_id": "/yubjc/14.html", "type_name": "动作片"}, ...]
    """
    subs = []
    seen = set()
    if not html_text:
        return subs
    # 只取页面靠前的部分, 避免把页脚/推荐区误收
    idx = html_text.find("</header>")
    head = html_text[: idx + 9] if idx > 0 else html_text[:20000]
    for href, cid, label in re.findall(
            r'<a[^>]*href="(/yubjc/(\d+)\.html)"[^>]*>([^<]{1,20})</a>', head):
        if cid == str(parent_cid):
            continue
        label = _strip(label)
        if not label or label == "全部" or cid in seen:
            continue
        seen.add(cid)
        subs.append({"type_id": href, "type_name": label})
    return subs


def build_filters(html_text, tid=""):
    """
    把分类页的筛选解析成 TVBox 标准下拉树:
    {tid: [{"key":"class","name":"分类","value":[{"n":"全部","v":""},...]}, ...]}
    value.v 存「取值片段」(如 "area/大陆" 或 子分类id), 由 category_content 拼 URL。
    """
    out = {}
    if not html_text:
        return out
    m = re.search(r"/yubjc/(\d+)", tid or "")
    cid = m.group(1) if m else ""

    groups = []

    # --- 1) 二级分类作为第一组 class ---
    subs = _parse_sub_classes(html_text, cid)
    if subs:
        vals = [("全部", "")] + [(s["type_name"], s["type_id"]) for s in subs]
        groups.append(("class", "分类", vals))

    # --- 2) dl 筛选组: 地区 / 年份 / 语言 / 排序 ---
    for dl in re.findall(r"<dl[^>]*>(.*?)</dl>", html_text, re.S):
        mt = re.search(r"<dt[^>]*>(.*?)</dt>", dl, re.S)
        if not mt:
            continue
        name = _strip(mt.group(1))
        key = _NAME2KEY.get(name)
        if not key:
            continue
        values = [("全部", "")]
        for href, label in re.findall(r'<a[^>]*href="([^"]+)"[^>]*>(.*?)</a>', dl, re.S):
            label = _strip(label)
            if not label or label == "全部":
                continue
            # /yubjc/4/area/大陆.html -> 取 "大陆"
            mm = re.search(r"/yubjc/\d+/%s/([^/\.]+)" % key, href)
            if mm:
                values.append((label, mm.group(1)))
        dedup, seen = [], set()
        for n, v in values:
            if v in seen:
                continue
            seen.add(v)
            dedup.append((n, v))
        if len(dedup) > 1:
            groups.append((key, name, dedup))

    if groups:
        out[tid] = [
            {"key": k, "name": n,
             "value": [{"n": nn, "v": vv} for nn, vv in vals]}
            for k, n, vals in groups
        ]
    return out


def _build_filter_url(cid, ext):
    """
    把 extend dict 拼成多段筛选 URL。
    ext 形如 {"class":"", "area":"大陆", "year":"2024", "by":"hits"}
    特殊: class 的值是纯数字(二级分类 id, 如 "14" 或 "/yubjc/14.html") -> 直接返回子栏目 URL。
    """
    if not ext:
        return "/yubjc/%s.html" % cid
    c = str(ext.get("class") or "").strip()
    if c.isdigit():
        return "/yubjc/%s.html" % c
    if c.startswith("/yubjc/") and c.endswith(".html"):
        return c
    segs = []
    for key in _FILTER_KEYS:
        v = str(ext.get(key) or "").strip()
        if not v or v == "全部":
            continue
        if "/" in v:  # 兼容直接传 "area/大陆" 片段
            segs.append(v)
        else:
            segs.append("%s/%s" % (key, urllib.parse.quote(v)))
    if not segs:
        return "/yubjc/%s.html" % cid
    return "/yubjc/%s/%s.html" % (cid, "/".join(segs))


def _extract_pagecount(html):
    """从「分页区域」稳健提取总页数, 避免误匹配图片 URL 里的 1/048431。"""
    if not html:
        return 0
    for ctx_pat in (
        r'<div[^>]*class="[^"]*(?:page|pagelist|pagination)[^"]*"[^>]*>(.*?)</div>',
        r'<ul[^>]*class="[^"]*(?:page|pagelist|pagination)[^"]*">(.*?)</ul>',
    ):
        for blk in re.findall(ctx_pat, html, re.S):
            m = re.search(r">\s*(\d{1,5})\s*/\s*(\d{1,5})\s*<", blk)
            if m:
                try:
                    v = int(m.group(2))
                    if 1 <= v <= 99999:
                        return v
                except Exception:
                    pass
    m = re.search(r">\s*\d{1,5}\s*/\s*(\d{1,5})\s*<", html)
    if m:
        try:
            v = int(m.group(1))
            if 1 <= v <= 99999:
                return v
        except Exception:
            pass
    ns = [int(x) for x in re.findall(r"/page/(\d{1,5})\.html", html)]
    if ns:
        return max(ns)
    return 0

# ============================================================================
# 四、TVBox 接口实现
# ============================================================================
def home_content(filter_=False):
    """
    【首页】{"class": [...], "list": [...], "filters": {type_id: [...]}}
    filters 以 type_id 为 key, T4 按当前分类自动应用下拉筛选。
    """
    classes = []
    home_html = fetch("/", ttl=CACHE_TTL)
    if home_html:
        mn = re.search(r'<div class="nav">(.*?)</div>\s*</div>', home_html, re.S) \
             or re.search(r'<div class="nav">(.*?)</div>', home_html, re.S)
        nav_block = mn.group(1) if mn else ""
        for a in re.findall(r'<a[^>]*href="(/yubjc/\d+\.html)"[^>]*>([^<]+)</a>', nav_block):
            classes.append({"type_id": a[0], "type_name": _strip(a[1])})
    if not classes:
        classes = list(DEFAULT_CLASSES)

    videos = _merged_cards(home_html) if home_html else []

    # ★ v2: 给每个分类构建筛选树 (含二级分类); 为控制首屏耗时只取前 3 个,
    #   需要全部分类都带筛选可改为 classes
    filters = {}
    for c in classes[:3]:
        try:
            cat_html = fetch(c["type_id"], ttl=600)
            filters.update(build_filters(cat_html, c["type_id"]))
        except Exception:
            continue

    return {"class": classes, "list": videos, "filters": filters}


def category_content(tid, pg="1", filter_=None):
    """
    【分类 / 二级分类 / 翻页 / 筛选】
    tid 形态:
      - "/yubjc/4.html"          一级分类
      - "/yubjc/14.html"         二级分类(子栏目)
      - "/yubjc/4/area/大陆.html" 筛选路径
      - "4" / "14"               纯数字 id
    filter_ (extend) 形态:
      - None
      - dict: {"class":"14", "area":"大陆", "year":"2024", "by":"hits"}
      - str:  JSON 串 或 旧版筛选 URL ("/yubjc/4/area/大陆.html")
    """
    tid = (tid or "").strip()
    pg = str(pg or "1")

    # --- 解析 extend ---
    ext = {}
    if isinstance(filter_, dict):
        ext = filter_
    elif isinstance(filter_, str) and filter_.strip():
        s = filter_.strip()
        if s.startswith("{"):
            try:
                ext = json.loads(s)
            except Exception:
                ext = {}
        elif s.startswith("/yubjc/"):
            tid = s   # 旧版: 直接传筛选 URL

    # --- 归一化, 取 cid ---
    m = re.search(r"/yubjc/(\d+)", tid)
    cid = m.group(1) if m else re.sub(r"\D", "", tid) or "4"

    # --- 拼 URL: extend 优先(多条件叠加), 否则按 tid 翻页 ---
    if ext:
        url = _build_filter_url(cid, ext)
    else:
        base = re.sub(r"/page/\d+\.html$", "", tid)
        base = base[:-5] if base.endswith(".html") else base
        base = re.sub(r"\.html$", "", base)
        if base.startswith("/yubjc/"):
            url = base + ".html" if pg in ("", "1") else "%s/page/%s.html" % (base, pg)
        else:
            base = "/yubjc/%s" % cid
            url = base + ".html" if pg in ("", "1") else "%s/page/%s.html" % (base, pg)

    page_html = fetch(url, ttl=120)
    videos = _merged_cards(page_html) if page_html else []

    # 空页兜底: 回退一级分类, 保证电视端不白屏
    if not videos:
        fb = fetch("/yubjc/%s.html" % cid, ttl=120)
        videos = _merged_cards(fb) if fb else []

    limit = _extract_pagecount(page_html) or 1

    result = {
        "page": int(pg) if pg.isdigit() else 1,
        "pagecount": limit,
        "limit": PAGE_LIMIT,
        "total": limit * PAGE_LIMIT if limit else 0,
        "list": videos,
    }
    try:
        _prefetch_images([v.get("vod_pic", "") for v in videos])
    except Exception:
        pass
    return result


def detail_content(ids):
    """【详情页】ids: list[str] 或 str。返回 {"list": [vod, ...]}"""
    if isinstance(ids, str):
        ids = [ids]
    out = []
    for vid in (ids or []):
        vid = re.sub(r"\D", "", str(vid))
        if not vid:
            continue
        url = "/yunsxs/%s.html" % vid
        t = fetch(url, ttl=CACHE_TTL)
        if not t:
            continue

        # 标题
        title = ""
        mt = re.search(r"<h1[^>]*>(.*?)</h1>", t, re.S)
        if mt:
            title = _strip(mt.group(1))
        if not title:
            mt2 = re.search(r"<title>(.*?)</title>", t, re.S)
            if mt2:
                title = _strip(mt2.group(1)).split("_")[0].split("-")[0].strip()
        title = title.strip("《》").strip()

        # 海报
        pic = ""
        for pat in (r'<div class="img-wrapper[^"]*"[^>]*data-original="([^"]+)"',
                    r'data-original="([^"]+)"'):
            mp = re.search(pat, t)
            if mp and "load.png" not in mp.group(1):
                pic = _fix_url(mp.group(1))
                break

        # 简介
        content = ""
        for pat in (r'class="detail-content[^"]*"[^>]*>(.*?)</div>',
                    r'class="detail-intro[^"]*"[^>]*>(.*?)</div>',
                    r'<p class="[^"]*desc[^"]*"[^>]*>(.*?)</p>'):
            mc = re.search(pat, t, re.S)
            if mc:
                content = _strip(mc.group(1))
                if content:
                    break

        # 元信息
        def _meta(label):
            m2 = re.search(r">\s*" + label + r"\s*[:：]\s*</[^>]+>\s*<?[^>]*>?(.*?)(?:</p>|</li>|</dd>|</div>)", t, re.S)
            if m2:
                return _strip(m2.group(1)).lstrip("：: ").strip()
            m3 = re.search(label + r"\s*[:：]\s*([^<\n]{1,60})", t)
            return _strip(m3.group(1)) if m3 else ""

        year = ""
        my = re.search(r'/yubjc/\d+/year/(\d{4})\.html', t)
        if my:
            year = my.group(1)
        if not year:
            my2 = re.search(r"(19|20)\d{2}", _meta("年份") or _meta("年代") or "")
            if my2:
                year = my2.group(0)

        area = _meta("地区")
        vtype = _meta("类型")
        actor = _meta("主演") or _meta("演员")
        director = _meta("导演")
        remarks = _meta("状态") or _meta("备注")

        play_from, play_url = _parse_playlist(t, vid)

        out.append({
            "vod_id": vid,
            "vod_name": title,
            "vod_pic": _proxy_pic(pic),
            "vod_year": year,
            "vod_area": area,
            "vod_type": vtype,
            "vod_actor": actor,
            "vod_director": director,
            "vod_remarks": remarks,
            "vod_content": content or title,
            "vod_play_from": play_from,
            "vod_play_url": play_url,
        })
    return {"list": out}


def _parse_playlist(t, vid):
    """详情页「线路 tab + 剧集列表」 -> (play_from, play_url)"""
    line_names = []
    tab_block = re.search(r'<div class="playlist-tab[^"]*">(.*?)</div>\s*</div>', t, re.S)
    tabs_html = tab_block.group(1) if tab_block else t
    for m in re.finditer(r'<li[^>]*data-target="#(ewave-playlist-\d+)"[^>]*>(.*?)</li>',
                         tabs_html, re.S):
        name = _strip(m.group(2))
        line_names.append(name or ("线路%s" % (len(line_names) + 1)))

    from_list = []
    url_list = []
    containers = re.findall(r'<ul[^>]*id="(ewave-playlist-\d+)"[^>]*>(.*?)</ul>', t, re.S)
    if not containers:
        eps = re.findall(r'href="(/vshow/%s/(\d+)/(\d+)\.html)"[^>]*>([^<]*)</a>' % vid, t)
        if eps:
            from_list.append(line_names[0] if line_names else "线路1")
            url_list.append("#".join(
                "%s$%s" % (_strip(e[3]) or ("第%s集" % e[2]), e[0]) for e in eps))
    else:
        for idx, (body_cid, body) in enumerate(containers):
            name = line_names[idx] if idx < len(line_names) else ("线路%s" % (idx + 1))
            eps = re.findall(r'href="(/vshow/%s/(\d+)/(\d+)\.html)"[^>]*>([^<]*)</a>' % vid, body)
            if not eps:
                continue
            from_list.append(name)
            url_list.append("#".join(
                "%s$%s" % (_strip(e[3]) or ("第%s集" % e[2]), e[0]) for e in eps))

    if not from_list:
        eps = re.findall(r'href="(/vshow/%s/(\d+)/(\d+)\.html)"[^>]*>([^<]*)</a>' % vid, t)
        if eps:
            from_list.append(line_names[0] if line_names else "线路1")
            url_list.append("#".join(
                "%s$%s" % (_strip(e[3]) or ("第%s集" % e[2]), e[0]) for e in eps))

    return "$$$".join(from_list), "$$$".join(url_list)


def search_content(key, quick=False):
    key = (key or "").strip()
    if not key:
        return {"list": []}
    q = urllib.parse.quote(key)
    t = fetch("/search.html?wd=%s" % q, ttl=120)
    videos = _merged_cards(t) if t else []
    return {"list": videos}


def search_page(key, pg):
    key = (key or "").strip()
    q = urllib.parse.quote(key)
    if str(pg) in ("", "1"):
        url = "/search.html?wd=%s" % q
    else:
        url = "/search/%s/page/%s.html" % (q, pg)
    t = fetch(url, ttl=120)
    videos = _merged_cards(t) if t else []
    return {"page": int(pg) if str(pg).isdigit() else 1, "list": videos}

# ============================================================================
# 五、播放地址解析 (核心)
# ============================================================================
def play_parse(flag, id_, flags=None):
    """
    播放页 player_aaaa.url 即直链 m3u8, 无需第三方解析。
    返回 {"parse": 0, "playUrl": ..., "url": ...}
    """
    if id_ and (".m3u8" in id_ or id_.startswith("http")):
        if ".m3u8" in id_:
            return {"parse": 0, "playUrl": id_, "url": id_}
        play_url = id_
    else:
        play_url = id_ or ""

    if "$" in play_url and not play_url.startswith("http"):
        play_url = play_url.split("$")[-1]
    if play_url.startswith("/"):
        play_url = BASE_HOST + play_url
    if not play_url:
        return {"parse": 0, "playUrl": ""}

    page = fetch(play_url, referer=BASE_HOST + "/", ttl=1800, timeout=PLAY_TIMEOUT)
    if not page:
        return {"parse": 0, "playUrl": ""}

    m = re.search(r"var\s+player_aaaa\s*=\s*(\{.*?\})\s*</script>", page, re.S)
    if not m:
        m = re.search(r"var\s+player_aaaa\s*=\s*(\{.*?\})", page, re.S)
    real_url = ""
    if m:
        try:
            info = json.loads(m.group(1))
        except Exception:
            info = {}
        real_url = info.get("url") or ""
        encrypt = str(info.get("encrypt", "0"))
        _log("player_aaaa url=%s encrypt=%s" % (real_url[:80], encrypt))
        if encrypt == "1" and PLAY_URL_BACKUP_PARSE:
            real_url = PLAY_URL_BACKUP_PARSE + urllib.parse.quote(real_url, safe="")

    if not real_url:
        m2 = re.search(r'(https?://[^\s"\']+\.m3u8[^\s"\']*)', page)
        if m2:
            real_url = m2.group(1)

    if not real_url:
        m3 = re.search(r'<iframe[^>]+src="([^"]+)"', page)
        if m3 and "player" in m3.group(1):
            return play_parse("", _fix_url(m3.group(1)))

    if real_url:
        real_url = real_url.replace("\\/", "/")
        if real_url.startswith("//"):
            real_url = "https:" + real_url

    return {"parse": 0, "playUrl": real_url, "url": real_url}

# ============================================================================
# 六、自测 && 导出
# ============================================================================
def _selftest():
    global DEBUG
    DEBUG = True
    ok = 0
    fail = 0

    def check(name, cond, extra=""):
        nonlocal ok, fail
        if cond:
            ok += 1
            print("  [PASS] %s %s" % (name, extra))
        else:
            fail += 1
            print("  [FAIL] %s %s" % (name, extra))

    print("=" * 70)
    print("晚秋剧场 TVBox 爬虫 —— 本地自测")
    print("=" * 70)

    # 1. 首页
    print("\n[1] 首页 home_content()")
    home = home_content()
    check("分类非空", len(home.get("class", [])) > 0,
          "-> %d 个分类" % len(home.get("class", [])))
    check("首页视频非空", len(home.get("list", [])) > 0,
          "-> %d 条" % len(home.get("list", [])))
    if home.get("list"):
        v = home["list"][0]
        print("  示例:", v["vod_name"], "|", v["vod_id"], "|", (v["vod_pic"] or "")[:60])
    if home.get("class"):
        print("  分类:", ", ".join(c["type_name"] for c in home["class"][:8]))
    if home.get("filters"):
        for tid, fl in list(home["filters"].items())[:1]:
            print("  filters[%s]:" % tid,
                  ", ".join("%s(%d项)" % (g["name"], len(g["value"])) for g in fl))

    # 2. 分类
    print("\n[2] 分类 category_content('/yubjc/4.html')")
    cat = category_content("/yubjc/4.html", "1")
    check("分类列表非空", len(cat.get("list", [])) > 0,
          "-> %d 条" % len(cat.get("list", [])))
    check("总页数>0", cat.get("pagecount", 0) > 0,
          "-> %d 页" % cat.get("pagecount", 0))

    # 3. 翻页
    print("\n[3] 翻页 category_content('/yubjc/4.html', '2')")
    cat2 = category_content("/yubjc/4.html", "2")
    check("第2页非空", len(cat2.get("list", [])) > 0,
          "-> %d 条" % len(cat2.get("list", [])))
    if cat.get("list") and cat2.get("list"):
        check("翻页内容不同",
              cat["list"][0]["vod_id"] != cat2["list"][0]["vod_id"],
              "-> p1=%s / p2=%s" % (cat["list"][0]["vod_id"], cat2["list"][0]["vod_id"]))

    # 4. 二级分类
    print("\n[4] 二级分类 category_content('/yubjc/14.html') [动作片]")
    sub = category_content("/yubjc/14.html", "1")
    check("二级分类非空", len(sub.get("list", [])) > 0,
          "-> %d 条" % len(sub.get("list", [])))

    print("\n[4b] 筛选 category_content('/yubjc/4/area/大陆.html')")
    flt = category_content("/yubjc/4/area/大陆.html", "1")
    check("地区筛选非空", len(flt.get("list", [])) > 0,
          "-> %d 条" % len(flt.get("list", [])))

    print("\n[4c] 二级分类 id 直传 category_content('14')")
    sub2 = category_content("14", "1")
    check("二级分类id直传非空", len(sub2.get("list", [])) > 0,
          "-> %d 条" % len(sub2.get("list", [])))

    print("\n[4d] extend 组合筛选 year=2024")
    comb = category_content("/yubjc/4.html", "1", {"year": "2024"})
    check("extend年份筛选非空", len(comb.get("list", [])) > 0,
          "-> %d 条" % len(comb.get("list", [])))

    # 5. 详情
    print("\n[5] 详情 detail_content()")
    did = (home["list"][0]["vod_id"] if home.get("list") else "2615582")
    det = detail_content([did])
    check("详情返回", len(det.get("list", [])) > 0)
    if det.get("list"):
        d = det["list"][0]
        check("详情标题非空", bool(d.get("vod_name")), "-> %s" % d.get("vod_name"))
        check("详情海报非空", bool(d.get("vod_pic")), "-> %s" % (d.get("vod_pic") or "")[:60])
        check("播放线路非空", bool(d.get("vod_play_from")), "-> %s" % d.get("vod_play_from"))
        check("剧集列表非空", bool(d.get("vod_play_url")),
              "-> %s 集" % len(d.get("vod_play_url", "").split("#")))
        print("  线路:", d.get("vod_play_from"))
        first_ep = (d.get("vod_play_url", "").split("#") or [""])[0]
        print("  首集:", first_ep[:80])
        ep_id = first_ep.split("$")[-1] if "$" in first_ep else first_ep

        # 6. 播放解析
        print("\n[6] 播放解析 play_parse()")
        pr = play_parse("", ep_id)
        pu = pr.get("playUrl", "")
        check("解析出直链", bool(pu), "-> %s" % pu[:90])
        check("是 m3u8 直链", ".m3u8" in (pu or ""))
        if pu:
            body = fetch(pu, ttl=60)
            check("m3u8 可拉取", "#EXTM3U" in (body or ""),
                  "-> %d bytes" % len(body or ""))

    # 7. 搜索
    print("\n[7] 搜索 search_content('一斩苍穹')")
    sr = search_content("一斩苍穹")
    check("搜索结果非空", len(sr.get("list", [])) > 0,
          "-> %d 条" % len(sr.get("list", [])))
    if sr.get("list"):
        print("  首条:", sr["list"][0]["vod_name"], "|", sr["list"][0]["vod_id"])

    print("\n" + "=" * 70)
    print("自测结果: %d 通过 / %d 失败" % (ok, fail))
    print("=" * 70)
    return 0 if fail == 0 else 1


# ---------------------------------------------------------------------------
# TVBox 导出 (函数式, 供部分壳直接读取)
# ---------------------------------------------------------------------------
exports = {
    "homeContent": home_content,
    "categoryContent": category_content,
    "detailContent": detail_content,
    "searchContent": search_content,
    "playContent": play_parse,
}


def homeVodContent():
    return {"list": home_content(False).get("list", [])}


def playerContent(flag, id_, flags=None):
    return play_parse(flag, id_, flags)


# ============================================================================
# 【关键】TVBox / 默影视 / FongMi(hipy) 标准类式 Spider 桥接层
# ============================================================================
try:
    from base.spider import Spider as _BaseSpider
except Exception:
    class _BaseSpider(object):
        pass


class Spider(_BaseSpider):
    """晚秋剧场 TVBox 爬虫 —— 类式包装(默影视/FongMi/hipy 兼容)"""

    def getName(self):
        return "晚秋剧场"

    # ---- 壳生命周期 ----
    def init(self, extend=""):
        return ""

    def destroy(self):
        return ""

    # ---- 壳强制元信息接口 ----
    def isVideoFormat(self, url):
        try:
            u = str(url or "").lower().strip()
            if not u:
                return False
            if u.startswith("http://") or u.startswith("https://"):
                return True
            return any(x in u for x in (".m3u8", ".mp4", ".flv", ".mkv"))
        except Exception:
            return False

    def manualVideoCheck(self):
        return False

    def localProxy(self, param):
        """本地代理: 图片加速 + 磁盘缓存"""
        try:
            url = ""
            if isinstance(param, dict):
                url = (param.get("url") or param.get("imageUrl")
                       or param.get("path") or param.get("src") or "")
            elif isinstance(param, str):
                url = param
            _probe_log("localProxy called, url=%s" % str(url)[:120])
            url = _fix_url(url)
            if not url.startswith("http"):
                return [404, "text/plain", b""]
            cache_dir = _img_cache_dir()
            import hashlib
            import os
            h = hashlib.md5(url.encode("utf-8")).hexdigest()
            ext = ".jpg"
            for e in (".png", ".webp", ".jpeg", ".gif"):
                if e in url.lower():
                    ext = e
                    break
            fp = os.path.join(cache_dir, h + ext) if cache_dir else ""
            if fp and os.path.exists(fp):
                try:
                    with open(fp, "rb") as f:
                        data = f.read()
                    if data:
                        ctype = "image/png" if ext == ".png" else (
                            "image/webp" if ext == ".webp" else "image/jpeg")
                        return [200, ctype, data]
                except Exception:
                    pass
            data = fetch(url, referer=BASE_HOST + "/", ttl=3600,
                         use_cache=False, binary=True, timeout=IMG_TIMEOUT)
            if not data:
                return [404, "text/plain", b""]
            if fp:
                try:
                    if not os.path.isdir(cache_dir):
                        os.makedirs(cache_dir, exist_ok=True)
                    with open(fp, "wb") as f:
                        f.write(data)
                except Exception:
                    pass
            ctype = "image/jpeg"
            if data[:8].startswith(b"\x89PNG"):
                ctype = "image/png"
            elif data[:4] == b"RIFF" and b"WEBP" in data[:16]:
                ctype = "image/webp"
            elif data[:3] == b"GIF":
                ctype = "image/gif"
            return [200, ctype, data]
        except Exception:
            return [404, "text/plain", b""]

    # ---- 主接口 ----
    def homeContent(self, filter):
        try:
            r = home_content(filter)
            if isinstance(r, dict):
                return r
        except Exception:
            pass
        return {"class": list(DEFAULT_CLASSES), "list": [], "filters": {}}

    def homeVideoContent(self):
        try:
            r = home_content(False)
            if isinstance(r, dict):
                return {"list": r.get("list", [])}
        except Exception:
            pass
        return {"list": []}

    def categoryContent(self, tid, pg, filter, extend):
        try:
            # extend: T4 传 JSON 串或 dict; 兼容 FongMi 传 "1"/"0"
            ext = extend
            if isinstance(ext, str) and ext.strip() and ext.strip() not in ("1", "0"):
                try:
                    ext = json.loads(ext)
                except Exception:
                    ext = None
            if not isinstance(ext, dict) or not ext:
                ext = None
            r = category_content(tid, pg, ext)
            if isinstance(r, dict):
                return r
        except Exception:
            pass
        try:
            pg = int(pg) if str(pg).isdigit() else 1
        except Exception:
            pg = 1
        return {"page": pg, "pagecount": 1, "limit": 20, "total": 0, "list": []}

    def detailContent(self, ids):
        try:
            if isinstance(ids, str):
                ids = [x for x in ids.split(",") if x.strip()]
            r = detail_content(ids)
            if isinstance(r, dict):
                return r
        except Exception:
            pass
        return {"list": []}

    def searchContent(self, key, quick, pg="1"):
        try:
            r = search_content(key, quick)
            if isinstance(r, dict):
                r.setdefault("page", int(pg) if str(pg).isdigit() else 1)
                r.setdefault("pagecount", 1)
                return r
        except Exception:
            pass
        return {"list": [], "page": 1, "pagecount": 1}

    def playerContent(self, flag, id_, vipFlags=None):
        try:
            r = play_parse(flag, id_, vipFlags)
            if isinstance(r, dict):
                u = r.get("url") or r.get("playUrl") or ""
                parse = r.get("parse", 0)
                if not u:
                    parse = 1
                return {"parse": parse, "url": u, "header": ""}
        except Exception:
            pass
        return {"parse": 1, "url": "", "header": ""}


if __name__ == "__main__":
    if "--selftest" in sys.argv or len(sys.argv) == 1:
        sys.exit(_selftest())
    else:
        # CLI: python3 暖秋剧场.py home|cat <tid> <pg>|detail <id>|search <kw>|play <url>
        cmd = sys.argv[1]
        arg = sys.argv[2:] if len(sys.argv) > 2 else []
        DEBUG = True
        if cmd == "home":
            print(json.dumps(home_content(), ensure_ascii=False, indent=2)[:5000])
        elif cmd == "cat":
            tid = arg[0] if arg else "/yubjc/4.html"
            pg = arg[1] if len(arg) > 1 else "1"
            print(json.dumps(category_content(tid, pg), ensure_ascii=False, indent=2)[:3000])
        elif cmd == "detail":
            print(json.dumps(detail_content(arg), ensure_ascii=False, indent=2)[:3000])
        elif cmd == "search":
            print(json.dumps(search_content(arg[0] if arg else ""), ensure_ascii=False, indent=2)[:3000])
        elif cmd == "play":
            print(json.dumps(play_parse("", arg[0] if arg else ""), ensure_ascii=False, indent=2))
        else:
            print("unknown cmd:", cmd)
