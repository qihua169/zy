# -*- coding: utf-8 -*-
"""
星星影视（xinghangxiaoyuanshi.com）TVBox 数据源
=========================================================
写法遵循 TVBox / CatVod / PyramidStore Spider 规范（参照 加菲猫影视.py）：
  - 类继承自 base.spider.Spider
  - 网络请求统一走基类 self.fetch()（TVBox 注入，自带编码/超时/header）
  - init 极简（不重写或仅 pass），让基类 __init__ 自然初始化
  - playerContent 的 header 字段为 json.dumps(dict)
  - 所有接口 try/except 兜底返回合法结构，避免 TVBox 框架标记源不可用

站点：苹果CMS + 自定义 SEO 路由（UTF-8）
  - 分类   GET  /xhgysp/{tid}s{pg}.html
  - 详情   GET  /xhgyxq/{id}.html
  - 播放   GET  /xhgybf/{id}d{sid}e{nid}.html（var player_xxxx={"url":...,"encrypt":0}）
  - 搜索   GET  /xhgycz/{quote(key)}rabcdltvos{pg}gmy.html
"""

import re
import json
import sys

try:
    from base.spider import Spider as _TVBase
except Exception:
    # 本地（PC）调试兜底：无 base.spider 时给个最小 fetch/post 桩
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
            r = urlopen(Request(url, data=body, headers=headers or {}, method="POST"), timeout=timeout)
            return self._resp(r.read())


SITE_NAME = "星星影视"
BASE_URL = "https://www.xinghangxiaoyuanshi.com"
UA = ("Mozilla/5.0 (Linux; Android 12) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/125.0.0.0 Mobile Safari/537.36")

# 兜底分类（首页解析失败时使用）
HOME_CLASSES = [
    {"type_id": "1", "type_name": "电影"},
    {"type_id": "2", "type_name": "电视剧"},
    {"type_id": "44", "type_name": "短剧"},
    {"type_id": "119", "type_name": "影视解说"},
    {"type_id": "4", "type_name": "动漫"},
    {"type_id": "3", "type_name": "综艺"},
]

# ── 正则 ──
RE_HOME_CLASS = re.compile(r'href="/(?:xhgysp|type)/(\d+)s\.html"[^>]*title="([^"]+)"', re.I)
RE_CARD = re.compile(
    r'<a[^>]*href="(/xhgyxq/(\d+)\.html)"[^>]*title="([^"]*)"[^>]*>(.*?)</a>',
    re.S | re.I)
RE_EM = re.compile(r'<em[^>]*>([^<]*)</em>', re.S | re.I)
RE_PIC = re.compile(r'data-original="([^"]+)"', re.I)
RE_TITLE = re.compile(r'<title>([^<]+)</title>', re.S | re.I)
RE_VOD_PIC = re.compile(r'<img[^>]*class="[^"]*vod-pic[^"]*"[^>]*data-original="([^"]+)"', re.S | re.I)
RE_REMARK = re.compile(r'<em[^>]*class="[^"]*label[^"]*"[^>]*>([^<]+)</em>', re.S | re.I)
RE_FIELD = re.compile(r'<dt[^>]*>([^<]*)</dt>\s*<dd[^>]*>(.*?)</dd>', re.S | re.I)
RE_CONTENT = re.compile(r'<dd[^>]*class="[^"]*vod-content[^"]*"[^>]*>(.*?)</dd>', re.S | re.I)
RE_TAB = re.compile(
    r'<a[^>]*href="#playlist_([a-z0-9]+)"[^>]*>.*?<span[^>]*></span>\s*([^<]+?)\s*</a>',
    re.S | re.I)
RE_PLBLK = re.compile(r'id="playlist_([a-z0-9]+)"(.*?)(?=id="playlist_|$)', re.S | re.I)
RE_EP = re.compile(r'<a[^>]*href="(/xhgybf/(\d+)d(\d+)e(\d+)\.html)"[^>]*>(.*?)</a>', re.S | re.I)
# 分页器：分类 /xhgysp/{tid}s{pg}.html，搜索 /xhgycz/{key}rabcdltvos{pg}gmy.html
RE_PAGE = re.compile(r'/(?:xhgysp/(?:\d+)s|xhgycz/[^"]*?rabcdltvos)(\d+)(?:gmy)?\.html', re.I)


def _clean(s):
    s = re.sub(r'<[^>]+>', '', s or "")
    s = s.replace("&nbsp;", " ").replace("\u3000", " ").replace("&amp;", "&")
    return re.sub(r'\s+', ' ', s).strip()


def _split_name(title, remark):
    name = _clean(title)
    if remark and name.endswith(" " + remark):
        name = name[: -(len(remark) + 1)]
    elif remark and name.endswith(remark):
        name = name[: -len(remark)]
    return name.strip()


class XingHangSpider(_TVBase):

    def getName(self):
        return SITE_NAME

    def init(self, extend=""):
        # 极简：让 TVBox Spider 基类 __init__ 自然初始化（self.fetch 依赖的 session 等）
        pass

    # ── 网络 ──

    def _headers(self):
        return {
            "User-Agent": UA,
            "Referer": BASE_URL + "/",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        }

    def _fetch_html(self, url):
        rsp = self.fetch(url, headers=self._headers(), timeout=15)
        try:
            rsp.encoding = rsp.apparent_encoding or "utf-8"
        except Exception:
            pass
        return rsp.text

    def _header_json(self):
        return json.dumps({"User-Agent": UA, "Referer": BASE_URL + "/"})

    # ── 列表/分页 ──

    def _parse_list(self, html):
        items, s = [], set()
        for m in RE_CARD.finditer(html or ""):
            vid = m.group(2)
            if vid in s:
                continue
            s.add(vid)
            em = RE_EM.search(m.group(4))
            remark = _clean(em.group(1)) if em else ""
            pic = RE_PIC.search(m.group(4))
            items.append({
                "vod_id": vid,
                "vod_name": _split_name(m.group(3), remark),
                "vod_pic": pic.group(1) if pic else "",
                "vod_remarks": remark,
            })
        return items

    def _pagecount(self, html):
        nums = [int(p) for p in RE_PAGE.findall(html or "") if p.isdigit()]
        return max(nums) if nums else 1

    # ── 选集 ──

    def _parse_episodes(self, html, vod_id):
        tabs = {pid: _clean(name) for pid, name in RE_TAB.findall(html or "")}
        groups = []
        for pid, block in RE_PLBLK.findall(html or ""):
            eps = []
            for href, _v, _s, nid, inner in RE_EP.findall(block):
                ep = _clean(inner) or "第%s集" % nid
                eps.append("%s$%s" % (ep, href))
            if eps:
                groups.append((tabs.get(pid, pid), "#".join(eps)))
        if not groups:
            return "默认线路", "播放$/xhgybf/%sd1e1.html" % vod_id
        return "$$$".join(g[0] for g in groups), "$$$".join(g[1] for g in groups)

    # ── 详情 ──

    def _detail(self, vid):
        html = self._fetch_html("%s/xhgyxq/%s.html" % (BASE_URL, vid))
        name = vid
        tm = RE_TITLE.search(html)
        if tm:
            t = tm.group(1).strip()
            if "在线观看" in t:
                name = t.split("在线观看")[0].strip()
            elif "-" in t:
                name = t.split("-")[0].strip()
        pic = ""
        pm = RE_VOD_PIC.search(html)
        if pm:
            pic = pm.group(1)
        else:
            pm2 = RE_PIC.search(html)
            if pm2:
                pic = pm2.group(1)
        rm = RE_REMARK.search(html)
        remark = _clean(rm.group(1)) if rm else ""
        fields = {}
        for dt, dd in RE_FIELD.findall(html):
            k = _clean(dt).rstrip("：:")
            if not k:
                continue
            v = _clean(dd)
            if k == "剧情":
                v = re.sub(r'分享\s*$', '', v).strip()
            fields[k] = v
        content = ""
        cm = RE_CONTENT.search(html)
        if cm:
            blk = re.sub(r'<a[^>]*>[^<]*?(?:详细|分享)[^<]*?</a>', '', cm.group(1))
            content = _clean(blk).rstrip("分享").strip()
        pf, pu = self._parse_episodes(html, vid)
        return {
            "vod_id": vid,
            "vod_name": name,
            "vod_pic": pic,
            "vod_remarks": remark,
            "vod_year": fields.get("年份", ""),
            "vod_area": fields.get("地区", ""),
            "vod_lang": fields.get("语言", ""),
            "vod_actor": fields.get("主演", ""),
            "vod_director": fields.get("导演", ""),
            "vod_class": fields.get("类型", ""),
            "vod_content": content,
            "vod_play_from": pf,
            "vod_play_url": pu,
        }

    # ── 播放器 ──

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

    # ══════════ TVBox 接口 ══════════

    def homeContent(self, filter):
        classes = HOME_CLASSES
        try:
            html = self._fetch_html(BASE_URL + "/")
            seen, parsed = set(), []
            for tid, name in RE_HOME_CLASS.findall(html):
                if tid in seen:
                    continue
                seen.add(tid)
                parsed.append({"type_id": tid, "type_name": name.strip()})
            if parsed:
                classes = parsed
        except Exception:
            pass
        return {"class": classes, "filters": {}}

    def homeVideoContent(self):
        try:
            html = self._fetch_html(BASE_URL + "/")
            return {"list": self._parse_list(html)}
        except Exception:
            return {"list": []}

    def categoryContent(self, tid, pg, filter, extend):
        page = int(pg) if pg else 1
        try:
            url = "%s/xhgysp/%ss%d.html" % (BASE_URL, tid, page)
            html = self._fetch_html(url)
            items = self._parse_list(html)
            return {"list": items, "page": page, "pagecount": self._pagecount(html),
                    "limit": 30, "total": len(items)}
        except Exception:
            return {"list": [], "page": page, "pagecount": 1, "limit": 30, "total": 0}

    def detailContent(self, ids):
        try:
            vid = str(ids[0]) if ids else ""
            return {"list": [self._detail(vid)]}
        except Exception as e:
            vid = str(ids[0]) if ids else ""
            return {"list": [{
                "vod_id": vid, "vod_name": "解析异常", "vod_pic": "",
                "vod_year": "", "vod_area": "", "vod_remarks": "",
                "vod_actor": "", "vod_director": "", "vod_content": str(e)[:200],
                "vod_play_from": "默认线路",
                "vod_play_url": "播放$/xhgybf/%sd1e1.html" % vid,
            }]}

    def searchContent(self, key, quick, pg="1"):
        page = int(pg) if pg else 1
        try:
            if page <= 1:
                # POST wd（带 Referer）
                html = self.post(
                    BASE_URL + "/xhgycz/rabcdltvosgmy.html",
                    data={"wd": key},
                    headers=self._headers(),
                    timeout=15,
                )
                try:
                    html.encoding = html.apparent_encoding or "utf-8"
                except Exception:
                    pass
                html = html.text
            else:
                url = "%s/xhgycz/%srabcdltvos%dgmy.html" % (
                    BASE_URL, quote(key), page)
                html = self._fetch_html(url)
            items = self._parse_list(html)
            return {"list": items, "page": page, "pagecount": self._pagecount(html),
                    "limit": 20, "total": len(items)}
        except Exception:
            return {"list": [], "page": page, "pagecount": 1, "limit": 20, "total": 0}

    def playerContent(self, flag, id, vipFlags):
        hd = self._header_json()
        try:
            play_url = id if id.startswith("http") else (BASE_URL + id)
            html = self.fetch(play_url, headers=self._headers(), timeout=15).text
            url = self._extract_player_url(html)
            if url:
                return {"parse": 0, "playUrl": "", "url": url, "header": hd}
            return {"parse": 1, "playUrl": "", "url": play_url, "header": hd}
        except Exception:
            return {"parse": 1, "playUrl": "", "url": id, "header": hd}

    def isVideoFormat(self, url):
        pass

    def manualVideoCheck(self):
        pass

    def localProxy(self, param):
        return [200, "video/MP2T", "", ""]


# 兼容部分 TVBox 按 `module.Spider` 类名加载的约定
Spider = XingHangSpider


if __name__ == "__main__":
    s = XingHangSpider()
    s.init()
    print("==> homeContent:", json.dumps(s.homeContent(False), ensure_ascii=False)[:300])
    print("==> homeVideoContent:", len(s.homeVideoContent().get("list", [])), "items")
    c = s.categoryContent("1", 1, False, {})
    print("==> categoryContent(1,1):", len(c.get("list", [])), "条, pagecount", c.get("pagecount"))
    if c.get("list"):
        vid = c["list"][0]["vod_id"]
        d = s.detailContent([vid])
        print("==> detailContent:", json.dumps(d, ensure_ascii=False)[:600])
        if d["list"] and d["list"][0].get("vod_play_url"):
            ep = d["list"][0]["vod_play_url"].split("#")[0].split("$")[1]
            print("==> playerContent:", json.dumps(s.playerContent("player", ep, ""), ensure_ascii=False)[:300])
    print("==> searchContent(短剧):", len(s.searchContent("短剧", False, "1").get("list", [])), "items")