# -*- coding: utf-8 -*-
"""
TVBox / 猫影视 Spider —— 骚火电影 (shdy2.com)
==============================================
站点特征（逆向结论，2026-08）：
  - 自研模板，非 MacCMS 默认路由：
      首页   https://shdy2.com/
      分类   /list/{tid}.html        分页 /list/{tid}-{pg}.html    （如 /list/1-2.html）
      详情   /movie/{id}.html
      选集   多播放源 tab「线路1 / 线路2」；每集 /play/{id}-{sid}-{nid}.html
      搜索   GET /s----------.html?wd={kw}      （来自搜索表单 action）
  - 播放页不内嵌直链，而是 iframe 到第三方播放器：
      <iframe src="https://hhjx.hhplayer.com/?url=<HEX>">
    iframe 页内 __HHJX_BOOTSTRAP__ = {url, t, key, ts_key}
    前端 JS 把 {url, t, key} POST 给 https://hhjx.hhplayer.com/api/parse
    服务端返回真实 m3u8：{"code":200,"url":".../playlist/<hash>.m3u8?expires=&sign=","ext":""}
    - ext==""      -> 直链 m3u8   （parse:0）
    - ext=="hls_rewrite" -> 经 /getts?url=..&t=..&key=ts_key 代理（parse:0）
    - ext=="youku" -> 需浏览器解析，交给框架（parse:1）
  - 实测 m3u8 为 media playlist，分片为 p.ananas.chaoxing.com 的 HTTPS 绝对地址，
    无广告分片 -> AD_MODE="off"，不启用 localProxy 清洗。
  - 源站 + Cloudflare 间歇 522（连接超时），故所有请求加重试退避。

部署规范（遵守 references/spider_tvbox_deploy.py）：
  1. 继承 base.spider.Spider；网络统一走 self.fetch（POST 用 data=）。
  2. init(extend="") 极简（仅置常量）。
  3. playerContent 的 header 字段为 json.dumps(dict) 字符串。
  4. 所有接口 try/except 兜底返回合法结构，异常不外抛。
  5. 模块级别名 Spider = ShaHuoSpider。
  6. isVideoFormat / manualVideoCheck / localProxy 提供 stub。

本地调试：PC 端无 base.spider 时，下方 _TVBase 桩用 urllib 实现 fetch/post（含 data=POST 支持），
保证 `python sp_shdy2_tvbox.py` 直接跑 __main__ 自检；TVBox 环境走基类真实实现。
"""

import re
import json
import html

try:
    from base.spider import Spider as _TVBase
except Exception:
    # ── 本地调试桩（PC 端无 base.spider）：urllib 实现 fetch/post，支持 data=POST ──
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

                def json(self):
                    return json.loads(self.text)
            return _R()

        def fetch(self, url, headers=None, timeout=15, data=None):
            from urllib.request import Request, urlopen
            method = "POST" if data is not None else "GET"
            body = None
            if data is not None:
                body = data.encode() if isinstance(data, str) else data
                if isinstance(data, (dict, list)):
                    from urllib.parse import urlencode
                    body = urlencode(data).encode()
            r = urlopen(Request(url, data=body, headers=headers or {},
                                method=method), timeout=timeout)
            return self._resp(r.read())

        def post(self, url, data=None, headers=None, timeout=15):
            from urllib.request import Request, urlopen
            from urllib.parse import urlencode
            if isinstance(data, (dict, list)):
                body = urlencode(data).encode()
            elif data is None:
                body = b""
            else:
                body = data.encode() if isinstance(data, str) else data
            r = urlopen(Request(url, data=body, headers=headers or {},
                                method="POST"), timeout=timeout)
            return self._resp(r.read())
    # ── 桩结束 ──


# ═══════════ 站点配置 ═══════════
SITE_NAME = "骚火电影"
BASE_URL = "https://shdy2.com"
PLAYER_BASE = "https://hhjx.hhplayer.com"
UA = ("Mozilla/5.0 (Linux; Android 12; Pixel 5) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/125.0.0.0 Mobile Safari/537.36")
API_PARSE = PLAYER_BASE + "/api/parse"

# 一级分类（站点真实顶层：电影/电视剧）
# 参考加菲猫影视.py 两级分类范式：CATE(一级) + SUB_CATE(二级类型筛选) + filters
CATE = [
    {"type_id": "1", "type_name": "电影"},
    {"type_id": "2", "type_name": "电视剧"},
]
# 二级类型筛选：genre 即独立 /list/{tid}.html 页，切换 tid 即筛选
# （骚火电影分类栏为扁平 genre 列表，故电影/电视剧下挂载同一套 genre）
GENRE = [
    {"n": "全部", "v": ""},
    {"n": "喜剧", "v": "6"}, {"n": "爱情", "v": "7"}, {"n": "恐怖", "v": "8"},
    {"n": "动作", "v": "9"}, {"n": "科幻", "v": "10"}, {"n": "战争", "v": "11"},
    {"n": "犯罪", "v": "12"}, {"n": "奇幻", "v": "14"}, {"n": "剧情", "v": "15"},
    {"n": "冒险", "v": "16"}, {"n": "悬疑", "v": "17"}, {"n": "惊悚", "v": "18"},
    {"n": "其它", "v": "19"},
]
SUB_CATE = {"1": list(GENRE), "2": list(GENRE)}

AD_MODE = "off"  # m3u8 无广告分片，不清洗

# ═══════════ 正则 ═══════════
RE_CARD = re.compile(
    r'<div class="v_img">\s*<a href="/movie/(\d+)\.html"[^>]*title="([^"]*)"[^>]*>'
    r'<img[^>]*?data-original="([^"]*)"[^>]*>\s*</a>'
    r'<div class="v_note">([^<]*)</div>', re.S | re.I)
RE_DETAIL_NAME = re.compile(r'<h1 class="v_title"><a[^>]*>([^<]+)</a>', re.S | re.I)
RE_DETAIL_META = re.compile(r'<h1 class="v_title">.*?</h1>\s*<p>(.*?)</p>', re.S | re.I)
RE_DETAIL_PIC = re.compile(r'data-original="([^"]+)"', re.I)
RE_CONTENT = re.compile(r'id="info_more"[^>]*>.*?<p[^>]*>(.*?)</p>', re.S | re.I)
RE_FROM = re.compile(r'class="from_list"[^>]*>(.*?)</ul>', re.S | re.I)
RE_FROM_ITEM = re.compile(r'<li[^>]*>(.*?)</', re.S | re.I)
RE_EP = re.compile(r'href="/play/(\d+)-(\d+)-(\d+)\.html"[^>]*>([^<]*)</a>', re.S | re.I)
RE_PAGE = re.compile(r'class="page"[^>]*>.*?<span>(\d+)/(\d+)</span>', re.S | re.I)
RE_IFRAME = re.compile(r'hhjx\.hhplayer\.com/\?url=([0-9A-Fa-f]+)', re.I)
RE_BOOT = re.compile(r'__HHJX_BOOTSTRAP__\s*=\s*(\{.*?\});', re.S)


def _clean(s):
    if not s:
        return ""
    s = re.sub(r'<[^>]+>', '', s)
    s = s.replace("&nbsp;", " ").replace("\u3000", " ").replace("&amp;", "&")
    return html.unescape(re.sub(r'\s+', ' ', s).strip())


def _parse_meta(meta):
    """解析详情 meta 行：'大陆 / 2026 / 剧情 / 导演:邓科 / 主演:丁禹兮...'
    返回 (area, year, cls, director, actor)。"""
    area = year = cls = director = actor = ""
    if not meta:
        return area, year, cls, director, actor
    parts = [p.strip() for p in meta.split("/")]
    # 前几段为 地区/年份/类型（可能缺）
    nums = [p for p in parts if re.fullmatch(r'\d{4}', p)]
    if nums:
        year = nums[0]
    # 地区 / 类型：非年份、非 导演/主演 的段
    others = [p for p in parts if p and p != year]
    # 去掉 导演/主演 段
    info = [p for p in others if not p.startswith(("导演", "主演"))]
    if len(info) >= 1:
        area = info[0]
    if len(info) >= 2:
        cls = info[1]
    for p in parts:
        if p.startswith("导演:"):
            director = p[3:].strip()
        elif p.startswith("主演:"):
            actor = p[3:].strip()
    return area, year, cls, director, actor


class ShaHuoSpider(_TVBase):

    def getName(self):
        return SITE_NAME

    def init(self, extend=""):
        # 极简：让基类 __init__ 自然初始化；无额外 session 状态
        pass

    # ── 网络（带重试退避，对抗 522 抖动）──
    def _headers(self, ref=None):
        h = {"User-Agent": UA, "Accept": "*/*", "Accept-Language": "zh-CN,zh;q=0.9"}
        if ref:
            h["Referer"] = ref
        return h

    def _header_json(self, ref=None):
        h = {"User-Agent": UA, "Referer": ref or (BASE_URL + "/")}
        return json.dumps(h)

    def _text(self, rsp):
        if rsp is None:
            return ""
        if hasattr(rsp, "text"):
            return rsp.text or ""
        return str(rsp)

    def _get(self, url, ref=None, tries=3):
        h = self._headers(ref or BASE_URL + "/")
        for i in range(tries):
            try:
                rsp = self.fetch(url, headers=h, timeout=15)
                t = self._text(rsp)
                if t and "error code: 522" not in t[:64]:
                    return t
            except Exception:
                pass
            if i < tries - 1:
                import time
                time.sleep(1.5 * (i + 1))
        return ""

    def _post_json(self, url, payload, headers):
        data = json.dumps(payload).encode("utf-8")
        h = dict(headers)
        h["Content-Type"] = "application/json"
        for i in range(3):
            try:
                rsp = self.fetch(url, headers=h, timeout=15, data=data)
                return self._text(rsp)
            except TypeError:
                # 本地桩无 data 支持时回退 post
                try:
                    rsp = self.post(url, data=payload, headers=h, timeout=15)
                    return self._text(rsp)
                except Exception:
                    return ""
            except Exception:
                pass
            if i < 2:
                import time
                time.sleep(1.5 * (i + 1))
        return ""

    # ── 解析钩子 ──
    def _parse_list(self, html):
        items = []
        for vid, name, pic, remark in RE_CARD.findall(html or ""):
            items.append({
                "vod_id": vid,
                "vod_name": _clean(name),
                "vod_pic": pic.strip(),
                "vod_remarks": _clean(remark),
            })
        return items

    def _pagecount(self, html):
        m = RE_PAGE.search(html or "")
        if m:
            try:
                return max(int(m.group(1)), int(m.group(2)))
            except Exception:
                pass
        # 兜底：尝试宽松的 N/M 形态
        mm = re.search(r'(\d+)/(\d+)', html or "")
        if mm:
            try:
                return max(int(mm.group(1)), int(mm.group(2)))
            except Exception:
                pass
        return 1

    def _detail(self, vid, html):
        name_m = RE_DETAIL_NAME.search(html or "")
        name = _clean(name_m.group(1)) if name_m else vid
        meta_m = RE_DETAIL_META.search(html or "")
        area, year, cls, director, actor = _parse_meta(_clean(meta_m.group(1)) if meta_m else "")
        pics = RE_DETAIL_PIC.findall(html or "")
        pic = pics[0].strip() if pics else ""
        cont_m = RE_CONTENT.search(html or "")
        content = _clean(cont_m.group(1)) if cont_m else ""
        # 播放源名映射
        names = ["线路%s" % (i + 1) for i in range(8)]
        fm = RE_FROM.search(html or "")
        if fm:
            items = [c.strip() for c in RE_FROM_ITEM.findall(fm.group(1)) if c.strip()]
            if items:
                names = items + names[len(items):]
        # 选集按 sid 分组（按 nid 去重，规避详情页顶部「海报立即播放」与列表重复）
        groups = {}
        seen = {}
        for _vid, sid, _nid, ep in RE_EP.findall(html or ""):
            seen.setdefault(sid, set())
            if _nid in seen[sid]:
                continue
            seen[sid].add(_nid)
            ep_name = _clean(ep) or _nid
            groups.setdefault(sid, []).append("%s$/play/%s-%s-%s.html" % (ep_name, vid, sid, _nid))
        vod = {
            "vod_id": vid,
            "vod_name": name,
            "vod_pic": pic,
            "vod_year": year,
            "vod_area": area,
            "vod_class": cls,
            "vod_director": director,
            "vod_actor": actor,
            "vod_content": content,
            "vod_remarks": "",
        }
        if groups:
            sids = sorted(groups.keys(), key=lambda x: int(x))
            vod["vod_play_from"] = "$$$".join(names[int(s) - 1] if (int(s) - 1) < len(names) else ("线路" + s) for s in sids)
            vod["vod_play_url"] = "$$$".join("#".join(groups[s]) for s in sids)
        return vod

    # ── TVBox 接口 ──
    def homeContent(self, filter):
        # 顶层分类：优先取首页导航真实分类，否则用 CATE 兜底
        classes = list(CATE)
        try:
            html = self._get(BASE_URL + "/")
            seen, parsed = set(), []
            for tid, name in re.findall(r'href="/list/(\d+)\.html"[^>]*>([^<]+)</a>', html):
                if tid in seen:
                    continue
                seen.add(tid)
                parsed.append({"type_id": tid, "type_name": name.strip()})
            if len(parsed) >= 2:
                classes = parsed
        except Exception:
            pass
        # filter=True 时生成两级筛选：类型（genre 即独立 /list/{tid} 页）
        if filter:
            filters = {}
            for c in classes:
                cid = c["type_id"]
                flist = []
                if cid in SUB_CATE:
                    flist.append({"key": "type", "name": "类型", "value": SUB_CATE[cid]})
                if flist:
                    filters[cid] = flist
            return {"class": classes, "filters": filters}
        return {"class": classes, "filters": {}}

    def homeVideoContent(self):
        try:
            html = self._get(BASE_URL + "/")
            return {"list": self._parse_list(html)}
        except Exception:
            return {"list": []}

    def categoryContent(self, tid, pg, filter, extend):
        page = int(pg) if pg else 1
        # 类型筛选：切换为二级 tid（genre 即独立 /list/{tid}.html 页）
        real_tid = tid
        if extend:
            sub = extend.get("type", "")
            if sub:
                real_tid = sub
        try:
            url = "%s/list/%s.html" % (BASE_URL, real_tid) if page <= 1 else "%s/list/%s-%s.html" % (BASE_URL, real_tid, page)
            html = self._get(url)
            items = self._parse_list(html)
            return {"list": items, "page": page,
                    "pagecount": self._pagecount(html), "limit": 30, "total": len(items)}
        except Exception:
            return {"list": [], "page": page, "pagecount": 1, "limit": 30, "total": 0}

    def detailContent(self, ids):
        try:
            vid = str(ids[0]) if ids else ""
            html = self._get("%s/movie/%s.html" % (BASE_URL, vid))
            return {"list": [self._detail(vid, html)]}
        except Exception as e:
            vid = str(ids[0]) if ids else ""
            return {"list": [{"vod_id": vid, "vod_name": "解析异常",
                              "vod_content": str(e)[:200]}]}

    def searchContent(self, key, quick, pg="1"):
        page = int(pg) if pg else 1
        try:
            from urllib.parse import quote
            url = "%s/s----------.html?wd=%s" % (BASE_URL, quote(key))
            html = self._get(url, ref=BASE_URL + "/")
            items = self._parse_list(html)
            return {"list": items, "page": page,
                    "pagecount": self._pagecount(html), "limit": 20, "total": len(items)}
        except Exception:
            return {"list": [], "page": page, "pagecount": 1, "limit": 20, "total": 0}

    def playerContent(self, flag, id, vipFlags):
        hd = self._header_json(PLAYER_BASE + "/")
        try:
            play_url = id if id.startswith("http") else (BASE_URL + id)
            html = self._get(play_url, ref=BASE_URL + "/")
            if not html:
                return {"parse": 1, "playUrl": "", "url": play_url, "header": hd}
            # 1) 取 iframe 中加密 hex
            m = RE_IFRAME.search(html)
            if not m:
                return {"parse": 1, "playUrl": "", "url": play_url, "header": hd}
            enc = m.group(1)
            # 2) 取 iframe 页 bootstrap（含 t / key / ts_key）
            boot_html = self._get(PLAYER_BASE + "/?url=" + enc, ref=BASE_URL + "/")
            bm = RE_BOOT.search(boot_html or "")
            if not bm:
                return {"parse": 1, "playUrl": "", "url": play_url, "header": hd}
            boot = json.loads(bm.group(1))
            # 3) POST /api/parse 拿真实 m3u8
            payload = {"url": boot.get("url", enc), "t": boot.get("t", 0),
                       "key": boot.get("key", ""), "client_fallback": False}
            api_hd = self._headers(PLAYER_BASE + "/")
            api_hd["Origin"] = PLAYER_BASE
            api_hd["Referer"] = PLAYER_BASE + "/"
            body = self._post_json(API_PARSE, payload, api_hd)
            if not body:
                return {"parse": 1, "playUrl": "", "url": play_url, "header": hd}
            try:
                resp = json.loads(body)
            except Exception:
                return {"parse": 1, "playUrl": "", "url": play_url, "header": hd}
            if resp.get("code") != 200 or not resp.get("url"):
                return {"parse": 1, "playUrl": "", "url": play_url, "header": hd}
            m3u8 = resp["url"]
            ext = resp.get("ext") or ""
            if ext == "youku":
                # 需浏览器解析，交给框架
                return {"parse": 1, "playUrl": "", "url": m3u8, "header": hd}
            if ext == "hls_rewrite":
                # 经播放器 CDN 代理重写分片
                gt = "%s/getts?%s" % (PLAYER_BASE, _urlencode([
                    ("url", m3u8), ("t", str(boot.get("t", ""))),
                    ("key", boot.get("ts_key", ""))]))
                return {"parse": 0, "playUrl": "", "url": gt, "header": hd}
            # 直链 m3u8
            return {"parse": 0, "playUrl": "", "url": m3u8, "header": hd}
        except Exception:
            return {"parse": 1, "playUrl": "", "url": id, "header": hd}

    def isVideoFormat(self, url):
        return any((url or "").lower().endswith(s) for s in (".m3u8", ".mp4", ".flv", ".ts"))

    def manualVideoCheck(self):
        pass

    def localProxy(self, param):
        # AD_MODE=off，无广告清洗，返回空桩
        return [200, "video/MP2T", "", ""]


def _urlencode(pairs):
    from urllib.parse import urlencode
    return urlencode(pairs)


# 兼容按 module.Spider 类名加载的 TVBox 变体
Spider = ShaHuoSpider


if __name__ == "__main__":
    s = ShaHuoSpider()
    s.init()
    print("== homeContent ==")
    hc = s.homeContent(False)
    print("classes:", len(hc.get("class", [])), hc.get("class", [])[:3])
    print("== homeVideoContent ==")
    hv = s.homeVideoContent()
    print("home list:", len(hv.get("list", [])), hv.get("list", [])[:1])
    print("== categoryContent (tid=1, pg=1) ==")
    cc = s.categoryContent("1", "1", False, {})
    print("list:", len(cc.get("list", [])), "pagecount:", cc.get("pagecount"),
          cc.get("list", [])[:1])
    print("== detailContent (id=50298) ==")
    dc = s.detailContent(["50298"])
    d0 = dc.get("list", [{}])[0]
    print("name:", d0.get("vod_name"), "| year:", d0.get("vod_year"),
          "| from:", d0.get("vod_play_from"))
    print("play_url head:", (d0.get("vod_play_url", "") or "")[:80])
    print("== searchContent (wd=花开锦绣) ==")
    sc = s.searchContent("花开锦绣", False, "1")
    print("list:", len(sc.get("list", [])), sc.get("list", [])[:1])
    print("== playerContent (线路1 第1集) ==")
    pc = s.playerContent("线路1", "/play/50298-1-1.html", "")
    print("parse:", pc.get("parse"), "| url:", str(pc.get("url"))[:120])
