# -*- coding: utf-8 -*-

import json
import re
import time
import urllib.parse
import html as _html
from concurrent.futures import ThreadPoolExecutor

from base.spider import Spider as BaseSpider

try:
    import requests
    from requests.adapters import HTTPAdapter
    from urllib3.util.retry import Retry
except Exception:
    requests = None
    HTTPAdapter = Retry = None

SITE_URL = "https://www.budaichuchen.net/"
SUGGEST_URL = SITE_URL + "index.php/ajax/suggest"
REQUEST_TIMEOUT = 15
PAGE_SIZE = 20
VERIFY_MARK = "系统安全验证"
MOBILE_UA = (
    "Mozilla/5.0 (iPhone; CPU iPhone OS 16_6 like Mac OS X) "
    "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.6 "
    "Mobile/15E148 Safari/604.1"
)
NORMAL_HEADERS = {
    "User-Agent": MOBILE_UA,
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.6",
    "Referer": SITE_URL,
}

API_HEADERS = {
    "User-Agent": MOBILE_UA,
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.6",
    "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
    "X-Requested-With": "XMLHttpRequest",
    "Origin": SITE_URL.rstrip("/"),
    "Referer": SITE_URL,
}

CARD_RE = re.compile(
    r'<a(?=[^>]*class="[^"]*public-list-exp[^"]*")[^>]*href="/detail/(\d+)\.html"[^>]*title="([^"]*)"[^>]*>(.*?)</a>',
    re.S,
)
PIC_RE = re.compile(r'(?:data-src|src)="(https?://[^"]+)"', re.I)
PRB_RE = re.compile(r'class="[^"]*public-list-prb[^"]*"[^>]*>.*?<i[^>]*>([^<]*)</i>', re.S)
PRT_RE = re.compile(r'class="[^"]*public-prt[^"]*"[^>]*>\s*([^<]+?)\s*<', re.S)
PAGE_RE = re.compile(r'/cupfox-list/(\d+)-(\d+)-----------\.html')

SECTION_H2_RE = re.compile(r'<h2[^>]*>(.*?)</h2>', re.S)

TID_SECTIONS = {
    "1": ("电影", "热播电影榜单"),
    "2": ("电视剧", "热播电视剧榜单"),
    "3": ("综艺", "热播综艺榜单"),
    "4": ("动漫", "热播动漫榜单"),
    "5": ("热门短剧", "热播热门短剧榜单"),
}
LABEL_SECTIONS = {
    "label_qq": ("腾讯SVIP热映", "腾讯SVIP热映榜单"),
    "label_youku": ("优酷SVIP热映", "优酷SVIP热映榜单"),
    "label_bli": ("B站SVIP热映", "B站SVIP热映榜单"),
}

RANK_RE = re.compile(
    r'<a(?=[^>]*class="[^"]*vod-link[^"]*")[^>]*href="/detail/(\d+)\.html"[^>]*>(.*?)</a>',
    re.S,
)
RANK_TITLE_RE = re.compile(r'<span class="[^"]*vod-title[^"]*"[^>]*title="([^"]*)"', re.S)
RANK_REMARK_RE = re.compile(r'<span class="[^"]*vod-sub-text[^"]*"[^>]*>([^<]+)</span>', re.S)

H1_RE = re.compile(r"<h1[^>]*>(.*?)</h1>", re.S)
TITLE_BOOK_RE = re.compile(r"《([^》]{1,80})》")
DIRECTOR_RE = re.compile(r"导演[：:]\s*</[^>]+>\s*([^<]{1,80})")
ACTOR_RE = re.compile(r"演员[：:]\s*</[^>]+>\s*([^<]{1,200})")
INTRO_RE = re.compile(r'id="height_limit"[^>]*>(.*?)</div>', re.S)
TAB_RE = re.compile(r'<a class="swiper-slide"[^>]*>\s*<i[^>]*></i>\s*([^<]{1,20})<', re.S)
BOX_RE = re.compile(r'<div class="anthology-list-box[^"]*"[^>]*>(.*?)</div>', re.S)
EPISODE_RE = re.compile(r'href="/play/(\d+)-(\d+)-(\d+)\.html"[^>]*>\s*([^<]{1,20})', re.S)

PLAYER_AAAA_RE = re.compile(r"var\s+player_aaaa\s*=\s*(\{.*?\})\s*;", re.S)
PLAY_ID_RE = re.compile(r"(\d+)-(\d+)-(\d+)")

LABEL_TAGS = {
    "label_qq": "腾讯精选",
    "label_youku": "优酷精选",
    "label_bli": "B站精选",
}

class Spider(BaseSpider):

    def __init__(self):
        self.site_url = SITE_URL
        self.page_size = PAGE_SIZE
        self.timeout = REQUEST_TIMEOUT
        self._session = None
        self._index_cache = None
        self._sections_cache = None
        self._name_pic_cache = None
        self._suggest_pic = {}
        self._index_ttl = 600

    def _make_session(self):
        if requests is None:
            return None
        session = requests.Session()
        retry = Retry(total=2, connect=2, read=2, backoff_factor=0.5,
                      status_forcelist=[500, 502, 503, 504])
        adapter = HTTPAdapter(max_retries=retry)
        session.mount("http://", adapter)
        session.mount("https://", adapter)
        return session

    def _fetch(self, url, referer=None):

        headers = dict(NORMAL_HEADERS)
        if referer:
            headers["Referer"] = referer
        if self._session is None:
            self._session = self._make_session()
        if self._session is not None:
            resp = self._session.get(url, headers=headers, timeout=self.timeout)
            return resp.text
        req = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req, timeout=self.timeout) as resp:
            return resp.read().decode("utf-8", errors="replace")

    def init(self, extend):

        if not extend:
            return
        if isinstance(extend, str):
            try:
                extend = json.loads(extend)
            except ValueError:
                raise ValueError("extend JSON 解析失败")
        if not isinstance(extend, dict):
            raise ValueError("extend 必须是 JSON 字符串或对象")
        if extend.get("web_url") or extend.get("request_url") or extend.get("site_url"):
            self.site_url = (extend.get("site_url") or extend.get("web_url")
                             or extend.get("request_url")).rstrip("/") + "/"
        if extend.get("page_size"):
            self.page_size = max(1, int(extend["page_size"]))
        if extend.get("timeout"):
            self.timeout = max(3, int(extend["timeout"]))

    def homeContent(self, filter):
        classes = [
            {"type_id": "1", "type_name": "电影"},
            {"type_id": "2", "type_name": "电视剧"},
            {"type_id": "3", "type_name": "综艺"},
            {"type_id": "4", "type_name": "动漫"},
            {"type_id": "5", "type_name": "短剧"},
            {"type_id": "label_qq", "type_name": "腾讯精选"},
            {"type_id": "label_youku", "type_name": "优酷精选"},
            {"type_id": "label_bli", "type_name": "B站精选"},
        ]
        return {"class": classes}

    def homeVideoContent(self):

        items = self._get_home_index()
        return {"list": items[:self.page_size], "page": 1, "pagecount": 1,
                "limit": self.page_size, "total": len(items)}

    def _get_home_index(self, force=False):

        now = time.time()
        if (not force and self._index_cache
                and now - self._index_cache[0] < self._index_ttl):
            return self._index_cache[1]
        try:
            html = self._fetch(self.site_url)
        except Exception:
            return self._index_cache[1] if self._index_cache else []
        items = self._parse_cards(html)

        seen = set()
        uniq = []
        for it in items:
            if it["vod_id"] in seen:
                continue
            seen.add(it["vod_id"])
            uniq.append(it)
        items = uniq
        if items:
            self._index_cache = (now, items)
        return items

    @staticmethod
    def _parse_ranking(html):

        items = []
        for m in RANK_RE.finditer(html):
            vod_id, block = m.group(1), m.group(2)
            tm = RANK_TITLE_RE.search(block)
            rm = RANK_REMARK_RE.search(block)
            items.append({
                "vod_id": "vod/" + vod_id,
                "vod_name": _html.unescape(tm.group(1)).strip() if tm else "",
                "vod_pic": "",
                "vod_remarks": _html.unescape(rm.group(1)).strip() if rm else "",
                "style": {"type": "rect", "ratio": 0.75},
            })
        return items

    def _get_home_sections(self, force=False):

        now = time.time()
        if (not force and self._sections_cache
                and now - self._sections_cache[0] < self._index_ttl):
            return self._sections_cache[1]
        try:
            html = self._fetch(self.site_url)
        except Exception:
            return self._sections_cache[1] if self._sections_cache else {}
        sections = {}
        matches = list(SECTION_H2_RE.finditer(html))
        for idx, m in enumerate(matches):
            title = _html.unescape(re.sub(r"<[^>]+>", "", m.group(1))).strip()
            if not title:
                continue
            end = matches[idx + 1].start() if idx + 1 < len(matches) else len(html)
            segment = html[m.end():end]
            items = self._parse_cards(segment) + self._parse_ranking(segment)
            if items:
                sections[title] = items

        name_pic = {}
        for items in sections.values():
            for it in items:
                if it["vod_pic"] and it["vod_name"]:
                    name_pic.setdefault(it["vod_name"], it["vod_pic"])
        self._name_pic_cache = name_pic
        for items in sections.values():
            for it in items:
                if not it["vod_pic"] and it["vod_name"] in name_pic:
                    it["vod_pic"] = name_pic[it["vod_name"]]
        if sections:
            self._sections_cache = (now, sections)
        return sections

    def _enrich_pics(self, items, limit=8):

        need = [it for it in items if not it.get("vod_pic") and it.get("vod_name")]
        if not need:
            return items

        leftovers = []
        for it in need:
            pic = (self._name_pic_cache or {}).get(it["vod_name"])
            if pic:
                it["vod_pic"] = pic
            else:
                leftovers.append(it)
        if not leftovers:
            return items

        leftovers = leftovers[:limit]
        todo = [it for it in leftovers if it["vod_name"] not in self._suggest_pic]
        if todo:
            self._suggest_pic.update(self._fetch_suggest_pics([it["vod_name"] for it in todo]))
        for it in leftovers:
            pic = self._suggest_pic.get(it["vod_name"])
            if pic:
                it["vod_pic"] = pic
        return items

    def _fetch_suggest_pics(self, names):

        def one(name):
            try:
                url = "%s?mid=1&wd=%s&limit=20" % (SUGGEST_URL, urllib.parse.quote(name))
                if self._session is not None:
                    resp = self._session.get(url, headers=API_HEADERS, timeout=6)
                    data = resp.json()
                else:
                    req = urllib.request.Request(url, headers=API_HEADERS)
                    with urllib.request.urlopen(req, timeout=6) as resp:
                        data = json.loads(resp.read().decode("utf-8"))
                for it in (data.get("list") if isinstance(data, dict) else None) or []:
                    if it.get("name") == name:
                        pic = _html.unescape(str(it.get("pic") or ""))
                        if pic and not pic.startswith("http"):
                            pic = (self.site_url.rstrip("/") + pic) if pic.startswith("/") else self.site_url + pic
                        return name, pic
                return name, ""
            except Exception:
                return name, ""
        results = {}
        for i in range(0, len(names), 4):
            batch = names[i:i + 4]
            with ThreadPoolExecutor(max_workers=4) as ex:
                for name, pic in ex.map(one, batch):
                    results[name] = pic
        return results

    def _section_items(self, tid):

        keys = LABEL_SECTIONS if str(tid) in LABEL_SECTIONS else TID_SECTIONS
        names = keys.get(str(tid))
        if not names:
            return None
        sections = self._get_home_sections()
        items = []
        seen = set()
        for name in names:
            for it in sections.get(name, []):
                if it["vod_id"] in seen:
                    continue
                seen.add(it["vod_id"])
                items.append(it)
        return items

    def categoryContent(self, tid, pg, filter, extend):
        try:
            page = max(1, int(pg))
        except (TypeError, ValueError):
            page = 1
        if not tid:
            return self._empty_page()
        tid = str(tid)

        if tid in LABEL_TAGS:
            return self._category_label(tid, page)

        if page <= 1:
            url = "%scupfox-list/%s-----------.html" % (self.site_url, tid)
        else:
            url = "%scupfox-list/%s-%s-----------.html" % (self.site_url, tid, page)
        try:
            html = self._fetch(url)
        except Exception:
            return self._empty_page()

        if VERIFY_MARK in html or "captcha.php" in html:
            return self._category_fallback(tid, page)

        items = self._parse_cards(html)
        if not items:
            return self._empty_page()
        return {
            "list": items,
            "page": page,
            "pagecount": self._guess_pagecount(html, tid, page),
            "limit": self.page_size,
            "total": 0,
        }

    def _category_label(self, tid, page):
        tag = tid.split("_")[-1]
        if page <= 1:
            url = "%slabel/%s.html" % (self.site_url, tag)
        else:
            url = "%slabel/%s-%s.html" % (self.site_url, tag, page)
        try:
            html = self._fetch(url)
        except Exception:
            return self._empty_page()
        if VERIFY_MARK in html:
            return self._category_fallback(tid, page)
        items = self._parse_cards(html)
        if not items:
            return self._empty_page()
        return {
            "list": items,
            "page": page,
            "pagecount": self._guess_pagecount(html, tag, page, label=True),
            "limit": self.page_size,
            "total": 0,
        }

    def _category_fallback(self, tid, page):

        items = self._section_items(tid)
        if items is None:
            items = self._get_home_index()
        if not items:
            return self._empty_page()
        total = len(items)
        pagecount = max(1, (total + self.page_size - 1) // self.page_size)
        page = min(page, pagecount)
        start = (page - 1) * self.page_size
        page_items = items[start:start + self.page_size]

        self._enrich_pics(page_items)
        return {"list": page_items, "page": page,
                "pagecount": pagecount, "limit": self.page_size, "total": total}

    @staticmethod
    def _guess_pagecount(html, tid, page, label=False):

        best = 1
        if label:
            for m in re.finditer(r'/label/%s-(\d+)\.html' % re.escape(tid), html):
                try:
                    best = max(best, int(m.group(1)))
                except ValueError:
                    pass
        else:
            for m in PAGE_RE.finditer(html):
                try:
                    best = max(best, int(m.group(2)))
                except ValueError:
                    pass
        return max(best, page)

    @staticmethod
    def _parse_cards(html):

        items = []
        for m in CARD_RE.finditer(html):
            vod_id, name, block = m.group(1), m.group(2), m.group(3)
            pic_m = PIC_RE.search(block)
            prb_m = PRB_RE.search(block)
            prt_m = PRT_RE.search(block)
            remark = ""
            if prb_m and prb_m.group(1).strip():
                remark = prb_m.group(1).strip()
            elif prt_m and prt_m.group(1).strip():
                remark = prt_m.group(1).strip()
            items.append({
                "vod_id": "vod/" + vod_id,
                "vod_name": name.strip(),
                "vod_pic": _html.unescape(pic_m.group(1)) if pic_m else "",
                "vod_remarks": remark,
                "style": {"type": "rect", "ratio": 0.75},
            })
        return items

    @staticmethod
    def _empty_page():
        return {"list": [], "page": 1, "pagecount": 1, "limit": PAGE_SIZE, "total": 0}

    def searchContent(self, key, quick, pg):

        if not key:
            return self._empty_page()
        data = None
        try:
            url = "%s?mid=1&wd=%s&limit=50" % (SUGGEST_URL, urllib.parse.quote(str(key)))
            if self._session is None:
                self._session = self._make_session()
            if self._session is not None:
                resp = self._session.get(url, headers=API_HEADERS, timeout=self.timeout)
                data = resp.json()
            else:
                req = urllib.request.Request(url, headers=API_HEADERS)
                with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                    data = json.loads(resp.read().decode("utf-8"))
        except Exception:
            return self._empty_page()
        data = data if isinstance(data, dict) else {}
        items = []
        for it in (data.get("list") or []):
            vod_id = it.get("id")
            if not vod_id:
                continue
            pic = _html.unescape(it.get("pic") or "")
            if pic and not pic.startswith("http"):
                pic = (self.site_url.rstrip("/") + pic) if pic.startswith("/") else (self.site_url + pic)
            items.append({
                "vod_id": "vod/%s" % vod_id,
                "vod_name": it.get("name") or "",
                "vod_pic": pic,
                "vod_remarks": "匹配结果",
                "style": {"type": "rect", "ratio": 0.75},
            })
        return {
            "list": items,
            "page": 1,
            "pagecount": max(1, (data or {}).get("pagecount") or 1),
            "limit": (data or {}).get("limit") or len(items) or 1,
            "total": (data or {}).get("total") or len(items),
        }

    @staticmethod
    def _strip_tags(text):
        return re.sub(r"<[^>]+>", "", text or "").strip()

    def detailContent(self, ids):
        ident = str(ids[0] if ids else "").split("/")[-1]
        if not ident or not ident.isdigit():
            return {"list": [], "msg": "无效的影片 ID"}
        try:
            html = self._fetch("%sdetail/%s.html" % (self.site_url, ident))
        except Exception:
            return {"list": [], "msg": "详情页获取失败"}
        if VERIFY_MARK in html:
            return {"list": [], "msg": "详情页被站点验证码拦截，请稍后再试"}

        title_m = H1_RE.search(html)
        if title_m:
            title = self._strip_tags(title_m.group(1))
        else:
            book_m = TITLE_BOOK_RE.search(html)
            title = book_m.group(1) if book_m else ident
        pic_m = re.search(r'(?:data-src|src)="(https?://[^"]+\.(?:jpg|jpeg|webp|png)[^"]*)"', html, re.I)
        director_m = DIRECTOR_RE.search(html)
        actor_m = ACTOR_RE.search(html)
        intro_m = INTRO_RE.search(html)
        vod = {
            "vod_id": "vod/" + ident,
            "vod_name": title,
            "vod_pic": _html.unescape(pic_m.group(1)) if pic_m else "",
            "type_name": "",
            "vod_year": "",
            "vod_area": "",
            "vod_remarks": "",
            "vod_actor": self._strip_tags(actor_m.group(1)) if actor_m else "",
            "vod_director": self._strip_tags(director_m.group(1)) if director_m else "",
            "vod_content": self._strip_tags(intro_m.group(1)) if intro_m else "",
        }

        tabs = [_html.unescape(t).strip() for t in TAB_RE.findall(html)]
        boxes = BOX_RE.findall(html)
        if not tabs or not boxes or len(tabs) != len(boxes):
            vod["vod_play_from"] = ""
            vod["vod_play_url"] = ""
            return {"list": [vod]}
        if len(boxes) < len(tabs):
            tabs = tabs[:len(boxes)]

        lines = []
        for idx, box_html in enumerate(boxes):
            eps = EPISODE_RE.findall(box_html)
            if not eps:
                continue

            if eps and int(eps[0][2]) > int(eps[-1][2]):
                eps.reverse()

            line = "#".join("%s$%s-%s-%s" % (e[3].strip(), e[0], e[1], e[2]) for e in eps)
            lines.append((tabs[idx], line))

        selected = [(n, v) for n, v in lines if "自营" in n]

        vod["vod_play_from"] = "$$$".join(n for n, _ in selected)
        vod["vod_play_url"] = "$$$".join(v for _, v in selected)
        return {"list": [vod]}

    def playerContent(self, flag, id, vipFlags):
        m = PLAY_ID_RE.search(str(id))
        if not m:
            return {"parse": 0, "url": "", "msg": "无效的播放地址"}
        vod_id, sid, nid = m.group(1), m.group(2), m.group(3)
        try:

            html = self._fetch("%splay/%s-%s-%s.html" % (self.site_url, vod_id, sid, nid),
                               referer="%sdetail/%s.html" % (self.site_url, vod_id))
        except Exception:
            return {"parse": 0, "url": "", "msg": "播放页获取失败"}
        if VERIFY_MARK in html:
            return {"parse": 0, "url": "", "msg": "播放页被验证码拦截"}

        text = self._extract_balanced(PLAYER_AAAA_RE, html, "player_aaaa")
        if not text:
            return {"parse": 0, "url": "", "msg": "未找到播放数据，请切换线路"}
        try:
            data = json.loads(text)
        except ValueError:
            return {"parse": 0, "url": "", "msg": "播放数据解析失败"}

        url = str(data.get("url") or "")
        if not url:
            return {"parse": 0, "url": "", "msg": "播放地址为空"}
        if not url.lower().startswith(("http://", "https://")):
            return {"parse": 0, "url": "", "msg": "该线路为第三方解析源，请切换自营线路"}
        headers = {
            "User-Agent": MOBILE_UA,
            "Referer": self.site_url,
        }
        return {"parse": 0, "jx": 0, "url": url, "header": json.dumps(headers)}

    @staticmethod
    def _extract_balanced(pattern, text, marker):

        m = pattern.search(text)
        if not m:
            return None
        start = m.start(1)
        depth = 0
        i = start
        in_str = False
        escape = False
        while i < len(text):
            c = text[i]
            if in_str:
                if escape:
                    escape = False
                elif c == "\\":
                    escape = True
                elif c == '"':
                    in_str = False
            else:
                if c == '"':
                    in_str = True
                elif c == "{":
                    depth += 1
                elif c == "}":
                    depth -= 1
                    if depth == 0:
                        return text[start:i + 1]
            i += 1
        return None

    def liveContent(self):
        return []

    def localProxy(self, param):
        return ""

    def isVideoFormat(self, url):
        return False

    def manualVideoCheck(self):
        return True

    def destroy(self):
        if self._session is not None:
            try:
                self._session.close()
            except Exception:
                pass
            self._session = None

if __name__ == "__main__":
    pass