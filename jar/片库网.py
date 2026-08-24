# -*- coding: utf-8 -*-
"""
TVBox / 猫影视 Spider — hnyqsw.com（片库网）部署版
====================================================
规范：继承 base.spider.Spider，网络请求走基类 self.fetch，不自写网络层。
技术栈：MacCMS（var maccms 确认），UTF-8，自定义路由：
  - 分类导航   /vodtype/{tid}.html
  - 列表页     /vodshow/{tid}-----------{pg}.html   （第 1 页省略 pg）
  - 详情页     /voddetail/{id}.html
  - 播放页     /vodplay/{id}-{sid}-{nid}.html
  - 搜索       GET /vodsearch/{wd}-------------{pg}.html（13 个横线占位）
播放直链：var player_aaaa = {"url":"...m3u8","encrypt":0} → 直链。
⚠ 广告：m3u8 混入 /video/adjump/time/*.ts 分片 → AD_MODE=proxy 自动清洗。
"""

import re
import json

try:
    from base.spider import Spider as _TVBase
except Exception:
    # ── 本地调试桩（PC 端无 base.spider）：urllib 实现 fetch/post ──
    class _TVBase(object):
        def _resp(self, raw):
            class _R(object):
                encoding = "utf-8"
                apparent_encoding = "utf-8"
                @property
                def text(self):
                    if isinstance(raw, bytes):
                        return raw.decode(self.encoding or "utf-8", errors="ignore")
                    return raw
            return _R()

        def fetch(self, url, headers=None, timeout=15):
            from urllib.request import Request, urlopen
            from urllib.parse import quote
            # 本地桩：URL 含中文路径时需百分号编码（TVBox 环境基类已处理）
            url = quote(url, safe=":/?&=#%+")
            r = urlopen(Request(url, headers=headers or {}), timeout=timeout)
            return self._resp(r.read())

        def post(self, url, data=None, headers=None, timeout=15):
            from urllib.request import Request, urlopen
            from urllib.parse import urlencode, quote
            url = quote(url, safe=":/?&=#%+")
            body = urlencode(data or {}).encode()
            r = urlopen(Request(url, data=body, headers=headers or {},
                                method="POST"), timeout=timeout)
            return self._resp(r.read())
    # ── 桩结束 ──


# ═══════════ 站点配置 ═══════════
SITE_NAME = "片库网"
BASE_URL = "https://hnyqsw.com"
UA = ("Mozilla/5.0 (Linux; Android 12) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/125.0.0.0 Mobile Safari/537.36")

HOME_CLASSES = [
    {"type_id": "1",  "type_name": "电影"},
    {"type_id": "2",  "type_name": "电视剧"},
    {"type_id": "3",  "type_name": "综艺"},
    {"type_id": "4",  "type_name": "动漫"},
    {"type_id": "35", "type_name": "动画片"},
    {"type_id": "36", "type_name": "短剧"},
]

# 广告处理模式："proxy" 保留线路自动清洗（推荐）
AD_MODE = "proxy"
AD_SOURCES = ()
RE_AD_SEG = re.compile(
    r'/(?:adjump|advert|adss?|gg\d*|ad|ads)/|(?:^|[-_.])ad[-_.]', re.I)

# ═══════════ 站点正则 ═══════════
# 列表卡片（box 网格卡片，div 容器）
RE_CARD = re.compile(
    r'<div class="ewave-vodlist__box">(.*?)</div>\s*</div>', re.S | re.I)
RE_THUMB = re.compile(
    r'title="([^"]*)"[^>]*data-original="([^"]+)"', re.S | re.I)
RE_DETAIL_LINK = re.compile(r'voddetail/(\d+)\.html', re.I)
RE_REMARK = re.compile(r'<span class="pic-text[^"]*">([^<]+)</span>', re.S | re.I)
# 搜索/列表 media 卡片（li 列表）
RE_MEDIA_CARD = re.compile(
    r'<a[^>]*href="/voddetail/(\d+)\.html"[^>]*title="([^"]*)"[^>]*data-original="([^"]+)"'
    r'[^>]*>.*?<span class="pic-text[^"]*">([^<]*)</span>', re.S | re.I)
# 详情标题
RE_TITLE = re.compile(
    r'<h1[^>]*class="title"[^>]*>\s*<span[^>]*>([^<]+)</span>', re.S | re.I)
# 详情元数据
RE_TYPE = re.compile(r'类型：</span><a[^>]*>([^<]+)</a>', re.S | re.I)
RE_AREA = re.compile(r'地区：</span><a[^>]*>([^<]+)</a>', re.S | re.I)
RE_YEAR = re.compile(r'年份：</span><a[^>]*>([^<]+)</a>', re.S | re.I)
RE_CONTENT = re.compile(
    r'<span class="left text-muted">简介：</span>(.*?)<a href="#desc">', re.S | re.I)
# 播放源 tab + 选集
RE_TAB = re.compile(r'<a href="#playlist(\d+)"[^>]*>([^<]+)</a>', re.S | re.I)
RE_EP = re.compile(
    r'<a href="/vodplay/(\d+)-(\d+)-(\d+)\.html"[^>]*>([^<]+)</a>', re.S | re.I)
# 分页页码（vodshow 分页：/vodshow/1--------2---.html 等）
RE_PAGE = re.compile(r'vodshow/\d+[^"]*?/(\d+)\.html', re.I)


def _clean(s):
    s = re.sub(r'<[^>]+>', '', s or "")
    s = s.replace("&nbsp;", " ").replace("\u3000", " ").replace("&amp;", "&")
    return re.sub(r'\s+', ' ', s).strip()


class HnyqswSpider(_TVBase):

    def getName(self):
        return SITE_NAME

    def init(self, extend=""):
        self._clean_cache = {}
        pass   # 让基类 __init__ 自然初始化

    # ── 网络 ──
    def _headers(self):
        return {"User-Agent": UA, "Referer": BASE_URL + "/",
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8"}

    def _fetch_html(self, url):
        rsp = self.fetch(url, headers=self._headers(), timeout=15)
        try:
            rsp.encoding = rsp.apparent_encoding or "utf-8"
        except Exception:
            pass
        return rsp.text

    def _header_json(self):
        return json.dumps({"User-Agent": UA, "Referer": BASE_URL + "/"})

    # ── 解析钩子 ──
    def _parse_list(self, html):
        items = []
        for m in RE_CARD.finditer(html or ""):
            block = m.group(1)
            tm = RE_THUMB.search(block)
            dm = RE_DETAIL_LINK.search(block)
            if not (tm and dm):
                continue
            name, pic = tm.group(1).strip(), tm.group(2).strip()
            vid = dm.group(1)
            rm = RE_REMARK.search(block)
            items.append({"vod_id": vid, "vod_name": name or vid,
                          "vod_pic": pic,
                          "vod_remarks": rm.group(1).strip() if rm else ""})
        for m in RE_MEDIA_CARD.finditer(html or ""):
            vid, name, pic, rm = m.groups()
            items.append({"vod_id": vid, "vod_name": (name or "").strip() or vid,
                          "vod_pic": (pic or "").strip(),
                          "vod_remarks": (rm or "").strip()})
        seen, uniq = set(), []
        for it in items:
            if it["vod_id"] in seen:
                continue
            seen.add(it["vod_id"])
            uniq.append(it)
        return uniq

    def _pagecount(self, html):
        nums = [int(p) for p in RE_PAGE.findall(html or "") if p.isdigit()]
        return max(nums) if nums else 1

    def _parse_episodes(self, html, vod_id):
        """返回 (源名列表, 每个源的选集串)。本站通常单源「高清云播」。"""
        tabs = {sid: name for sid, name in RE_TAB.findall(html or "")}
        groups = {}
        for m in RE_EP.finditer(html or ""):
            _vid, sid, nid, ep_name = m.groups()
            ep = (ep_name or "").strip() or nid
            groups.setdefault(sid, []).append(
                "%s$/vodplay/%s-%s-%s.html" % (ep, _vid, sid, nid))
        if not groups:
            return "默认线路", "播放$/vodplay/%s-1-1.html" % vod_id
        sids = sorted(groups.keys(), key=int)
        names = "$$$".join(tabs.get(s, s) for s in sids)
        urls = "$$$".join("#".join(groups[s]) for s in sids)
        return names, urls

    def _detail(self, vid):
        url = "%s/voddetail/%s.html" % (BASE_URL, vid)
        html = self._fetch_html(url)
        name_m = RE_TITLE.search(html)
        vod = {"vod_id": str(vid),
               "vod_name": name_m.group(1).strip() if name_m else str(vid)}
        for _re, key in ((RE_TYPE, "vod_class"), (RE_YEAR, "vod_year"),
                         (RE_AREA, "vod_area")):
            m = _re.search(html)
            if m:
                vod[key] = m.group(1).strip()
        cm = RE_CONTENT.search(html)
        if cm:
            vod["vod_content"] = _clean(cm.group(1))
        frm, urls = self._parse_episodes(html, vid)
        vod["vod_play_from"] = frm
        vod["vod_play_url"] = urls
        return vod

    def _clean_playlist(self, body, base_url):
        """过滤广告分片，返回 (清洗后m3u8, 移除分片数)。"""
        base_dir = base_url.rsplit("/", 1)[0] + "/"
        out, removed = [], 0
        for line in (body or "").splitlines():
            s = line.strip()
            if not s or s.startswith("#"):
                if "#EXT-X-KEY" in line and 'URI="' in line:
                    m = re.search(r'URI="([^"]+)"', line)
                    if m and not m.group(1).startswith("http"):
                        line = line.replace(m.group(1),
                                            base_dir + m.group(1).lstrip("/"))
                out.append(line)
                continue
            if RE_AD_SEG.search(s):
                removed += 1
                continue
            out.append(s if s.startswith("http") else base_dir + s.lstrip("/"))
        return "\n".join(out), removed

    def _extract_player_url(self, html):
        m = re.search(r'var\s+player_\w+\s*=\s*\{', html)
        if not m:
            return None
        start = html.find('{', m.start())
        depth, end = 0, -1
        for i in range(start, len(html)):
            if html[i] == '{':
                depth += 1
            elif html[i] == '}':
                depth -= 1
                if depth == 0:
                    end = i
                    break
        if end < 0:
            return None
        try:
            return json.loads(html[start:end + 1].replace(r'\/', '/')).get('url')
        except Exception:
            return None

    # ═══════════ TVBox 接口 ═══════════
    def homeContent(self, filter):
        return {"class": HOME_CLASSES, "filters": {}}

    def homeVideoContent(self):
        try:
            return {"list": self._parse_list(self._fetch_html(BASE_URL + "/"))}
        except Exception:
            return {"list": []}

    def categoryContent(self, tid, pg, filter, extend):
        page = int(pg) if pg else 1
        try:
            url = self._cat_url(tid, page)
            html = self._fetch_html(url)
            items = self._parse_list(html)
            return {"list": items, "page": page,
                    "pagecount": self._pagecount(html), "limit": 30,
                    "total": len(items)}
        except Exception:
            return {"list": [], "page": page, "pagecount": 1,
                    "limit": 30, "total": 0}

    def _cat_url(self, tid, page):
        if page <= 1:
            return "%s/vodshow/%s-----------.html" % (BASE_URL, tid)
        # 真实分页：/vodshow/{tid}--------{pg}---.html（8 横线+pg+3 横线）
        return "%s/vodshow/%s--------%d---.html" % (BASE_URL, tid, page)

    def detailContent(self, ids):
        try:
            vid = str(ids[0]) if ids else ""
            return {"list": [self._detail(vid)]}
        except Exception as e:
            vid = str(ids[0]) if ids else ""
            return {"list": [{"vod_id": vid, "vod_name": "解析异常",
                              "vod_content": str(e)[:200],
                              "vod_play_from": "默认线路",
                              "vod_play_url": "播放$/vodplay/%s-1-1.html" % vid}]}

    def searchContent(self, key, quick, pg="1"):
        page = int(pg) if pg else 1
        try:
            url = self._search_url(key, page)
            html = self._fetch_html(url)
            items = self._parse_list(html)
            return {"list": items, "page": page,
                    "pagecount": self._pagecount(html), "limit": 20,
                    "total": len(items)}
        except Exception:
            return {"list": [], "page": page, "pagecount": 1,
                    "limit": 20, "total": 0}

    def _search_url(self, key, page):
        from urllib.parse import quote
        kw = quote(key, safe="")
        if page <= 1:
            return "%s/vodsearch/%s-------------.html" % (BASE_URL, kw)
        return "%s/vodsearch/%s-------------%d.html" % (BASE_URL, kw, page)

    def playerContent(self, flag, id, vipFlags):
        hd = self._header_json()
        try:
            play_url = id if id.startswith("http") else (BASE_URL + id)
            html = self.fetch(play_url, headers=self._headers(), timeout=15).text
            url = self._extract_player_url(html)
            if not url:
                return {"parse": 1, "playUrl": "", "url": play_url, "header": hd}
            if AD_MODE == "proxy":
                body = self.fetch(url, headers=self._headers(), timeout=15).text
                if body and "#EXT-X-STREAM-INF" not in body:
                    cleaned, removed = self._clean_playlist(body, url)
                    if removed:
                        param = "xh_%d" % len(self._clean_cache)
                        self._clean_cache[param] = cleaned
                        return {"parse": 0, "playUrl": "", "url": "local://" + param,
                                "header": hd}
            return {"parse": 0, "playUrl": "", "url": url, "header": hd}
        except Exception:
            return {"parse": 1, "playUrl": "", "url": id, "header": hd}

    def isVideoFormat(self, url):
        pass

    def manualVideoCheck(self):
        pass

    def localProxy(self, param):
        body = self._clean_cache.get(param, "")
        if not body:
            return [200, "video/MP2T", "", ""]
        return [200, "application/vnd.apple.mpegurl", body.encode("utf-8"), ""]


# 兼容按 module.Spider 类名加载的 TVBox 变体
Spider = HnyqswSpider


if __name__ == "__main__":
    s = HnyqswSpider()
    s.init()
    print("home:", s.homeContent(False))
    print("homeVideo:", s.homeVideoContent()["list"][:2])
    print("cat:", s.categoryContent("1", 1, False, {})["list"][:2])
    print("detail:", s.detailContent(["132"])["list"][0])
    print("search:", s.searchContent("灵武大陆", False, "1")["list"][:3])
    print("player:", s.playerContent("play", "/vodplay/132-1-1.html", ""))
