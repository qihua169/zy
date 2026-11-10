# -*- coding: utf-8 -*-
"""
APTV 影视 (https://aptv.pro) - TVBox 爬虫源

站点已于 2026-10 改版：由 PHP(苹果CMS) 模板改为 Next.js 单页应用，
页面 HTML 只剩骨架屏（Suspense fallback），数据全部走同源 JSON 接口，
因此本脚本完全基于 /api/* 抓取，不再解析 HTML（分享页除外）。

接口清单（均同源，需带移动端 UA + Referer）：
  分类树   GET  /api/categories/tree            -> [{id,name,children:[{id,name}]}]
  首页聚合 GET  /api/home                       -> {banners,hot,cn_show,kids,cn_drama,
                                                    movie_rec,short_drama,latest,rankings}
  分类列表 GET  /api/videos?category_id=&page=&page_size=&sort=(new|hot|rating)
  详情     GET  /api/videos/{video_id}           -> {title,description,cover_url,play_url,
                                                    director,actors,year,area,duration,
                                                    episodes:[{episode_num,title,play_url}]}
  搜索     GET  /api/search?keyword=&page=&page_size=
  热词     GET  /api/search/hot

播放解析：
  episodes[].play_url 形如 https://v.gsuus.com/play/{code}（分享页），
  分享页 JS 里有 `const vid = 'https://v.gsuus.com/play/{code}/index.m3u8';`
  取出该地址即为可直连的 HLS 主播放列表（实测无需 Referer）。
  旧版分享页用 `var main = "...";` 的形式，一并做兼容兜底。
"""

import re
import json
import time
import threading
from urllib.parse import quote

import requests
from requests.adapters import HTTPAdapter

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
API = HOST + "/api"

UA = ("Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) "
      "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1")
PLAY_UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"

TIMEOUT_API = 8
TIMEOUT_PLAY = 6

PAGE_SIZE = 36

TTL_CLASS = 21600
TTL_HOME = 600
TTL_LIST = 180
TTL_DETAIL_OK = 1800
TTL_DETAIL_EMPTY = 30
TTL_SEARCH = 300
TTL_PLAY = 3600

# 分类树兜底（/api/categories/tree 拉取失败时使用，值为线上真实 category_id）
FALLBACK_TREE = [
    {"id": 1, "name": "电影", "children": [
        {"id": 6, "name": "动作片"}, {"id": 7, "name": "喜剧片"},
        {"id": 8, "name": "爱情片"}, {"id": 9, "name": "科幻片"},
        {"id": 10, "name": "剧情片"}, {"id": 11, "name": "恐怖片"},
        {"id": 12, "name": "战争片"}, {"id": 20, "name": "动漫电影"},
    ]},
    {"id": 2, "name": "电视剧", "children": [
        {"id": 13, "name": "大陆剧"}, {"id": 14, "name": "欧美剧"},
        {"id": 15, "name": "港澳剧"}, {"id": 16, "name": "韩剧"},
        {"id": 21, "name": "日剧"}, {"id": 22, "name": "台湾剧"},
        {"id": 23, "name": "泰剧"},
    ]},
    {"id": 3, "name": "综艺", "children": [
        {"id": 37, "name": "大陆综艺"}, {"id": 38, "name": "日韩综艺"},
        {"id": 39, "name": "港台综艺"}, {"id": 40, "name": "欧美综艺"},
    ]},
    {"id": 4, "name": "动漫", "children": [
        {"id": 41, "name": "中国动漫"}, {"id": 42, "name": "日本动漫"},
        {"id": 43, "name": "欧美动漫"},
    ]},
    {"id": 999, "name": "少儿", "children": []},
    {"id": 24, "name": "记录片", "children": []},
    {"id": 30, "name": "体育赛事", "children": [
        {"id": 33, "name": "足球"}, {"id": 34, "name": "篮球"},
        {"id": 35, "name": "台球"}, {"id": 36, "name": "其他赛事"},
    ]},
    {"id": 31, "name": "短剧", "children": [
        {"id": 44, "name": "古装仙侠"}, {"id": 45, "name": "现代都市"},
        {"id": 46, "name": "穿越年代"}, {"id": 47, "name": "言情总裁"},
        {"id": 48, "name": "重生民国"}, {"id": 49, "name": "反转爽剧"},
        {"id": 50, "name": "脑洞悬疑"}, {"id": 51, "name": "擦边短剧"},
        {"id": 52, "name": "AI漫剧"},
    ]},
    {"id": 32, "name": "预告片", "children": []},
]

SORTS = [{"n": "最新", "v": "new"}, {"n": "最热", "v": "hot"}, {"n": "评分", "v": "rating"}]

# 站点后端对以下分类始终返回 total>0 但 items 为空（体育赛事 30 及其子类 33~36），
# 挂出来只会是个空 Tab，直接不展示；若日后恢复，删掉这行即可。
SKIP_CATS = {30}

# 首页聚合接口里各分区的展示顺序
HOME_SECTIONS = ["hot", "banners", "movie_rec", "cn_drama", "cn_show",
                 "short_drama", "kids", "latest", "rankings"]

TYPE_NAME_MAP = {
    "movie": "电影", "series": "电视剧", "show": "综艺", "variety": "综艺",
    "anime": "动漫", "short": "短剧", "documentary": "记录片",
    "sports": "体育赛事", "trailer": "预告片",
}

_Base = _BaseSpider if _BaseSpider is not None else object


class Spider(_Base):
    siteUrl = HOST
    headers = {
        'User-Agent': UA,
        'Accept': 'application/json, text/plain, */*',
        'Accept-Language': 'zh-CN,zh;q=0.9',
        'Referer': HOST + '/',
    }
    playHeaders = {
        'User-Agent': PLAY_UA,
        'Referer': HOST + '/',
    }

    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update(self.headers)
        self.session.headers['Connection'] = 'keep-alive'
        self.session.verify = False
        adapter = HTTPAdapter(pool_connections=20, pool_maxsize=40,
                              max_retries=0, pool_block=False)
        self.session.mount('http://', adapter)
        self.session.mount('https://', adapter)

        self._lock = threading.Lock()
        self._tree = None
        self._tree_time = 0
        self._class_data = None
        self._home_data = None
        self._home_time = 0
        self._list_cache = {}
        self._detail_cache = {}
        self._search_cache = {}
        self._play_cache = {}
        # 详情接口没有分类字段(category/category_id 恒为 null)，只能靠列表项的
        # category_name 回填，这里做一份 vod_id -> 分类名 的轻量映射
        self._type_cache = {}

    def init(self, extend=""):
        self.extend = extend or ""

    def getName(self):
        return "APTV影视"

    @staticmethod
    def isVideoFormat(url):
        u = str(url or '').lower()
        return '.m3u8' in u or '.mp4' in u or '.flv' in u or '.mkv' in u

    # ============================================================
    # HTTP
    # ============================================================
    def _get(self, url, referer='', timeout=TIMEOUT_API, ua=None):
        headers = {'Connection': 'keep-alive'}
        if ua:
            headers['User-Agent'] = ua
        if referer:
            headers['Referer'] = referer
        # 站点在连续请求下偶发连接重置，重试到 3 次降低误判为空数据的概率
        for attempt in range(3):
            try:
                r = self.session.get(url, timeout=timeout, headers=headers)
                if r.status_code in (429, 500, 502, 503, 504):
                    time.sleep(0.4 + attempt * 0.5)
                    continue
                if r.status_code != 200:
                    return None
                return r
            except Exception:
                if attempt < 2:
                    time.sleep(0.3 + attempt * 0.3)
        return None

    def _get_json(self, url, referer=HOST + '/', timeout=TIMEOUT_API):
        r = self._get(url, referer, timeout)
        if r is None:
            return None
        try:
            return json.loads(r.text)
        except Exception:
            return None

    def _get_text(self, url, referer=HOST + '/', timeout=TIMEOUT_PLAY, ua=None):
        r = self._get(url, referer, timeout, ua)
        return r.text if r is not None else ""

    @staticmethod
    def _cache_get(cache, key, ttl):
        item = cache.get(key)
        if item and time.time() - item[0] < ttl:
            return item[1]
        return None

    @staticmethod
    def _cache_set(cache, key, value, ttl):
        if len(cache) > 512:
            cache.clear()
        cache[key] = (time.time(), value)

    # ============================================================
    # 字段映射
    # ============================================================
    @staticmethod
    def _pic(url):
        u = str(url or '').strip()
        if not u:
            return ''
        if u.startswith('//'):
            return 'https:' + u
        if u.startswith('/'):
            return HOST + u
        return u

    def _to_vod(self, it):
        """列表项 -> TVBox vod"""
        if not isinstance(it, dict):
            return None
        vid = str(it.get('id') or '').strip()
        name = str(it.get('title') or '').strip()
        if not vid or not name:
            return None

        cat = str(it.get('category_name') or '').strip()
        sub = str(it.get('category_sub') or '').strip()
        if not cat:
            cat = TYPE_NAME_MAP.get(str(it.get('video_type') or ''), '')

        type_name = (cat + '/' + sub) if (cat and sub) else (cat or sub)
        if type_name:
            if len(self._type_cache) > 2048:
                self._type_cache.clear()
            self._type_cache[vid] = type_name

        remarks = str(it.get('duration') or '').strip()
        if not remarks:
            bits = []
            year = it.get('year')
            if year:
                bits.append(str(year))
            area = str(it.get('area') or '').strip()
            if area:
                bits.append(area)
            remarks = ' '.join(bits)

        return {
            'vod_id': vid,
            'vod_name': name,
            'vod_pic': self._pic(it.get('cover_url')),
            'vod_remarks': remarks,
            'type_name': type_name,
            'vod_year': str(it.get('year') or ''),
            'vod_area': str(it.get('area') or ''),
        }

    def _to_vod_list(self, items, limit=None):
        out, seen = [], set()
        for it in items or []:
            v = self._to_vod(it)
            if not v or v['vod_id'] in seen:
                continue
            seen.add(v['vod_id'])
            out.append(v)
            if limit and len(out) >= limit:
                break
        return out

    # ============================================================
    # 分类树
    # ============================================================
    def _load_tree(self):
        now = time.time()
        with self._lock:
            if self._tree and now - self._tree_time < TTL_CLASS:
                return self._tree

        tree = self._get_json(API + "/categories/tree")
        if not isinstance(tree, list) or not tree:
            with self._lock:
                return self._tree or FALLBACK_TREE

        clean = []
        for g in tree:
            if not isinstance(g, dict) or not g.get('id'):
                continue
            kids = []
            for k in (g.get('children') or []):
                if isinstance(k, dict) and k.get('id') and k.get('name'):
                    kids.append({'id': int(k['id']), 'name': str(k['name']).strip()})
            clean.append({'id': int(g['id']), 'name': str(g.get('name') or '').strip(), 'children': kids})

        if not clean:
            with self._lock:
                return self._tree or FALLBACK_TREE

        with self._lock:
            self._tree = clean
            self._tree_time = now
            self._class_data = None
        return clean

    def _build_class(self):
        tree = self._load_tree()
        classes, filters = [], {}
        for g in tree:
            if g['id'] in SKIP_CATS:
                continue
            tid = str(g['id'])
            classes.append({'type_id': tid, 'type_name': g['name']})
            fs = []
            if g['children']:
                vals = [{'n': '全部', 'v': ''}]
                vals += [{'n': k['name'], 'v': str(k['id'])} for k in g['children']]
                fs.append({'key': 'cate', 'name': '分类', 'value': vals})
            fs.append({'key': 'sort', 'name': '排序', 'value': SORTS})
            filters[tid] = fs
        return classes, filters

    # ============================================================
    # 首页
    # ============================================================
    def homeContent(self, filter=False):
        try:
            if self._class_data is None:
                self._class_data = self._build_class()
            classes, filters = self._class_data
            return {'class': classes, 'filters': filters}
        except Exception:
            classes = [{'type_id': str(g['id']), 'type_name': g['name']} for g in FALLBACK_TREE]
            return {'class': classes}

    def _load_home(self):
        now = time.time()
        with self._lock:
            if self._home_data and now - self._home_time < TTL_HOME:
                return self._home_data

        data = self._get_json(API + "/home")
        if not isinstance(data, dict):
            return self._home_data or {}

        with self._lock:
            self._home_data = data
            self._home_time = now
        return data

    def homeVideoContent(self):
        try:
            data = self._load_home()
            items = []
            for key in HOME_SECTIONS:
                sec = data.get(key)
                if isinstance(sec, list):
                    items.extend(sec)
            vod_list = self._to_vod_list(items, limit=60)
            if vod_list:
                return {'list': vod_list}
            # 首页接口异常时退化到"最新"列表
            r = self._get_json(API + "/videos?page=1&page_size=36&sort=new")
            if isinstance(r, dict):
                return {'list': self._to_vod_list(r.get('items'), limit=36)}
            return {'list': []}
        except Exception:
            return {'list': []}

    # ============================================================
    # 分类列表
    # ============================================================
    @staticmethod
    def _empty_category(page=1):
        return {'list': [], 'page': page, 'pagecount': 1,
                'limit': PAGE_SIZE, 'total': 0}

    def categoryContent(self, tid, pg, filter, extend):
        try:
            page = max(1, int(pg or 1))
        except Exception:
            page = 1
        tid = str(tid or '').strip()

        try:
            ext = extend or {}
            if isinstance(ext, str):
                try:
                    ext = json.loads(ext)
                except Exception:
                    ext = {}
            if not isinstance(ext, dict):
                ext = {}

            cid = str(ext.get('cate') or '').strip() or tid
            if not cid:
                return self._empty_category(page)

            sort = str(ext.get('sort') or '').strip()
            if sort not in ('new', 'hot', 'rating'):
                sort = ''

            ckey = "%s|%s|%s" % (cid, sort, page)
            cached = self._cache_get(self._list_cache, ckey, TTL_LIST)
            if cached is not None:
                return cached

            url = "%s/videos?category_id=%s&page=%d&page_size=%d" % (API, quote(cid), page, PAGE_SIZE)
            if sort:
                url += "&sort=" + sort

            data = self._get_json(url)
            if not isinstance(data, dict):
                return self._empty_category(page)

            items = data.get('items') or []
            total = int(data.get('total') or 0)
            size = int(data.get('page_size') or PAGE_SIZE) or PAGE_SIZE
            pagecount = (total + size - 1) // size if total else 1

            result = {
                'list': self._to_vod_list(items),
                'page': page,
                'pagecount': max(1, pagecount),
                'limit': size,
                'total': total,
            }
            if result['list']:
                self._cache_set(self._list_cache, ckey, result, TTL_LIST)
            return result
        except Exception:
            return self._empty_category(page)

    # ============================================================
    # 详情
    # ============================================================
    @staticmethod
    def _clean_id(ids):
        if isinstance(ids, (list, tuple)):
            raw = ids[0] if ids else ''
        else:
            raw = ids
        raw = str(raw or '').split(',')[0].strip()
        m = re.search(r'(\d+)', raw)
        return m.group(1) if m else ''

    def detailContent(self, ids):
        vid = self._clean_id(ids)
        if not vid:
            return {'list': []}

        cached = self._cache_get(self._detail_cache, vid, TTL_DETAIL_OK)
        if cached is not None:
            return cached

        data = self._get_json("%s/videos/%s" % (API, vid))
        if data is None:
            # 网络/限流导致的失败不写缓存，下次请求重试
            return {'list': []}
        if not isinstance(data, dict) or not data.get('title'):
            self._cache_set(self._detail_cache, vid, {'list': []}, TTL_DETAIL_EMPTY)
            return {'list': []}

        episodes = self._sorted_episodes(data.get('episodes'))
        if not episodes:
            # 兜底：部分片目（多为单片/正片类）episodes 为空，播放地址只在顶层 play_url
            top = str(data.get('play_url') or '').replace('\\/', '/').strip()
            if top:
                episodes = [{'title': str(data.get('duration') or '').strip() or '正片',
                             'play_url': top}]
        if not episodes:
            self._cache_set(self._detail_cache, vid, {'list': []}, TTL_DETAIL_EMPTY)
            return {'list': []}

        play_items = []
        for i, ep in enumerate(episodes):
            name = str(ep.get('title') or '').strip() or ('第%d集' % (i + 1))
            url = str(ep.get('play_url') or '').replace('\\/', '/').strip()
            if not url:
                continue
            play_items.append("%s$%s" % (name, url))
        if not play_items:
            self._cache_set(self._detail_cache, vid, {'list': []}, TTL_DETAIL_EMPTY)
            return {'list': []}

        name = str(data.get('title') or '').strip()
        duration = str(data.get('duration') or '').strip()
        remarks = duration or ('全%d集' % len(play_items))

        vod = {
            'vod_id': vid,
            'vod_name': name,
            'vod_pic': self._pic(data.get('cover_url')),
            'vod_year': str(data.get('year') or ''),
            'vod_area': str(data.get('area') or ''),
            'vod_remarks': remarks,
            'type_name': (self._type_cache.get(vid)
                          or TYPE_NAME_MAP.get(str(data.get('video_type') or ''), '')),
            'vod_director': str(data.get('director') or '').strip(),
            'vod_actor': str(data.get('actors') or '').strip(),
            'vod_content': str(data.get('description') or '').strip()[:1500],
            'vod_play_from': 'APTV线路',
            'vod_play_url': '#'.join(play_items),
        }

        result = {'list': [vod]}
        self._cache_set(self._detail_cache, vid, result, TTL_DETAIL_OK)
        return result

    @staticmethod
    def _sorted_episodes(eps):
        if not isinstance(eps, list):
            return []
        out = [e for e in eps if isinstance(e, dict) and e.get('play_url')]

        def _key(e):
            try:
                return int(e.get('episode_num') or 0)
            except Exception:
                return 0

        out.sort(key=_key)
        return out

    # ============================================================
    # 播放解析
    # ============================================================
    def _resolve_play(self, url):
        """分享页 -> m3u8 直链"""
        url = str(url or '').strip()
        if not url:
            return ''
        if '.m3u8' in url.lower() or '.mp4' in url.lower():
            return url

        cached = self._cache_get(self._play_cache, url, TTL_PLAY)
        if cached:
            return cached

        text = self._get_text(url, referer=HOST + '/', ua=PLAY_UA)
        if not text:
            return ''

        real = ''

        # 新版分享页：const vid = 'https://.../index.m3u8';
        m = re.search(r"""vid\s*=\s*['"]([^'"]+\.m3u8[^'"]*)['"]""", text)
        if m:
            real = m.group(1).replace('\\/', '/').strip()
        if not real:
            m = re.search(r"""['"](https?://[^'"]+?\.m3u8[^'"]*)['"]""", text)
            if m:
                real = m.group(1).replace('\\/', '/').strip()
        if not real:
            # 旧版分享页：var main = "相对路径";
            m = re.search(r"""var\s+main\s*=\s*['"]([^'"]+)['"]""", text)
            if m:
                path = m.group(1).replace('\\/', '/').strip()
                if path.startswith('http'):
                    real = path
                elif path:
                    base = re.match(r'(https?://[^/]+)', url)
                    if base:
                        real = base.group(1) + ('' if path.startswith('/') else '/') + path

        if real:
            self._cache_set(self._play_cache, url, real, TTL_PLAY)
        return real

    def playerContent(self, flag, id, vipFlags):
        raw = str(id or '').strip()
        if not raw:
            return {'parse': 0, 'url': ''}

        # 直链
        if '.m3u8' in raw.lower() or '.mp4' in raw.lower():
            return {'parse': 0, 'url': raw, 'header': dict(self.playHeaders)}

        # 分享页（详情给出的标准形态）
        if '/play/' in raw or 'gsuus.com' in raw:
            real = self._resolve_play(raw)
            if real:
                return {'parse': 0, 'url': real, 'header': dict(self.playHeaders)}
            return {'parse': 1, 'url': raw, 'header': dict(self.playHeaders)}

        # 兜底：纯数字 id 或含 id 的链接
        vid = self._clean_id(raw)
        if vid:
            detail = self.detailContent([vid])
            if detail.get('list'):
                play_url = detail['list'][0].get('vod_play_url') or ''
                for item in play_url.split('#'):
                    parts = item.split('$', 1)
                    if len(parts) == 2 and parts[1]:
                        real = self._resolve_play(parts[1])
                        if real:
                            return {'parse': 0, 'url': real, 'header': dict(self.playHeaders)}
                        break

        return {'parse': 1, 'url': raw, 'header': dict(self.playHeaders)}

    # ============================================================
    # 搜索
    # ============================================================
    def searchContent(self, keyword, quick=False, pg=1):
        raw = (keyword or '').strip()
        if not raw:
            return {'list': [], 'msg': '请输入搜索关键词'}
        try:
            page = max(1, int(pg or 1))
        except Exception:
            page = 1

        ckey = "%s|%s" % (page, raw)
        cached = self._cache_get(self._search_cache, ckey, TTL_SEARCH)
        if cached is not None:
            return cached

        result = {'list': [], 'msg': '未找到相关内容'}
        data = self._get_json(
            "%s/search?keyword=%s&page=%d&page_size=%d" % (API, quote(raw), page, PAGE_SIZE)
        )
        if isinstance(data, dict):
            vod_list = self._to_vod_list(data.get('items'))
            if vod_list:
                total = int(data.get('total') or len(vod_list))
                size = int(data.get('page_size') or PAGE_SIZE) or PAGE_SIZE
                result = {
                    'list': vod_list,
                    'page': page,
                    'pagecount': max(1, (total + size - 1) // size),
                    'limit': size,
                    'total': total,
                }

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
