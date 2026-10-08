# -*- coding: utf-8 -*-
"""
APTV 影视 (https://aptv.pro) - TVBox 爬虫源
"""

import re
import json
import time
import threading
import base64
from urllib.parse import quote, unquote

import requests
from requests.adapters import HTTPAdapter

try:
    from bs4 import BeautifulSoup
except ImportError:
    BeautifulSoup = None

try:
    import urllib3
    urllib3.disable_warnings()
except Exception:
    pass

try:
    import sys
    sys.path.append('..')
    from base.spider import Spider as _BaseSpider
except ImportError:
    _BaseSpider = None

# ============================================================
# 常量
# ============================================================
HOST = "https://aptv.pro"
UA = "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1"

TIMEOUT_PAGE = 6
TIMEOUT_API = 5
TIMEOUT_PLAY = 4

TTL_HOME = 600
TTL_DETAIL_OK = 600
TTL_DETAIL_EMPTY = 30
TTL_SEARCH = 180
TTL_PLAY = 900
TTL_LIVE = 1800

SOURCES = ["暴风资源", "量子源"]

GROUPS = [
    {"id": "movie", "name": "电影", "subs": ["剧情片", "喜剧片", "动作片", "恐怖片", "爱情片", "电影解说", "动画片"]},
    {"id": "tv", "name": "电视剧", "subs": ["国产剧", "台湾剧", "香港剧", "韩国剧", "日本剧", "泰国剧", "欧美剧", "海外剧"]},
    {"id": "variety", "name": "综艺", "subs": ["大陆综艺", "日韩综艺", "港台综艺", "欧美综艺"]},
    {"id": "anime", "name": "动漫", "subs": ["国产动漫", "日韩动漫", "欧美动漫"]},
    {"id": "short", "name": "短剧", "subs": ["短剧"]},
    
]

ALL_CLASSES = [{"type_id": g["id"], "type_name": g["name"]} for g in GROUPS]

_Base = _BaseSpider if _BaseSpider is not None else object


class Spider(_Base):
    siteUrl = HOST
    headers = {
        'User-Agent': UA,
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
        'Accept-Language': 'zh-CN,zh;q=0.9',
        'Accept-Encoding': 'gzip, deflate',
        'Referer': HOST + '/',
    }

    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update(self.headers)
        self.session.headers['Connection'] = 'keep-alive'
        self.session.verify = False
        adapter = HTTPAdapter(pool_connections=20, pool_maxsize=40, max_retries=0, pool_block=False)
        self.session.mount('http://', adapter)
        self.session.mount('https://', adapter)

        self._lock = threading.Lock()
        self._home_data = {}
        self._home_time = 0
        self._detail_cache = {}
        self._search_cache = {}
        self._share_cache = {}

    def init(self, extend=""):
        self.extend = extend or ""

    def _get(self, url, referer='', timeout=TIMEOUT_PAGE):
        headers = {'Connection': 'keep-alive'}
        if referer:
            headers['Referer'] = referer
        for attempt in range(2):
            try:
                r = self.session.get(url, timeout=timeout, headers=headers)
                if r.status_code == 429:
                    time.sleep(1.5)
                    continue
                r.raise_for_status()
                r.encoding = r.apparent_encoding or 'utf-8'
                return r
            except Exception:
                if attempt == 0:
                    time.sleep(0.3)
                else:
                    return None
        return None

    def _get_text(self, url, referer='', timeout=TIMEOUT_PAGE):
        r = self._get(url, referer, timeout)
        return r.text if r is not None else ""

    def _get_json(self, url, referer='', timeout=TIMEOUT_API):
        text = self._get_text(url, referer, timeout)
        if not text:
            return None
        try:
            return json.loads(text)
        except Exception:
            return None

    @staticmethod
    def _cache_get(cache, key, ttl=None):
        item = cache.get(key)
        if item and time.time() - item[0] < (ttl if ttl is not None else item[2]):
            return item[1]
        return None

    @staticmethod
    def _cache_set(cache, key, value, ttl=TTL_DETAIL_OK):
        if len(cache) > 512:
            cache.clear()
        cache[key] = (time.time(), value, ttl)

    @staticmethod
    def _scan_json(text, start):
        depth = 0
        in_str = False
        esc = False
        n = len(text)
        i = start
        while i < n:
            c = text[i]
            if in_str:
                if esc:
                    esc = False
                elif c == '\\':
                    esc = True
                elif c == '"':
                    in_str = False
            else:
                if c == '"':
                    in_str = True
                elif c in '[{':
                    depth += 1
                elif c in ']}':
                    depth -= 1
                    if depth == 0:
                        return text[start:i + 1]
            i += 1
        return None

    @staticmethod
    def _find_json_var(text, marker):
        i = text.find(marker)
        if i < 0:
            return None
        j = i + len(marker)
        while j < len(text) and text[j] in ' \t\r\n=':
            j += 1
        if j >= len(text) or text[j] not in '[{':
            return None
        chunk = Spider._scan_json(text, j)
        if not chunk:
            return None
        try:
            return json.loads(chunk)
        except Exception:
            return None

    # ============================================================
    # 首页数据解析（保持不变）
    # ============================================================
    def _load_home_data(self, force=False):
        now = int(time.time())
        with self._lock:
            if not force and self._home_data and now - self._home_time < TTL_HOME:
                return self._home_data
        data = {}
        html = self._get_text(HOST, timeout=TIMEOUT_PAGE)
        if html:
            data = self._parse_home(html)
        if data:
            with self._lock:
                self._home_data = data
                self._home_time = int(time.time())
        return data

    def _parse_home(self, html):
        result = {}

        def _extract_id(href):
            m = re.search(r'vod_play\.php\?id=(\d+)&source=([^&"\']+)', href or '')
            if m:
                return m.group(1), unquote(m.group(2))
            return None, None

        def _card_from(a, cat):
            href = str(a.get('href') or '')
            vid, src = _extract_id(href)
            if not vid:
                return None
            title = str(a.get('title') or '').strip()
            if not title:
                name_el = a.select_one('.hot-name')
                title = name_el.get_text(strip=True) if name_el else ''
            if not title:
                title = str(a.get('alt') or '').strip()
            if not title:
                return None
            pic = ''
            img = a.select_one('.hot-thumb img')
            if img:
                pic = str(img.get('src') or img.get('data-src') or '').strip()
            remarks = ''
            meta_el = a.select_one('.hot-meta')
            if meta_el:
                remarks = meta_el.get_text(strip=True)
            return {
                'vod_id': (vid + '|' + src) if src else vid,
                'vod_name': title,
                'vod_pic': pic,
                'vod_remarks': remarks,
                'source': src,
            }

        if BeautifulSoup is not None:
            try:
                soup = BeautifulSoup(html, 'html.parser')
                nav = soup.find('div', id='hotNav')
                cats = []
                if nav is not None:
                    cats = [str(t.get('data-cat') or '') for t in nav.find_all(attrs={'data-cat': True})]
                    cats = [c for c in cats if c]
                grids = soup.select('.hot-grid')
                for cat, grid in zip(cats, grids):
                    cards = []
                    for a in grid.select('a.hot-card'):
                        card = _card_from(a, cat)
                        if card:
                            cards.append(card)
                    if cards:
                        result[cat] = cards
                if result:
                    return result
            except Exception:
                pass

        cats = [c for c in re.findall(r'data-cat="([^"]+)"', html) if c][:30]
        blocks = re.findall(
            r'<div class="hot-grid(.*?)(?=<div class="hot-grid|'
            r'<div class="ranking-section|<div class="hot-section|$)', html, re.S
        )
        for cat, block in zip(cats, blocks):
            cards = []
            for am in re.finditer(r'<a[^>]*class="hot-card[^"]*"[^>]*href="([^"]*)"[^>]*>(.*?)</a>', block, re.S):
                href, inner = am.group(1), am.group(2)
                vid, src = _extract_id(href)
                if not vid:
                    continue
                tm = re.search(r'class="hot-name">([^<]+)<', inner)
                title = tm.group(1).strip() if tm else ''
                if not title:
                    continue
                pm = re.search(r'<img[^>]*src="([^"]+)"', inner)
                pic = pm.group(1) if pm else ''
                mm = re.search(r'class="hot-meta">([^<]+)<', inner)
                remarks = mm.group(1).strip() if mm else ''
                cards.append({
                    'vod_id': (vid + '|' + src) if src else vid,
                    'vod_name': title, 'vod_pic': pic, 'vod_remarks': remarks, 'source': src,
                })
            if cards:
                result[cat] = cards
        return result

    def _all_cards(self, limit=60):
        data = self._load_home_data()
        out, seen, ordered = [], set(), []
        for cat in data:
            for c in data[cat]:
                ordered.append(c)
        ordered.sort(key=lambda c: 0 if c.get('vod_pic') else 1)
        for c in ordered:
            vid = c['vod_id'].split('|')[0]
            if vid in seen:
                continue
            seen.add(vid)
            out.append(c)
            if len(out) >= limit:
                break
        return out

    # ============================================================
    # 首页（保持不变）
    # ============================================================
    def homeContent(self, filter=False):
        return {"class": ALL_CLASSES}

    def homeVideoContent(self):
        try:
            return {"list": self._all_cards(40)}
        except Exception:
            return {"list": []}

    # ============================================================
    # 分类列表
    # ============================================================
    def _empty_category(self, page=1):
        return {"list": [], "page": page, "pagecount": 1, "limit": 36, "total": 0}

    # 🚨 修复点 1：为每个频道补充 type 字段，否则 TVBox 判为无效数据
    def _live_category(self, pg=1):
        page = max(1, int(pg or 1))
        ckey = "live_all"
        cached = self._cache_get(self._detail_cache, ckey, TTL_LIVE)
        if cached is not None:
            return cached

        live_list = []
        url = f"{HOST}/tv/channels.json"
        data = self._get_json(url, referer=f"{HOST}/tv/", timeout=TIMEOUT_API)

        if isinstance(data, dict):
            data = data.get('data') or data.get('channels') or data.get('list') or []

        if isinstance(data, list):
            for it in data:
                if not isinstance(it, dict):
                    continue
                name = str(it.get('name') or '').strip()
                raw_url = str(it.get('url') or '').strip()
                group = str(it.get('group') or '其他').strip()
                if not name or not raw_url:
                    continue

                # 用 base64 编码真实 URL 作为 vod_id，避免 TVBox 对 URL 做编码破坏
                try:
                    safe_id = 'live_' + base64.urlsafe_b64encode(
                        raw_url.encode('utf-8')
                    ).decode('ascii').rstrip('=')
                except Exception:
                    safe_id = raw_url

                live_list.append({
                    "vod_id": safe_id,
                    "vod_name": name,
                    "vod_pic": "",
                    "vod_remarks": group,
                    "type_name": group,
                    "type": "m3u8",          # 🚨 关键修复：TVBox 直播列表必填字段
                })

        result = {"list": live_list, "page": page, "pagecount": 1, "limit": 9999, "total": len(live_list)}
        self._cache_set(self._detail_cache, ckey, result, TTL_LIVE)
        return result

    def categoryContent(self, tid, pg, filter, extend):
        try:
            page = max(1, int(pg or 1))
            tid = str(tid)
            if tid == "live":
                return self._live_category(page)

            ext = {}
            if extend:
                if isinstance(extend, dict):
                    ext = extend
                elif isinstance(extend, str):
                    try:
                        ext = json.loads(extend)
                    except Exception:
                        ext = {}

            sub = (ext.get('class') or '').strip()
            group = None
            for g in GROUPS:
                if g["id"] == tid:
                    group = g
                    break
            if group is None:
                return self._empty_category(page)

            data = self._load_home_data()
            cards = []
            subs = [sub] if sub else group["subs"]
            for s in subs:
                cards.extend(data.get(s, []))
            seen, out = set(), []
            for c in cards:
                if c['vod_id'].split('|')[0] in seen:
                    continue
                seen.add(c['vod_id'].split('|')[0])
                out.append(c)
            return {"list": out, "page": page, "pagecount": 1, "limit": 36, "total": len(out)}
        except Exception:
            return self._empty_category(1)

    # ============================================================
    # 详情页（保持不变）
    # ============================================================
    def detailContent(self, ids):
        if isinstance(ids, str):
            ids = [ids]
        raw = str(ids[0]).split(',')[0].strip()
        raw = unquote(raw)
        parts = raw.split('|')
        vid = parts[0].strip()
        src = parts[1].strip() if len(parts) > 1 else ''
        if not vid or not vid.isdigit():
            return {"list": []}

        ckey = f"{vid}|{src}"
        cached = self._cache_get(self._detail_cache, ckey, None)
        if cached is not None:
            return cached

        result = self._fetch_detail(vid, src)
        ttl = TTL_DETAIL_OK if result.get("list") else TTL_DETAIL_EMPTY
        self._cache_set(self._detail_cache, ckey, result, ttl)
        return result

    def _fetch_detail(self, vid, prefer=''):
        sources = [prefer] if prefer else []
        sources += [s for s in SOURCES if s != prefer]
        for src in sources:
            url = f"{HOST}/vod_play.php?id={vid}&source={quote(src)}"
            html = self._get_text(url, referer=HOST + '/', timeout=TIMEOUT_PAGE)
            if not html:
                continue
            detail = self._parse_play_page(html, vid, src)
            if detail:
                return {"list": [detail]}
        return {"list": []}

    def _parse_play_page(self, html, vid, src):
        eps = []
        lines = self._find_json_var(html, 'linesData')
        if isinstance(lines, list):
            for line in lines:
                if not isinstance(line, dict):
                    continue
                line_name = str(line.get('name') or '线路').strip()
                for ep in (line.get('eps') or []):
                    if not isinstance(ep, dict):
                        continue
                    name = str(ep.get('name') or '').strip() or '播放'
                    u = str(ep.get('url') or '').replace('\\/', '/').strip()
                    if u:
                        eps.append((line_name, name, u))

        if not eps:
            m3u8_urls = re.findall(r'https?://[^"\'<>\s\\]+\.m3u8[^"\'<>\s\\]*', html)
            for i, u in enumerate(list(set(m3u8_urls))):
                eps.append(("默认线路", f"第{i+1}集", u))

        if not eps:
            return None

        pic, year, area, director, actor, content, type_name = ('', '', '', '', '', '', '')
        ld_name = ''
        for m in re.finditer(r'<script type="application/ld\+json">(.*?)</script>', html, re.S):
            try:
                d = json.loads(m.group(1))
            except Exception:
                continue
            if not isinstance(d, dict) or not d.get('name'):
                continue
            ld_name = str(d.get('name') or '').strip() or ld_name
            year = str(d.get('dateCreated') or '')[:4] or year
            area = str(d.get('countryOfOrigin') or '') or area
            type_name = str(d.get('genre') or '') or type_name
            content = str(d.get('description') or '').strip() or content
            dr = d.get('director')
            if isinstance(dr, dict) and dr.get('name'):
                director = str(dr['name']).strip() or director
            ac = d.get('actor')
            if isinstance(ac, list):
                names = [str(x.get('name') or '').strip() for x in ac if isinstance(x, dict) and x.get('name')]
                if names:
                    actor = '、'.join(names)

        name = ''
        tm = re.search(r'<title>([^<]+?)\s*-\s*APTV', html)
        if tm:
            name = tm.group(1).strip()
        if not name:
            name = ld_name
        if not name:
            return None

        if not pic:
            om = re.search(r'<meta property="og:image" content="([^"]+)"', html)
            if om:
                pic = om.group(1)

        remarks = ''
        last_ep = eps[-1][1]
        remarks = last_ep if len(eps) < 200 else f'共{len(eps)}集'
        rm = re.search(r'更新至([^\s<"]{0,20})', html)
        if rm:
            remarks = '更新至' + rm.group(1)

        lines_map = {}
        for line_name, ep_name, u in eps:
            lines_map.setdefault(line_name, []).append((ep_name, u))
        play_from = '$$$'.join(lines_map.keys())
        play_url = '$$$'.join(
            '#'.join(f"{n}${u}" for n, u in items)
            for items in lines_map.values()
        )

        return {
            "vod_id": vid,
            "vod_name": name,
            "vod_pic": pic,
            "type_name": type_name or src,
            "vod_remarks": remarks,
            "vod_year": year,
            "vod_area": area,
            "vod_director": director,
            "vod_actor": actor,
            "vod_content": content[:500],
            "vod_play_from": play_from,
            "vod_play_url": play_url,
        }

    # ============================================================
    # 播放解析
    # ============================================================
    def _resolve_share(self, share_url):
        cached = self._cache_get(self._share_cache, share_url, TTL_PLAY)
        if cached:
            return cached
        real = ''
        text = self._get_text(share_url, referer=HOST + '/', timeout=TIMEOUT_PLAY)
        if text:
            m = re.search(r'var\s+main\s*=\s*["\']([^"\']+)', text)
            if m:
                path = m.group(1).strip()
                if path:
                    if path.startswith('http'):
                        real = path.replace('\\/', '/')
                    else:
                        base = re.match(r'(https?://[^/]+)', share_url)
                        if base:
                            real = base.group(1) + ('' if path.startswith('/') else '/') + path.replace('\\/', '/')
        if real:
            self._cache_set(self._share_cache, share_url, real, TTL_PLAY)
        return real

    def _play_payload(self, playurl, referer=HOST + '/'):
        return {
            "parse": 0,
            "playUrl": "",
            "url": playurl,
            "header": {
                "User-Agent": UA,
                "Referer": referer,
                "Origin": HOST,
            },
            "format": "application/x-mpegURL" if '.m3u8' in playurl.lower() else "",
            "contentType": "application/x-mpegURL" if '.m3u8' in playurl.lower() else "",
        }

    # 🚨 修复点 2：直播用 live_ 前缀的 base64 id，返回时只填 url 字段
    def playerContent(self, flag, id, vipFlags):
        if not id:
            return {"parse": 0, "url": ""}

        playurl = unquote(str(id).strip())

        # 电视直播：base64 编码的 id
        if playurl.startswith('live_'):
            try:
                s = playurl[5:]
                s += '=' * (-len(s) % 4)
                real_url = base64.urlsafe_b64decode(s.encode('ascii')).decode('utf-8')
                if real_url:
                    # http 源走网站 /live/ 代理，避免 https 环境下的混合内容限制
                    if real_url.startswith('http://'):
                        play_url = f"{HOST}/live/{real_url}"
                    else:
                        play_url = real_url
                    return {
                        "parse": 0,
                        "url": play_url,
                        "header": {
                            "User-Agent": UA,
                            "Referer": HOST + '/tv/',
                        },
                    }
            except Exception:
                pass

        # 电视直播（旧格式兜底，以防缓存里还有）
        if playurl.startswith(HOST + '/live/'):
            return {
                "parse": 0,
                "url": playurl,
                "header": {"User-Agent": UA, "Referer": HOST + '/tv/'},
            }

        # 直链
        if '.m3u8' in playurl.lower() or '.mp4' in playurl.lower():
            return {
                "parse": 0,
                "url": playurl,
                "header": {"User-Agent": UA, "Referer": HOST + '/'},
            }

        # 分享页
        if '/share/' in playurl.lower():
            real = self._resolve_share(playurl)
            if real:
                return {
                    "parse": 0,
                    "url": real,
                    "header": {"User-Agent": UA, "Referer": HOST + '/'},
                }
            return {"parse": 1, "url": playurl,
                    "header": {"User-Agent": UA, "Referer": HOST + "/"}}

        # 兜底：id 是播放页 URL 或纯 vod_id
        vid = None
        m = re.search(r'id=(\d+)', playurl)
        if m:
            vid = m.group(1)
        elif playurl.isdigit():
            vid = playurl
        if vid:
            result = self._fetch_detail(vid)
            if result.get("list"):
                d = result["list"][0]
                first = ''
                for seg in (d.get("vod_play_url") or "").split("$$$"):
                    for item in seg.split("#"):
                        parts = item.split("$", 1)
                        if len(parts) == 2 and parts[1]:
                            first = parts[1]
                            break
                    if first:
                        break
                if first:
                    self._cache_set(self._detail_cache, vid, result, TTL_DETAIL_OK)
                    return {
                        "parse": 0,
                        "url": first,
                        "header": {"User-Agent": UA, "Referer": HOST + '/'},
                    }
        return {"parse": 1, "url": playurl,
                "header": {"User-Agent": UA, "Referer": HOST + "/"}}

    # ============================================================
    # 搜索（保持不变）
    # ============================================================
    def searchContent(self, keyword, quick=False, pg=1):
        raw = (keyword or '').strip()
        if not raw:
            return {"list": [], "msg": "请输入搜索关键词"}
        page = int(pg or 1)
        ckey = "%s|%s" % (page, raw)
        cached = self._cache_get(self._search_cache, ckey, TTL_SEARCH)
        if cached is not None:
            return cached
        result = {"list": [], "msg": "未找到相关内容"}
        data = self._get_json(
            f"{HOST}/index.php?action=ai_recommend&desc={quote(raw)}",
            referer=HOST + '/', timeout=TIMEOUT_API,
        )
        if data and isinstance(data, dict) and data.get('results'):
            out = []
            for it in data['results']:
                if not isinstance(it, dict):
                    continue
                vid = str(it.get('vod_id') or '')
                nm = str(it.get('vod_name') or it.get('title') or '').strip()
                if not vid or not nm:
                    continue
                out.append({
                    'vod_id': vid,
                    'vod_name': nm,
                    'vod_pic': str(it.get('vod_pic') or ''),
                    'vod_remarks': str(it.get('vod_remarks') or ''),
                    'type_name': str(it.get('type_name') or ''),
                })
            if out:
                result = {"list": out}
        self._cache_set(self._search_cache, ckey, result, TTL_SEARCH)
        return result

    def localProxy(self, param):
        return [200, "video/MP2T", b"", ""]

    def destroy(self):
        try:
            self.session.close()
        except Exception:
            pass

    def close(self):
        self.destroy()


if __name__ == '__main__':
    s = Spider()
    print(s.homeContent())