# -*- coding: utf-8 -*-
"""
蓝海影院 Python Spider — https://www.zhongyoujia.com/
苹果 CMS (maccms v10) 自定义路由站点。

关键路由:
  首页         /                                    (含最新更新 + 轮播推荐)
  一级分类     /zhotp/{tid}.html                     e.g. /zhotp/1.html (电影)
  一级分类分页 /zhotp/{tid}-{page}.html               e.g. /zhotp/1-2.html
  子分类       /zhotp/{sub_tid}.html                 e.g. /zhotp/6.html (动作片)
  子分类分页   /zhotp/{sub_tid}-{page}.html          e.g. /zhotp/6-2.html
  详情页       /zhodetail/{id}.html                  e.g. /zhodetail/261051.html
  播放页       /zhoplay/{id}-{sid}-{nid}.html        e.g. /zhoplay/261051-1-1.html
                真实 m3u8 藏在 <script>var player_aaaa={...}</script> 的 url 字段
  搜索         /zhosc/-------------.html             (触发验证码, 暂不支持)

性能优化:
  1. requests.Session + HTTPAdapter, 连接池扩到 20, 复用 TCP/SSL
  2. 预编译所有正则到类属性 (一次性编译, 多次复用)
  3. 首页/分类/详情各自独立超时, 首屏秒出
  4. 首页推荐只取前 30 条, 避免一次抓太多
  5. 分类页 60s 缓存, 详情页 5min 缓存, 翻页秒出
  6. 失败熔断: host 连续失败 3 次暂停 30s, 不让 TVBox 一直转圈
  7. gzip Accept-Encoding, requests 自动解压
  8. 详情路径统一为 /zhodetail/{id}.html, 播放路径统一为 /zhoplay/{id}-{sid}-{nid}.html
"""

import re
import json
import time
import warnings
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from urllib.parse import urljoin, quote

# 屏蔽 SSL 证书告警, 保持日志干净
try:
    warnings.filterwarnings("ignore")
    import urllib3
    urllib3.disable_warnings()
except Exception:
    pass

# 兼容 TVBox / 猫影视框架注入的基类
try:
    from base.spider import Spider
except ImportError:
    import requests as _rq
    from requests.adapters import HTTPAdapter

    class Spider:
        """无框架环境下的兜底实现, 供独立测试 / 命令行运行。"""

        def __init__(self):
            self._session = _rq.Session()
            adapter = HTTPAdapter(pool_connections=20, pool_maxsize=20)
            self._session.mount("http://", adapter)
            self._session.mount("https://", adapter)

        def fetch(self, url, headers=None, timeout=15, **kw):
            headers = headers or {}
            headers.setdefault("User-Agent", UA)
            return self._session.get(
                url, headers=headers, timeout=timeout, verify=False, **kw
            )

        def destroy(self):
            try:
                self._session.close()
            except Exception:
                pass


# ============================================================
# 常量
# ============================================================
HOST = "https://www.zhongyoujia.com"
# 关键: 站点对桌面 UA 可能返回不同布局, 用安卓移动端 UA 兼容性最好
UA = ("Mozilla/5.0 (Linux; Android 12; M2007J22C) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/120.0.0.0 Mobile Safari/537.36")

# 一级分类 (type_id 即 /zhotp/ 路径里的 tid)
CLASSES = [
    {"type_name": "电影", "type_id": "1"},
    {"type_name": "电视剧", "type_id": "2"},
    {"type_name": "综艺", "type_id": "3"},
    {"type_name": "动漫", "type_id": "4"},
    {"type_name": "短剧", "type_id": "5"},
]

# 二级分类 (子分类有独立 tid, 通过 /zhotp/{sub_tid}.html 访问)
# 注意: /zhosw/ 筛选路由会触发验证码, 故只保留子分类(class)筛选
FILTERS = {
    "1": [
        {"key": "class", "name": "类型", "value": [
            {"n": "全部", "v": ""},
            {"n": "动作片", "v": "6"},
            {"n": "喜剧片", "v": "7"},
            {"n": "爱情片", "v": "8"},
            {"n": "科幻片", "v": "9"},
            {"n": "恐怖片", "v": "10"},
            {"n": "剧情片", "v": "11"},
            {"n": "战争片", "v": "12"},
            {"n": "纪录片", "v": "13"},
            {"n": "悬疑片", "v": "14"},
            {"n": "犯罪片", "v": "15"},
            {"n": "奇幻片", "v": "16"},
            {"n": "动画片", "v": "31"},
            {"n": "预告片", "v": "32"},
        ]},
    ],
    "2": [
        {"key": "class", "name": "类型", "value": [
            {"n": "全部", "v": ""},
            {"n": "国产剧", "v": "17"},
            {"n": "港台剧", "v": "18"},
            {"n": "日韩剧", "v": "20"},
            {"n": "欧美剧", "v": "21"},
            {"n": "海外剧", "v": "22"},
        ]},
    ],
    "3": [
        {"key": "class", "name": "类型", "value": [
            {"n": "全部", "v": ""},
            {"n": "大陆综艺", "v": "23"},
            {"n": "日韩综艺", "v": "24"},
            {"n": "欧美综艺", "v": "25"},
            {"n": "港台综艺", "v": "26"},
        ]},
    ],
    "4": [
        {"key": "class", "name": "类型", "value": [
            {"n": "全部", "v": ""},
            {"n": "国产动漫", "v": "27"},
            {"n": "日韩动漫", "v": "28"},
            {"n": "欧美动漫", "v": "29"},
            {"n": "其他动漫", "v": "30"},
        ]},
    ],
    "5": [
        {"key": "class", "name": "类型", "value": [
            {"n": "全部", "v": ""},
        ]},
    ],
}

# 缓存 / 分页参数
LIST_PAGE_SIZE = 36           # 列表页每页条数 (实测约 36 条)
HOME_PAGE_SIZE = 30           # 首页推荐抓取上限
LIST_CACHE_TTL = 60           # 列表页缓存秒数 (TVBox 翻页体验)
DETAIL_CACHE_TTL = 300        # 详情页缓存秒数
CIRCUIT_FAILS = 3             # 连续失败 N 次触发熔断
CIRCUIT_COOLDOWN = 30         # 熔断冷却秒数

# URL 模板
CATEGORY_URL_TEMPLATE = "{host}/zhotp/{tid}{page}.html"
SEARCH_URL_TEMPLATE = "{host}/index.php?m=vod-search-pg-{page}-wd-{kw}.html"


# ============================================================
# 工具函数
# ============================================================
def _urlencode(s):
    """URL 编码 (空安全)。"""
    return quote(s or "", safe="")


def _strip(txt):
    """折叠所有空白 + strip。"""
    return re.sub(r"\s+", " ", txt or "").strip()


def _unescape(txt):
    """HTML 实体码 → 中文 (&#31867; → 类)。"""
    if not txt:
        return ""
    try:
        import html as _html
        return _html.unescape(txt)
    except Exception:
        return re.sub(r"&#(\d+);", lambda m: chr(int(m.group(1))), txt)


def _abs_url(url, base):
    """把站点内相对路径拼成绝对 URL。"""
    if not url:
        return ""
    if url.startswith("//"):
        return "https:" + url
    if url.startswith("http"):
        return url
    if url.startswith("/"):
        return base + url
    return urljoin(base + "/", url)


# ============================================================
# Spider 主类
# ============================================================
class Spider(Spider):
    """蓝海影院 Spider, 框架约定继承同名基类。"""

    # ---------- 预编译正则 (类属性, 一次编译, 多次复用) ----------
    # 列表卡片: <a href="/zhodetail/NNNN.html" title="..." data-original="...">
    _RE_LIST_ITEM = re.compile(
        r'<a[^>]+href="(/zhodetail/(\d+)\.html)"[^>]*title="([^"]*)"'
        r'[^>]*?data-original="([^"]*)"',
    )
    # 宽松版: data-original 在 title 之前
    _RE_LIST_ITEM_LOOSE = re.compile(
        r'<a[^>]+href="(/zhodetail/(\d+)\.html)"[^>]*data-original="([^"]*)"'
        r'[^>]*?title="([^"]*)"',
    )
    # 兜底: 只要 href + title, 封面在 <a> 内 <img> 里取
    _RE_LIST_TITLE_ONLY = re.compile(
        r'<a[^>]+href="(/zhodetail/(\d+)\.html)"[^>]*title="([^"]*)"',
    )
    # 兜底 2: 匹配 <a> 标签后在其内 <img> 的 src
    _RE_LIST_IMG_SRC = re.compile(
        r'<a[^>]+href="(/zhodetail/(\d+)\.html)"[\s\S]{0,800}?<img[^>]+src="([^"]+)"',
    )
    # 卡片备注 (如"抢先版" "更新至第10集")
    _RE_PIC_TEXT = re.compile(
        r'class="[^"]*pic-text[^"]*"[^>]*>([^<]+)<',
    )
    # 分页: /zhotp/1-3018.html 中的 3018 即最大页
    _RE_PAGE_NUM = re.compile(r"/zhotp/\d+-(\d+)\.html")
    # 详情页标题
    _RE_DETAIL_TITLE = re.compile(
        r'<h3[^>]*class="[^"]*title[^"]*"[^>]*>([^<]+)</h3>',
    )
    # 详情页封面 (thumb 块内的 data-original)
    _RE_DETAIL_PIC = re.compile(
        r'<div[^>]+class="[^"]*stui-content__thumb[^"]*"[\s\S]*?'
        r'data-original="([^"]+)"',
    )
    # 详情页 <p class="data"> 整块
    _RE_DATA_P = re.compile(
        r'<p[^>]+class="[^"]*data[^"]*"[^>]*>([\s\S]*?)</p>',
    )
    # 简介 (detail-sketch 或 detail-content)
    _RE_VOD_CONTENT = re.compile(
        r'class="[^"]*detail-sketch[^"]*"[^>]*>([\s\S]*?)</span>',
    )
    _RE_VOD_CONTENT_FULL = re.compile(
        r'class="[^"]*detail-content[^"]*"[^>]*>([\s\S]*?)</span>',
    )
    # 播放源 + 剧集
    _RE_PLAY_UL = re.compile(
        r'<ul[^>]*class="stui-content__playlist[^"]*"[^>]*>([\s\S]*?)</ul>',
    )
    _RE_PLAY_EP = re.compile(
        r'<a[^>]+href="(/zhoplay/(\d+-\d+-\d+)\.html)"[^>]*>([\s\S]*?)</a>',
    )
    # 播放页 player_xxxx JSON
    _RE_PLAYER_JSON = re.compile(
        r'var\s+player_\w+\s*=\s*(\{[\s\S]*?\})\s*;?\s*</script>',
    )
    _RE_PLAYER_URL = re.compile(r'"url"\s*:\s*"([^"]+)"')
    # m3u8 直链兜底
    _RE_M3U8_DIRECT = re.compile(
        r'https?://[^"\'\s]+\.(?:m3u8|mp4)(?:[^"\'\s]*)',
    )

    # ============================================================
    # 框架回调: 基础信息
    # ============================================================
    def getName(self):
        return "蓝海影院"

    def init(self, extend=""):
        """初始化: 自己 new 一个 Session, 完全掌控 HTTP 行为。"""
        self.header = {
            "User-Agent": UA,
            "Referer": HOST + "/",
            "Accept": ("text/html,application/xhtml+xml,application/xml;"
                       "q=0.9,image/avif,image/webp,*/*;q=0.8"),
            "Accept-Encoding": "gzip, deflate",
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
            "Connection": "keep-alive",
        }
        self._sess_lock = threading.Lock()
        try:
            import requests
            from requests.adapters import HTTPAdapter
            self._session = requests.Session()
            adapter = HTTPAdapter(pool_connections=20, pool_maxsize=20)
            self._session.mount("http://", adapter)
            self._session.mount("https://", adapter)
            self._session.trust_env = False
        except Exception as e:
            print(f"[蓝海] requests 不可用, 回退到框架 fetch: {e}")
            self._session = None
        # 缓存
        self._list_cache = {}        # (tid, page) -> (ts, payload)
        self._detail_cache = {}      # vod_id -> (ts, payload)
        self._cache_lock = threading.Lock()
        # 熔断
        self._cb_fails = 0
        self._cb_open_until = 0
        self._cb_lock = threading.Lock()

    def isVideoFormat(self, url):
        u = (url or "").lower().rstrip("?#")
        return any(u.endswith(ext) for ext in (".m3u8", ".mp4", ".flv", ".ts"))

    def destroy(self):
        """关闭 Session, 释放连接。"""
        sess = getattr(self, "_session", None)
        if sess is not None:
            try:
                sess.close()
            except Exception:
                pass

    # ============================================================
    # 熔断器
    # ============================================================
    def _circuit_allow(self):
        """返回 True 表示可以发请求, False 表示熔断中。"""
        with self._cb_lock:
            if self._cb_open_until and time.time() < self._cb_open_until:
                return False
            return True

    def _circuit_record(self, ok):
        with self._cb_lock:
            if ok:
                self._cb_fails = 0
            else:
                self._cb_fails += 1
                if self._cb_fails >= CIRCUIT_FAILS:
                    self._cb_open_until = time.time() + CIRCUIT_COOLDOWN
                    print(f"[蓝海] 熔断 {CIRCUIT_COOLDOWN}s (连续失败 {self._cb_fails} 次)")

    # ============================================================
    # 网络层
    # ============================================================
    def _http_get(self, url, timeout=10):
        """统一的 GET, 优先走自己 new 的 Session, 失败回退到 self.fetch。"""
        if not self._circuit_allow():
            return ""

        ok = False
        sess = getattr(self, "_session", None)
        if sess is not None and hasattr(sess, "get"):
            try:
                rsp = sess.get(url, headers=self.header,
                               timeout=timeout, verify=False)
                if rsp is not None and getattr(rsp, "status_code", 0) == 200 \
                        and (getattr(rsp, "text", None) or ""):
                    ok = True
                    return rsp.text
            except Exception as e:
                print(f"[蓝海] session 失败, 回退 fetch: {url} ({e})")

        try:
            rsp = self.fetch(url, headers=self.header, timeout=timeout)
            if rsp is not None and getattr(rsp, "status_code", 0) == 200 \
                    and (getattr(rsp, "text", None) or ""):
                ok = True
                return rsp.text
        except Exception as e:
            print(f"[蓝海] fetch 也失败: {url} ({e})")
        finally:
            self._circuit_record(ok)
        return ""

    def _abs(self, url):
        return _abs_url(url, HOST)

    # ============================================================
    # 列表解析 (首页 / 分类共用)
    # ============================================================
    def _parse_vod(self, html):
        """解析所有详情卡片, 返回 list[dict]。
        多策略: 严格 → 宽松 → img src 兜底 → title only 兜底。
        """
        items = []
        seen = set()
        pic_texts = [_strip(_unescape(rm.group(1)))
                     for rm in self._RE_PIC_TEXT.finditer(html)]

        def _add(url, title, pic, remark=""):
            if not url or url in seen:
                return
            seen.add(url)
            items.append({
                "vod_id": url,
                "vod_name": _strip(_unescape(title)),
                "vod_pic": self._abs(_unescape(pic)),
                "vod_remarks": remark,
            })

        # 策略 1: 严格 (data-original 在 title 后)
        list_matches = list(self._RE_LIST_ITEM.finditer(html))
        for i, m in enumerate(list_matches):
            _add(m.group(1), m.group(3), m.group(4),
                 pic_texts[i] if i < len(pic_texts) else "")

        # 策略 2: 宽松 (data-original 在 title 前)
        loose_count = 0
        for m in self._RE_LIST_ITEM_LOOSE.finditer(html):
            idx = len(list_matches) + loose_count
            _add(m.group(1), m.group(4), m.group(3),
                 pic_texts[idx] if idx < len(pic_texts) else "")
            loose_count += 1

        # 策略 3: 兜底 (用 <img> src 当封面)
        for m in self._RE_LIST_IMG_SRC.finditer(html):
            pic = m.group(3)
            if "load.gif" in pic or "loading" in pic.lower():
                continue
            idx = len(list_matches) + loose_count
            _add(m.group(1), "", pic,
                 pic_texts[idx] if idx < len(pic_texts) else "")
            loose_count += 1

        # 策略 4: 终极兜底 — 只要 href + title
        if not items:
            for i, m in enumerate(self._RE_LIST_TITLE_ONLY.finditer(html)):
                _add(m.group(1), m.group(3), "",
                     pic_texts[i] if i < len(pic_texts) else "")

        return items

    def _pagecount(self, html, cur_page):
        """从分页链接里取最大页码, 兜底返回 cur_page。"""
        mx = cur_page
        for pm in self._RE_PAGE_NUM.finditer(html):
            n = int(pm.group(1))
            if n > mx:
                mx = n
        return mx

    # ============================================================
    # 框架回调: 首页 / 分类 / 筛选 / 详情 / 搜索 / 播放
    # ============================================================
    def homeContent(self, filter):
        """返回一级分类 + 二级筛选配置。"""
        return {"class": CLASSES, "filters": FILTERS}

    def homeVideoContent(self):
        """首页推荐: 抓首页, 取前 30 条最新更新。"""
        html = self._http_get(HOST + "/", timeout=6)
        if not html:
            return {"list": []}
        return {"list": self._parse_vod(html)[:HOME_PAGE_SIZE]}

    def categoryContent(self, tid, pg, filter, extend):
        """分类列表: 拼 /zhotp/{tid}-{page}.html URL。
        如果 extend 中有 class (子分类 tid), 则使用该子分类 tid。
        优化: 列表页 60s 缓存, 翻页秒出。
        """
        try:
            page = int(pg or 1)
            if page < 1:
                page = 1

            ext = extend or {}
            cls = str(ext.get("class", "") or "")
            # 子分类有独立 tid, 直接使用
            use_tid = cls if cls else str(tid)

            cache_key = (use_tid, page)
            now = time.time()
            with self._cache_lock:
                hit = self._list_cache.get(cache_key)
                if hit and now - hit[0] < LIST_CACHE_TTL:
                    return hit[1]

            page_str = f"-{page}" if page > 1 else ""
            url = CATEGORY_URL_TEMPLATE.format(
                host=HOST, tid=use_tid, page=page_str,
            )

            html = self._http_get(url, timeout=7)
            if not html:
                print(f"[蓝海] categoryContent empty tid={use_tid} pg={page}")
                payload = {"list": [], "page": page, "pagecount": 1,
                           "limit": LIST_PAGE_SIZE, "total": 0}
                return payload

            videos = self._parse_vod(html)
            pagecount = self._pagecount(html, page)
            if not videos:
                pagecount = max(1, page)

            payload = {
                "list": videos,
                "page": page,
                "pagecount": pagecount,
                "limit": len(videos) or LIST_PAGE_SIZE,
                "total": pagecount * LIST_PAGE_SIZE,
            }
            with self._cache_lock:
                self._list_cache[cache_key] = (now, payload)
            return payload
        except Exception as e:
            print(f"[蓝海] categoryContent 异常 tid={tid} pg={pg} extend={extend!r}: {e}")
            return {"list": [], "page": 1, "pagecount": 1,
                    "limit": LIST_PAGE_SIZE, "total": 0}

    def detailContent(self, ids):
        """详情页: 解析元数据 + 播放列表。
        vod_id 格式: /zhodetail/{id}.html 或纯数字 id。
        优化: 详情页 5 分钟缓存。
        """
        try:
            if isinstance(ids, (list, tuple)):
                ids = ids[0]
            vod_id = str(ids)

            now = time.time()
            with self._cache_lock:
                hit = self._detail_cache.get(vod_id)
                if hit and now - hit[0] < DETAIL_CACHE_TTL:
                    return hit[1]

            if vod_id.startswith("/"):
                url = HOST + vod_id
            else:
                url = HOST + "/zhodetail/" + vod_id + ".html"

            html = self._http_get(url, timeout=8)
            if not html:
                return {"list": []}

            vod = {
                "vod_id": vod_id,
                "vod_name": "",
                "vod_pic": "",
                "vod_year": "",
                "vod_area": "",
                "vod_lang": "",
                "vod_remarks": "",
                "vod_actor": "",
                "vod_director": "",
                "vod_class": "",
                "vod_content": "",
                "vod_play_from": "",
                "vod_play_url": "",
            }

            # 标题
            m = self._RE_DETAIL_TITLE.search(html)
            if m:
                vod["vod_name"] = _strip(_unescape(m.group(1)))

            # 封面
            m = self._RE_DETAIL_PIC.search(html)
            if m:
                vod["vod_pic"] = self._abs(_unescape(m.group(1)).strip())

            # 解析 <p class="data"> 块
            data_ps = self._RE_DATA_P.findall(html)
            if data_ps:
                # p0: 主演
                actors = re.findall(r'<a[^>]*>([^<]+)</a>', data_ps[0])
                if actors:
                    vod["vod_actor"] = ",".join(_strip(_unescape(a)) for a in actors)

                # p1: 导演
                if len(data_ps) >= 2:
                    directors = re.findall(r'<a[^>]*>([^<]+)</a>', data_ps[1])
                    if directors:
                        vod["vod_director"] = ",".join(_strip(_unescape(d)) for d in directors)

                # p3: 类型 / 地区 / 年份
                if len(data_ps) >= 4:
                    p3 = data_ps[3]
                    # 类型
                    type_match = re.search(r'类型[：:]\s*</span>\s*<a[^>]*>([^<]+)</a>', p3)
                    if type_match:
                        vod["vod_class"] = _strip(_unescape(type_match.group(1)))
                    # 地区
                    area_match = re.search(r'地区[：:]\s*</span>\s*<a[^>]*>([^<]+)</a>', p3)
                    if area_match:
                        vod["vod_area"] = _strip(_unescape(area_match.group(1)))
                    # 年份
                    year_match = re.search(r'年份[：:]\s*</span>\s*<a[^>]*>(\d{4})</a>', p3)
                    if year_match:
                        vod["vod_year"] = year_match.group(1)

            # 备注 (从 thumb 块的 pic-text 取)
            remark_m = re.search(r'class="pic-text[^"]*"[^>]*>([^<]+)<', html)
            if remark_m:
                vod["vod_remarks"] = _strip(_unescape(remark_m.group(1)))

            # 简介
            m = self._RE_VOD_CONTENT_FULL.search(html)
            if not m:
                m = self._RE_VOD_CONTENT.search(html)
            if m:
                txt = re.sub(r"<[^>]+>", "", m.group(1))
                vod["vod_content"] = _strip(txt)[:500]

            # 播放源 + 剧集
            play_from, play_url = self._collect_playlist(html)
            if play_from:
                vod["vod_play_from"] = "$$$".join(play_from)
                vod["vod_play_url"] = "$$$".join(play_url)

            payload = {"list": [vod]}
            with self._cache_lock:
                self._detail_cache[vod_id] = (now, payload)
            return payload
        except Exception as e:
            print(f"[蓝海] detailContent 异常: {e}")
            return {"list": []}

    def _collect_playlist(self, html):
        """解析播放源 + 剧集。
        每个 <ul class="stui-content__playlist"> = 1 个播放源。
        过滤广告链接 (//app2.zstv47.com 等)。
        按 nid 升序排列。
        """
        play_from, play_url = [], []
        ul_blocks = self._RE_PLAY_UL.findall(html)
        if not ul_blocks:
            return play_from, play_url

        for idx, chunk in enumerate(ul_blocks, 1):
            eps_raw = []
            seen_paths = set()
            for em in self._RE_PLAY_EP.finditer(chunk):
                path = em.group(1)
                ep_name = _strip(_unescape(re.sub(r"<[^>]+>", "", em.group(3)))) or "正片"
                if path in seen_paths:
                    continue
                seen_paths.add(path)
                nm = re.search(r"-(\d+)\.html$", path)
                nid = int(nm.group(1)) if nm else 0
                eps_raw.append((nid, ep_name, path))
            eps_raw.sort(key=lambda x: x[0])
            eps = [f"{name}${path}" for _, name, path in eps_raw]
            if eps:
                src_name = f"线路{idx}" if len(ul_blocks) > 1 else "播放"
                play_from.append(src_name)
                play_url.append("#".join(eps))
        return play_from, play_url

    def searchContent(self, key, quick, pg="1"):
        """搜索: 站点 /zhosc/ 路由触发验证码, 暂不支持搜索。
        返回空列表, 避免 TVBox 框架报错。
        """
        return {"list": [], "page": 1, "pagecount": 1, "limit": 0, "total": 0}

    def playerContent(self, flag, id, vipFlags):
        """播放: 从 /zhoplay/ 页 player_xxx JSON 取真实 m3u8。"""
        play_path = str(id or "")
        if not play_path:
            return {"parse": 0, "url": ""}

        if self.isVideoFormat(play_path):
            return {"parse": 0, "url": play_path,
                    "header": {"User-Agent": UA, "Referer": HOST + "/"}}

        if "/zhoplay/" in play_path:
            if not play_path.startswith("http"):
                play_url = HOST + play_path
            else:
                play_url = play_path
            html = self._http_get(play_url, timeout=6)
            if html:
                real = self._extract_m3u8(html)
                if real:
                    return {"parse": 0, "url": real,
                            "header": {"User-Agent": UA, "Referer": play_url}}

        return {"parse": 0, "url": play_path,
                "header": {"User-Agent": UA, "Referer": HOST + "/"}}

    def _extract_m3u8(self, html):
        """从播放页提取真实 m3u8。"""
        m = self._RE_PLAYER_JSON.search(html)
        if m:
            try:
                obj = json.loads(m.group(1))
                u = obj.get("url") or ""
                if u:
                    return u
            except Exception:
                pass
            um = self._RE_PLAYER_URL.search(m.group(1))
            if um:
                val = um.group(1).replace("\\/", "/").replace("\\\\", "\\")
                return val

        m = self._RE_M3U8_DIRECT.search(html)
        return m.group(0) if m else ""

    def localProxy(self, param):
        return [200, "video/MP2T", b"", ""]


# ============================================================
# 独立运行自检 (框架下不会触发, 方便本地调试)
# ============================================================
if __name__ == "__main__":
    import sys

    def _bench(label, fn):
        t0 = time.time()
        r = fn()
        print(f"  [{label}] 耗时 {time.time() - t0:.2f}s")
        return r

    print("== homeContent ==")
    sp = Spider()
    sp.init()
    print(json.dumps(sp.homeContent(True), ensure_ascii=False)[:300])

    print("\n== homeVideoContent 前3条 ==")
    hvc = _bench("首页", lambda: sp.homeVideoContent())
    for it in hvc["list"][:3]:
        print(" ", it)

    print("\n== categoryContent 电影第1页 ==")
    cc = _bench("电影分类", lambda: sp.categoryContent("1", 1, True, {}))
    print("  条数:", len(cc["list"]), "总页数:", cc["pagecount"])
    if cc["list"]:
        print("  第一个 vod_id:", cc["list"][0]["vod_id"])

    print("\n== 二级分类 动作片 ==")
    cc2 = _bench("动作片", lambda: sp.categoryContent("1", 1, True, {"class": "6"}))
    print("  条数:", len(cc2["list"]), "总页数:", cc2["pagecount"])
    if cc2["list"]:
        print("  第一个 vod_id:", cc2["list"][0]["vod_id"])

    if cc["list"]:
        print("\n== detailContent ==")
        vid = cc["list"][0]["vod_id"]
        print("  用 vod_id:", vid)
        dc = _bench("详情", lambda: sp.detailContent([vid]))
        if dc["list"]:
            v = dc["list"][0]
            for k in ("vod_name", "vod_year", "vod_area", "vod_class",
                      "vod_actor", "vod_director", "vod_remarks"):
                print(f"  {k}: {v.get(k)}")
            print("  vod_play_from:", v.get("vod_play_from"))
            first = (v.get("vod_play_url") or "").split("#")[0]
            print("  第一集:", first)
            if first:
                print("\n== playerContent ==")
                pc = _bench("播放解析",
                            lambda: sp.playerContent("", first.split("$")[-1], []))
                print("  parse:", pc["parse"])
                print("  url:", pc["url"][:120] if pc["url"] else "空")

    print("\n== searchContent 测试 ==")
    sc = _bench("搜索", lambda: sp.searchContent("爱情", True))
    print("  total:", sc["total"], "条数:", len(sc["list"]))

    sp.destroy()
    print("\n== 自检完成 ==")
