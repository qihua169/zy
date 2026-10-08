# -*- coding: utf-8 -*-
"""
暮色影院 (msyy.tv) TVBox / 猫影视 Spider
=========================================
站点类型: 苹果CMS v10 + ds3 模板 (又称 maccms, 自定义 ds3 前端)

数据采集策略 (经现场逆向确认):
  - 首页/分类列表: 服务端 SSR 渲染, 路由 /vodtype/{type_id}.html
    (注意: 该站 JSON 列表接口 /index.php/api/vod 已被模板作者禁用,
     任何参数均返回 "本模板作者QQ为..." 拦截页, 故列表走 HTML 正则解析)
  - 搜索: JSON 接口 /index.php/ajax/suggest?mid=1&wd={kw} 可用
  - 详情: SSR 渲染 /vod/{id}.html, 含信息表 + 播放列表(anthology-list-play)
  - 播放: 播放页 /play/{id}/{sid}/{nid}.html 内嵌 var player_aaaa={...}
          encrypt=0 时 url 字段即直链 m3u8; 否则降级嗅探模式

已知限制:
  - 仅顶级分类 (电影/电视剧/综艺/动漫/短剧/纪录片/体育) 提供 SSR 列表,
    子分类 (剧情片/动作片/国产剧...) 依赖被禁用的 JSON 接口, 无法抓取。
  - 分类页无可用分页 (POST ?page=N 返回内容不变), 单页约 180 条。

播放标识约定: vod_play_url 中每集存放完整播放页路径
  "第NN集$/play/{vodId}/{sid}/{nid}.html", playerContent 直接抓播放页取直链。
"""

import re
import json
import time
import threading
from urllib.parse import quote

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


# ---------------- 站点常量 ----------------
HOST = "https://www.msyy.tv"
UA = ("Mozilla/5.0 (Linux; Android 12; M2007J22C) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/120.0.0.0 Mobile Safari/537.36")

# 仅收录可 SSR 抓取的视频型顶级分类。
# 注: 综艺(66)/短剧(67)/纪录片(68)/体育(127) 为站点「资讯/文章」型分类,
#     其 vodtype 页为空壳且无 SSR 视频列表, 列表依赖已被禁用的 JSON 接口,
#     故不收录 (收录后 TVBox 中这些分类会一直空白)。
CLASSES = [
    {"type_name": "电影", "type_id": "63"},
    {"type_name": "电视剧", "type_id": "64"},
    {"type_name": "动漫", "type_id": "65"},
]
FILTERS = {}

HOME_PAGE_SIZE = 30
LIST_CACHE_TTL = 120
DETAIL_CACHE_TTL = 600
HOME_CACHE_TTL = 60
SEARCH_CACHE_TTL = 60
CIRCUIT_FAILS = 3
CIRCUIT_COOLDOWN = 30

# ---------------- 正则 ----------------
_RE_CARD = re.compile(
    r'<a[^>]*class="public-list-exp"[^>]*href="/vod/(\d+)\.html"[^>]*title="([^"]*)"',
    re.S,
)
_RE_CARD_PIC = re.compile(r'data-src="([^"]+)"')
_RE_CARD_REMARK = re.compile(r'class="public-list-prb[^"]*"[^>]*>([^<]*)')
_RE_CARD_SUB = re.compile(r'class="public-prt[^"]*"[^>]*>([^<]*)')

_RE_INFO_LI = re.compile(r'<li><em class="cor4">([^<：:]+)[：:]\s*</em>(.*?)</li>', re.S)
_RE_INFO_A_TXT = re.compile(r'<a[^>]*>([^<]+)</a>')
_RE_H1 = re.compile(r'<h1[^>]*>([^<]+)</h1>')
_RE_PIC = re.compile(r'<img[^>]*class="[^"]*gen-movie-img[^"]*"[^>]*data-src="([^"]+)"')
_RE_DESC = re.compile(r'剧情简介：([^"]+)')
_RE_PLAY_BLOCKS = re.compile(r'class="anthology-list-play[^"]*">(.*?)</ul>', re.S)
_RE_PLAY_LINK = re.compile(r'href="/play/(\d+)/(\d+)/(\d+)\.html"[^>]*>([^<]*)')
_RE_SRC_LABEL = re.compile(
    r'class="swiper-slide[^"]*"[^>]*>(?:<i[^>]*></i>)?&nbsp;([^<]{1,20})<span class="badge">\d+'
)
_RE_PLAYER = re.compile(r'var\s+player_aaaa\s*=\s*')

# ---------------- 工具函数 ----------------

def _strip(txt):
    return re.sub(r"\s+", " ", txt or "").strip()

def _unescape(txt):
    if not txt:
        return ""
    try:
        import html as _h
        return _h.unescape(txt)
    except Exception:
        return txt

def _abs(url):
    if not url:
        return ""
    if url.startswith("http"):
        return url
    if url.startswith("//"):
        return "https:" + url
    if url.startswith("/"):
        return HOST + url
    return url

def _info_value(raw):
    """提取信息 <li> 值: 含 <a> 时拼接文本, 否则取纯文本"""
    raw = raw.strip()
    if "<a" in raw:
        parts = [m.group(1).strip() for m in _RE_INFO_A_TXT.finditer(raw)]
        return _strip(" ".join(p for p in parts if p))
    return _strip(re.sub(r"<[^>]*>", "", raw))


class Spider(Spider):

    def getName(self):
        return "暮色影院"

    def init(self, extend=""):
        self.header = {
            "User-Agent": UA,
            "Referer": HOST + "/",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
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
            print("[暮色影院] requests 不可用, 回退框架 fetch: " + str(e))
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
        u = (url or "").lower()
        base = u.split("?")[0].rstrip("/")
        return any(base.endswith(ext) for ext in (".m3u8", ".mp4", ".flv", ".ts"))

    def destroy(self):
        sess = getattr(self, "_session", None)
        if sess is not None:
            try:
                sess.close()
            except Exception:
                pass

    # ---------------- 熔断 ----------------
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
                    print("[暮色影院] 熔断 " + str(CIRCUIT_COOLDOWN) + "s")

    # ---------------- HTTP ----------------
    def _http_get(self, url, headers=None, timeout=10):
        if not self._circuit_allow():
            return ""
        ok = False
        hdrs = headers or self.header
        sess = getattr(self, "_session", None)
        if sess is not None and hasattr(sess, "get"):
            try:
                rsp = sess.get(url, headers=hdrs, timeout=timeout, verify=False)
                txt = getattr(rsp, "text", None) or ""
                if getattr(rsp, "status_code", 0) == 200 and txt:
                    ok = True
                    return txt
            except Exception as e:
                print("[暮色影院] session 失败: " + url + " (" + str(e) + ")")
        try:
            rsp = self.fetch(url, headers=hdrs, timeout=timeout)
            txt = getattr(rsp, "text", None) or ""
            if getattr(rsp, "status_code", 0) == 200 and txt:
                ok = True
                return txt
        except Exception as e:
            print("[暮色影院] fetch 失败: " + url + " (" + str(e) + ")")
        finally:
            self._circuit_record(ok)
        return ""

    # ---------------- 列表卡片解析 ----------------
    def _parse_cards(self, html):
        out = []
        seen = set()
        for m in _RE_CARD.finditer(html):
            vid = m.group(1)
            if vid in seen:
                continue
            seen.add(vid)
            seg = html[m.start(): m.start() + 1200]
            pic_m = _RE_CARD_PIC.search(seg)
            remark_m = _RE_CARD_REMARK.search(seg)
            sub_m = _RE_CARD_SUB.search(seg)
            name = _unescape(_strip(m.group(2)))
            pic = _abs(pic_m.group(1)) if pic_m else ""
            remark = _strip(remark_m.group(1)) if remark_m else ""
            if sub_m:
                sub = _strip(sub_m.group(1))
                if sub and remark and sub not in remark:
                    remark = sub + " " + remark
                elif sub:
                    remark = sub
            if not name:
                continue
            out.append({
                "vod_id": vid,
                "vod_name": name,
                "vod_pic": pic,
                "vod_remarks": remark,
            })
        return out

    # ---------------- TVBox 标准接口 ----------------
    def homeContent(self, filter):
        return {"class": CLASSES, "filters": FILTERS}

    def homeVideoContent(self):
        now = time.time()
        with self._cache_lock:
            if self._home_cache:
                ts, payload = self._home_cache
                if now - ts < HOME_CACHE_TTL:
                    return payload
        html = self._http_get(HOST + "/")
        items = self._parse_cards(html)[:HOME_PAGE_SIZE]
        payload = {"list": items}
        with self._cache_lock:
            self._home_cache = (now, payload)
        return payload

    def categoryContent(self, tid, pg, filter, extend):
        try:
            page = int(pg or 1)
            if page < 1:
                page = 1
            use_tid = str(tid)
            cache_key = (use_tid, page)
            now = time.time()
            with self._cache_lock:
                hit = self._list_cache.get(cache_key)
                if hit and now - hit[0] < LIST_CACHE_TTL:
                    return hit[1]

            # 顶级分类 SSR 列表路由; 该站无可用分页(?page=N 返回相同内容)
            url = HOST + "/vodtype/" + use_tid + ".html"
            html = self._http_get(url)
            videos = self._parse_cards(html)

            pagecount = 1 if videos else 0
            payload = {
                "list": videos,
                "page": page,
                "pagecount": pagecount,
                "limit": len(videos) or HOME_PAGE_SIZE,
                "total": len(videos),
            }
            with self._cache_lock:
                self._list_cache[cache_key] = (now, payload)
            return payload
        except Exception as e:
            print("[暮色影院] categoryContent 异常: " + str(e))
            return {"list": [], "page": 1, "pagecount": 1, "limit": HOME_PAGE_SIZE, "total": 0}

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

            url = HOST + "/vod/" + vod_id + ".html"
            html = self._http_get(url)

            vod = {
                "vod_id": vod_id,
                "vod_name": "", "vod_pic": "", "vod_year": "", "vod_area": "",
                "vod_lang": "", "vod_remarks": "", "vod_actor": "", "vod_director": "",
                "vod_class": "", "vod_content": "",
                "vod_play_from": "", "vod_play_url": "",
            }

            # 名称
            h1 = _RE_H1.search(html)
            if h1:
                vod["vod_name"] = _unescape(_strip(h1.group(1)))
            # 封面
            pic = _RE_PIC.search(html)
            if pic:
                vod["vod_pic"] = _abs(pic.group(1))
            # 信息表
            for li in _RE_INFO_LI.finditer(html):
                label = _strip(li.group(1))
                val = _info_value(li.group(2))
                if not val:
                    continue
                if label == "状态":
                    vod["vod_remarks"] = val
                elif label == "主演":
                    vod["vod_actor"] = val
                elif label == "导演":
                    vod["vod_director"] = val
                elif label == "年份":
                    vod["vod_year"] = val
                elif label == "地区":
                    vod["vod_area"] = val
                elif label == "语言":
                    vod["vod_lang"] = val
                elif label in ("类型", "分类"):
                    vod["vod_class"] = val
            # 简介
            desc = _RE_DESC.search(html)
            if desc:
                vod["vod_content"] = _unescape(_strip(desc.group(1)))

            # 播放列表
            labels = _RE_SRC_LABEL.findall(html)
            blocks = _RE_PLAY_BLOCKS.findall(html)
            from_list = []
            url_list = []
            for idx, blk in enumerate(blocks):
                src_name = labels[idx] if idx < len(labels) else ("线路%d" % (idx + 1))
                from_list.append(src_name)
                eps = []
                for pm in _RE_PLAY_LINK.finditer(blk):
                    vid, sid, nid, ep_name = pm.group(1), pm.group(2), pm.group(3), _strip(pm.group(4))
                    if not ep_name:
                        ep_name = "第%s集" % nid
                    # 标识存放完整播放页路径, playerContent 据此取直链
                    eps.append("%s$/play/%s/%s/%s.html" % (ep_name, vid, sid, nid))
                if eps:
                    url_list.append("#".join(eps))
            if from_list and url_list:
                vod["vod_play_from"] = "$$$".join(from_list)
                vod["vod_play_url"] = "$$$".join(url_list)

            payload = {"list": [vod]}
            with self._cache_lock:
                self._detail_cache[vod_id] = (now, payload)
            return payload
        except Exception as e:
            print("[暮色影院] detailContent 异常: " + str(e))
            return {"list": []}

    def searchContent(self, key, quick, pg="1"):
        try:
            page = int(pg or 1)
            if page < 1:
                page = 1
            kw = (key or "").strip()
            if not kw:
                return {"list": [], "page": 1, "pagecount": 1, "limit": 20, "total": 0}
            cache_key = (kw, page)
            now = time.time()
            with self._cache_lock:
                hit = self._search_cache.get(cache_key)
                if hit and now - hit[0] < SEARCH_CACHE_TTL:
                    return hit[1]

            api = HOST + "/index.php/ajax/suggest?mid=1&wd=" + quote(kw) + "&page=" + str(page)
            raw = self._http_get(api, headers={
                "User-Agent": UA, "Referer": HOST + "/",
                "Accept": "application/json, text/plain, */*",
                "X-Requested-With": "XMLHttpRequest",
            })
            videos = []
            total = 0
            pagecount = 1
            if raw:
                try:
                    data = json.loads(raw)
                    if data.get("code") == 1:
                        total = int(data.get("total", 0) or 0)
                        pagecount = int(data.get("pagecount", 1) or 1)
                        for it in data.get("list", []) or []:
                            vid = str(it.get("id", ""))
                            if not vid:
                                continue
                            videos.append({
                                "vod_id": vid,
                                "vod_name": _unescape(_strip(it.get("name", ""))),
                                "vod_pic": _abs(it.get("pic", "")),
                                "vod_remarks": "",
                            })
                except Exception as e:
                    print("[暮色影院] 搜索 JSON 解析失败: " + str(e))

            payload = {
                "list": videos,
                "page": page,
                "pagecount": max(1, pagecount),
                "limit": len(videos) or 20,
                "total": total,
            }
            with self._cache_lock:
                self._search_cache[cache_key] = (now, payload)
            return payload
        except Exception as e:
            print("[暮色影院] searchContent 异常: " + str(e))
            return {"list": [], "page": 1, "pagecount": 1, "limit": 20, "total": 0}

    # ---------------- 播放解析 ----------------
    def _extract_player_url(self, html):
        """从播放页提取 player_aaaa 中的真实地址。返回 (url, encrypt)"""
        m = _RE_PLAYER.search(html)
        if not m:
            return "", 0
        start = m.end()
        # 括号计数定位 JSON 结束位置
        depth = 0
        in_str = False
        esc = False
        end = -1
        for i in range(start, min(start + 8000, len(html))):
            c = html[i]
            if esc:
                esc = False
                continue
            if c == "\\":
                esc = True
                continue
            if c == '"':
                in_str = not in_str
                continue
            if in_str:
                continue
            if c == "{":
                depth += 1
            elif c == "}":
                depth -= 1
                if depth == 0:
                    end = i + 1
                    break
        if end <= start:
            return "", 0
        blob = html[start:end]
        try:
            obj = json.loads(blob)
        except Exception:
            return "", 0
        return obj.get("url", "") or "", int(obj.get("encrypt", 0) or 0)

    def playerContent(self, flag, id, vipFlags):
        play_id = str(id or "")
        if not play_id:
            return {"parse": 0, "url": ""}

        if play_id.startswith("http") and self.isVideoFormat(play_id):
            return {"parse": 0, "url": play_id, "header": {"User-Agent": UA, "Referer": HOST + "/"}}

        # 约定标识: /play/{vodId}/{sid}/{nid}.html
        m = re.match(r"^/play/(\d+)/(\d+)/(\d+)\.html$", play_id)
        if m:
            page_url = HOST + play_id
            html = self._http_get(page_url, headers={
                "User-Agent": UA, "Referer": HOST + "/vod/" + m.group(1) + ".html",
                "Accept": "text/html,application/xhtml+xml,*/*;q=0.9",
            })
            if html:
                url, encrypt = self._extract_player_url(html)
                if url and url.startswith("http"):
                    if encrypt == 0:
                        return {
                            "parse": 0,
                            "url": url,
                            "header": {"User-Agent": UA, "Referer": HOST + "/"},
                        }
                    # encrypt != 0: 降级嗅探模式
                    return {
                        "parse": 1,
                        "url": page_url,
                        "header": {"User-Agent": UA, "Referer": HOST + "/"},
                    }

            # 兜底嗅探
            return {
                "parse": 1,
                "url": page_url,
                "header": {"User-Agent": UA, "Referer": HOST + "/"},
            }

        if self.isVideoFormat(play_id):
            return {"parse": 0, "url": play_id, "header": {"User-Agent": UA, "Referer": HOST + "/"}}

        return {"parse": 0, "url": play_id, "header": {"User-Agent": UA, "Referer": HOST + "/"}}

    def localProxy(self, param):
        return [200, "video/MP2T", b"", ""]
