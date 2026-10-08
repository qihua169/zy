# -*- coding: utf-8 -*-
"""
爱壹帆Pro TVBox/猫影视爬虫插件 — https://www.ayfox.com/
自研 ds3 模板 (非 苹果CMS), 数据结构与 jqqzx(剧圈圈) 不同, 本脚本复用剧圈圈.py 的
解析框架(Spider 基类 / 请求降级 / 缓存熔断 / player_aaaa 提取 / 字段分隔符), 并针对
新站点的 HTML 结构重写各解析函数。

路由:
  首页           /
  分类           /show/{dianying,dianshiju,zongyi,dongman,duanju}
  子分类/类型     /show/{subpinyin}                         (如 /show/xijupian)
  筛选           /show/{tid}/area/{地区}/year/{年份}        (地区为中文, 请求时 URL 编码)
  分页           /show/{tid}/page/{n}                      (尾页链接给出总页数)
  详情           /voddetail/{id}
  选集(线路)     /voddetail/{id} 内 <ul class="anthology-list-play size"> (每源一个 ul)
  播放           /vodplay/{id}-{n}  -> 页面内 var player_aaaa.url (明文 m3u8, encrypt:0)
  搜索           /search/wd/{关键词}

与剧圈圈的异同(适配说明):
  相同(复用): Spider 框架、HOST/UA/CLASSES/FILTERS 配置方式、缓存与熔断、请求三级降级、
              _extract_player_aaaa 提取、列表去重、detailContent 字段结构与分隔符($$$/#/$)、
              localProxy 兜底。
  不同(调整): 剧圈圈播放地址经 /jx/api.php + 站点 sign() 加密, 需本地复刻解密;
              ayfox 播放地址为明文 m3u8(encrypt:0), 直接读取 player_aaaa.url 即可,
              故删除 _jqq_* sign 解密函数, 改为从 player_aaaa 与播放页选集提取。
  不同(调整): 列表容器 class 为 public-list-box(非 module-poster-item); 详情信息在
              info-parameter 的 <li><em>标签</em>值</li>(非 module-info-item); 搜索页
              名称位于 <span class="vod-title" title="...">(非锚点 title 属性)。
"""

import re
import json
import time
import base64
import hashlib
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


HOST = "https://www.ayfox.com"
UA = ("Mozilla/5.0 (Linux; Android 12; M2007J22C) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/120.0.0.0 Mobile Safari/537.36")

# 主分类 (type_id 即 /show/{pinyin} 的拼音)
CLASSES = [
    {"type_name": "电影", "type_id": "dianying"},
    {"type_name": "电视剧", "type_id": "dianshiju"},
    {"type_name": "综艺", "type_id": "zongyi"},
    {"type_name": "动漫", "type_id": "dongman"},
    {"type_name": "短剧", "type_id": "duanju"},
]

# 二级筛选: 地区(中文, 请求时 URL 编码) / 年份。各分类共用一份(站点筛选 URL 结构一致)。
# 注: 地区列表依据电影频道实测, 若某分类无对应地区, 过滤页可能返回更少/空结果(已做兜底)。
_AREAS = ["大陆", "香港", "台湾", "美国", "韩国", "日本", "泰国", "英国", "法国",
          "德国", "意大利", "西班牙", "印度", "加拿大", "其他"]
_YEARS = ["2026", "2025", "2024", "2023", "2022", "2021", "2020", "2019", "2018"]

FILTERS = {}
for _c in CLASSES:
    FILTERS[_c["type_id"]] = [
        {"key": "area", "name": "地区", "value": [{"n": "全部", "v": ""}] +
         [{"n": a, "v": a} for a in _AREAS]},
        {"key": "year", "name": "年份", "value": [{"n": "全部", "v": ""}] +
         [{"n": y, "v": y} for y in _YEARS]},
    ]

LIST_PAGE_SIZE = 40
HOME_PAGE_SIZE = 24
LIST_CACHE_TTL = 60
DETAIL_CACHE_TTL = 300
HOME_CACHE_TTL = 30
SEARCH_CACHE_TTL = 30
CIRCUIT_FAILS = 3
CIRCUIT_COOLDOWN = 30


def _urlencode(s):
    return quote(s or "", safe="")


# ---------------------------------------------------------------------------
# 复用剧圈圈的通用工具函数
# ---------------------------------------------------------------------------

def _md5_hex(s):
    if isinstance(s, str):
        try:
            s = s.encode("utf-8")
        except Exception:
            pass
    return hashlib.md5(s).hexdigest()


def _b64decode_str(s):
    """base64 解码为文本, 失败返回空串"""
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
# 复用剧圈圈的 player_aaaa 提取 (括号平衡扫描, 兼容换行/转义)
# ayfox 的 player_aaaa.url 为明文 m3u8, 无需 sign 解密
# ---------------------------------------------------------------------------

def _extract_player_aaaa(html):
    if not html:
        return None
    # 优先正则匹配 { ... } 再用括号计数兜底
    m = re.search(r'var\s+player_aaaa\s*=\s*(\{[\s\S]*?\})\s*(?:</script>|;|&)', html)
    if m:
        try:
            json_str = m.group(1)
            brace_count = 0
            end_idx = 0
            for i, c in enumerate(json_str):
                if c == '{':
                    brace_count += 1
                elif c == '}':
                    brace_count -= 1
                    if brace_count == 0:
                        end_idx = i + 1
                        break
            return json.loads(json_str[:end_idx])
        except Exception as e:
            print("[爱壹帆Pro] player_aaaa 正则解析异常: " + str(e))
    try:
        idx = html.find("player_aaaa")
        if idx < 0:
            return None
        brace_start = html.find("{", idx)
        if brace_start < 0:
            return None
        depth = 0
        for i in range(brace_start, len(html)):
            c = html[i]
            if c == '{':
                depth += 1
            elif c == '}':
                depth -= 1
                if depth == 0:
                    return json.loads(html[brace_start:i + 1])
    except Exception as e:
        print("[爱壹帆Pro] player_aaaa 兜底解析异常: " + str(e))
    return None


class Spider(Spider):
    # ---- 列表/详情/选集解析正则 (适配 ayfox ds3 模板) ----
    _RE_ITEM_ID = re.compile(r'href="/voddetail/(\d+)"')
    _RE_ITEM_PIC = re.compile(r'(?:data-src|src)="(https?://[^"]+\.(?:webp|jpg|jpeg|png))"')
    _RE_TITLE_ANCHOR = re.compile(r'href="/voddetail/\d+"[^>]*\btitle="([^"]+)"')
    _RE_TITLE_H3 = re.compile(r'<h3[^>]*>\s*<a[^>]+href="/voddetail/\d+"[^>]*>([^<]+)</a>')
    _RE_TITLE_SPAN = re.compile(r'class="vod-title"[^>]*\btitle="([^"]+)"')
    _RE_PRT = re.compile(r'class="public-prt[^"]*"[^>]*>([^<]*)</span>')
    _RE_PRB = re.compile(r'class="public-list-prb[^"]*"[^>]*>([\s\S]*?)</span>')

    _RE_DETAIL_TITLE = re.compile(r'<h1[^>]*>([^<]+)</h1>')
    _RE_DETAIL_PIC = re.compile(r'<img[^>]*data-src="([^"]+\.(?:webp|jpg|jpeg|png))"')
    _RE_META_DESC = re.compile(r'<meta\s+name="description"\s+content="([^"]*)"', re.I)
    _RE_INFO_LI = re.compile(r'<li><em[^>]*>([^<：:]+)[：:]\s*</em>([\s\S]*?)</li>')

    _RE_UL = re.compile(r'<ul class="anthology-list-play size">([\s\S]*?)</ul>')
    _RE_EP = re.compile(r'<a[^>]+href="/vodplay/(\d+-\d+)"[^>]*>([\s\S]*?)</a>')

    _RE_PAGE_LINK = re.compile(r'class="page-link[^"]*"[^>]*href="[^"]*?/page/(\d+)"')
    _RE_PAGE_LAST = re.compile(r'尾页"[^>]*href="[^"]*?/page/(\d+)')
    _RE_PLAY_EP_N = re.compile(r'/vodplay/\d+-(\d+)')
    _RE_PU_A = re.compile(r'data-play-nid="(\d+)"[^>]*data-play-from="([^"]+)"[^>]*data-play-url="([^"]+)"')

    def getName(self):
        return "爱壹帆Pro"

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
            print("[爱壹帆Pro] requests 不可用, 回退到框架 fetch: " + str(e))
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

    # ---- 熔断 (复用) ----
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
                    print("[爱壹帆Pro] 熔断 " + str(CIRCUIT_COOLDOWN) + "s")

    # ---- 请求三级降级 (复用) ----
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
                print("[爱壹帆Pro] session 失败: " + url + " (" + str(e) + ")")
        try:
            rsp = self.fetch(url, headers=self.header, timeout=timeout)
            sc = getattr(rsp, "status_code", 0)
            txt = getattr(rsp, "text", None) or ""
            if rsp is not None and sc == 200 and txt:
                ok = True
                return rsp.text
        except Exception as e:
            print("[爱壹帆Pro] fetch 失败: " + url + " (" + str(e) + ")")
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
            print("[爱壹帆Pro] JSON解析失败: " + url + " (" + str(e) + ")")
            return None

    def _http_post(self, url, data, timeout=10):
        sess = getattr(self, "_session", None)
        if sess is not None and hasattr(sess, "post"):
            try:
                rsp = sess.post(url, data=data, headers=self.header, timeout=timeout, verify=False)
                if getattr(rsp, "status_code", 0) == 200:
                    return rsp.text
            except Exception as e:
                print("[爱壹帆Pro] POST session 失败: " + url + " (" + str(e) + ")")
        try:
            try:
                from urllib.request import Request as _Req, urlopen as _Uo
                from urllib.parse import urlencode as _Ue
            except ImportError:
                from urllib2 import Request as _Req, urlopen as _Uo
                from urllib import urlencode as _Ue
            body = _Ue(data)
            try:
                body = body.encode("utf-8")
            except Exception:
                pass
            req = _Req(url, data=body, headers=self.header)
            try:
                import ssl as _ssl
                ctx = _ssl._create_unverified_context()
                rsp = _Uo(req, timeout=timeout, context=ctx)
            except Exception:
                rsp = _Uo(req, timeout=timeout)
            raw = rsp.read()
            if not isinstance(raw, str):
                raw = raw.decode("utf-8", errors="replace")
            if raw:
                return raw
        except Exception as e:
            print("[爱壹帆Pro] POST urllib 失败: " + url + " (" + str(e) + ")")
        try:
            rsp = self.fetch(url, headers=self.header, timeout=timeout, data=data)
            if getattr(rsp, "status_code", 0) == 200:
                return rsp.text
        except Exception as e:
            print("[爱壹帆Pro] POST fetch 失败: " + url + " (" + str(e) + ")")
        return None

    def _abs(self, url):
        return _abs_url(url, HOST)

    # ---- 列表解析 (适配 public-list-box 容器) ----
    def _parse_vod(self, html):
        items = []
        seen = set()

        for blk in re.split(r'<div class="public-list-box', html):
            im = self._RE_ITEM_ID.search(blk)
            if not im:
                continue
            vid = im.group(1)
            if vid in seen:
                continue

            pm = self._RE_ITEM_PIC.search(blk)
            pic = self._abs(pm.group(1)) if pm else ""

            tm = (self._RE_TITLE_ANCHOR.search(blk)
                  or self._RE_TITLE_H3.search(blk)
                  or self._RE_TITLE_SPAN.search(blk))
            name = _strip(_unescape(tm.group(1))) if tm else ""

            prtm = self._RE_PRT.search(blk)
            prt = prtm.group(1).strip() if prtm else ""
            prbm = self._RE_PRB.search(blk)
            prb = re.sub(r"<[^>]+>", "", prbm.group(1)).strip() if prbm else ""
            remark = _strip((prt + " " + prb).strip())

            items.append({
                "vod_id": vid,
                "vod_name": name,
                "vod_pic": pic,
                "vod_remarks": remark,
            })
            seen.add(vid)

        return items

    def _pagecount(self, html, cur_page):
        mx = cur_page
        m = self._RE_PAGE_LAST.search(html)
        if m:
            mx = max(mx, int(m.group(1)))
        for pm in self._RE_PAGE_LINK.finditer(html):
            n = int(pm.group(1))
            if n > mx:
                mx = n
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
            area = str(ext.get("area", "") or "")
            year = str(ext.get("year", "") or "")
            use_tid = str(tid)

            cache_key = (use_tid, area, year, page)
            now = time.time()
            with self._cache_lock:
                hit = self._list_cache.get(cache_key)
                if hit and now - hit[0] < LIST_CACHE_TTL:
                    return hit[1]

            url = HOST + "/show/" + use_tid
            if area:
                url += "/area/" + _urlencode(area)
            if year:
                url += "/year/" + _urlencode(year)
            if page > 1:
                url += "/page/" + str(page)

            html = self._http_get(url, timeout=7)
            if not html:
                print("[爱壹帆Pro] categoryContent empty: " + url)
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
            print("[爱壹帆Pro] categoryContent 异常: " + str(e))
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

            m = self._RE_DETAIL_PIC.search(html)
            if m:
                pic = m.group(1)
                if pic and not pic.endswith("load.gif") and not pic.endswith("loading.gif"):
                    vod["vod_pic"] = self._abs(_unescape(pic).strip())

            for label, content in self._RE_INFO_LI.findall(html):
                label = _strip(label)
                text = _strip(re.sub(r"<[^>]+>", " ", content))
                text = _unescape(text).replace("&nbsp;", " ")
                text = _strip(text)
                if "主演" in label or "演员" in label:
                    vod["vod_actor"] = text
                elif "导演" in label:
                    vod["vod_director"] = text
                elif "类型" in label:
                    vod["vod_class"] = text
                elif "地区" in label:
                    vod["vod_area"] = text
                elif "年份" in label:
                    vod["vod_year"] = text
                elif "语言" in label:
                    vod["vod_lang"] = text
                elif "状态" in label or "备注" in label or "更新" in label:
                    vod["vod_remarks"] = text

            # 简介: 优先 meta description (含完整剧情), 否则详情页简介块
            dm = self._RE_META_DESC.search(html)
            if dm:
                vod["vod_content"] = _strip(_unescape(dm.group(1)))[:500]

            play_from, play_url = self._collect_playlist(html)
            if play_from:
                vod["vod_play_from"] = "$$$".join(play_from)
                vod["vod_play_url"] = "$$$".join(play_url)

            payload = {"list": [vod]}
            with self._cache_lock:
                self._detail_cache[vod_id] = (now, payload)
            return payload
        except Exception as e:
            print("[爱壹帆Pro] detailContent 异常: " + str(e))
            return {"list": []}

    def _collect_playlist(self, html):
        """选集(线路): 每源一个 <ul class="anthology-list-play size">, 内部 <a href="/vodplay/{id}-{n}">"""
        play_from, play_url = [], []
        for i, chunk in enumerate(self._RE_UL.findall(html), 1):
            eps = []
            for em in self._RE_EP.finditer(chunk):
                ep_name = _strip(_unescape(re.sub(r"<[^>]+>", "", em.group(2)))) or ("第" + str(len(eps) + 1) + "集")
                eps.append(ep_name + "$" + "/vodplay/" + em.group(1))
            if eps:
                play_from.append("线路" + str(i))
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
            url = HOST + "/search/wd/" + kw
            if page > 1:
                url += "?page=" + str(page)

            html = self._http_get(url, timeout=8)
            if not html:
                return {"list": [], "page": page, "pagecount": 1, "limit": 20, "total": 0}

            videos = self._parse_vod(html)
            pagecount = self._pagecount(html, page)

            payload = {
                "list": videos,
                "page": page,
                "pagecount": pagecount,
                "limit": len(videos) or 20,
                "total": pagecount * 20,
            }
            with self._cache_lock:
                self._search_cache[cache_key] = (now, payload)
            return payload
        except Exception as e:
            print("[爱壹帆Pro] searchContent 异常: " + str(e))
            return {"list": [], "page": 1, "pagecount": 1, "limit": 20, "total": 0}

    def playerContent(self, flag, id, vipFlags):
        play_path = str(id or "")
        if not play_path:
            return {"parse": 0, "url": ""}

        if self.isVideoFormat(play_path):
            return {"parse": 0, "url": play_path, "header": {"User-Agent": UA, "Referer": HOST + "/"}}

        if "/vodplay/" in play_path:
            url = play_path if play_path.startswith("http") else HOST + play_path
            html = self._http_get(url, timeout=10)

            # 默认源: player_aaaa.url (明文 m3u8, encrypt:0)
            default_url = ""
            pa = _extract_player_aaaa(html)
            if pa and pa.get("url"):
                default_url = str(pa.get("url")).replace("\\/", "/")

            # 当前集号
            nm = self._RE_PLAY_EP_N.search(play_path)
            n = int(nm.group(1)) if nm else 0

            # 播放页选集: 所有源 x 当前集的 m3u8
            chosen = ""
            if flag:
                for nid, frm, u in self._RE_PU_A.findall(html):
                    if frm == flag and (n == 0 or int(nid) == n):
                        chosen = u
                        break
            if not chosen and n:
                # 索引选择: flag="线路N" -> 第 N 个源
                idx = 0
                im = re.search(r'(\d+)', flag or "")
                if im:
                    idx = int(im.group(1))
                pool = [u for nid, frm, u in self._RE_PU_A.findall(html) if int(nid) == n]
                if idx and 1 <= idx <= len(pool):
                    chosen = pool[idx - 1]
                elif pool:
                    chosen = pool[0]
            if not chosen and default_url:
                chosen = default_url

            if chosen and chosen.startswith("http"):
                return {
                    "parse": 0,
                    "url": chosen,
                    "header": {"User-Agent": UA, "Referer": HOST + "/"},
                }

            # 降级: 嗅探
            print("[爱壹帆Pro] 解析失败, 降级嗅探: " + url)
            return {
                "parse": 1,
                "url": url,
                "header": {"User-Agent": UA, "Referer": HOST + "/"},
            }

        return {"parse": 0, "url": play_path, "header": {"User-Agent": UA, "Referer": HOST + "/"}}

    def localProxy(self, param):
        return [200, "video/MP2T", b"", ""]
