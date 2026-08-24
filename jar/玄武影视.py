# -*- coding: utf-8 -*-
"""
玄武影视 Python Spider — https://www.pywxw.com/
苹果 CMS v10 + 蚂蚁模板(mayi)，TVBox / 猫影视框架插件。

路由:
  首页         /
  分类         /movtype/{tid}.html  或  /movshow/{tid}.html
  分类分页     /movtype/{tid}-{page}.html  或  /movshow/{tid}/page/{page}.html
  筛选         /movshow/{tid}/class/{class}/area/{area}/year/{year}/lang/{lang}/page/{page}.html
  详情         /movdetail/{id}.html
  播放         /movplay/{id}-{sid}-{nid}.html
  搜索         /search.html?wd={kw}&page={page}
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


HOST = "https://www.pywxw.com"
UA = ("Mozilla/5.0 (Linux; Android 12; M2007J22C) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/120.0.0.0 Mobile Safari/537.36")

CLASSES = [
    {"type_name": "电影", "type_id": "1"},
    {"type_name": "电视剧", "type_id": "2"},
    {"type_name": "动漫", "type_id": "5"},
    {"type_name": "短剧", "type_id": "29"},
    {"type_name": "综艺", "type_id": "37"},
]

FILTERS = {
    "1": [
        {"key": "class", "name": "类型", "value": [
            {"n": "全部", "v": ""},
            {"n": "动作", "v": "动作"},
            {"n": "喜剧", "v": "喜剧"},
            {"n": "爱情", "v": "爱情"},
            {"n": "科幻", "v": "科幻"},
            {"n": "恐怖", "v": "恐怖"},
            {"n": "剧情", "v": "剧情"},
            {"n": "战争", "v": "战争"},
            {"n": "悬疑", "v": "悬疑"},
            {"n": "犯罪", "v": "犯罪"},
            {"n": "警匪", "v": "警匪"},
            {"n": "武侠", "v": "武侠"},
            {"n": "古装", "v": "古装"},
            {"n": "历史", "v": "历史"},
            {"n": "冒险", "v": "冒险"},
            {"n": "奇幻", "v": "奇幻"},
            {"n": "动画", "v": "动画"},
            {"n": "惊悚", "v": "惊悚"},
            {"n": "青春", "v": "青春"},
            {"n": "文艺", "v": "文艺"},
            {"n": "运动", "v": "运动"},
            {"n": "农村", "v": "农村"},
            {"n": "儿童", "v": "儿童"},
            {"n": "微电影", "v": "微电影"},
            {"n": "网络电影", "v": "网络电影"},
            {"n": "经典", "v": "经典"},
            {"n": "枪战", "v": "枪战"},
        ]},
        {"key": "area", "name": "地区", "value": [
            {"n": "全部", "v": ""},
            {"n": "大陆", "v": "大陆"},
            {"n": "香港", "v": "香港"},
            {"n": "台湾", "v": "台湾"},
            {"n": "美国", "v": "美国"},
            {"n": "韩国", "v": "韩国"},
            {"n": "日本", "v": "日本"},
            {"n": "泰国", "v": "泰国"},
            {"n": "英国", "v": "英国"},
            {"n": "法国", "v": "法国"},
            {"n": "德国", "v": "德国"},
            {"n": "意大利", "v": "意大利"},
            {"n": "西班牙", "v": "西班牙"},
            {"n": "印度", "v": "印度"},
            {"n": "加拿大", "v": "加拿大"},
            {"n": "其他", "v": "其他"},
        ]},
        {"key": "year", "name": "年份", "value": [
            {"n": "全部", "v": ""},
            {"n": "2025", "v": "2025"},
            {"n": "2024", "v": "2024"},
            {"n": "2023", "v": "2023"},
            {"n": "2022", "v": "2022"},
            {"n": "2021", "v": "2021"},
            {"n": "2020", "v": "2020"},
            {"n": "2019", "v": "2019"},
            {"n": "2018", "v": "2018"},
            {"n": "2017", "v": "2017"},
            {"n": "2016", "v": "2016"},
            {"n": "2015", "v": "2015"},
            {"n": "2014", "v": "2014"},
            {"n": "2013", "v": "2013"},
            {"n": "2012", "v": "2012"},
            {"n": "2011", "v": "2011"},
            {"n": "2010", "v": "2010"},
        ]},
        {"key": "lang", "name": "语言", "value": [
            {"n": "全部", "v": ""},
            {"n": "国语", "v": "国语"},
            {"n": "粤语", "v": "粤语"},
            {"n": "英语", "v": "英语"},
            {"n": "韩语", "v": "韩语"},
            {"n": "日语", "v": "日语"},
            {"n": "法语", "v": "法语"},
            {"n": "德语", "v": "德语"},
            {"n": "闽南语", "v": "闽南语"},
            {"n": "其他", "v": "其他"},
        ]},
    ],
    "2": [
        {"key": "class", "name": "类型", "value": [
            {"n": "全部", "v": ""},
            {"n": "国产剧", "v": "国产剧"},
            {"n": "港台剧", "v": "港台剧"},
            {"n": "日韩剧", "v": "日韩剧"},
            {"n": "欧美剧", "v": "欧美剧"},
            {"n": "海外剧", "v": "海外剧"},
        ]},
        {"key": "area", "name": "地区", "value": [
            {"n": "全部", "v": ""},
            {"n": "大陆", "v": "大陆"},
            {"n": "香港", "v": "香港"},
            {"n": "台湾", "v": "台湾"},
            {"n": "韩国", "v": "韩国"},
            {"n": "日本", "v": "日本"},
            {"n": "美国", "v": "美国"},
            {"n": "泰国", "v": "泰国"},
            {"n": "英国", "v": "英国"},
            {"n": "其他", "v": "其他"},
        ]},
        {"key": "year", "name": "年份", "value": [
            {"n": "全部", "v": ""},
            {"n": "2025", "v": "2025"},
            {"n": "2024", "v": "2024"},
            {"n": "2023", "v": "2023"},
            {"n": "2022", "v": "2022"},
            {"n": "2021", "v": "2021"},
            {"n": "2020", "v": "2020"},
            {"n": "2019", "v": "2019"},
            {"n": "2018", "v": "2018"},
            {"n": "2017", "v": "2017"},
        ]},
    ],
    "5": [
        {"key": "class", "name": "类型", "value": [
            {"n": "全部", "v": ""},
            {"n": "国产动漫", "v": "国产动漫"},
            {"n": "日韩动漫", "v": "日韩动漫"},
            {"n": "欧美动漫", "v": "欧美动漫"},
            {"n": "其他动漫", "v": "其他动漫"},
        ]},
        {"key": "area", "name": "地区", "value": [
            {"n": "全部", "v": ""},
            {"n": "大陆", "v": "大陆"},
            {"n": "日本", "v": "日本"},
            {"n": "韩国", "v": "韩国"},
            {"n": "美国", "v": "美国"},
            {"n": "其他", "v": "其他"},
        ]},
        {"key": "year", "name": "年份", "value": [
            {"n": "全部", "v": ""},
            {"n": "2025", "v": "2025"},
            {"n": "2024", "v": "2024"},
            {"n": "2023", "v": "2023"},
            {"n": "2022", "v": "2022"},
            {"n": "2021", "v": "2021"},
            {"n": "2020", "v": "2020"},
        ]},
    ],
    "29": [
        {"key": "class", "name": "类型", "value": [
            {"n": "全部", "v": ""},
        ]},
    ],
    "37": [
        {"key": "class", "name": "类型", "value": [
            {"n": "全部", "v": ""},
            {"n": "大陆综艺", "v": "大陆综艺"},
            {"n": "日韩综艺", "v": "日韩综艺"},
            {"n": "欧美综艺", "v": "欧美综艺"},
            {"n": "港台综艺", "v": "港台综艺"},
        ]},
        {"key": "area", "name": "地区", "value": [
            {"n": "全部", "v": ""},
            {"n": "大陆", "v": "大陆"},
            {"n": "香港", "v": "香港"},
            {"n": "台湾", "v": "台湾"},
            {"n": "韩国", "v": "韩国"},
            {"n": "日本", "v": "日本"},
            {"n": "美国", "v": "美国"},
            {"n": "其他", "v": "其他"},
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


class Spider(Spider):
    _RE_LIST_ITEM = re.compile(
        r'<a[^>]+href="(/movdetail/(\d+)\.html)"[^>]*title="([^"]*)"[^>]*?data-original="([^"]*)"'
    )
    _RE_LIST_ITEM_LOOSE = re.compile(
        r'<a[^>]+href="(/movdetail/(\d+)\.html)"[^>]*data-original="([^"]*)"[^>]*?title="([^"]*)"'
    )
    _RE_LIST_TITLE_ONLY = re.compile(
        r'<a[^>]+href="(/movdetail/(\d+)\.html)"[^>]*title="([^"]*)"'
    )
    _RE_LIST_IMG_SRC = re.compile(
        r'<a[^>]+href="(/movdetail/(\d+)\.html)"[\s\S]{0,800}?<img[^>]+src="([^"]+)"'
    )
    _RE_PIC_TEXT = re.compile(r'<span[^>]*class="pic-text[^"]*"[^>]*>([^<]+)</span>')
    _RE_TEXT_RIGHT = re.compile(r'<span[^>]*class="text-right[^"]*"[^>]*>([^<]+)</span>')
    _RE_PAGE_NUM = re.compile(r'/movshow/\d+/page/(\d+)\.html')
    _RE_PAGE_NUM2 = re.compile(r'/movtype/\d+-(\d+)\.html')
    _RE_DETAIL_TITLE = re.compile(r'<h1[^>]*>([^<]+)</h1>')
    _RE_DETAIL_PIC = re.compile(
        r'<div[^>]+class="[^"]*stui-content__thumb[^"]*"[\s\S]*?data-original="([^"]+)"'
    )
    _RE_DETAIL_PIC2 = re.compile(r'<img[^>]+class="[^"]*img[^"]*"[^>]+src="([^"]+)"')
    _RE_DATA_P = re.compile(r'<p[^>]+class="[^"]*data[^"]*"[^>]*>([\s\S]*?)</p>')
    _RE_VOD_CONTENT = re.compile(r'class="[^"]*detail-sketch[^"]*"[^>]*>([\s\S]*?)</span>')
    _RE_VOD_CONTENT_FULL = re.compile(r'class="[^"]*detail-content[^"]*"[^>]*>([\s\S]*?)</span>')
    _RE_PLAY_UL = re.compile(r'<ul[^>]*class="stui-content__playlist[^"]*"[^>]*>([\s\S]*?)</ul>')
    _RE_PLAY_EP = re.compile(r'<a[^>]+href="(/movplay/(\d+-\d+-\d+)\.html)"[^>]*>([\s\S]*?)</a>')
    _RE_PLAYER_JSON = re.compile(r'var\s+player_\w+\s*=\s*(\{[\s\S]*?\})\s*;?\s*</script>')
    _RE_PLAYER_URL = re.compile(r'"url"\s*:\s*"([^"]+)"')

    def getName(self):
        return "玄武影视"

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
            print("[玄武] requests 不可用, 回退到框架 fetch: " + str(e))
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
                    print("[玄武] 熔断 " + str(CIRCUIT_COOLDOWN) + "s")

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
                print("[玄武] session 失败: " + url + " (" + str(e) + ")")
        try:
            rsp = self.fetch(url, headers=self.header, timeout=timeout)
            sc = getattr(rsp, "status_code", 0)
            txt = getattr(rsp, "text", None) or ""
            if rsp is not None and sc == 200 and txt:
                ok = True
                return rsp.text
        except Exception as e:
            print("[玄武] fetch 失败: " + url + " (" + str(e) + ")")
        finally:
            self._circuit_record(ok)
        return ""

    def _abs(self, url):
        return _abs_url(url, HOST)

    def _parse_vod(self, html):
        items = []
        seen = set()

        # 提取备注: 优先 text-right (分类页状态如"HD国语")，其次 pic-text
        text_rights = [_strip(_unescape(m.group(1))) for m in self._RE_TEXT_RIGHT.finditer(html)]
        pic_texts = [_strip(_unescape(m.group(1))) for m in self._RE_PIC_TEXT.finditer(html)]

        def _get_remark(idx):
            if idx < len(text_rights):
                return text_rights[idx]
            tidx = idx - len(text_rights)
            if tidx < len(pic_texts):
                return pic_texts[tidx]
            return ""

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

        list_matches = list(self._RE_LIST_ITEM.finditer(html))
        for i, m in enumerate(list_matches):
            _add(m.group(1), m.group(3), m.group(4), _get_remark(i))

        loose_count = 0
        for m in self._RE_LIST_ITEM_LOOSE.finditer(html):
            idx = len(list_matches) + loose_count
            _add(m.group(1), m.group(4), m.group(3), _get_remark(idx))
            loose_count += 1

        for m in self._RE_LIST_IMG_SRC.finditer(html):
            pic = m.group(3)
            if "load.gif" in pic or "loading" in pic.lower():
                continue
            idx = len(list_matches) + loose_count
            _add(m.group(1), "", pic, _get_remark(idx))
            loose_count += 1

        if not items:
            for i, m in enumerate(self._RE_LIST_TITLE_ONLY.finditer(html)):
                _add(m.group(1), m.group(3), "", _get_remark(i))

        return items

    def _pagecount(self, html, cur_page):
        mx = cur_page
        for pm in self._RE_PAGE_NUM.finditer(html):
            n = int(pm.group(1))
            if n > mx:
                mx = n
        for pm in self._RE_PAGE_NUM2.finditer(html):
            n = int(pm.group(1))
            if n > mx:
                mx = n
        m = re.search(r'page/(\d+)\.html[^>]*>\s*尾页', html)
        if m:
            mx = max(mx, int(m.group(1)))
        m = re.search(r'class="[^"]*page[^"]*"[^>]*>.*?(\d+)</a>\s*<span[^>]*>尾页', html)
        if m:
            mx = max(mx, int(m.group(1)))
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
        payload = {"list": self._parse_vod(html)[:HOME_PAGE_SIZE]}
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

            # 构建URL
            has_filter = cls or area or year or lang
            if has_filter:
                url = HOST + "/movshow/" + use_tid
                if cls:
                    url += "/class/" + _urlencode(cls)
                if area:
                    url += "/area/" + _urlencode(area)
                if year:
                    url += "/year/" + _urlencode(year)
                if lang:
                    url += "/lang/" + _urlencode(lang)
                if page > 1:
                    url += "/page/" + str(page) + ".html"
                else:
                    url += ".html"
            else:
                if page > 1:
                    url = HOST + "/movshow/" + use_tid + "/page/" + str(page) + ".html"
                else:
                    url = HOST + "/movshow/" + use_tid + ".html"

            html = self._http_get(url, timeout=7)
            if not html:
                print("[玄武] categoryContent empty: " + url)
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
            print("[玄武] categoryContent 异常: " + str(e))
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
                url = HOST + "/movdetail/" + vod_id + ".html"

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

            m = self._RE_DETAIL_PIC.search(html)
            if not m:
                m = self._RE_DETAIL_PIC2.search(html)
            if m:
                vod["vod_pic"] = self._abs(_unescape(m.group(1)).strip())

            data_ps = self._RE_DATA_P.findall(html)
            if data_ps:
                actors = re.findall(r'<a[^>]*>([^<]+)</a>', data_ps[0])
                if actors:
                    vod["vod_actor"] = ",".join(_strip(_unescape(a)) for a in actors)
                if len(data_ps) >= 2:
                    directors = re.findall(r'<a[^>]*>([^<]+)</a>', data_ps[1])
                    if directors:
                        vod["vod_director"] = ",".join(_strip(_unescape(d)) for d in directors)

            remark_m = re.search(r'<span[^>]*class="pic-text[^"]*"[^>]*>([^<]+)</span>', html)
            if remark_m:
                vod["vod_remarks"] = _strip(_unescape(remark_m.group(1)))

            m = self._RE_VOD_CONTENT_FULL.search(html)
            if not m:
                m = self._RE_VOD_CONTENT.search(html)
            if m:
                txt = re.sub(r"<[^>]+>", "", m.group(1))
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
            print("[玄武] detailContent 异常: " + str(e))
            return {"list": []}

    def _collect_playlist(self, html):
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
            eps = [name + "$" + path for _, name, path in eps_raw]
            if eps:
                src_name = "线路" + str(idx) if len(ul_blocks) > 1 else "播放"
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
            url = HOST + "/search.html?wd=" + kw + "&page=" + str(page)
            html = self._http_get(url, timeout=8)
            if not html:
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
                self._search_cache[cache_key] = (now, payload)
            return payload
        except Exception as e:
            print("[玄武] searchContent 异常: " + str(e))
            return {"list": [], "page": 1, "pagecount": 1, "limit": LIST_PAGE_SIZE, "total": 0}

    def playerContent(self, flag, id, vipFlags):
        play_path = str(id or "")
        if not play_path:
            return {"parse": 0, "url": ""}
        if self.isVideoFormat(play_path):
            return {"parse": 0, "url": play_path, "header": {"User-Agent": UA, "Referer": HOST + "/"}}
        if "/movplay/" in play_path:
            if not play_path.startswith("http"):
                play_url = HOST + play_path
            else:
                play_url = play_path
            html = self._http_get(play_url, timeout=6)
            if html:
                real = self._extract_m3u8(html)
                if real:
                    return {"parse": 0, "url": real, "header": {"User-Agent": UA, "Referer": play_url}}
        return {"parse": 0, "url": play_path, "header": {"User-Agent": UA, "Referer": HOST + "/"}}

    def _extract_m3u8(self, html):
        m = self._RE_PLAYER_JSON.search(html)
        if m:
            json_str = m.group(1).replace("\\/", "/").replace("\\\\", "\\")
            um = self._RE_PLAYER_URL.search(json_str)
            if um:
                url_val = um.group(1)
                # 修复重复拼接的URL
                https_count = url_val.count("https://")
                if https_count > 1:
                    second = url_val.find("https://", url_val.find("https://") + 1)
                    if second > 0:
                        candidate = url_val[second:]
                        end = candidate.find(".m3u8")
                        if end > 0:
                            return candidate[:end + 5]
                if url_val.endswith(".m3u8") or url_val.endswith(".mp4"):
                    return url_val
                # 兜底: 从字符串中提取第一个有效的m3u8链接
                m2 = re.search(r'(https?://[^"\'\s]+?\.m3u8)(?=["\'\s]|$)', json_str)
                if m2:
                    return m2.group(1)
        return ""

    def localProxy(self, param):
        return [200, "video/MP2T", b"", ""]


if __name__ == "__main__":
    import json as _json
    def _bench(label, fn):
        t0 = time.time()
        r = fn()
        print("  [" + label + "] 耗时 " + str(round(time.time() - t0, 2)) + "s")
        return r

    print("== homeContent ==")
    sp = Spider()
    sp.init()
    print(_json.dumps(sp.homeContent(True), ensure_ascii=False)[:300])

    print("\n== homeVideoContent 前3条 ==")
    hvc = _bench("首页", lambda: sp.homeVideoContent())
    for it in hvc["list"][:3]:
        print(" ", it)

    print("\n== categoryContent 电影第1页 ==")
    cc = _bench("电影分类", lambda: sp.categoryContent("1", 1, True, {}))
    print("  条数:", len(cc["list"]), "总页数:", cc["pagecount"])
    if cc["list"]:
        print("  第一个:", cc["list"][0]["vod_id"], cc["list"][0]["vod_name"], cc["list"][0]["vod_remarks"])

    print("\n== 二级分类 动作片 ==")
    cc2 = _bench("动作筛选", lambda: sp.categoryContent("1", 1, True, {"class": "动作"}))
    print("  条数:", len(cc2["list"]), "总页数:", cc2["pagecount"])
    if cc2["list"]:
        print("  第一个:", cc2["list"][0]["vod_name"], cc2["list"][0]["vod_remarks"])

    print("\n== searchContent 测试 ==")
    sc = _bench("搜索", lambda: sp.searchContent("爱情", True))
    print("  total:", sc["total"], "条数:", len(sc["list"]))

    if cc["list"]:
        print("\n== detailContent ==")
        vid = cc["list"][0]["vod_id"]
        print("  vod_id:", vid)
        dc = _bench("详情", lambda: sp.detailContent([vid]))
        if dc["list"]:
            v = dc["list"][0]
            for k in ("vod_name", "vod_actor", "vod_director", "vod_remarks", "vod_play_from"):
                print("  " + k + ": " + str(v.get(k)))
            first = (v.get("vod_play_url") or "").split("#")[0]
            print("  第一集:", first)
            if first:
                print("\n== playerContent ==")
                pc = _bench("播放", lambda: sp.playerContent("", first.split("$")[-1], []))
                print("  parse:", pc["parse"])
                print("  url:", (pc["url"][:120] if pc["url"] else "空"))

    sp.destroy()
    print("\n== 自检完成 ==")
