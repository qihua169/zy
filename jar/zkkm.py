# -*- coding: utf-8 -*-

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
SITE_NAME = "片库网"
BASE_URL = "https://www.zk-km.com"
UA = ("Mozilla/5.0 (Linux; Android 12) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/125.0.0.0 Mobile Safari/537.36")

# ── 一级分类（对齐加菲猫影视 CATE 结构） ──
CATE = {
    "电影": "1",
    "电视剧": "2",
    "综艺": "3",
    "动漫": "4",
    "短剧": "26",
}

# ── 二级分类 filter（类型筛选；zk-km 子分类是独立 tid，type 值=子分类 tid） ──
SUB_CATE = {
    "1": [
        {"n": "全部", "v": ""},
        {"n": "动作片", "v": "6"},
        {"n": "喜剧片", "v": "7"},
        {"n": "爱情片", "v": "8"},
        {"n": "科幻片", "v": "9"},
        {"n": "恐怖片", "v": "10"},
        {"n": "剧情片", "v": "11"},
        {"n": "战争片", "v": "12"},
        {"n": "纪录片", "v": "24"},
    ],
    "2": [
        {"n": "全部", "v": ""},
        {"n": "国产剧", "v": "25"},
        {"n": "美剧", "v": "20"},
        {"n": "韩剧", "v": "13"},
        {"n": "日剧", "v": "14"},
        {"n": "泰剧", "v": "15"},
        {"n": "港剧", "v": "16"},
    ],
    # 3 综艺 / 4 动漫 / 26 短剧 无子分类
}

YEAR_FILTERS = [
    {"n": "全部", "v": ""},
] + [{"n": str(y), "v": str(y)} for y in range(2026, 2009, -1)]

AREA_FILTERS = [
    {"n": "全部", "v": ""},
    {"n": "大陆", "v": "大陆"},
    {"n": "中国香港", "v": "香港"},
    {"n": "中国台湾", "v": "台湾"},
    {"n": "美国", "v": "美国"},
    {"n": "韩国", "v": "韩国"},
    {"n": "日本", "v": "日本"},
    {"n": "英国", "v": "英国"},
    {"n": "泰国", "v": "泰国"},
    {"n": "法国", "v": "法国"},
    {"n": "德国", "v": "德国"},
    {"n": "西班牙", "v": "西班牙"},
    {"n": "意大利", "v": "意大利"},
    {"n": "加拿大", "v": "加拿大"},
    {"n": "印度", "v": "印度"},
    {"n": "其他", "v": "其他"},
]
# 播放源直链为标准 m3u8 且无广告分片 → off（直链返回，零额外开销）。
# 若某线路日后混入 /adjump/ 等广告分片，改为 "proxy"（localProxy 清洗）或 "drop"（过滤线路）。
AD_MODE = "off"
AD_SOURCES = ()
# 不可播线路名（用户反馈：线路一=路线一、线路四=播放四；站点线路名全集：
# 路线一/路线二/路线三/播放四，tab 名与 sid 映射混乱，按线路名过滤）
EXCLUDE_SOURCES = ("路线一", "播放四")
RE_AD_SEG = re.compile(
    r'/(?:adjump|advert|adss?|gg\d*|ad|ads)/|(?:^|[-_.])ad[-_.]', re.I)


# ═══════════ 站点正则（STUI 模板） ═══════════
# 列表卡片：pic-text1（分类）在前、pic-text（备注）在后，用 (?!1) 排除 pic-text1
RE_CARD = re.compile(
    r'<a[^>]*class="[^"]*stui-vodlist__thumb[^"]*"[^>]*'
    r'href="/product/(\d+)\.html"[^>]*title="([^"]*)"[^>]*?'
    r'(?:data-original|src)="([^"]*)"[^>]*>(?:(?!</a>).)*?'
    r'<span class="pic-text(?!1)[^"]*"[^>]*><b>(.*?)</b></span>',
    re.S | re.I)
# tab 名 → sid（实测 playlist2 对应「路线三」，必须映射）
RE_TAB = re.compile(
    r'<a[^>]*href="#playlist(\d+)"[^>]*data-toggle="tab"[^>]*>(.*?)</a>',
    re.S | re.I)
RE_PLBLK = re.compile(
    r'<div[^>]*id="playlist(\d+)"[^>]*>.*?'
    r'<ul class="stui-content__playlist[^"]*"[^>]*>(.*?)</ul>',
    re.S | re.I)
RE_EP = re.compile(
    r'<a href="(/html/\d+-\d+-\d+\.html)"[^>]*title="([^"]*)"[^>]*>(.*?)</a>',
    re.S | re.I)
RE_OG = re.compile(r'<meta property="([^"]+)" content="([^"]*)"', re.I)
RE_REMARK = re.compile(r'状态[：:]\s*<[^>]*>\s*([^<]+?)\s*<', re.S)
RE_YEAR = re.compile(r'年份[：:]\s*<[^>]*>\s*(\d{4})', re.S)
RE_PAGECOUNT = re.compile(r'<li class="active num"><a>\d+/(\d+)</a></li>', re.S)


def _clean(s):
    s = re.sub(r'<[^>]+>', '', s or "")
    s = s.replace("&nbsp;", " ").replace("\u3000", " ").replace("&amp;", "&")
    return re.sub(r'\s+', ' ', s).strip()


class ZkkmSpider(_TVBase):

    def getName(self):
        return SITE_NAME

    def init(self, extend=""):
        self._clean_cache = {}
        self._cdn_ok = {}   # CDN 域名可用性缓存（True 永久 / False 短 TTL）
        self._cdn_ts = {}   # CDN 探测时间戳（False 缓存过期判断）
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
            vid, name, pic, remark = m.groups()
            item = {"vod_id": vid, "vod_name": name.strip(),
                    "vod_pic": pic.strip()}
            if remark and remark.strip():
                item["vod_remarks"] = remark.strip()
            items.append(item)
        return items

    def _pagecount(self, html):
        m = RE_PAGECOUNT.search(html or "")
        if m:
            try:
                return int(m.group(1))
            except Exception:
                pass
        return 1

    def _parse_episodes(self, html, vod_id):
        """返回 (vod_play_from, vod_play_url)；tab 名与 sid 显式映射。"""
        names = {}
        for m in RE_TAB.finditer(html or ""):
            names[m.group(1)] = _clean(m.group(2)) or m.group(1)
        groups = {}
        for m in RE_PLBLK.finditer(html or ""):
            sid = m.group(1)
            src_name = names.get(sid, sid)
            if src_name in EXCLUDE_SOURCES:
                continue          # 静态名单：用户点名不可播线路（路线一 / 播放四）
            if AD_MODE == "drop" and src_name in AD_SOURCES:
                continue
            eps = []
            for e in RE_EP.finditer(m.group(2)):
                path = e.group(1)
                title = e.group(2).strip()
                text = _clean(e.group(3))
                eps.append("%s$%s" % (text or title or path, path))
            if eps:
                groups[sid] = (src_name, eps)
        # 动态探测：以能播放为准，舍弃探测失败的线路（CDN 域名级缓存）
        groups = self._keep_playable(groups)
        sids = sorted(groups.keys(), key=int)
        if not sids:
            # 无可用线路：明确标「失效」，避免误导（原「默认线路」是假路径，实际不可播）
            return "失效", "无可用线路$/html/%sd1e1.html" % vod_id
        vod_from = "$$$".join(groups[s][0] for s in sids)
        vod_url = "$$$".join("#".join(groups[s][1]) for s in sids)
        return vod_from, vod_url

    # ── 线路动态探测（以能播放为准，兼顾抗误判） ──
    PROBE_FALSE_TTL = 120   # False 缓存时长（秒）：CDN 抖动时短 TTL 允许重新探测
    PROBE_RETRY = 1         # 探测失败重试次数

    def _keep_playable(self, groups):
        """过滤不可播线路：探测每条线路第 1 集 m3u8 可达性；
        高失败率（≥50%）视为网络抖动 → 回退原始列表，避免误删能播线路。"""
        import time as _t
        out = {}
        total = len(groups or {})
        for sid, (name, eps) in (groups or {}).items():
            play_path = eps[0].split("$", 1)[1]
            if self._probe_episode(play_path):
                out[sid] = (name, eps)
        failed = total - len(out)
        if out and failed and failed * 2 >= total:
            return groups   # 抖动/异常：保留全部，交给播放器验证
        return out if out else groups

    def _probe_episode(self, play_path):
        """抓播放页 → 提取直链 → 探测 m3u8；抓取失败重试 1 次。"""
        import time as _t
        play_url = play_path if play_path.startswith("http") else (BASE_URL + play_path)
        html = ""
        for _ in range(self.PROBE_RETRY + 1):
            try:
                html = self.fetch(play_url, headers=self._headers(), timeout=8).text
                if html:
                    break
            except Exception:
                html = ""
            _t.sleep(0.8)
        url = self._extract_player_url(html)
        if not url:
            return False
        return self._probe_m3u8(url)

    def _probe_m3u8(self, url):
        """探测 m3u8 可达性（响应非空即有效，不做 #EXTM3U 硬校验）；
        True 永久缓存，False 短 TTL（PROBE_FALSE_TTL）避免 CDN 抖动误判。"""
        import time as _t
        from urllib.parse import urlparse
        host = urlparse(url).netloc
        cached = self._cdn_ok.get(host)
        if cached is True:
            return True
        if cached is False and _t.time() - self._cdn_ts.get(host, 0) < self.PROBE_FALSE_TTL:
            return False
        ok = False
        for _ in range(self.PROBE_RETRY + 1):
            try:
                rsp = self.fetch(url, headers=self._headers(), timeout=5)
                ok = bool((getattr(rsp, "text", "") or "").strip())
                if ok:
                    break
            except Exception:
                ok = False
            _t.sleep(0.8)
        self._cdn_ok[host] = ok
        self._cdn_ts[host] = _t.time()
        return ok

    def _detail(self, vid):
        html = self._fetch_html("%s/product/%s.html" % (BASE_URL, vid))
        vod = {"vod_id": vid}   # 注意：不能预置 vod_name，否则 og:title 无法覆盖
        og_map = {
            "og:title": "vod_name", "og:image": "vod_pic",
            "og:video:area": "vod_area", "og:video:language": "vod_lang",
            "og:video:class": "vod_class", "og:video:director": "vod_director",
            "og:video:actor": "vod_actor", "og:description": "vod_content",
        }
        for key, val in RE_OG.findall(html):
            field = og_map.get(key)
            if field and val.strip() and field not in vod:
                vod[field] = val.strip()
        if not vod.get("vod_name"):
            vod["vod_name"] = vid
        m = RE_YEAR.search(html)
        if m:
            vod["vod_year"] = m.group(1)
        rm = RE_REMARK.search(html)
        if rm:
            vod["vod_remarks"] = rm.group(1).strip()
        vod_from, vod_url = self._parse_episodes(html, vid)
        vod["vod_play_from"] = vod_from
        vod["vod_play_url"] = vod_url
        return vod

    # ═══════════ TVBox 接口 ═══════════
    def homeContent(self, filter):
        """一级分类 + 二级分类 filter（对齐加菲猫影视：filter=True 才生成 filters）。
        注意：站点类型子分类是独立 tid；年份/地区 URL 为实测格式（见 _cat_url）。"""
        classes = [{'type_name': n, 'type_id': CATE[n]} for n in CATE]
        if filter:
            filters = {}
            for cid in CATE.values():
                flist = []
                if cid in SUB_CATE:
                    flist.append({"key": "type", "name": "类型", "value": SUB_CATE[cid]})
                flist.append({"key": "year", "name": "年份", "value": YEAR_FILTERS})
                flist.append({"key": "area", "name": "地区", "value": AREA_FILTERS})
                filters[cid] = flist
            return {"class": classes, "filters": filters}
        return {"class": classes, "filters": {}}

    def homeVideoContent(self):
        try:
            return {"list": self._parse_list(self._fetch_html(BASE_URL + "/"))}
        except Exception:
            return {"list": []}

    def categoryContent(self, tid, pg, filter, extend):
        page = int(pg) if pg else 1
        try:
            extend = extend or {}
            sub_type = extend.get('type', '')
            year = extend.get('year', '')
            area = extend.get('area', '')
            # 类型筛选：zk-km 子分类是独立 tid，直接切换 tid（其余筛选对子分类同样有效）
            if sub_type:
                tid = sub_type
            html = self._fetch_html(self._cat_url(tid, page, year, area))
            items = self._parse_list(html)
            return {"list": items, "page": page,
                    "pagecount": self._pagecount(html), "limit": 12,
                    "total": len(items)}
        except Exception:
            return {"list": [], "page": page, "pagecount": 1,
                    "limit": 12, "total": 0}

    def _cat_url(self, tid, page, year="", area=""):
        """zk-km 筛选 URL（实测格式，非 MacCMS 标准 6 字段）：
          无筛选  /vodshow/{tid}--------{pg}---.html
          年份    /vodshow/{tid}--------{pg}---{year}.html
          地区    /vodshow/{tid}-{area}-------{pg}---.html
          ⚠ 地区+年份组合模板不支持（实测 0 条），单维度优先：year > area
        """
        from urllib.parse import quote
        if year:
            return "%s/vodshow/%s--------%d---%s.html" % (BASE_URL, tid, page, year)
        if area:
            return "%s/vodshow/%s-%s-------%d---.html" % (BASE_URL, tid, quote(area), page)
        return "%s/vodshow/%s--------%d---.html" % (BASE_URL, tid, page)

    def detailContent(self, ids):
        try:
            vid = str(ids[0]) if ids else ""
            return {"list": [self._detail(vid)]}
        except Exception as e:
            vid = str(ids[0]) if ids else ""
            return {"list": [{"vod_id": vid, "vod_name": "解析异常",
                              "vod_content": str(e)[:200],
                              "vod_play_from": "失效",
                              "vod_play_url": "无可用线路$/html/%sd1e1.html" % vid}]}

    def searchContent(self, key, quick, pg="1"):
        page = int(pg) if pg else 1
        try:
            html = self._fetch_html(self._search_url(key, page))
            items = self._parse_list(html)
            return {"list": items, "page": page, "pagecount": 1,
                    "limit": 20, "total": len(items)}
        except Exception:
            return {"list": [], "page": page, "pagecount": 1,
                    "limit": 20, "total": 0}

    def _search_url(self, key, page):
        from urllib.parse import quote
        # GET 伪静态；POST /vodsearch/-------------.html 返回被 JSON 转义的
        # HTML 字符串不可解析，必须走 GET
        return "%s/vodsearch/%s-------------.html" % (BASE_URL, quote(key))

    def _extract_player_url(self, html):
        """var player_xxxx={"encrypt":0,"url":...} → 直链（encrypt=0 才返回）。"""
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
            obj = json.loads(html[start:end + 1].replace(r'\/', '/'))
        except Exception:
            return None
        if obj.get("encrypt") not in (0, "0", None):
            return None
        return obj.get("url")

    def playerContent(self, flag, id, vipFlags):
        hd = self._header_json()
        try:
            play_url = id if id.startswith("http") else (BASE_URL + id)
            html = self.fetch(play_url, headers=self._headers(), timeout=15).text
            url = self._extract_player_url(html)
            if not url:
                return {"parse": 1, "playUrl": "", "url": play_url, "header": hd}
            return {"parse": 0, "playUrl": "", "url": url, "header": hd}
        except Exception:
            return {"parse": 1, "playUrl": "", "url": id, "header": hd}

    def isVideoFormat(self, url):
        return any(url.lower().endswith(s) for s in (".m3u8", ".mp4", ".flv", ".ts"))

    def manualVideoCheck(self):
        pass

    def localProxy(self, param):
        # AD_MODE=off：直链返回，无需本地代理
        return [200, "video/MP2T", "", ""]


# 兼容按 module.Spider 类名加载的 TVBox 变体
Spider = ZkkmSpider


if __name__ == "__main__":
    s = ZkkmSpider()
    s.init()
    print("== home ==")
    print(json.dumps(s.homeContent(False), ensure_ascii=False)[:300])
    print("== homeVideo ==")
    hv = s.homeVideoContent()
    print("首页列表:", len(hv["list"]), "条；首条:",
          json.dumps(hv["list"][0], ensure_ascii=False) if hv["list"] else "N/A")
    print("== category ==")
    c = s.categoryContent("1", 1, False, {})
    print("分类电影: %d条 pagecount=%d；首条: %s" % (
        len(c["list"]), c["pagecount"],
        json.dumps(c["list"][0], ensure_ascii=False) if c["list"] else "N/A"))
    print("== detail ==")
    d = s.detailContent(["5"])
    v = d["list"][0]
    print("vod_name:", v.get("vod_name"), "| year:", v.get("vod_year"),
          "| remarks:", v.get("vod_remarks"))
    print("play_from:", v.get("vod_play_from"))
    print("源1前3集:", v.get("vod_play_url", "").split("$$$")[0].split("#")[:3])
    print("== search ==")
    q = s.searchContent("仙逆", False, "1")
    print("搜索'仙逆': %d条；首条: %s" % (
        len(q["list"]), json.dumps(q["list"][0], ensure_ascii=False) if q["list"] else "N/A"))
    print("== player ==")
    p = s.playerContent("player", "/html/5-1-1.html", "")
    print(json.dumps(p, ensure_ascii=False))
