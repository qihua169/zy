# coding: utf-8
"""
懂片帝AI (dongpian.ai) —— TVBox / 猫影视 规范 Python 爬虫
============================================================
站点性质: 自定义 React SPA (非 MacCMS)，所有数据走 JSON API，请求需 HMAC-SHA256 签名。

接口契约 (已逆向并实测验证):
  - 列表/分类 : GET /v1/browse/catalog?intent=latest_catalog[&kind={content_kind}]&page=&limit=
  - 详情       : GET /v1/catalog/{id}                (影片元数据)
                GET /v1/catalog/{id}/episodes?offset=&limit=60   (选集, 每集带 token)
  - 播放解析   : GET /v1/playback/resolve/{episodeToken}  -> line_options[]
                line.url_kind=="m3u8" & resolve_mode=="direct"  -> 直链 m3u8 (parse:0)
                line.url 为 "resolve://rpt1.<jwt>"             -> POST /v1/playback/resolve-line {"ticket":...} -> .line.url
  - 签名       : HMAC-SHA256(SECRET, "{METHOD}\\n{pathname}{search}\\n{timestamp}\\n{nonce}")
                头: x-ai-movie-timestamp / x-ai-movie-nonce / x-ai-movie-signature
                     + x-ai-movie-client-name / -client-version / -build-version / -protocol-version

注意: 该站"搜索"为 AI 助手式语义搜索(需会话流)，公开 catalog API 的 catalog_search 意图会忽略
      query 返回默认推荐流。本爬虫 searchContent 改用 /v1/suggest 联想接口: 按关键词返回片名
      匹配建议(每条带真实 catalog variant_id)，再逐条拉 /v1/catalog/{id} 组装卡片，可做到"按片名
      精确命中"。无片名匹配时退回 catalog_search 推荐流兜底。分类浏览/详情/播放均完全可用。

部署: 继承 base.spider.Spider，网络统一走 self.fetch；本地 __main__ 用 urllib 自测。
"""
import json
import re
import time
import hmac
import hashlib
import secrets
import urllib.parse
import urllib.request
import ssl

BASE = "https://dongpian.ai"
SECRET = "8b9a908a05eac640e1ee06f52acaa741bfe4ba9e004eeffdbeb635e532e06666"
CLIENT_NAME = "movie-search-frontend"
CLIENT_VERSION = "1.0.0"
BUILD_VERSION = "dongpiandi-v2026.09.08.3-6a4fbcaaef9f-web"
PROTOCOL_VERSION = "2026-07-05.library-v2.playback-v1"
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")
REFERER = BASE + "/"

# 一级分类: type_id -> type_name。kind 过滤走 browse/catalog 的 kind 参数。
# "latest" 为伪分类(最新上架, 不带 kind)。
CATEGORIES = [
    ("latest", "最新"),
    ("movie", "电影"),
    ("series", "剧集"),
    ("short_drama", "短剧"),
    ("anime", "动漫"),
    ("variety", "综艺"),
    ("documentary", "纪录片"),
    ("sports", "体育"),
    ("adult", "成人"),
]
PAGE_LIMIT = 30
SEARCH_LIMIT = 10   # 搜索最多返回的精确片名匹配数 (suggest 命中后逐条取详情组装)
PLAY_FROM = "懂片帝"

# m3u8 广告分片清洗配置
#   "proxy" = 通过 localProxy 清洗含广告分片的 m3u8 (推荐)
#   "off"   = 不清洗
AD_MODE = "proxy"
# 广告分片域名/路径特征: 39074 博彩赞助、常见广告目录/文件名
RE_AD_SEG = re.compile(
    r'39074|'
    r'/(?:adjump|advert|adss?|gg\d*|ad|ads|jump|vast|popunder|preroll|midroll|postroll)/|'
    r'(?:^|[-/_.])ad[-/_.]|'
    r'(?:^|[-/_.])gg[-/_.]', re.I)


# --------------------------------------------------------------------------- #
# 签名 + HTTP
# --------------------------------------------------------------------------- #
def _sign(path, method="GET"):
    """构造 dongpian.ai 所需的全套请求头(含 HMAC 签名)。path 需含 querystring。"""
    ts = str(int(time.time() * 1000))
    nonce = secrets.token_hex(16)
    msg = "%s\n%s\n%s\n%s" % (method.upper(), path, ts, nonce)
    sig = hmac.new(SECRET.encode("utf-8"), msg.encode("utf-8"),
                   hashlib.sha256).hexdigest()
    return {
        "User-Agent": UA,
        "Accept": "application/json, text/plain, */*",
        "Referer": REFERER,
        "Origin": BASE,
        "x-ai-movie-client-name": CLIENT_NAME,
        "x-ai-movie-client-version": CLIENT_VERSION,
        "x-ai-movie-build-version": BUILD_VERSION,
        "x-ai-movie-protocol-version": PROTOCOL_VERSION,
        "x-ai-movie-timestamp": ts,
        "x-ai-movie-nonce": nonce,
        "x-ai-movie-signature": sig,
    }


def _urllib_get(path, timeout=20):
    req = urllib.request.Request(BASE + path, headers=_sign(path))
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    with urllib.request.urlopen(req, timeout=timeout, context=ctx) as r:
        return r.read().decode("utf-8", "ignore")


def _urllib_post(path, body, timeout=20):
    headers = _sign(path, "POST")
    headers["Content-Type"] = "application/json"
    data = body if isinstance(body, bytes) else json.dumps(body).encode("utf-8")
    req = urllib.request.Request(BASE + path, headers=headers, data=data, method="POST")
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    with urllib.request.urlopen(req, timeout=timeout, context=ctx) as r:
        return r.read().decode("utf-8", "ignore")


def _http_get(self, path, timeout=20):
    """TVBox 环境走 self.fetch，本地退化走 urllib。"""
    if hasattr(self, "fetch") and callable(self.fetch):
        return _norm(self.fetch(BASE + path, headers=_sign(path), timeout=timeout))
    return _urllib_get(path, timeout)


def _http_post(self, path, body, timeout=20):
    if hasattr(self, "fetch") and callable(self.fetch):
        headers = _sign(path, "POST")
        headers["Content-Type"] = "application/json"
        data = body if isinstance(body, bytes) else json.dumps(body).encode("utf-8")
        return _norm(self.fetch(BASE + path, headers=headers, data=data, timeout=timeout))
    return _urllib_post(path, body, timeout)


def _norm(resp):
    """把 TVBox / 本地 urllib 各种 fetch 返回形态统一成字符串。

    TVBox 不同发布版 (CatVod / 猫影视 / 影视仓 ...) 的 self.fetch 返回值不一致:
      - str              (部分版本直接返回文本)
      - bytes            (原始字节)
      - Response 对象    (含 .text / .content / .get_text())
      - 元组            (如 (code, body) / (body, headers) / (body, headers, cookies))
    统一收敛成 utf-8 字符串; 任何无法识别的形态都返回 "", 由调用方 try/except 兜底
    —— 绝不能在此抛异常, 否则 TVBox 会整源判不可用 ("连列表都没有")。
    """
    if resp is None:
        return ""
    if isinstance(resp, str):
        return resp
    if isinstance(resp, (bytes, bytearray)):
        return resp.decode("utf-8", "ignore")
    if isinstance(resp, (tuple, list)):
        for x in resp:
            s = _norm(x)
            if s:
                return s
        return ""
    # 对象型响应: 优先取原始字节 (.content) 避免编码错乱, 再取 .text / get_text()
    for attr in ("content", "text", "string"):
        v = getattr(resp, attr, None)
        if isinstance(v, (bytes, bytearray)):
            return v.decode("utf-8", "ignore")
        if isinstance(v, str) and v:
            return v
        if callable(v):
            try:
                r = v()
            except Exception:
                r = None
            if isinstance(r, (bytes, bytearray)):
                return r.decode("utf-8", "ignore")
            if isinstance(r, str) and r:
                return r
    g = getattr(resp, "get_text", None)
    if callable(g):
        try:
            r = g()
        except Exception:
            r = None
        if isinstance(r, str) and r:
            return r
    return ""


# --------------------------------------------------------------------------- #
# TVBox Spider
# --------------------------------------------------------------------------- #
try:
    from base.spider import Spider as _BaseSpider
except Exception:  # 本地独立运行(无 base 模块)时退化
    class _BaseSpider:
        pass


class DongPianSpider(_BaseSpider):

    def getName(self):
        return "懂片帝AI"

    def init(self, extend=""):
        # 基类 __init__ 已建立 self.fetch；此处仅保持框架钩子，调用父类 init 即可。
        self._clean_cache = {}
        try:
            super().init(extend)
        except Exception:
            pass

    # ----------------------------- 首页分类 ----------------------------- #
    def homeContent(self, filter_):
        classes = [{"type_id": tid, "type_name": name} for tid, name in CATEGORIES]
        return {"class": classes, "filters": {}}

    # --------------------------- 首页推荐流 ---------------------------- #
    def homeVideoContent(self):
        return self._browse("latest", 1)

    # ----------------------------- 分类列表 ----------------------------- #
    def categoryContent(self, tid, pg, filter_, extend):
        return self._browse(tid, int(pg or 1))

    def _browse(self, tid, pg):
        try:
            if tid == "latest":
                path = "/v1/browse/catalog?intent=latest_catalog&page=%d&limit=%d" % (pg, PAGE_LIMIT)
            else:
                path = "/v1/browse/catalog?intent=latest_catalog&kind=%s&page=%d&limit=%d" % (
                    urllib.parse.quote(tid), pg, PAGE_LIMIT)
            data = json.loads(_http_get(self, path))
            cards = data.get("cards") or []
            vods = [self._card_to_vod(c) for c in cards]
            vods = [v for v in vods if v]
            pagecount = pg if len(cards) < PAGE_LIMIT else 999
            return {
                "list": vods,
                "page": pg,
                "pagecount": pagecount,
                "limit": PAGE_LIMIT,
                "total": pagecount * PAGE_LIMIT,
            }
        except Exception as e:
            return {"list": [], "page": pg, "pagecount": 1, "limit": PAGE_LIMIT, "total": 0}

    # ------------------------------ 搜索 ------------------------------- #
    def searchContent(self, key, quick, pg="1"):
        # 真实搜索是 AI 会话式(需会话流)，公开 catalog_search 会忽略 query 返回推荐流。
        # 改用 /v1/suggest 联想接口: 它按关键词返回片名匹配建议，每条带真实 catalog
        # variant_id，再逐条拉 /v1/catalog/{id} 组装卡片 —— 做到"按片名精确命中"。
        # 若没有任何片名匹配，则退回公开 catalog_search 推荐流兜底(原行为)。
        try:
            q = urllib.parse.quote(key or "")
            sug = json.loads(_http_get(self, "/v1/suggest?q=%s" % q))
            sugs = sug.get("suggestions") or []
            ids = []
            for s in sugs:
                if s.get("type") != "title":
                    continue
                vid = (s.get("target") or {}).get("variant_id")
                if vid and vid not in ids:
                    ids.append(vid)
                if len(ids) >= SEARCH_LIMIT:
                    break
            if ids:
                vods = []
                for vid in ids:
                    try:
                        det = json.loads(_http_get(self, "/v1/catalog/%s" % urllib.parse.quote(vid)))
                        vod = self._detail_to_vod(det)
                        if vod:
                            vods.append(vod)
                    except Exception:
                        continue
                if vods:
                    return {"list": vods, "page": 1, "pagecount": 1,
                            "limit": len(vods), "total": len(vods)}
            # 兜底: 退回公开 catalog_search 推荐流
            path = "/v1/browse/catalog?intent=catalog_search&query=%s&page=%d&limit=%d" % (
                q, int(pg or 1), PAGE_LIMIT)
            data = json.loads(_http_get(self, path))
            cards = data.get("cards") or []
            vods = [v for v in (self._card_to_vod(c) for c in cards) if v]
            return {"list": vods, "page": int(pg or 1), "pagecount": 999,
                    "limit": PAGE_LIMIT, "total": 999 * PAGE_LIMIT}
        except Exception:
            return {"list": [], "page": int(pg or 1), "pagecount": 1,
                    "limit": PAGE_LIMIT, "total": 0}

    # ------------------------------ 详情 ------------------------------- #
    def detailContent(self, ids):
        try:
            vid = ids[0]
            detail = json.loads(_http_get(self, "/v1/catalog/%s" % urllib.parse.quote(vid)))
            # 分页拉取全部选集
            episodes = []
            offset = 0
            while True:
                epath = "/v1/catalog/%s/episodes?offset=%d&limit=60" % (
                    urllib.parse.quote(vid), offset)
                edata = json.loads(_http_get(self, epath))
                eps = edata.get("episodes") or []
                episodes.extend(eps)
                pag = edata.get("episode_pagination") or {}
                if not pag.get("has_more") or len(eps) == 0:
                    break
                offset += len(eps)
                if offset >= (pag.get("total_count") or 0):
                    break

            play_url = "#".join(
                "%s$%s" % (self._ep_label(e), e.get("token", ""))
                for e in episodes if e.get("token")
            )

            vod = {
                "vod_id": vid,
                "vod_name": detail.get("title") or detail.get("normalized_title") or "",
                "vod_pic": detail.get("poster_url") or detail.get("carousel_url") or "",
                "vod_year": str(detail.get("year") or ""),
                "vod_area": detail.get("area") or "",
                "vod_lang": detail.get("language") or "",
                "vod_actor": " / ".join(detail.get("actors") or []),
                "vod_director": " / ".join(detail.get("directors") or []),
                "vod_class": " / ".join(detail.get("genres") or []),
                "vod_remarks": detail.get("remarks") or "",
                "vod_content": (detail.get("description") or detail.get("overview") or "")[:500],
                "vod_play_from": PLAY_FROM,
                "vod_play_url": play_url,
            }
            return {"list": [vod]}
        except Exception:
            return {"list": []}

    @staticmethod
    def _ep_label(e):
        t = (e.get("title") or "").strip()
        n = e.get("number")
        if t and t != str(n):
            return t
        return "第%s集" % n if n else (t or "正片")

    # ------------------------------ 播放 ------------------------------- #
    def playerContent(self, flag, id, vipFlags):
        try:
            url = self._resolve_episode(id)
            if not url:
                return {"parse": 0, "url": "", "header": json.dumps(_player_header())}
            # 仅对 m3u8 且开启清洗时处理; mp4/flv 直链直接放行。
            if AD_MODE == "proxy" and url.split("?")[0].lower().endswith(".m3u8"):
                try:
                    body = _fetch_m3u8_text(self, url)
                    # 主 m3u8 (含 #EXT-X-STREAM-INF) 直接放行, 只清洗媒体 playlist
                    if body and "#EXT-X-STREAM-INF" not in body:
                        cleaned, removed = _clean_playlist(body, url)
                        if removed:
                            key = "dp_%d" % len(self._clean_cache)
                            self._clean_cache[key] = cleaned
                            return {"parse": 0, "url": "local://" + key,
                                    "header": json.dumps(_player_header())}
                except Exception:
                    pass
            return {"parse": 0, "url": url, "header": json.dumps(_player_header())}
        except Exception:
            return {"parse": 0, "url": "", "header": json.dumps(_player_header())}

    def _resolve_episode(self, token):
        """解析单集播放地址: 优先直链 m3u8，否则解析 resolve 票据。"""
        if not token:
            return None
        resolve = json.loads(_http_get(self, "/v1/playback/resolve/%s" % urllib.parse.quote(token)))
        lines = resolve.get("line_options") or []
        if not lines:
            return None
        # 1) 优先直链 m3u8
        for L in lines:
            if L.get("url_kind") == "m3u8" and L.get("resolve_mode") == "direct":
                return L.get("url")
        # 2) 解析票据 (resolve://rpt1.<jwt>)
        for L in lines:
            url = L.get("url") or ""
            if url.startswith("resolve://"):
                ticket = url[len("resolve://"):]
                resolved = self._resolve_ticket(ticket)
                if resolved:
                    return resolved
        # 3) 兜底: 任意 http(s) 直链
        for L in lines:
            url = L.get("url") or ""
            if url.startswith("http"):
                return url
        return None

    def _resolve_ticket(self, ticket):
        try:
            data = json.loads(_http_post(self, "/v1/playback/resolve-line",
                                         {"ticket": ticket}))
            line = data.get("line") or {}
            return line.get("url")
        except Exception:
            return None

    # --------------------------- 工具 / 桩 ---------------------------- #
    def isVideoFormat(self, url):
        if not url:
            return False
        return url.split("?")[0].lower().endswith((".m3u8", ".mp4", ".flv", ".ts"))

    def manualVideoCheck(self, url):
        return False

    def localProxy(self, param):
        body = self._clean_cache.get(param, "")
        if not body:
            return [200, "video/MP2T", "", ""]
        return [200, "application/vnd.apple.mpegurl", body.encode("utf-8"), ""]

    def destroy(self):
        pass

    # --------------------------- 卡片 -> vod -------------------------- #
    @staticmethod
    def _card_to_vod(c):
        if not c or not c.get("id"):
            return None
        return {
            "vod_id": c.get("id"),
            "vod_name": c.get("title") or c.get("normalized_title") or "",
            "vod_pic": c.get("poster_url") or c.get("carousel_url") or "",
            "vod_remarks": c.get("remarks") or "",
            "vod_year": str(c.get("year") or ""),
            "vod_area": c.get("area") or "",
            "vod_actor": " / ".join(c.get("actors") or [])[:120],
            "vod_class": " / ".join(c.get("genres") or [])[:80],
        }

    @staticmethod
    def _detail_to_vod(d):
        """由 /v1/catalog/{id} 详情直接构造列表卡片(搜索结果用，不含选集)。"""
        if not d or not d.get("id"):
            return None
        return {
            "vod_id": d.get("id"),
            "vod_name": d.get("title") or d.get("normalized_title") or "",
            "vod_pic": d.get("poster_url") or d.get("carousel_url") or "",
            "vod_remarks": d.get("remarks") or "",
            "vod_year": str(d.get("year") or ""),
            "vod_area": d.get("area") or "",
            "vod_actor": " / ".join(d.get("actors") or [])[:120],
            "vod_class": " / ".join(d.get("genres") or [])[:80],
        }


def _fetch_m3u8_text(self, url, timeout=15):
    """取 m3u8 文本; TVBox 走 self.fetch, 本地退化走 urllib。"""
    if hasattr(self, "fetch") and callable(self.fetch):
        return _norm(self.fetch(url, headers=_player_header(), timeout=timeout))
    req = urllib.request.Request(url, headers=_player_header())
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    with urllib.request.urlopen(req, timeout=timeout, context=ctx) as r:
        return r.read().decode("utf-8", "ignore")


def _clean_playlist(body, base_url):
    """清洗 m3u8 中的广告分片, 相对路径按 base_url 目录绝对化。

    - 广告分片按 RE_AD_SEG 匹配(39074/广告目录/广告文件名特征)剔除
    - 同时剔除与广告分片对应的 #EXTINF 行
    - #EXT-X-KEY URI 如果是相对路径则绝对化
    """
    if not body:
        return body, 0
    base_dir = base_url.rsplit("/", 1)[0] + "/"
    out, removed = [], 0
    pending_extinf = None
    for line in body.splitlines():
        s = line.strip()
        if not s:
            continue
        if s.startswith("#"):
            if s.startswith("#EXTINF"):
                if pending_extinf is not None:
                    out.append(pending_extinf)
                pending_extinf = s
            else:
                if "#EXT-X-KEY" in s and 'URI="' in s:
                    m = re.search(r'URI="([^"]+)"', s)
                    if m and not m.group(1).startswith("http"):
                        s = s.replace(m.group(1), base_dir + m.group(1).lstrip("/"))
                out.append(s)
            continue
        if RE_AD_SEG.search(s):
            removed += 1
            pending_extinf = None
            continue
        if pending_extinf is not None:
            out.append(pending_extinf)
            pending_extinf = None
        out.append(s if s.startswith("http") else base_dir + s.lstrip("/"))
    if pending_extinf is not None:
        out.append(pending_extinf)
    return "\n".join(out), removed


def _player_header():
    return {"User-Agent": UA, "Referer": REFERER, "Origin": BASE}


# TVBox 按 module.Spider 类名加载的兼容别名
Spider = DongPianSpider


# --------------------------------------------------------------------------- #
# 本地自测 (urllib 模式, 无需 base 模块)
# --------------------------------------------------------------------------- #
if __name__ == "__main__":
    sp = DongPianSpider()
    print("=== getName ===", sp.getName())

    print("\n=== homeContent ===")
    hc = sp.homeContent(False)
    print("分类数:", len(hc.get("class", [])),
          [c["type_name"] for c in hc.get("class", [])][:9])

    print("\n=== categoryContent(movie,1) ===")
    cat = sp.categoryContent("movie", 1, "", {})
    vl = cat.get("list", [])
    print("返回条数:", len(vl), " pagecount:", cat.get("pagecount"))
    if vl:
        print("首条:", vl[0]["vod_name"], "|", vl[0]["vod_remarks"], "|", vl[0]["vod_id"])

    print("\n=== detailContent(首条) ===")
    if vl:
        did = vl[0]["vod_id"]
        det = sp.detailContent([did])
        d = det.get("list", [{}])[0]
        print("片名:", d.get("vod_name"), " 年份:", d.get("vod_year"),
              " 地区:", d.get("vod_area"))
        print("选集数:", d.get("vod_play_url").count("#") + 1 if d.get("vod_play_url") else 0)
        print("play_from:", d.get("vod_play_from"))
        # 取第一集 token 测试播放
        first_ep = d.get("vod_play_url", "").split("#")[0]
        token = first_ep.split("$")[-1] if first_ep else ""
        print("\n=== playerContent(首集 token) ===")
        pc = sp.playerContent("懂片帝", token, "")
        print("parse:", pc.get("parse"), "url:", (pc.get("url") or "")[:160])

    print("\n=== searchContent(庆余年) ===")
    sres = sp.searchContent("庆余年", False, "1")
    print("返回条数:", len(sres.get("list", [])),
          [v["vod_name"] for v in sres.get("list", [])][:3])
    print("\n[说明] 搜索走 /v1/suggest 联想接口按片名精确命中; 无片名匹配时退回推荐流兜底。")
 0