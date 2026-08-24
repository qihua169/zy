# -*- coding: utf-8 -*-
"""
ruichenjiahe.com (ace影院) 影视爬虫
兼容 FongMi/TV (T3) 与 WebHomeTV / PeekPro (T4)

【已验证结构 - 真实抓取过】
    HOST         : https://www.ruichenjiahe.com
    分类         : /vodtype/{X}8888D.html
                   X = D=电影  G=连续剧  J=综艺  W=动漫  S=短剧
    分类分页     : /vodtype/D8888D-{N}.html  (N=1,2,3...)
    详情页       : /aceyingyuan/{id}.html
    播放页(分集): /aceyingyuanplay/{id}-{sid}-{nid}.html
                   sid=线路  nid=集数
    播放源       : player_aaaa JSON.url (m3u8)
    图片域名     : pic.ry-pic.com
    播放源域名   : svip.ryplay14.com
"""

import sys, os, re, time, json, logging
from urllib.parse import urlencode, quote

sys.path.append('..')

# ============================================================
# 文件日志
# ============================================================
try:
    _LOG_DIR = "/sdcard/Download/spider_logs"
    os.makedirs(_LOG_DIR, exist_ok=True)
except Exception:
    _LOG_DIR = "/tmp"
    try: os.makedirs(_LOG_DIR, exist_ok=True)
    except Exception: pass
_LOG_FILE = os.path.join(_LOG_DIR, "ruichenjiahe.log")

logging.basicConfig(
    level=logging.INFO,
    format='[%(asctime)s] %(levelname)s %(message)s',
    handlers=[
        logging.FileHandler(_LOG_FILE, encoding='utf-8'),
        logging.StreamHandler(),
    ],
)
log = logging.getLogger("spider.ruichenjiahe")


# ============================================================
# 兼容导入
# ============================================================
try:
    from base.spider import Spider
except ImportError:
    import requests as _rq
    try:
        import urllib3; urllib3.disable_warnings()
    except Exception: pass
    class Spider:                                       # noqa: F811
        def fetch(self, url, headers=None, data=None, **kw):
            t = kw.pop('timeout', 15)
            m = kw.pop('method', 'POST' if data else 'GET').upper()
            r = (_rq.post if m == 'POST' else _rq.get)(
                url, headers=headers, data=data, timeout=t,
                verify=False, **kw)
            r.encoding = r.apparent_encoding or 'utf-8'
            return r


# ============================================================
# 配置
# ============================================================
HOST = "https://www.ruichenjiahe.com"
SITE_NAME = "ace影院"
IMG_HOST = "https://pic.ry-pic.com"

# 真实分类 (字母代码 → 名称)
CLASSES = [
    {"type_name": "电影",   "type_id": "D"},
    {"type_name": "连续剧", "type_id": "G"},
    {"type_name": "动漫",   "type_id": "W"},
    {"type_name": "综艺",   "type_id": "J"},
    {"type_name": "短剧",   "type_id": "S"},
]

# ============================================================
# 常量
# ============================================================
PAGE_SIZE  = 36          # 一页 36 条 (已验证)
TIMEOUT    = 12
RETRY      = 3
RETRY_SLEEP = 0.4
CACHE_TTL  = 300
HOME_LIMIT = 72

UA = ("Mozilla/5.0 (Linux; Android 13; Pixel 7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/120.0.0.0 Mobile Safari/537.36")


# ============================================================
# 工具
# ============================================================
def unescape(s):
    if not s: return ""
    try:
        import html as _h
        return _h.unescape(s).strip()
    except Exception: return s.strip()


def build_filters():
    """分类筛选器: 排序"""
    return {c["type_id"]: [{
        "key": "by", "name": "排序",
        "value": [{"n": "最新", "v": "time"},
                  {"n": "人气", "v": "hits"}],
    }] for c in CLASSES}


# ============================================================
# 主类
# ============================================================
class Spider(Spider):                                   # noqa: F811

    def getName(self): return SITE_NAME

    def init(self, extend=""):
        self.extend = extend if isinstance(extend, str) else ""
        self.header = {
            "User-Agent":      UA,
            "Referer":         HOST + "/",
            "Accept":          "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
            "Accept-Language": "zh-CN,zh;q=0.9",
            "Accept-Encoding": "gzip, deflate, br",
            "Cache-Control":   "no-cache",
        }
        self._home_cache, self._home_cache_time = [], 0
        log.info("init HOST=%s LOG=%s", HOST, _LOG_FILE)

    def destroy(self): pass
    def close(self):   self.destroy()

    # ---- 网络底层 ----
    def _ok(self, rsp):
        # 兼容 requests (.status_code) 和 urllib (.status)
        code = getattr(rsp, "status_code", None)
        if code is None:
            code = getattr(rsp, "status", 0)
        try: return int(code) == 200
        except Exception: return False

    def _text(self, rsp):
        # 检测编码 (requests / urllib 都兼容)
        def _enc(r):
            try: return r.apparent_encoding or "utf-8"
            except Exception: pass
            try:
                ce = r.headers.get("Content-Type", "")
                if "charset=" in ce.lower():
                    return ce.lower().split("charset=")[-1].split(";")[0].strip()
            except Exception: pass
            return "utf-8"

        # 优先 requests 的 .text
        try:
            t = rsp.text
            if t: return t
        except Exception: pass
        # 其次 requests 的 .content (bytes)
        try:
            c = rsp.content
            if c:
                return c.decode(_enc(rsp), 'ignore')
        except Exception: pass
        # 最后 urllib 的 read(), 处理 gzip/deflate
        try:
            raw = rsp.read()
            if not raw: return ""
            enc = ""
            try:
                enc = (rsp.headers.get("Content-Encoding") or "").lower()
            except Exception: pass
            if "gzip" in enc or raw[:2] == b'\x1f\x8b':
                import gzip
                raw = gzip.decompress(raw)
            elif "deflate" in enc or (raw[:2] == b'\x78\x9c' and enc == ""):
                import zlib
                try: raw = zlib.decompress(raw)
                except Exception: pass
            return raw.decode(_enc(rsp), 'ignore')
        except Exception as e:
            log.debug("_text fail: %s", e)
            return ""

    def _get(self, url, referer=None, t=TIMEOUT):
        h = dict(self.header)
        if referer: h["Referer"] = referer
        try:
            r = self.fetch(url, headers=h, timeout=t)
            return self._text(r) if self._ok(r) else ""
        except Exception as e:
            log.debug("GET %s: %s", url, e); return ""

    def _abs(self, u):
        if not u: return ""
        u = u.replace("\\/", "/")
        if u.startswith("//"):  return "https:" + u
        if u.startswith("http"): return u
        if u.startswith("/"):    return HOST + u
        return HOST + "/" + u

    def _abs_img(self, u):
        if not u: return ""
        u = u.replace("\\/", "/")
        if u.startswith("//"):  return "https:" + u
        if u.startswith("http"): return u
        if u.startswith("/"):    return IMG_HOST + u
        return IMG_HOST + "/" + u

    def _hdr(self):
        return {"User-Agent": UA, "Referer": HOST + "/"}

    # ---- URL 构造 ----
    def _category_url(self, code, page=1):
        if page <= 1:
            return f"{HOST}/vodtype/{code}8888D.html"
        return f"{HOST}/vodtype/{code}8888D-{page}.html"

    def _detail_url(self, vid):
        return f"{HOST}/aceyingyuan/{vid}.html"

    def _play_url(self, vid, sid, nid):
        return f"{HOST}/aceyingyuanplay/{vid}-{sid}-{nid}.html"

    # ---- 列表解析 ----
    def _parse_list(self, html):
        """已验证的卡片结构:
        <a href="/aceyingyuan/{id}.html" title="{name}">
          <div class="movie-post-wrapper">
            <div class="movie-post-lazyload" data-original="{pic}">...</div>
            <div class="movie-item-score">{score}</div>
            <div class="movie-item-note">{note}</div>
          </div>
          <div class="movie-info">
            <div class="movie-title" title="{name}">{name}</div>
          </div>
        </a>
        """
        cards = []
        if not html: return cards
        # 用一个大正则抓所有卡片
        blk = re.findall(
            r'<a[^>]+href="(/aceyingyuan/(\d+)\.html)"[^>]+title="([^"]*)"[^>]*>.*?'
            r'data-original="([^"]+)"[^>]*>.*?'
            r'movie-item-note[^>]*>([^<]*)<',
            html, re.S)
        seen = set()
        for href, vid, name, pic, note in blk:
            if vid in seen: continue
            seen.add(vid)
            cards.append({
                "vod_id":      vid,
                "vod_name":    unescape(name),
                "vod_pic":     self._abs_img(pic),
                "vod_remarks": unescape(note) or "HD",
            })
        return cards

    def _max_page(self, html):
        """从分页器抓最大页码"""
        if not html: return 1
        # 找 /vodtype/{code}8888D-{N}.html 的所有 N
        nums = re.findall(r'/vodtype/[A-Z]8888D-(\d+)\.html', html)
        if nums:
            try: return max(int(n) for n in nums)
            except Exception: pass
        return 1

    # ---- 详情页解析 ----
    def _parse_detail(self, html, vid):
        """解析 /aceyingyuan/{id}.html, 拿到所有线路的所有集数"""
        if not html: return None
        try:
            # 标题
            name = ""
            for pat in [
                r'<h1[^>]*>([^<]+)</h1>',
                r'<title>([^<|-]+)',
            ]:
                m = re.search(pat, html)
                if m: name = unescape(m.group(1)); break
            if not name: return None

            # 海报
            pic = ""
            m = re.search(r'<div[^>]*class="[^"]*movie-post[^"]*"[^>]*>.*?data-original="([^"]+)"', html, re.S)
            if not m:
                m = re.search(r'<img[^>]+class="[^"]*movie-post[^"]*"[^>]+data-original="([^"]+)"', html, re.S)
            if not m:
                m = re.search(r'data-original="([^"]+)"', html)
            if m: pic = self._abs_img(unescape(m.group(1)))

            # 提取播放线路 + 集数
            # 直接全页找 aceyingyuanplay/{vid}-{sid}-{nid}.html, 按 sid 分组
            play_from = []  # ["线路一", "线路二", ...]
            play_url = []   # ["第01集$url#第02集$url...", ...]
            sid2eps = {}    # sid -> [(nid, label)]

            for href, sid, nid, lbl in re.findall(
                r'href="(/aceyingyuanplay/' + re.escape(vid) + r'-(\d+)-(\d+)\.html)"[^>]*>([^<]+)</a>',
                html):
                sid2eps.setdefault(sid, []).append((nid, unescape(lbl)))

            # 给线路一个友好名
            sid2name = {sid: f"线路{idx+1}" for idx, sid in enumerate(sorted(sid2eps.keys(), key=int))}
            for sid in sorted(sid2eps.keys(), key=int):
                eps = sid2eps[sid]
                if not eps: continue
                play_from.append(sid2name[sid])
                # 每集用占位 URL, 真正播放时 playerContent 才去取 m3u8
                play_url.append("#".join(f"{label}$/aceyingyuanplay/{vid}-{sid}-{nid}.html"
                                          for nid, label in eps))

            if not play_from:
                log.warning("详情 %s 没拿到播放线路", vid)
                return None

            # 简介/演员/导演
            director = unescape(re.search(r'导演[：:]\s*([^<\n]+)', html).group(1)) if re.search(r'导演[：:]\s*([^<\n]+)', html) else ""
            actor    = unescape(re.search(r'主演[：:]\s*([^<\n]+)', html).group(1)) if re.search(r'主演[：:]\s*([^<\n]+)', html) else ""
            year     = unescape(re.search(r'(\d{4})年', html).group(1)) if re.search(r'(\d{4})年', html) else ""
            content  = unescape(re.search(r'<meta[^>]+name="description"[^>]+content="([^"]+)"', html).group(1))[:500] \
                       if re.search(r'<meta[^>]+name="description"[^>]+content="([^"]+)"', html) else ""

            return {
                "vod_id":        vid,
                "vod_name":      name,
                "vod_pic":       pic,
                "type_name":     "",
                "vod_year":      year,
                "vod_area":      "",
                "vod_remarks":   year or "HD",
                "vod_actor":     actor,
                "vod_director":  director,
                "vod_content":   content,
                "vod_play_from": "$$$".join(play_from),
                "vod_play_url":  "$$$".join(play_url),
            }
        except Exception as e:
            log.warning("parse_detail %s: %s", vid, e)
            return None

    # ---- 播放页解析: 拿 m3u8 ----
    def _parse_play(self, html):
        """从 /aceyingyuanplay/{id}-{sid}-{nid}.html 拿 m3u8
        页面里有 var player_aaaa={...,"url":"...m3u8",...}
        直接抓 url 字段,避免被内嵌 } 截断
        """
        if not html: return ""
        # 方式 1: 完整解析 JSON
        m = re.search(r'var\s+player_aaaa\s*=\s*(\{.*?\}\s*\}?)\s*</script>', html, re.S)
        if m:
            try:
                data = json.loads(m.group(1))
                url = data.get("url", "")
                if url: return url
            except Exception: pass
        # 方式 2: 直接正则抓 "url":"...m3u8"
        m2 = re.search(r'"url"\s*:\s*"(https?://[^"]+\.m3u8[^"]*)"', html)
        if m2:
            return m2.group(1).replace("\\/", "/")
        return ""

    # ============================================================
    # 业务接口
    # ============================================================
    def homeContent(self, filter):
        return {
            "class":   [{"type_name": c["type_name"], "type_id": c["type_id"]}
                        for c in CLASSES],
            "filters": build_filters(),
        }

    def homeVideoContent(self):
        now = int(time.time())
        if self._home_cache and now - self._home_cache_time < CACHE_TTL:
            return {"list": self._home_cache[:HOME_LIMIT]}

        videos = []
        # 抓每个分类首页拼起来
        for c in CLASSES:
            try:
                html = self._get(self._category_url(c["type_id"], 1))
                cards = self._parse_list(html)
                videos.extend(cards)
                if len(videos) >= HOME_LIMIT: break
            except Exception as e:
                log.warning("home %s: %s", c["type_name"], e)

        self._home_cache = videos[:HOME_LIMIT]
        self._home_cache_time = now
        log.info("首页: %d 条", len(self._home_cache))
        return {"list": self._home_cache}

    def categoryContent(self, tid, pg, filter, extend):
        try:
            page = max(int(pg or 1), 1)
            # tid 是字母代码 (D/G/J/W/S), 已直接从 CLASSES 传来
            code = str(tid).upper()
            url = self._category_url(code, page)
            html = self._get(url, referer=HOST + "/")
            cards = self._parse_list(html)
            pagecount = self._max_page(html) if cards else 1
            log.info("分类 %s p%d: 拿到 %d 条, 共 %d 页",
                     code, page, len(cards), pagecount)
            return {
                "page": page, "pagecount": pagecount,
                "limit": PAGE_SIZE, "total": len(cards),
                "list": cards,
            }
        except Exception as e:
            log.warning("categoryContent: %s", e)
            return {"page": 1, "pagecount": 1, "limit": PAGE_SIZE,
                    "total": 0, "list": []}

    def detailContent(self, ids):
        if isinstance(ids, str): ids = [ids]
        vid = str(ids[0])
        for _ in range(RETRY):
            html = self._get(self._detail_url(vid), referer=HOST + "/")
            vod = self._parse_detail(html, vid)
            if vod: return {"list": [vod]}
            time.sleep(RETRY_SLEEP)
        return {"list": []}

    def searchContent(self, key, quick, pg="1"):
        """搜索 - 使用 MacCMS AJAX suggest 接口
        搜索页 /search.html 有滑动验证码, 但 AJAX suggest 接口可直接返回 JSON
        """
        try:
            if not key or not key.strip():
                return {"list": []}
            wd = key.strip()
            limit = 20
            url = (f"{HOST}/index.php/ajax/suggest"
                   f"?mid=1&wd={quote(wd)}&limit={limit}")
            text = self._get(url, referer=HOST + "/")
            if not text:
                log.warning("search empty response: wd=%s", wd)
                return {"list": []}
            data = json.loads(text)
            if data.get("code") != 1:
                log.warning("search code!=1: %s", data.get("msg", ""))
                return {"list": []}
            items = []
            for v in data.get("list", []):
                vid = str(v.get("id", ""))
                if not vid:
                    continue
                items.append({
                    "vod_id":      vid,
                    "vod_name":    unescape(v.get("name", "")),
                    "vod_pic":     self._abs_img(v.get("pic", "")),
                    "vod_remarks": "HD",
                })
            log.info("search wd=%s: %d 条", wd, len(items))
            return {"list": items}
        except Exception as e:
            log.warning("searchContent: %s", e)
            return {"list": []}

    def playerContent(self, flag, id, vipFlags):
        """id 形如: /aceyingyuanplay/{vid}-{sid}-{nid}.html
        真正去播放页拿 m3u8
        """
        raw = str(id or "").strip()
        # 兼容带 https:// 前缀的
        if raw.startswith("http"):
            # 直接当 m3u8
            return {"parse": 0, "playUrl": "", "url": raw, "header": self._hdr()}
        # 相对路径
        if not raw.startswith("/"):
            raw = "/" + raw
        url = self._abs(raw)

        # 访问播放页拿 m3u8
        html = self._get(url, referer=HOST + "/")
        m3u8 = self._parse_play(html)
        if m3u8:
            log.info("player %s -> m3u8 OK", url)
            return {"parse": 0, "playUrl": "", "url": m3u8, "header": self._hdr()}

        # 兜底: 把播放页 URL 交给嗅探器
        log.warning("player %s 拿不到 m3u8, 走嗅探", url)
        return {"parse": 1, "playUrl": "", "url": url, "header": self._hdr()}

    def localProxy(self, param):
        return [200, "video/MP2T", b"", ""]


# ============================================================
# CLI 自检
# ============================================================
if __name__ == "__main__":
    sp = Spider(); sp.init("")
    print("=" * 60)
    print(f"CLI 自检 - HOST={HOST}")
    print(f"日志: {_LOG_FILE}")
    print("=" * 60)

    print("\n[1/4] 分类页 (电影 D p1) ...")
    r = sp.categoryContent("D", 1, None, None)
    print(f"  page={r['page']} pagecount={r['pagecount']} total={r['total']}")
    for c in r["list"][:3]:
        print(f"  - {c['vod_name']}  ({c['vod_id']})  pic={c['vod_pic'][:60]}")

    if r["list"]:
        print("\n[2/4] 详情页 (第一个 vod_id) ...")
        r2 = sp.detailContent([r["list"][0]["vod_id"]])
        for v in r2["list"]:
            print(f"  标题: {v['vod_name']}")
            print(f"  海报: {v['vod_pic'][:80]}")
            print(f"  线路: {v['vod_play_from']}")
            print(f"  集数: {v['vod_play_url'][:200]}")

        if r2["list"]:
            print("\n[3/4] 播放页 (第一集) ...")
            # 从 play_url 抽第一集的 URL
            first_url = r2["list"][0]["vod_play_url"].split("#")[0].split("$")[-1]
            r3 = sp.playerContent("线路1", first_url, None)
            print(f"  url: {r3['url']}")
            print(f"  parse: {r3['parse']}")

    print("\n[4/4] 首页 ...")
    r4 = sp.homeVideoContent()
    print(f"  total: {len(r4['list'])}")
    for c in r4["list"][:3]:
        print(f"  - {c['vod_name']}  ({c['vod_id']})")

    print("\n完事。")
