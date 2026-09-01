# -*- coding: utf-8 -*-
"""
永乐视频（ylys.tv / 59v.net 镜像）TVBox 部署版
==============================================
- 技术栈：苹果CMS（MacCMS），UTF-8；路由带尾部斜杠
    vodtype  /vodtype/{tid}/   vodshow /vodshow/{12段}/
    detail   /voddetail/{id}/  play /play/{id}-{sid}-{nid}/  search /vodsearch/{quote(kw)}-------------/
- vodshow 12 段布局（实测）：segs[0]=tid segs[1]=area segs[3]=class segs[8]=pg segs[11]=year
    组合限制：year 只能单独；area 不可与 pg 组合（categoryContent 已降级处理）
- 列表卡片：module-poster-item（分类）/ module-card-item（搜索，<strong> 标题）
- 选集：ylsp-detail-old-playlist 内 module-play-list-link；线路名=tab-item 顺序
- 播放：player_aaaa.encrypt=0 直链 m3u8；无广告分片，直链播放

部署规范：继承 base.spider.Spider，网络走 self.fetch；playerContent.header 为 json 字符串；
所有接口 try/except 兜底；模块级 Spider = YlysSpider。PC 端可用 __main__ 自检（本地 urllib 桩）。
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
            r = urlopen(Request(url, headers=headers or {}), timeout=timeout)
            return self._resp(r.read())

        def post(self, url, data=None, headers=None, timeout=15):
            from urllib.request import Request, urlopen
            from urllib.parse import urlencode
            body = urlencode(data or {}).encode()
            r = urlopen(Request(url, data=body, headers=headers or {},
                                method="POST"), timeout=timeout)
            return self._resp(r.read())
    # ── 桩结束 ──


# ═══════════ 站点配置 ═══════════
SITE_NAME = "永乐视频"
BASE_URL = "https://www.ylys.tv"
UA = ("Mozilla/5.0 (Linux; Android 12) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/125.0.0.0 Mobile Safari/537.36")

HOME_CLASSES = [
    {"type_id": "1", "type_name": "电影"},
    {"type_id": "2", "type_name": "剧集"},
    {"type_id": "3", "type_name": "综艺"},
    {"type_id": "4", "type_name": "动漫"},
]

# 广告处理：实测无广告分片，off 直链播放
AD_MODE = "off"
AD_SOURCES = ()
RE_AD_SEG = re.compile(
    r'/(?:adjump|advert|adss?|gg\d*|ad|ads)/|(?:^|[-_.])ad[-_.]', re.I)

# 二级「类型」筛选（vodshow class 字段，索引 3）
SUB_CATE = [
    {"n": "全部", "v": ""},
    {"n": "动作", "v": "动作"},
    {"n": "喜剧", "v": "喜剧"},
    {"n": "爱情", "v": "爱情"},
    {"n": "科幻", "v": "科幻"},
    {"n": "恐怖", "v": "恐怖"},
    {"n": "剧情", "v": "剧情"},
    {"n": "战争", "v": "战争"},
    {"n": "古装", "v": "古装"},
    {"n": "犯罪", "v": "犯罪"},
    {"n": "悬疑", "v": "悬疑"},
    {"n": "奇幻", "v": "奇幻"},
    {"n": "冒险", "v": "冒险"},
    {"n": "惊悚", "v": "惊悚"},
    {"n": "动画", "v": "动画"},
    {"n": "记录", "v": "记录"},
    {"n": "音乐", "v": "音乐"},
]
YEAR_FILTERS = [{"n": "全部", "v": ""}] + \
    [{"n": str(y), "v": str(y)} for y in range(2026, 2019, -1)]

# ═══════════ 站点正则 ═══════════
RE_POSTER = re.compile(
    r'<a[^>]*href="/voddetail/(\d+)/"[^>]*title="([^"]*)"[^>]*'
    r'class="module-poster-item[^"]*">.*?'
    r'<div class="module-item-note">([^<]*)</div>.*?'
    r'<img[^>]*?(?:data-original|src)="([^"]*)"',
    re.S | re.I)
RE_CARD = re.compile(
    r'<div class="module-card-item module-item">.*?'
    r'<a[^>]*href="/voddetail/(\d+)/"[^>]*>.*?'
    r'<div class="module-item-note">([^<]*)</div>.*?'
    r'<img[^>]*?(?:data-original|src)="([^"]*)"[^>]*>.*?'
    r'<div class="module-card-item-title"><a[^>]*><strong>([^<]*)</strong></a>',
    re.S | re.I)
RE_TAB_ITEM = re.compile(r'data-dropdown-value="([^"]+)"')
RE_BLOCK = re.compile(r'<div class="module-list sort-list tab-list his-tab-list">')
RE_EP_LINK = re.compile(
    r'<a class="module-play-list-link" href="/play/\d+-(\d+)-(\d+)/"[^>]*>'
    r'<span>([^<]*)</span></a>', re.S | re.I)
RE_H1 = re.compile(r'<div class="module-info-heading">.*?<h1>([^<]+)</h1>', re.S | re.I)
RE_TAG_LINK = re.compile(r'<div class="module-info-tag-link">(.*?)</div>', re.S | re.I)
RE_TAG_A = re.compile(r'<a[^>]*href="([^"]*)"[^>]*>([^<]*)</a>', re.S | re.I)
RE_DIR = re.compile(r'<span class="module-info-item-title">导演：</span>.*?'
                    r'<div class="module-info-item-content">(.*?)</div>', re.S | re.I)
RE_ACTOR = re.compile(r'<span class="module-info-item-title">主演：</span>.*?'
                      r'<div class="module-info-item-content">(.*?)</div>', re.S | re.I)
RE_DESC = re.compile(r'<div class="module-info-introduction-content">(.*?)</div>',
                     re.S | re.I)
RE_POSTER_IMG = re.compile(
    r'<div class="module-info-poster">.*?<img[^>]*?(?:data-original|src)="([^"]*)"',
    re.S | re.I)
# 分页器：尾页链接 / 页码链接（pg 段在 vodshow 12 段 idx8）
RE_PAGE_LAST = re.compile(r'href="(/vodshow/[^"]*?)"[^>]*title="尾页"', re.I)
RE_PAGE_NUM = re.compile(r'class="page-link page-number[^"]*"[^>]*>(\d+)</a>', re.I)
RE_PAGE_CUR = re.compile(r'page-link page-number page-current[^>]*>(\d+)</', re.I)

_tag_re = re.compile(r'<[^>]+>')


def _clean(s):
    s = _tag_re.sub('', s or "")
    s = s.replace("&nbsp;", " ").replace("\u3000", " ").replace("&amp;", "&")
    return re.sub(r'\s+', ' ', s).strip()


def _abs(url):
    url = (url or "").strip()
    if not url:
        return ""
    if url.startswith("//"):
        return "https:" + url
    if url.startswith("/"):
        return BASE_URL + url
    return url


class YlysSpider(_TVBase):

    def getName(self):
        return SITE_NAME

    def init(self, extend=""):
        self._clean_cache = {}
        pass  # 基类 __init__ 自然初始化

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

    # ── 解析 ──
    def _parse_list(self, html):
        items, seen = [], set()
        for m in RE_POSTER.finditer(html or ""):
            vid, name, note, pic = m.groups()
            if vid in seen:
                continue
            seen.add(vid)
            items.append({"vod_id": vid, "vod_name": (name or "").strip(),
                          "vod_pic": _abs(pic), "vod_remarks": (note or "").strip()})
        for m in RE_CARD.finditer(html or ""):
            vid, note, pic, name = m.groups()
            if vid in seen:
                continue
            seen.add(vid)
            items.append({"vod_id": vid, "vod_name": (name or "").strip(),
                          "vod_pic": _abs(pic), "vod_remarks": (note or "").strip()})
        return items

    def _parse_episodes(self, html, vid):
        """返回 (线路名列表, [(线路名, [集名$播放路径,...])])。"""
        names = [n for n in RE_TAB_ITEM.findall(html or "")]
        starts = [m.start() for m in RE_BLOCK.finditer(html or "")]
        groups = []
        for i, st in enumerate(starts):
            en = starts[i + 1] if i + 1 < len(starts) else len(html)
            block = html[st:en]
            eps = []
            for sid, nid, ep_name in RE_EP_LINK.findall(block):
                eps.append("%s$/play/%s-%s-%s/" % (ep_name.strip() or nid, vid, sid, nid))
            if not eps:
                continue
            name = names[i] if i < len(names) else "线路%d" % (i + 1)
            groups.append((name, eps))
        return names, groups

    def _detail(self, vid):
        html = self._fetch_html(BASE_URL + "/voddetail/%s/" % vid)
        name_m = RE_H1.search(html)
        name = _clean(name_m.group(1)) if name_m else vid
        vod = {"vod_id": vid, "vod_name": name}

        pic_m = RE_POSTER_IMG.search(html)
        if pic_m:
            vod["vod_pic"] = _abs(pic_m.group(1))

        year, area, cls = "", "", []
        for blk in RE_TAG_LINK.findall(html):
            for href, text in RE_TAG_A.findall(blk):
                t = text.strip()
                segs = href.strip("/").split("/")
                p = segs[-1].split("-") if segs else []
                if len(p) != 12:
                    continue
                if p[11] and re.fullmatch(r"\d{4}", t):
                    year = t
                elif p[1]:
                    area = t
                elif p[3] and t and t not in cls:
                    cls.append(t)
        if year:
            vod["vod_year"] = year
        if area:
            vod["vod_area"] = area
        if cls:
            vod["vod_class"] = ",".join(cls)

        dir_m = RE_DIR.search(html)
        if dir_m:
            vod["vod_director"] = _clean(dir_m.group(1))
        actor_m = RE_ACTOR.search(html)
        if actor_m:
            vod["vod_actor"] = _clean(actor_m.group(1))
        desc_m = RE_DESC.search(html)
        if desc_m:
            vod["vod_content"] = _clean(desc_m.group(1))

        _, groups = self._parse_episodes(html, vid)
        if groups:
            vod["vod_play_from"] = "$$$".join(n for n, _ in groups)
            vod["vod_play_url"] = "$$$".join("#".join(eps) for _, eps in groups)
        return vod

    # ── 分类 URL（vodshow 12 段） ──
    def _cat_url(self, tid, page, cls="", year=""):
        from urllib.parse import quote
        segs = [""] * 12
        segs[0] = str(tid)
        if cls:
            segs[3] = quote(cls)
        if year:
            segs[11] = str(year)
        if int(page or 1) > 1:
            segs[8] = str(int(page or 1))
        return BASE_URL + "/vodshow/" + "-".join(segs) + "/"

    def _pagecount(self, html):
        """从分页器提取真实总页数（尾页链接优先，其次页码链接最大值）。"""
        m = RE_PAGE_LAST.search(html or "")
        if m:
            p = m.group(1).strip("/").split("/")[-1].split("-")
            if len(p) == 12 and p[8].isdigit():
                return int(p[8])
        nums = [int(n) for n in RE_PAGE_NUM.findall(html or "")]
        nums += [int(n) for n in RE_PAGE_CUR.findall(html or "")]
        if nums:
            return max(nums)
        return 1

    # ═══════════ TVBox 接口 ═══════════
    def homeContent(self, filter):
        classes = HOME_CLASSES
        try:
            if filter:
                filters = {}
                for c in classes:
                    tid = c["type_id"]
                    filters[tid] = [
                        {"key": "type", "name": "类型", "value": SUB_CATE},
                        {"key": "year", "name": "年份", "value": YEAR_FILTERS},
                    ]
                return {"class": classes, "filters": filters}
        except Exception:
            pass
        return {"class": classes, "filters": {}}

    def homeVideoContent(self):
        try:
            return {"list": self._parse_list(self._fetch_html(BASE_URL + "/"))}
        except Exception:
            return {"list": []}

    def categoryContent(self, tid, pg, filter, extend):
        page = int(pg) if pg else 1
        try:
            ext = extend or {}
            cls, year = ext.get("type", ""), ext.get("year", "")
            if year:  # 模板限制：year 只能单独用
                cls = ""
            url = self._cat_url(tid, page, cls, year)
            # 空结果重试（站点对连续请求偶发限流/抖动，返回空页）
            import time
            items = []
            for attempt in range(3):
                html = self._fetch_html(url)
                items = self._parse_list(html)
                if items or attempt == 2:
                    break
                time.sleep(1.5)
            return {"list": items, "page": page,
                    "pagecount": self._pagecount(html), "limit": 30,
                    "total": len(items)}
        except Exception:
            return {"list": [], "page": page, "pagecount": 1, "limit": 30, "total": 0}

    def detailContent(self, ids):
        vid = str(ids[0]) if ids else ""
        try:
            return {"list": [self._detail(vid)]}
        except Exception as e:
            return {"list": [{"vod_id": vid, "vod_name": "解析异常",
                              "vod_content": str(e)[:200],
                              "vod_play_from": "默认线路",
                              "vod_play_url": "播放$/play/%s-1-1/" % vid}]}

    def searchContent(self, key, quick, pg="1"):
        page = int(pg) if pg else 1
        try:
            from urllib.parse import quote
            url = BASE_URL + "/vodsearch/" + quote(key) + "-------------/"
            # 空结果重试（搜索接口限流：连续搜索偶发返回空页）
            import time
            items = []
            for attempt in range(3):
                items = self._parse_list(self._fetch_html(url))
                if items or attempt == 2:
                    break
                time.sleep(1.5)
            return {"list": items, "page": page,
                    "pagecount": 1, "limit": 20, "total": len(items)}
        except Exception:
            return {"list": [], "page": page, "pagecount": 1, "limit": 20, "total": 0}

    def playerContent(self, flag, id, vipFlags):
        hd = self._header_json()
        try:
            play_url = id if id.startswith("http") else (BASE_URL + id)
            html = self._fetch_html(play_url)
            url = self._extract_player_url(html)
            if not url:
                return {"parse": 1, "playUrl": "", "url": play_url, "header": hd}
            # 实测无广告分片 → off 直链播放；如需清洗切 AD_MODE="proxy"
            return {"parse": 0, "playUrl": "", "url": url, "header": hd}
        except Exception:
            return {"parse": 1, "playUrl": "", "url": id, "header": hd}

    def _extract_player_url(self, html):
        """var player_xxxx={...,"encrypt":0,"url":"..."} → 直链。"""
        m = re.search(r'var\s+player_\w+\s*=\s*\{', html or "")
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

    def isVideoFormat(self, url):
        u = (url or "").lower().split("?")[0]
        return any(u.endswith(s) for s in (".m3u8", ".mp4", ".flv", ".ts"))

    def manualVideoCheck(self):
        pass

    def localProxy(self, param):
        body = self._clean_cache.get(param, "")
        if not body:
            return [200, "video/MP2T", "", ""]
        return [200, "application/vnd.apple.mpegurl", body.encode("utf-8"), ""]


# 兼容按 module.Spider 类名加载的 TVBox 变体
Spider = YlysSpider


if __name__ == "__main__":
    s = YlysSpider()
    s.init()
    print("home:", s.homeContent(False))
    print("cat:", s.categoryContent("1", 2, False, {}))
    print("detail:", s.detailContent(["119419"]))
    print("player:", s.playerContent("自营1线", "/play/119419-1-1/", ""))
