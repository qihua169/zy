# coding: utf-8
"""
大师兄影视 (www.dsxys.me) —— TVBox / 猫影视 规范 Python 爬虫
============================================================
站点性质: 自定义 MacCMS (苹果CMS) 模板 ("大师兄影视" 主题 /mxtheme/)，前端 Cloudflare。
          全部页面为服务端渲染 HTML，无独立 JSON API，按 HTML 解析即可。

接口契约 (已逆向并实测验证):
  - 分类 / 列表 : GET /t/{tid}.html          (tid: 1=电影 2=剧集 3=综艺 4=动漫)
                 分页 /t/{tid}-{pg}.html  —— 注意: 本站服务端分页无效，
                 任意页码返回完全相同内容 (Cloudflare 缓存 + 前端 JS 分页)，
                 故 categoryContent 按单页返回 (pagecount=1)，诚实呈现站点现状。
  - 详情       : GET /dsx/{id}.html          含完整选集列表 + 年份/地区/类型/导演/主演
  - 选集       : 详情页 <a href="/video/{id}-{sid}-{nid}.html">  按 sid(线路) 分组
  - 播放解析   : GET /video/{id}-{sid}-{nid}.html
                 <script> var player_xxxx = {"flag":"play","encrypt":0,...,
                          "url":"https://.../index.m3u8","from":"源名",...};
                 encrypt:0 → 直链 m3u8，无需 jsdec。
  - 搜索       : GET /s/{kw}-------------.html   (关键词 URL 编码，后接 13 个短横，伪静态)

源名 (线路名, 如 ylzy / hnm3u8 / snm3u8) 不在详情页，须逐线路取一集播放页解析 player.from 获得。

部署: 继承 base.spider.Spider，网络统一走 self.fetch；本地 __main__ 用 urllib 自测。
"""
import json
import re
import ssl
import urllib.parse
import urllib.request

BASE = "https://www.dsxys.me"
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")
REFERER = BASE + "/"

# 一级分类: type_id -> type_name (对应 /t/{tid}.html)
CATEGORIES = [
    (1, "电影"),
    (2, "剧集"),
    (3, "综艺"),
    (4, "动漫"),
]
# 搜索伪静态短横数 (MacCMS 规则: /s/{kw}-------------.html)
SEARCH_DASHES = "-" * 13
# 详情页单线路最多追链的选集数 (安全上限，防异常死循环)
MAX_EPISODES_PER_SOURCE = 300


# --------------------------------------------------------------------------- #
# HTTP
# --------------------------------------------------------------------------- #
def _urllib_get(path, timeout=25):
    req = urllib.request.Request(BASE + path, headers=_http_header())
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    with urllib.request.urlopen(req, timeout=timeout, context=ctx) as r:
        return r.read().decode("utf-8", "ignore")


def _http_get(self, path, timeout=25):
    """TVBox 环境走 self.fetch，本地退化走 urllib。"""
    if hasattr(self, "fetch") and callable(self.fetch):
        return _norm(self.fetch(BASE + path, headers=_http_header(), timeout=timeout))
    return _urllib_get(path, timeout)


def _http_header():
    return {
        "User-Agent": UA,
        "Referer": REFERER,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "zh-CN,zh;q=0.9",
    }


def _norm(resp):
    """把 TVBox / 本地 urllib 各种 fetch 返回形态统一成字符串。

    TVBox 不同发布版 (CatVod / 猫影视 / 影视仓 ...) 的 self.fetch 返回值不一致:
      - str / bytes / Response 对象 (.text/.content/.get_text()) / 元组
    统一收敛成 utf-8 字符串; 任何无法识别的形态都返回 ""，由调用方 try/except 兜底，
    绝不能在此抛异常，否则 TVBox 会整源判不可用。
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
# HTML 解析工具
# --------------------------------------------------------------------------- #
def _parse_cards(html):
    """解析影片卡片 → [vod, ...]。同时兼容两类卡片:

    分类/首页 (module-poster-item):
      <a href="/dsx/{id}.html" title="{name}" class="module-poster-item module-item">
        ...<img data-original="{poster}" src="/loading.png" alt="{name}">
        <div class="module-poster-item-title">{name}</div>

    搜索结果 (module-card-item):
      <a href="/dsx/{id}.html" class="module-card-item-poster">
        ...<img data-original="{poster}" alt="{name}">
      </a><div class="module-card-item-title"><a ...><strong>{name}</strong></a></div>

    poster 在 data-original (懒加载)，兜底 src / data-src。
    """
    vods = []
    seen = set()
    for m in re.finditer(r'<a\b([^>]*)href="/dsx/(\d+)\.html"([^>]*)>', html):
        vid = m.group(2)
        open_tag = m.group(0)
        block = html[max(0, m.start() - 120): m.end() + 1600]
        # 片名: 1) 锚点自身 title 属性 2) *-title div 3) img alt
        name = ""
        mt = re.search(r'\stitle="([^"]*)"', open_tag)
        if mt:
            name = mt.group(1).strip()
        if not name:
            mx = re.search(
                r'class="[^"]*(?:card-item-title|poster-item-title)[^"]*"[^>]*>(.*?)</div>',
                block, re.S)
            if mx:
                name = re.sub(r"<[^>]+>", "", mx.group(1)).strip()
        if not name:
            ma = re.search(r'<img[^>]+alt="([^"]*)"', block)
            if ma:
                name = ma.group(1).strip()
        # 海报
        pic = ""
        mp = re.search(r'data-original="([^"]+)"', block)
        if mp:
            pic = mp.group(1).strip()
        else:
            ms = re.search(r'data-src="([^"]+)"', block)
            if ms:
                pic = ms.group(1).strip()
            else:
                mr = re.search(r'src="([^"]+)"', block)
                if mr and "/loading.png" not in mr.group(1):
                    pic = mr.group(1).strip()
        if pic and pic.startswith("/"):
            pic = BASE + pic
        if not name or vid in seen:
            continue
        seen.add(vid)
        vods.append({"vod_id": vid, "vod_name": name, "vod_pic": pic})
    return vods


def _extract_player(html):
    """括号平衡提取 var player_xxxx = {...}; 返回 (name, dict|None)。"""
    m = re.search(r'var\s+(player_\w+)\s*=\s*', html)
    if not m:
        return None, None
    i = m.end()
    if i >= len(html) or html[i] != "{":
        return m.group(1), None
    depth = 0
    for j in range(i, len(html)):
        c = html[j]
        if c == "{":
            depth += 1
        elif c == "}":
            depth -= 1
            if depth == 0:
                break
    if depth != 0:
        return m.group(1), None
    raw = html[i:j + 1]
    try:
        return m.group(1), json.loads(raw)
    except Exception:
        return m.group(1), None


def _clean_text(s):
    return re.sub(r"<[^>]+>", "", s or "").strip()


# --------------------------------------------------------------------------- #
# TVBox Spider
# --------------------------------------------------------------------------- #
try:
    from base.spider import Spider as _BaseSpider
except Exception:  # 本地独立运行 (无 base 模块) 时退化
    class _BaseSpider:
        pass


class DsxysSpider(_BaseSpider):

    def getName(self):
        return "大师兄影视"

    def init(self, extend=""):
        try:
            super().__init__()
        except Exception:
            pass

    # ----------------------------- 首页分类 ----------------------------- #
    def homeContent(self, filter_):
        classes = [{"type_id": str(tid), "type_name": name} for tid, name in CATEGORIES]
        return {"class": classes, "filters": {}}

    # --------------------------- 首页推荐流 ---------------------------- #
    def homeVideoContent(self):
        try:
            html = _http_get(self, "/")
            vods = _parse_cards(html)
            if not vods:  # 兜底: 取电影分类第一页
                return self.categoryContent("1", 1, False, {})
            return {"list": vods}
        except Exception:
            return {"list": []}

    # ----------------------------- 分类列表 ----------------------------- #
    def categoryContent(self, tid, pg, filter_, extend):
        try:
            html = _http_get(self, "/t/%s.html" % tid)
            vods = _parse_cards(html)
            # 服务端分页无效 (任意页码同内容)，按单页返回，诚实呈现。
            return {
                "list": vods,
                "page": int(pg or 1),
                "pagecount": 1,
                "limit": len(vods),
                "total": len(vods),
            }
        except Exception:
            return {"list": [], "page": int(pg or 1), "pagecount": 1,
                    "limit": 0, "total": 0}

    # ------------------------------ 搜索 ------------------------------- #
    def searchContent(self, key, quick, pg="1"):
        try:
            q = urllib.parse.quote(key or "")
            html = _http_get(self, "/s/%s%s.html" % (q, SEARCH_DASHES))
            vods = _parse_cards(html)
            return {"list": vods, "page": int(pg or 1), "pagecount": 1,
                    "limit": len(vods), "total": len(vods)}
        except Exception:
            return {"list": [], "page": int(pg or 1), "pagecount": 1,
                    "limit": 0, "total": 0}

    # ------------------------------ 详情 ------------------------------- #
    def detailContent(self, ids):
        try:
            vid = ids[0]
            html = _http_get(self, "/dsx/%s.html" % vid)
            vod = self._parse_detail(html, vid)
            return {"list": [vod]} if vod else {"list": []}
        except Exception:
            return {"list": []}

    def _parse_detail(self, html, vid):
        # 标题
        m = re.search(r'class="module-info-heading"[^>]*>\s*<h1>(.*?)</h1>', html, re.S)
        name = _clean_text(m.group(1)) if m else ""
        if not name:
            mt = re.search(r'<title>(.*?)</title>', html)
            name = _clean_text(mt.group(1)).split("-")[0] if mt else ""

        # 海报
        pic = ""
        mo = re.search(r'<meta[^>]+property="og:image"[^>]+content="([^"]+)"', html, re.I)
        if mo:
            pic = mo.group(1).strip()
        if not pic:
            md = re.search(r'data-original="([^"]+)"', html)
            if md:
                pic = md.group(1).strip()
                if pic.startswith("/"):
                    pic = BASE + pic

        # 年份 / 地区 / 类型 (module-info-tag-link 区块，按序)
        tag_blocks = re.findall(
            r'class="module-info-tag-link"[^>]*>(.*?)</div>', html, re.S)
        tag_texts = [_clean_text(b) for b in tag_blocks]
        year = tag_texts[0] if len(tag_texts) > 0 and re.search(r"\d{4}", tag_texts[0]) else ""
        area = tag_texts[1] if len(tag_texts) > 1 else ""
        vod_class = tag_texts[2] if len(tag_texts) > 2 else ""

        # 导演 / 主演 / 简介 (从 og:description 解析)
        desc = ""
        md2 = re.search(
            r'<meta[^>]+property="og:description"[^>]+content="([^"]*)"', html, re.I)
        if md2:
            desc = md2.group(1).strip()
        director = ""
        actor = ""
        if desc:
            dm = re.search(r"由(.+?)执导", desc)
            if dm:
                director = dm.group(1).strip()
            am = re.search(r"主演[:：](.+?)[。,，]", desc)
            if am:
                actor = am.group(1).strip()

        # 选集: 详情页含完整列表，按 sid(线路) 分组
        eps = re.findall(r'href="/video/%s-(\d+)-(\d+)\.html"' % re.escape(vid), html)
        sources = []          # [(sid, [nid,...])]
        order = []
        for sid, nid in eps:
            if sid not in order:
                order.append(sid)
                sources.append((sid, []))
            idx = order.index(sid)
            if nid not in sources[idx][1]:
                sources[idx][1].append(nid)

        if not sources:
            return None

        # 逐线路取首集播放页，得到真实源名 (from)
        play_from = []
        play_url_parts = []
        for sid, nids in sources:
            nids_sorted = sorted(set(int(x) for x in nids))
            from_name = "线路" + sid
            try:
                phtml = _http_get(self, "/video/%s-%s-%s.html" % (vid, sid, nids_sorted[0]))
                _, pobj = _extract_player(phtml)
                if isinstance(pobj, dict) and pobj.get("from"):
                    from_name = pobj["from"]
            except Exception:
                pass
            play_from.append(from_name)
            eps_str = "#".join(
                "第%s集$/video/%s-%s-%s.html" % (n, vid, sid, n)
                for n in nids_sorted
            )
            play_url_parts.append(eps_str)

        return {
            "vod_id": vid,
            "vod_name": name,
            "vod_pic": pic,
            "vod_year": year,
            "vod_area": area,
            "vod_class": vod_class,
            "vod_actor": actor,
            "vod_director": director,
            "vod_remarks": "",
            "vod_content": desc[:500],
            "vod_play_from": "$$$".join(play_from),
            "vod_play_url": "$$$".join(play_url_parts),
        }

    # ------------------------------ 播放 ------------------------------- #
    def playerContent(self, flag, id, vipFlags):
        try:
            # id 形如 /video/{vid}-{sid}-{nid}.html
            if id.startswith("http"):
                url_path = id
            else:
                url_path = id if id.startswith("/") else "/" + id
            html = _http_get(self, url_path)
            _, pobj = _extract_player(html)
            if not isinstance(pobj, dict):
                return {"parse": 0, "url": "", "header": json.dumps(_player_header())}
            url = pobj.get("url") or ""
            encrypt = pobj.get("encrypt", 0)
            if encrypt and encrypt != 0:
                # 本站实测均为 encrypt:0 直链；非 0 需 jsdec，此处无法解码，返回空。
                return {"parse": 1, "url": "", "header": json.dumps(_player_header())}
            if not url:
                return {"parse": 0, "url": "", "header": json.dumps(_player_header())}
            return {"parse": 0, "url": url, "header": json.dumps(_player_header())}
        except Exception:
            return {"parse": 0, "url": "", "header": json.dumps(_player_header())}

    # --------------------------- 工具 / 桩 ---------------------------- #
    def isVideoFormat(self, url):
        if not url:
            return False
        return url.split("?")[0].lower().endswith((".m3u8", ".mp4", ".flt", ".ts"))

    def manualVideoCheck(self, url):
        return False

    def localProxy(self, param):
        # 本站为直链 m3u8 (encrypt:0)，无需代理清洗
        return [200, "video/MP2T", "", ""]

    def destroy(self):
        pass


def _player_header():
    return {"User-Agent": UA, "Referer": REFERER}


# TVBox 按 module.Spider 类名加载的兼容别名
Spider = DsxysSpider


# --------------------------------------------------------------------------- #
# 本地自测 (urllib 模式, 无需 base 模块)
# --------------------------------------------------------------------------- #
if __name__ == "__main__":
    sp = DsxysSpider()
    print("=== getName ===", sp.getName())

    print("\n=== homeContent ===")
    hc = sp.homeContent(False)
    print("分类数:", len(hc.get("class", [])),
          [(c["type_id"], c["type_name"]) for c in hc.get("class", [])])

    print("\n=== homeVideoContent (首页推荐) ===")
    hv = sp.homeVideoContent()
    hvl = hv.get("list", [])
    print("返回条数:", len(hvl))
    if hvl:
        print("首条:", hvl[0]["vod_name"], "|", hvl[0]["vod_id"], "|", hvl[0]["vod_pic"][:60])

    print("\n=== categoryContent(1=电影,1) ===")
    cat = sp.categoryContent("1", 1, False, {})
    vl = cat.get("list", [])
    print("返回条数:", len(vl), " pagecount:", cat.get("pagecount"),
          " total:", cat.get("total"))
    if vl:
        print("首条:", vl[0]["vod_name"], "|", vl[0]["vod_id"], "|", vl[0]["vod_pic"][:60])

    print("\n=== detailContent (取电影首条) ===")
    if vl:
        did = vl[0]["vod_id"]
        det = sp.detailContent([did])
        d = det.get("list", [{}])[0]
        print("片名:", d.get("vod_name"), " 年份:", d.get("vod_year"),
              " 地区:", d.get("vod_area"), " 类型:", d.get("vod_class"))
        print("导演:", d.get("vod_director"), " 主演:", d.get("vod_actor")[:60])
        pfrom = d.get("vod_play_from", "").split("$$$")
        purl = d.get("vod_play_url", "").split("$$$")
        print("线路数:", len(pfrom), " play_from:", pfrom)
        for i, seg in enumerate(purl):
            print("  线路[%d] 选集数: %d" % (i, seg.count("#") + 1 if seg else 0))
        # 取第一集测试播放
        first_ep = purl[0].split("#")[0] if purl and purl[0] else ""
        ep_path = first_ep.split("$")[-1] if first_ep else ""
        print("\n=== playerContent (首集) ===")
        pc = sp.playerContent(pfrom[0] if pfrom else "", ep_path, "")
        print("parse:", pc.get("parse"), "url:", (pc.get("url") or "")[:140])

    print("\n=== searchContent(庆余年) ===")
    sres = sp.searchContent("庆余年", False, "1")
    sl = sres.get("list", [])
    print("返回条数:", len(sl), [v["vod_name"] for v in sl][:5])

    print("\n[说明] 分类服务端分页无效(固定单页)，已按 pagecount=1 返回;")
    print("      源名(from)经逐线路播放页解析获得; player encrypt:0 直链 m3u8。")
