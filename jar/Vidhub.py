# -*- coding: utf-8 -*-
"""
Vidhub 视频库 TVBox/猫影视爬虫插件 — https://vidhub2.top/
苹果CMS v10 + LAYUI(mxTheme) 模板

路由:
  首页         /
  分类落地页   /vodtype/{tid}.html            (1=电影 2=连续剧 3=综艺 4=动漫)
  分类筛选列表 /vodshow/{tid}-{area}-{order}-{class}-{lang}-{letter}-{star}-{state}-{page}-{director}-{by}-{year}.html
  详情         /voddetail/{id}.html
  播放         /vodplay/{id}-{sid}-{nid}.html
  搜索API      /index.php/ajax/suggest?mid=1&wd={kw}&page={page}   (与剧圈圈完全一致)

列表页 12 字段(0-based)含义:
  0=tid  1=地区  2=排序(time/hits/score)  3=类型  4=语言  5=首字母
  6=明星 7=状态 8=页码  9=导演  10=排序方式 11=年份
  page=1 时省略页码字段(留空), 与站点生成的"全部"链接一致。

播放解析(vidhub 专属, 与剧圈圈 sign 解密无关):
  1. GET /vodplay/{id}-{sid}-{nid}.html -> 提取 <iframe src="/player/?u=...">
  2. GET /player/?u=... -> 页面内联 var config = {"url":"...m3u8", ...}
  3. 直接返回 config.url 作为真实播放地址 (parse=0)
  注: 剧圈圈复刻 jqqzx.one 的 sign()/customStrDecode 解密逻辑在本站不适用, 已移除。
"""

import re
import json
import time
import warnings
import threading
from urllib.parse import urljoin, quote

try:
    warnings.filterwarnings("ignore")
    import urllib3
    urllib3.disable_warnings()
except Exception:
    pass

try:
    from base.spider import Spider
except ImportError:
    import requests as _rq
    from requests.adapters import HTTPAdapter

    class Spider:
        def __init__(self):
            self._session = _rq.Session()
            adapter = HTTPAdapter(pool_connections=20, pool_maxsize=20)
            self._session.mount("http://", adapter)
            self._session.mount("https://", adapter)

        def fetch(self, url, headers=None, timeout=15, **kw):
            headers = headers or {}
            headers.setdefault("User-Agent", UA)
            return self._session.get(url, headers=headers, timeout=timeout, verify=False, **kw)

        def destroy(self):
            try:
                self._session.close()
            except Exception:
                pass


HOST = "https://vidhub2.top"
UA = ("Mozilla/5.0 (Linux; Android 12; M2007J22C) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/120.0.0.0 Mobile Safari/537.36")

# 主分类 (取自站点导航 menu: /vodtype/{tid}.html)
CLASSES = [
    {"type_name": "电影", "type_id": "1"},
    {"type_name": "连续剧", "type_id": "2"},
    {"type_name": "综艺", "type_id": "3"},
    {"type_name": "动漫", "type_id": "4"},
]

# 二级分类筛选条件
# 注意: 键名保持与剧圈圈一致 (class/area/year/lang), 映射关系见 categoryContent:
#   class -> 字段位3, area -> 字段位1, lang -> 字段位4, year -> 字段位11
FILTERS = {
    "1": [
        {"key": "class", "name": "类型", "value": [
            {"n": "全部", "v": ""},
            {"n": "动作", "v": "动作"}, {"n": "爱情", "v": "爱情"}, {"n": "剧情", "v": "剧情"},
            {"n": "喜剧", "v": "喜剧"}, {"n": "科幻", "v": "科幻"}, {"n": "恐怖", "v": "恐怖"},
            {"n": "悬疑", "v": "悬疑"}, {"n": "惊悚", "v": "惊悚"}, {"n": "犯罪", "v": "犯罪"},
            {"n": "战争", "v": "战争"}, {"n": "奇幻", "v": "奇幻"}, {"n": "古装", "v": "古装"},
            {"n": "历史", "v": "历史"}, {"n": "武侠", "v": "武侠"}, {"n": "冒险", "v": "冒险"},
            {"n": "动画", "v": "动画"}, {"n": "青春", "v": "青春"}, {"n": "文艺", "v": "文艺"},
            {"n": "运动", "v": "运动"}, {"n": "枪战", "v": "枪战"}, {"n": "警匪", "v": "警匪"},
            {"n": "微电影", "v": "微电影"}, {"n": "网络电影", "v": "网络电影"}, {"n": "经典", "v": "经典"},
        ]},
        {"key": "area", "name": "地区", "value": [
            {"n": "全部", "v": ""},
            {"n": "大陆", "v": "大陆"}, {"n": "香港", "v": "香港"}, {"n": "台湾", "v": "台湾"},
            {"n": "美国", "v": "美国"}, {"n": "韩国", "v": "韩国"}, {"n": "日本", "v": "日本"},
            {"n": "泰国", "v": "泰国"}, {"n": "英国", "v": "英国"}, {"n": "法国", "v": "法国"},
            {"n": "德国", "v": "德国"}, {"n": "意大利", "v": "意大利"}, {"n": "西班牙", "v": "西班牙"},
            {"n": "印度", "v": "印度"}, {"n": "加拿大", "v": "加拿大"}, {"n": "其他", "v": "其他"},
        ]},
        {"key": "lang", "name": "语言", "value": [
            {"n": "全部", "v": ""},
            {"n": "国语", "v": "国语"}, {"n": "粤语", "v": "粤语"}, {"n": "英语", "v": "英语"},
            {"n": "日语", "v": "日语"}, {"n": "韩语", "v": "韩语"}, {"n": "法语", "v": "法语"},
            {"n": "德语", "v": "德语"}, {"n": "闽南语", "v": "闽南语"}, {"n": "汉语普通话", "v": "汉语普通话"},
            {"n": "其它", "v": "其它"},
        ]},
        {"key": "year", "name": "年份", "value": [
            {"n": "全部", "v": ""},
            {"n": "2026", "v": "2026"}, {"n": "2025", "v": "2025"}, {"n": "2024", "v": "2024"},
            {"n": "2023", "v": "2023"}, {"n": "2022", "v": "2022"}, {"n": "2021", "v": "2021"},
            {"n": "2020", "v": "2020"}, {"n": "2019", "v": "2019"}, {"n": "2018", "v": "2018"},
            {"n": "2017", "v": "2017"}, {"n": "2016", "v": "2016"}, {"n": "2015", "v": "2015"},
            {"n": "2014", "v": "2014"}, {"n": "2013", "v": "2013"},
        ]},
    ],
    "2": [
        {"key": "class", "name": "类型", "value": [
            {"n": "全部", "v": ""},
            {"n": "剧情", "v": "剧情"}, {"n": "喜剧", "v": "喜剧"}, {"n": "动作", "v": "动作"},
            {"n": "爱情", "v": "爱情"}, {"n": "古装", "v": "古装"}, {"n": "历史", "v": "历史"},
            {"n": "战争", "v": "战争"}, {"n": "犯罪", "v": "犯罪"}, {"n": "奇幻", "v": "奇幻"},
            {"n": "家庭", "v": "家庭"}, {"n": "情景", "v": "情景"}, {"n": "商战", "v": "商战"},
            {"n": "乡村", "v": "乡村"}, {"n": "青春偶像", "v": "青春偶像"}, {"n": "网剧", "v": "网剧"},
            {"n": "经典", "v": "经典"}, {"n": "其他", "v": "其他"},
        ]},
        {"key": "area", "name": "地区", "value": [
            {"n": "全部", "v": ""},
            {"n": "内地", "v": "内地"}, {"n": "香港", "v": "香港"}, {"n": "台湾", "v": "台湾"},
            {"n": "美国", "v": "美国"}, {"n": "韩国", "v": "韩国"}, {"n": "日本", "v": "日本"},
            {"n": "泰国", "v": "泰国"}, {"n": "英国", "v": "英国"}, {"n": "新加坡", "v": "新加坡"},
            {"n": "其他", "v": "其他"},
        ]},
        {"key": "lang", "name": "语言", "value": [
            {"n": "全部", "v": ""},
            {"n": "国语", "v": "国语"}, {"n": "粤语", "v": "粤语"}, {"n": "英语", "v": "英语"},
            {"n": "日语", "v": "日语"}, {"n": "韩语", "v": "韩语"}, {"n": "闽南语", "v": "闽南语"},
            {"n": "汉语普通话", "v": "汉语普通话"}, {"n": "其它", "v": "其它"},
        ]},
        {"key": "year", "name": "年份", "value": [
            {"n": "全部", "v": ""},
            {"n": "2026", "v": "2026"}, {"n": "2025", "v": "2025"}, {"n": "2024", "v": "2024"},
            {"n": "2023", "v": "2023"}, {"n": "2022", "v": "2022"}, {"n": "2021", "v": "2021"},
            {"n": "2020", "v": "2020"}, {"n": "2019", "v": "2019"}, {"n": "2018", "v": "2018"},
            {"n": "2017", "v": "2017"}, {"n": "2016", "v": "2016"}, {"n": "2015", "v": "2015"},
            {"n": "2014", "v": "2014"}, {"n": "2013", "v": "2013"},
        ]},
    ],
    "3": [
        {"key": "class", "name": "类型", "value": [
            {"n": "全部", "v": ""},
            {"n": "选秀", "v": "选秀"}, {"n": "音乐", "v": "音乐"}, {"n": "访谈", "v": "访谈"},
            {"n": "美食", "v": "美食"}, {"n": "生活", "v": "生活"}, {"n": "纪实", "v": "纪实"},
            {"n": "游戏互动", "v": "游戏互动"}, {"n": "旅游", "v": "旅游"}, {"n": "求职", "v": "求职"},
            {"n": "曲艺", "v": "曲艺"}, {"n": "财经", "v": "财经"}, {"n": "播报", "v": "播报"},
            {"n": "情感", "v": "情感"},
        ]},
        {"key": "area", "name": "地区", "value": [
            {"n": "全部", "v": ""},
            {"n": "内地", "v": "内地"}, {"n": "港台", "v": "港台"}, {"n": "日韩", "v": "日韩"},
            {"n": "欧美", "v": "欧美"},
        ]},
        {"key": "lang", "name": "语言", "value": [
            {"n": "全部", "v": ""},
            {"n": "国语", "v": "国语"}, {"n": "粤语", "v": "粤语"}, {"n": "英语", "v": "英语"},
            {"n": "日语", "v": "日语"}, {"n": "韩语", "v": "韩语"}, {"n": "闽南语", "v": "闽南语"},
            {"n": "汉语普通话", "v": "汉语普通话"}, {"n": "其它", "v": "其它"},
        ]},
        {"key": "year", "name": "年份", "value": [
            {"n": "全部", "v": ""},
            {"n": "2026", "v": "2026"}, {"n": "2025", "v": "2025"}, {"n": "2024", "v": "2024"},
            {"n": "2023", "v": "2023"}, {"n": "2022", "v": "2022"}, {"n": "2021", "v": "2021"},
            {"n": "2020", "v": "2020"}, {"n": "2019", "v": "2019"}, {"n": "2018", "v": "2018"},
            {"n": "2017", "v": "2017"}, {"n": "2016", "v": "2016"}, {"n": "2015", "v": "2015"},
            {"n": "2014", "v": "2014"}, {"n": "2013", "v": "2013"},
        ]},
    ],
    "4": [
        {"key": "class", "name": "类型", "value": [
            {"n": "全部", "v": ""},
            {"n": "热血", "v": "热血"}, {"n": "搞笑", "v": "搞笑"}, {"n": "机战", "v": "机战"},
            {"n": "科幻", "v": "科幻"}, {"n": "推理", "v": "推理"}, {"n": "冒险", "v": "冒险"},
            {"n": "运动", "v": "运动"}, {"n": "益智", "v": "益智"}, {"n": "社会", "v": "社会"},
            {"n": "情感", "v": "情感"}, {"n": "校园", "v": "校园"}, {"n": "少女", "v": "少女"},
            {"n": "少年", "v": "少年"}, {"n": "萝莉", "v": "萝莉"}, {"n": "原创", "v": "原创"},
            {"n": "励志", "v": "励志"}, {"n": "战争", "v": "战争"}, {"n": "亲子", "v": "亲子"},
            {"n": "其他", "v": "其他"},
        ]},
        {"key": "area", "name": "地区", "value": [
            {"n": "全部", "v": ""},
            {"n": "国产", "v": "国产"}, {"n": "日本", "v": "日本"}, {"n": "欧美", "v": "欧美"},
            {"n": "其他", "v": "其他"},
        ]},
        {"key": "lang", "name": "语言", "value": [
            {"n": "全部", "v": ""},
            {"n": "国语", "v": "国语"}, {"n": "粤语", "v": "粤语"}, {"n": "英语", "v": "英语"},
            {"n": "日语", "v": "日语"}, {"n": "韩语", "v": "韩语"}, {"n": "闽南语", "v": "闽南语"},
            {"n": "汉语普通话", "v": "汉语普通话"}, {"n": "其它", "v": "其它"},
        ]},
        {"key": "year", "name": "年份", "value": [
            {"n": "全部", "v": ""},
            {"n": "2026", "v": "2026"}, {"n": "2025", "v": "2025"}, {"n": "2024", "v": "2024"},
            {"n": "2023", "v": "2023"}, {"n": "2022", "v": "2022"}, {"n": "2021", "v": "2021"},
            {"n": "2020", "v": "2020"}, {"n": "2019", "v": "2019"}, {"n": "2018", "v": "2018"},
            {"n": "2017", "v": "2017"}, {"n": "2016", "v": "2016"}, {"n": "2015", "v": "2015"},
            {"n": "2014", "v": "2014"}, {"n": "2013", "v": "2013"},
        ]},
    ],
}

LIST_PAGE_SIZE = 36
HOME_PAGE_SIZE = 24
LIST_CACHE_TTL = 60
DETAIL_CACHE_TTL = 300
HOME_CACHE_TTL = 30
SEARCH_CACHE_TTL = 30
CIRCUIT_FAILS = 3
CIRCUIT_COOLDOWN = 30


def _urlencode(s):
    return quote(s or "", safe="")


def _b64decode_str(s):
    """base64 解码为文本, 失败返回空串"""
    import base64
    try:
        raw = base64.b64decode(s)
        if isinstance(raw, str):
            return raw
        return raw.decode("utf-8", errors="replace")
    except Exception:
        return ""


def _strip(txt):
    return re.sub(r"\s+", " ", txt or "").strip()


def _unescape(txt):
    if not txt:
        return ""
    try:
        import html as _html
        return _html.unescape(txt)
    except Exception:
        return re.sub(r"&#(\d+);", lambda m: chr(int(m.group(1))), txt)


def _abs_url(url, base):
    if not url:
        return ""
    if url.startswith("//"):
        return "https:" + url
    if url.startswith("http"):
        return url
    if url.startswith("/"):
        return base + url
    return urljoin(base + "/", url)


# ---------------------------------------------------------------------------
# Vidhub 播放地址提取 (LAYUI 模板: /player/?u= 页面内联 config.url)
# 流程: play 页 iframe src(/player/?u=...) -> GET /player/ 页 -> 解析 var config.url
# ---------------------------------------------------------------------------

def _extract_player_iframe(html):
    """从 /vodplay/ 页提取 <iframe src="/player/?u=..."> 的完整 src"""
    if not html:
        return ""
    m = re.search(r'src="(/player/\?u=[^"]+)"', html)
    if m:
        return m.group(1)
    # 兜底: 部分模板可能用 data-src 或 javascript 变量
    m = re.search(r'player_if[^>]*src="([^"]+)"', html)
    if m:
        return m.group(1)
    return ""


def _extract_player_config(html):
    """从 /player/ 页提取 var config = {...} 并解析为 dict; 用大括号计数保证完整"""
    if not html:
        return None
    idx = html.find("var config")
    if idx < 0:
        return None
    brace_start = html.find("{", idx)
    if brace_start < 0:
        return None
    depth = 0
    for i in range(brace_start, len(html)):
        c = html[i]
        if c == "{":
            depth += 1
        elif c == "}":
            depth -= 1
            if depth == 0:
                try:
                    return json.loads(html[brace_start:i + 1])
                except Exception as e:
                    print("[Vidhub] config JSON解析失败: " + str(e))
                    return None
    return None


class Spider(Spider):
    # 列表项: 锚点(/voddetail/{id}.html, 带 title) + 其后的封面 data-src
    _RE_VOD_ANCHOR = re.compile(
        r'<a[^>]+href="(/voddetail/(\d+)\.html)"[^>]*title="([^"]*)"'
    )
    _RE_ITEM_PIC = re.compile(r'data-src="([^"]+)"')
    _RE_ITEM_CAPTION = re.compile(
        r'class="module-item-caption">([\s\S]*?)</div>'
    )
    # 详情页
    _RE_DETAIL_TITLE = re.compile(r'<h1[^>]*>([^<]+)</h1>')
    _RE_DETAIL_PIC = re.compile(
        r'class="[^"]*module-item-pic[^"]*"[^>]*>[\s\S]*?data-src="([^"]+)"'
    )
    _RE_DETAIL_CAPTION = re.compile(
        r'class="module-item-caption">\s*<span>([^<]*)</span>\s*'
        r'<span[^>]*class="video-class"[^>]*>([^<]*)</span>\s*<span>([^<]*)</span>'
    )
    _RE_INFO_ITEM = re.compile(
        r'class="video-info-itemtitle">([^<]+)</span>\s*'
        r'<div class="video-info-item[^"]*"[^>]*>([\s\S]*?)</div>'
    )
    _RE_VOD_CONTENT = re.compile(
        r'class="video-info-itemtitle">剧情[：:]</span>[\s\S]*?<div class="video-info-item[^"]*"[^>]*>([\s\S]*?)</div>'
    )
    # 播放列表
    _RE_PLAYLIST_BLOCK = re.compile(
        r'class="[^"]*module-player-list[^"]*"[^>]*>([\s\S]*?)</div>\s*</div>'
    )
    _RE_PLAY_EP = re.compile(
        r'<a[^>]+href="(/vodplay/(\d+-\d+-\d+)\.html)"[^>]*>([\s\S]*?)</a>'
    )
    # 分页 (列表页页码链接 /vodshow/{tid}--------{N}---.html)
    _RE_PAGE_NUM = re.compile(r'/vodshow/\d+--------(\d+)---')
    _RE_PAGE_LAST = re.compile(r'/vodshow/\d+--------(\d+)---"[^>]*>\s*尾页')

    def getName(self):
        return "Vidhub"

    def init(self, extend=""):
        self.header = {
            "User-Agent": UA,
            "Referer": HOST + "/",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
            "Accept-Encoding": "gzip, deflate",
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
            "Connection": "keep-alive",
        }
        try:
            import requests
            from requests.adapters import HTTPAdapter
            self._session = requests.Session()
            adapter = HTTPAdapter(pool_connections=20, pool_maxsize=20)
            self._session.mount("http://", adapter)
            self._session.mount("https://", adapter)
            self._session.trust_env = False
        except Exception as e:
            print("[Vidhub] requests 不可用, 回退到框架 fetch: " + str(e))
            self._session = None

        self._list_cache = {}
        self._detail_cache = {}
        self._home_cache = None
        self._search_cache = {}
        self._cache_lock = threading.Lock()
        self._cb_fails = 0
        self._cb_open_until = 0
        self._cb_lock = threading.Lock()

    def isVideoFormat(self, url):
        u = (url or "").lower().rstrip("?#")
        return any(u.endswith(ext) for ext in (".m3u8", ".mp4", ".flv", ".ts"))

    def destroy(self):
        sess = getattr(self, "_session", None)
        if sess is not None:
            try:
                sess.close()
            except Exception:
                pass

    def _circuit_allow(self):
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
                    print("[Vidhub] 熔断 " + str(CIRCUIT_COOLDOWN) + "s")

    def _http_get(self, url, timeout=10):
        if not self._circuit_allow():
            return ""
        ok = False
        sess = getattr(self, "_session", None)
        if sess is not None and hasattr(sess, "get"):
            try:
                rsp = sess.get(url, headers=self.header, timeout=timeout, verify=False)
                sc = getattr(rsp, "status_code", 0)
                txt = getattr(rsp, "text", None) or ""
                if rsp is not None and sc == 200 and txt:
                    ok = True
                    return rsp.text
            except Exception as e:
                print("[Vidhub] session 失败: " + url + " (" + str(e) + ")")
        try:
            rsp = self.fetch(url, headers=self.header, timeout=timeout)
            sc = getattr(rsp, "status_code", 0)
            txt = getattr(rsp, "text", None) or ""
            if rsp is not None and sc == 200 and txt:
                ok = True
                return rsp.text
        except Exception as e:
            print("[Vidhub] fetch 失败: " + url + " (" + str(e) + ")")
        finally:
            self._circuit_record(ok)
        return ""

    def _http_get_json(self, url, timeout=10):
        html = self._http_get(url, timeout=timeout)
        if not html:
            return None
        try:
            return json.loads(html)
        except Exception as e:
            print("[Vidhub] JSON解析失败: " + url + " (" + str(e) + ")")
            return None

    def _abs(self, url):
        return _abs_url(url, HOST)

    # ------------------------------------------------------------------
    # 列表解析 (LAYUI module-item: 封面在 data-src, 详情在 /voddetail/)
    # ------------------------------------------------------------------
    def _parse_vod(self, html):
        items = []
        seen = set()

        def _add(vid, name, pic, remark=""):
            if not vid or vid in seen:
                return
            seen.add(vid)
            items.append({
                "vod_id": vid,
                "vod_name": _strip(_unescape(name)),
                "vod_pic": self._abs(_unescape(pic)),
                "vod_remarks": _strip(_unescape(remark)),
            })

        for m in self._RE_VOD_ANCHOR.finditer(html):
            href, vid, name = m.group(1), m.group(2), m.group(3)
            if not vid:
                continue
            # 取该锚点后最近的 data-src 作为封面 (懒加载图)
            tail = html[m.end():m.end() + 1200]
            pm = self._RE_ITEM_PIC.search(tail)
            pic = pm.group(1) if pm else ""
            # 备注: 尝试从附近 module-item-caption 取 (年份/类型/地区)
            remark = ""
            cm = self._RE_ITEM_CAPTION.search(tail)
            if cm:
                remark = re.sub(r"<[^>]+>", " ", cm.group(1))
            _add(href, name, pic, remark)

        return items

    def _pagecount(self, html, cur_page):
        mx = cur_page
        for pm in self._RE_PAGE_NUM.finditer(html):
            n = int(pm.group(1))
            if n > mx:
                mx = n
        lm = self._RE_PAGE_LAST.search(html)
        if lm:
            mx = max(mx, int(lm.group(1)))
        return mx

    def homeContent(self, filter):
        return {"class": CLASSES, "filters": FILTERS}

    def homeVideoContent(self):
        now = time.time()
        with self._cache_lock:
            if self._home_cache:
                ts, payload = self._home_cache
                if now - ts < HOME_CACHE_TTL:
                    return payload

        html = self._http_get(HOST + "/", timeout=6)
        if not html:
            return {"list": []}

        items = self._parse_vod(html)
        payload = {"list": items[:HOME_PAGE_SIZE]}

        with self._cache_lock:
            self._home_cache = (now, payload)
        return payload

    def categoryContent(self, tid, pg, filter, extend):
        try:
            page = int(pg or 1)
            if page < 1:
                page = 1
            ext = extend or {}
            cls = str(ext.get("class", "") or "")
            area = str(ext.get("area", "") or "")
            year = str(ext.get("year", "") or "")
            lang = str(ext.get("lang", "") or "")
            use_tid = str(tid)

            cache_key = (use_tid, cls, area, year, lang, page)
            now = time.time()
            with self._cache_lock:
                hit = self._list_cache.get(cache_key)
                if hit and now - hit[0] < LIST_CACHE_TTL:
                    return hit[1]

            # 12 字段: 0=tid 1=area 2=order 3=class 4=lang 5=letter
            #          6=star 7=state 8=page 9=director 10=by 11=year
            parts = [""] * 12
            parts[0] = use_tid
            parts[1] = _urlencode(area)        # 地区
            parts[3] = _urlencode(cls)         # 类型
            parts[4] = _urlencode(lang)        # 语言
            parts[11] = _urlencode(year)       # 年份
            if page > 1:
                parts[8] = str(page)           # 页码(仅>1时填入, 与站点一致)
            url = HOST + "/vodshow/" + "-".join(parts) + ".html"

            html = self._http_get(url, timeout=7)
            if not html:
                print("[Vidhub] categoryContent empty: " + url)
                return {"list": [], "page": page, "pagecount": 1, "limit": LIST_PAGE_SIZE, "total": 0}

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
            print("[Vidhub] categoryContent 异常: " + str(e))
            return {"list": [], "page": 1, "pagecount": 1, "limit": LIST_PAGE_SIZE, "total": 0}

    def detailContent(self, ids):
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
                url = HOST + "/voddetail/" + vod_id + ".html"

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

            m = self._RE_DETAIL_TITLE.search(html)
            if m:
                vod["vod_name"] = _strip(_unescape(m.group(1)))

            # 主海报: 第一个 module-item-pic 内的 data-src
            m = self._RE_DETAIL_PIC.search(html)
            if m:
                pic = m.group(1)
                if pic and not pic.endswith("load.gif") and not pic.endswith("loading.gif"):
                    vod["vod_pic"] = self._abs(_unescape(pic).strip())

            # 年份/类型/地区: 标题附近首个 module-item-caption (年份 类型 地区)
            m = self._RE_DETAIL_CAPTION.search(html)
            if m:
                vod["vod_year"] = _strip(m.group(1))
                vod["vod_class"] = _strip(m.group(2))
                vod["vod_area"] = _strip(m.group(3))

            # 信息行: 导演/主演/更新/集数/剧情
            for label, content in self._RE_INFO_ITEM.findall(html):
                label = _strip(label)
                text = _strip(re.sub(r"<[^>]+>", " ", content))
                text = text.replace("/", " ").strip()
                if "导演" in label:
                    vod["vod_director"] = text
                elif "主演" in label:
                    vod["vod_actor"] = text
                elif "更新" in label:
                    vod["vod_remarks"] = text
                elif "集数" in label or "状态" in label:
                    if vod["vod_remarks"]:
                        vod["vod_remarks"] += " " + text
                    else:
                        vod["vod_remarks"] = text

            m = self._RE_VOD_CONTENT.search(html)
            if m:
                txt = re.sub(r"<[^>]*>", "", m.group(1))
                vod["vod_content"] = _strip(txt)[:500]

            play_from, play_url = self._collect_playlist(html)
            if play_from:
                vod["vod_play_from"] = "$$$".join(play_from)
                vod["vod_play_url"] = "$$$".join(play_url)

            payload = {"list": [vod]}
            with self._cache_lock:
                self._detail_cache[vod_id] = (now, payload)
            return payload
        except Exception as e:
            print("[Vidhub] detailContent 异常: " + str(e))
            return {"list": []}

    def _collect_playlist(self, html):
        play_from, play_url = [], []
        blocks = self._RE_PLAYLIST_BLOCK.findall(html)
        if not blocks:
            # 兜底: 直接在全页找 /vodplay/ 链接
            blocks = [html]

        for idx, chunk in enumerate(blocks, 1):
            eps_raw = []
            seen_paths = set()
            for em in self._RE_PLAY_EP.finditer(chunk):
                path = em.group(1)
                ep_name = _strip(_unescape(re.sub(r"<[^>]*>", "", em.group(3)))) or "正片"
                if path in seen_paths:
                    continue
                seen_paths.add(path)
                nm = re.search(r"-(\d+)\.html$", path)
                nid = int(nm.group(1)) if nm else 0
                eps_raw.append((nid, ep_name, path))
            eps_raw.sort(key=lambda x: x[0])
            eps = [name + "$" + path for _, name, path in eps_raw]
            if eps:
                src_name = "线路" + str(idx) if len(blocks) > 1 else "播放"
                play_from.append(src_name)
                play_url.append("#".join(eps))
        return play_from, play_url

    def searchContent(self, key, quick, pg="1"):
        try:
            page = int(pg or 1)
            if page < 1:
                page = 1
            cache_key = (key, page)
            now = time.time()
            with self._cache_lock:
                hit = self._search_cache.get(cache_key)
                if hit and now - hit[0] < SEARCH_CACHE_TTL:
                    return hit[1]

            kw = _urlencode(key)
            url = HOST + "/index.php/ajax/suggest?mid=1&wd=" + kw + "&page=" + str(page)
            data = self._http_get_json(url, timeout=8)

            if not data or data.get("code") != 1:
                return {"list": [], "page": page, "pagecount": 1, "limit": 20, "total": 0}

            videos = []
            for item in data.get("list", []):
                vid = str(item.get("id", ""))
                if not vid:
                    continue
                videos.append({
                    "vod_id": vid,
                    "vod_name": _strip(item.get("name", "")),
                    "vod_pic": self._abs(item.get("pic", "")),
                    "vod_remarks": "",
                })

            total = data.get("total", 0)
            limit = data.get("limit", 20)
            pagecount = data.get("pagecount", 1)

            payload = {
                "list": videos,
                "page": page,
                "pagecount": pagecount,
                "limit": limit,
                "total": total,
            }
            with self._cache_lock:
                self._search_cache[cache_key] = (now, payload)
            return payload
        except Exception as e:
            print("[Vidhub] searchContent 异常: " + str(e))
            return {"list": [], "page": 1, "pagecount": 1, "limit": 20, "total": 0}

    def playerContent(self, flag, id, vipFlags):
        play_path = str(id or "")
        if not play_path:
            return {"parse": 0, "url": ""}

        if self.isVideoFormat(play_path):
            return {"parse": 0, "url": play_path, "header": {"User-Agent": UA, "Referer": HOST + "/"}}

        if "/vodplay/" in play_path:
            if play_path.startswith("http"):
                play_url = play_path
            else:
                play_url = HOST + play_path

            html = self._http_get(play_url, timeout=10)
            if not html:
                print("[Vidhub] play页请求为空: " + play_url)

            iframe_src = _extract_player_iframe(html)
            if iframe_src:
                player_page_url = self._abs(iframe_src)
                p_html = self._http_get(player_page_url, timeout=10)
                if p_html:
                    cfg = _extract_player_config(p_html)
                    if cfg and cfg.get("url"):
                        real_url = cfg.get("url", "")
                        # 还原 JSON 转义后的反斜杠(如有)
                        real_url = real_url.replace("\\/", "/")
                        if real_url.startswith("http") and self.isVideoFormat(real_url):
                            return {
                                "parse": 0,
                                "url": real_url,
                                "header": {
                                    "User-Agent": UA,
                                    "Referer": HOST + "/",
                                },
                            }
                        print("[Vidhub] config.url 非直链: " + str(real_url[:80]))

            # 降级: 嗅探模式, 把 /player/ 页交给框架处理
            print("[Vidhub] 解析失败, 降级嗅探: " + play_url)
            return {
                "parse": 1,
                "url": play_url,
                "header": {
                    "User-Agent": UA,
                    "Referer": HOST + "/",
                }
            }

        return {"parse": 0, "url": play_path, "header": {"User-Agent": UA, "Referer": HOST + "/"}}

    def localProxy(self, param):
        return [200, "video/MP2T", b"", ""]
