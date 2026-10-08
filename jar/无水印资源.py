# -*- coding: utf-8 -*-
# ============================================================
# 无水印资源 FongMi/影视壳 Python 爬虫
# 站点: https://wsyzy.cc/     采集接口: https://wsyzy.cc/api.php/provide/vod/
#
# █ 接口要点(2026-10-07 实测):
#   1. 60 个子分类(动作/喜剧/科幻/国产剧/韩剧/综艺/动漫/4K电影/Netflix/伦理等)
#      大类 t=1/2/3/4 无数据, 必须用子分类 ID
#   2. ac=videolist 单请求即返回含封面/年份/演员/导演/简介的完整字段
#   3. 搜索: ac=videolist&wd= 被禁(返回"暂不支持搜索"),
#      但 index.php/ajax/suggest?mid=1&wd= 可用(返回 id/name/pic),
#      二次调 ac=detail&ids= 补全
#   4. 播放: wsym3u8 直链, 主 m3u8 带 #EXT-X-STREAM-INF 多码率变体需选最高码率,
#      子 m3u8 含广告碎片(0.8s 短片), 进程内清洗 → file:// 预清洗模式
#   5. SSL: 禁用证书校验(部分网络环境证书问题)
# ============================================================

import json
import re
import time
import threading
import os
import tempfile
import hashlib
import ssl
from urllib.parse import urlencode, urljoin, unquote, urlparse, parse_qs, urlunparse

try:
    import sys
    sys.path.append('..')
    from base.spider import Spider as BaseSpider
except ImportError:
    class BaseSpider(object):
        pass

# ---------------- 配置区 ----------------
API = "https://wsyzy.cc/api.php/provide/vod/"
SITE = "https://wsyzy.cc/"
UA = ('Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
      'AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36')

TTL_HOME = 600
TTL_CAT = 300
TTL_DETAIL = 900
TTL_PLAY = 1800
TTL_SEARCH = 300

# 4 个大类，子分类由 _build_filters 注入首页筛选菜单
CLASSES = [
    {"type_id": "1", "type_name": "电影"},
    {"type_id": "2", "type_name": "电视剧"},
    {"type_id": "3", "type_name": "综艺"},
    {"type_id": "4", "type_name": "动漫"},
]

# 子分类映射(按大类归类)
CATEGORY_MAP = {
    "1": {"type_name": "电影", "children": [
        ("6", "动作片"), ("7", "喜剧片"), ("8", "爱情片"), ("9", "科幻片"),
        ("10", "恐怖片"), ("11", "剧情片"), ("12", "战争片"), ("20", "纪录片"),
        ("51", "预告片"), ("62", "4K电影"), ("70", "邵氏电影"), ("71", "Netflix电影"),
    ]},
    "2": {"type_name": "电视剧", "children": [
        ("13", "国产剧"), ("14", "欧美剧"), ("15", "韩剧"), ("16", "日剧"),
        ("17", "港剧"), ("18", "台剧"), ("19", "泰剧"), ("23", "海外剧"),
        ("72", "Netflix自制剧"),
    ]},
    "3": {"type_name": "综艺", "children": [
        ("25", "大陆综艺"), ("26", "日韩综艺"), ("27", "港台综艺"), ("28", "欧美综艺"),
        ("47", "演唱会"), ("48", "体育赛事"), ("49", "篮球"), ("50", "足球"),
        ("52", "斯诺克"), ("53", "影视解说"), ("74", "预告解说"), ("75", "科普学习"),
    ]},
    "4": {"type_name": "动漫", "children": [
        ("29", "国产动漫"), ("30", "日韩动漫"), ("31", "欧美动漫"), ("39", "动画片"),
        ("44", "港台动漫"), ("45", "海外动漫"), ("63", "有声动漫"), ("76", "漫剧"),
        ("60", "两性课堂"),
    ]},
}


def _build_filters(tid):
    children = CATEGORY_MAP.get(tid, {}).get("children", [])
    class_values = [{"n": "全部", "v": ""}]
    for cid, cname in children:
        class_values.append({"n": cname, "v": cid})
    return [{"key": "class", "name": "类型", "value": class_values}]


ALL_FILTERS = {tid: _build_filters(tid) for tid in CATEGORY_MAP}


def _clean_html(s):
    if not s:
        return ""
    s = re.sub(r"<[^>]+>", "", str(s))
    return s.replace("&nbsp;", " ").replace("&amp;", "&").strip()


def _norm_list(it):
    """列表页条目; 图片域名降级 http 以兼容壳内网络"""
    pic = str(it.get("vod_pic") or "")
    # img1.wsyzy.org 在部分网络/壳环境下 https 证书被拦截,
    # 降级为 http 提升图片加载成功率(内容本身无敏感信息)
    if pic.startswith("https://img1.wsyzy.org"):
        pic = pic.replace("https://", "http://", 1)
    return {
        "vod_id": str(it.get("vod_id") or ""),
        "vod_name": str(it.get("vod_name") or ""),
        "vod_pic": pic,
        "vod_remarks": str(it.get("vod_remarks") or ""),
    }


def _norm_detail(d):
    """详情页条目"""
    pic = str(d.get("vod_pic") or "")
    if pic.startswith("https://img1.wsyzy.org"):
        pic = pic.replace("https://", "http://", 1)
    return {
        "vod_id": str(d.get("vod_id") or ""),
        "vod_name": str(d.get("vod_name") or ""),
        "vod_pic": pic,
        "type_name": str(d.get("type_name") or ""),
        "vod_year": str(d.get("vod_year") or ""),
        "vod_area": str(d.get("vod_area") or ""),
        "vod_remarks": str(d.get("vod_remarks") or ""),
        "vod_actor": str(d.get("vod_actor") or ""),
        "vod_director": str(d.get("vod_director") or ""),
        "vod_content": _clean_html(d.get("vod_content")),
        "vod_play_from": str(d.get("vod_play_from") or "无水印").replace("wsym3u8", "无水印"),
        "vod_play_url": str(d.get("vod_play_url") or ""),
    }


# ============================================================
# ============ m3u8 去广告引擎(移植自量子资源) ============
# ============================================================
class M3U8Cleaner(object):
    AD_DUR_FP = (
        (5.567, 2.933, 5.7, 3.333, 1.533),
        (6.667, 2.133, 3.233, 3.733),
        (4.6, 5.533, 0.233),
    )
    FP_TOL = 0.20
    FRAME_GRID = 0.04
    GRID_TOL = 0.02
    GRID_DISABLE_RATIO = 0.30
    MAX_REMOVE_RATIO = 0.15
    GROUP_MAX_ITEMS = 12
    EXPAND_GROUPS = True
    BLOCK_TOL = 0.35
    BASE_DUR_WIN = (3.8, 4.2)

    GRID_CANDIDATES = (0.04, 0.02, 1 / 24.0, 1 / 30.0, 1 / 60.0,
                       1001 / 24000.0, 1001 / 30000.0, 1 / 48.0)
    GRID_FIT_TOL = 0.002
    GRID_MIN_RATIO = 0.90
    GRID_TIE = 0.05
    USE_MULTI_GRID = True

    USE_COUNTER_CHAIN = True
    COUNTER_MIN_RATIO = 0.50

    AD_PATH_KEYWORDS = ('/adjump/', '/ad/', '/ads/', '/gg/')
    USE_PATH_KEYWORD = True

    def __init__(self, debug=False):
        self.debug = debug
        self.last_stats = None

    @staticmethod
    def _normalize_lines(lines):
        out, i, n = [], 0, len(lines)
        while i < n:
            if (lines[i].startswith('#EXTINF') and i + 2 < n
                    and lines[i + 1] == '#EXT-X-DISCONTINUITY'
                    and not lines[i + 2].startswith('#')):
                out.extend((lines[i + 1], lines[i], lines[i + 2]))
                i += 3
            else:
                out.append(lines[i])
                i += 1
        return out

    def _split_playlist(self, content):
        lines = self._normalize_lines(
            [l.strip() for l in content.splitlines() if l.strip()])
        header, i = [], 0
        while i < len(lines) and lines[i].startswith('#EXT') and \
                not lines[i].startswith(('#EXTINF', '#EXT-X-DISCONTINUITY')):
            header.append(lines[i])
            i += 1
        footer, end = [], len(lines)
        for j in range(len(lines) - 1, i - 1, -1):
            if lines[j] == '#EXT-X-ENDLIST':
                footer, end = [lines[j]], j
                break
        items, extras, disc, k = [], [], False, i
        while k < end:
            line = lines[k]
            if line == '#EXT-X-DISCONTINUITY':
                disc = True
            elif line.startswith('#EXTINF') and k + 1 < end and not lines[k + 1].startswith('#'):
                try:
                    dur = float(line.split(':', 1)[1].split(',')[0])
                except (ValueError, IndexError):
                    dur = 0.0
                items.append({'dur': dur, 'inf': line, 'uri': lines[k + 1],
                              'disc': disc, 'extras': extras})
                extras, disc = [], False
                k += 1
            elif line.startswith('#'):
                extras.append(line)
            k += 1
        return header, items, footer

    def _detect_duration_fp(self, items):
        durs = [it['dur'] for it in items]
        ads = set()
        for fp in self.AD_DUR_FP:
            n = len(fp)
            for i in range(len(durs) - n + 1):
                if all(abs(durs[i + j] - fp[j]) <= self.FP_TOL for j in range(n)):
                    ads.update(range(i, i + n))
        return ads

    def _grid_is_valid(self, items):
        if not items:
            return False
        non_grid = 0
        for it in items:
            d = it['dur']
            if d > 0:
                q = d / self.FRAME_GRID
                if abs(q - round(q)) > self.GRID_TOL:
                    non_grid += 1
        return non_grid / len(items) <= self.GRID_DISABLE_RATIO

    def _detect_frame_grid(self, items):
        durs = [it['dur'] for it in items]
        ads = set()
        for i, d in enumerate(durs):
            if d <= 0:
                continue
            q = d / self.FRAME_GRID
            if abs(q - round(q)) > self.GRID_TOL:
                ads.add(i)
        return ads

    def _pick_grid(self, items):
        durs = [it['dur'] for it in items if it['dur'] > 0]
        if len(durs) < 20:
            return None, 0.0, set()
        ratios = []
        for g in self.GRID_CANDIDATES:
            ok = sum(1 for d in durs if abs(d / g - round(d / g)) * g <= self.GRID_FIT_TOL)
            ratios.append((ok / len(durs), g))
        ratios.sort(reverse=True)
        best_ratio = ratios[0][0]
        if best_ratio < self.GRID_MIN_RATIO:
            return None, best_ratio, set()
        tied = [g for r, g in ratios if best_ratio - r <= self.GRID_TIE]
        best_g = max(tied)
        ads = set()
        for i, it in enumerate(items):
            d = it['dur']
            if d > 0 and abs(d / best_g - round(d / best_g)) * best_g > self.GRID_FIT_TOL:
                ads.add(i)
        return best_g, best_ratio, ads

    @staticmethod
    def _extract_counter(uri):
        name = uri.rsplit('/', 1)[-1].strip()
        name = name.split('?', 1)[0]
        if name.lower().endswith('.ts'):
            name = name[:-3]
        m = re.search(r'(\d+)$', name)
        return int(m.group(1)) if m else None

    def _detect_counter_chain(self, items, groups):
        if not self.USE_COUNTER_CHAIN or len(groups) < 2:
            return set()
        info = []
        for s, e in groups:
            cnts = [c for c in (self._extract_counter(items[i]['uri'])
                                for i in range(s, e)) if c is not None]
            info.append({'first': cnts[0] if cnts else None,
                         'last': cnts[-1] if cnts else None,
                         'n': e - s, 'has': len(cnts) > 0})
        if not all(x['has'] for x in info):
            return set()
        m = len(info)
        dp, prev = [1] * m, [-1] * m
        for a in range(m):
            for b in range(a):
                if info[a]['first'] == info[b]['last'] + 1 and dp[b] + 1 > dp[a]:
                    dp[a], prev[a] = dp[b] + 1, b
        best = max(range(m), key=lambda x: (dp[x], info[x]['n']))
        chain = [False] * m
        k = best
        while k != -1:
            chain[k] = True
            k = prev[k]
        total_n = sum(x['n'] for x in info)
        main_n = sum(info[x]['n'] for x in range(m) if chain[x])
        if total_n <= 0 or main_n / total_n < self.COUNTER_MIN_RATIO:
            return set()
        ads = set()
        for x in range(m):
            if not chain[x]:
                s, e = groups[x]
                ads |= set(range(s, e))
        return ads

    def _detect_path_keyword(self, items):
        if not self.USE_PATH_KEYWORD or not self.AD_PATH_KEYWORDS:
            return set()
        ads = set()
        for i, it in enumerate(items):
            u = it['uri'].lower()
            if any(kw in u for kw in self.AD_PATH_KEYWORDS):
                ads.add(i)
        return ads

    def _disc_groups(self, items):
        out, start = [], 0
        for i, it in enumerate(items):
            if it['disc'] and i > start:
                out.append((start, i))
                start = i
        if len(items) > start:
            out.append((start, len(items)))
        return out

    def _expand_to_groups(self, ads, groups):
        out = set(ads)
        for s, e in groups:
            span = set(range(s, e))
            if ads & span and e - s <= self.GROUP_MAX_ITEMS:
                out |= span
        return out

    @staticmethod
    def _has_base_dur(items, s, e):
        lo, hi = M3U8Cleaner.BASE_DUR_WIN
        return any(lo <= items[i]['dur'] <= hi for i in range(s, e))

    def _absorb_blocks(self, ads, groups, items):
        blocks = [sum(fp) for fp in self.AD_DUR_FP[:2]]
        out = set(ads)
        changed, rounds = True, 0
        while changed and rounds < 5:
            changed = False
            rounds += 1
            for idx, (s, e) in enumerate(groups):
                if not (set(range(s, e)) & out):
                    continue
                for j in (idx - 1, idx + 1):
                    if 0 <= j < len(groups):
                        s2, e2 = groups[j]
                        if set(range(s2, e2)) & out or self._has_base_dur(items, s2, e2):
                            continue
                        d2 = sum(items[i]['dur'] for i in range(s2, e2))
                        if any(abs(d2 - bd) <= self.BLOCK_TOL for bd in blocks):
                            out |= set(range(s2, e2))
                            changed = True
        return out

    @staticmethod
    def _rewrite_extra(line, base_url):
        m = re.search(r'URI="([^"]+)"', line) if 'URI="' in line else None
        if m and not m.group(1).startswith(('http://', 'https://')):
            return line.replace('URI="%s"' % m.group(1),
                                'URI="%s"' % urljoin(base_url, m.group(1)))
        return line

    @staticmethod
    def _abs_uri(uri, base_url):
        return uri if uri.startswith(('http://', 'https://')) else urljoin(base_url, uri)

    def clean_text(self, content, base_url):
        header, items, footer = self._split_playlist(content)
        if not items:
            return content
        total = sum(it['dur'] for it in items)

        fp_ads = self._detect_duration_fp(items)

        grid_rate = None
        if self.USE_MULTI_GRID:
            grid_rate, grid_ratio, grid_ads = self._pick_grid(items)
            grid_disabled = not grid_ads and grid_rate is None
        else:
            if self._grid_is_valid(items):
                grid_ads = self._detect_frame_grid(items)
                grid_disabled = False
            else:
                grid_ads = set()
                grid_disabled = True

        groups = self._disc_groups(items)
        counter_ads = self._detect_counter_chain(items, groups)
        path_ads = self._detect_path_keyword(items)

        ads = fp_ads | grid_ads | counter_ads | path_ads

        # 末尾残片保护: 最后一片若远短于均值(流结束残留帧, 非广告), 从广告集移除
        if items and (len(items) - 1) in ads:
            avg_dur = total / len(items)
            if items[-1]['dur'] < avg_dur * 0.5:
                ads.discard(len(items) - 1)

        expanded = False
        absorbed = False
        if ads and self.EXPAND_GROUPS:
            new_ads = self._expand_to_groups(ads, groups)
            if new_ads != ads:
                ads, expanded = new_ads, True
            new_ads = self._absorb_blocks(ads, groups, items)
            if new_ads != ads:
                ads, absorbed = new_ads, True

        removed = sum(items[i]['dur'] for i in ads)
        over_limit = False
        if total > 0 and removed / total > self.MAX_REMOVE_RATIO:
            ads, removed, over_limit = set(), 0.0, True

        self.last_stats = {
            'total_items': len(items), 'total_dur': round(total, 1),
            'removed_items': len(ads), 'removed_dur': round(removed, 1),
            'fp_hits': len(fp_ads), 'grid_hits': len(grid_ads),
            'counter_hits': len(counter_ads), 'path_hits': len(path_ads),
            'grid_rate': grid_rate, 'group_expanded': expanded,
            'block_absorbed': absorbed, 'over_limit': over_limit,
        }

        body, maxdur, pending = [], 0.0, False
        for i, it in enumerate(items):
            if i in ads:
                pending = True
                continue
            if (it['disc'] or pending) and body:
                body.append('#EXT-X-DISCONTINUITY')
            pending = False
            for line in it['extras']:
                body.append(self._rewrite_extra(line, base_url))
            maxdur = max(maxdur, it['dur'])
            body.append(it['inf'])
            body.append(self._abs_uri(it['uri'], base_url))
        out = [self._rewrite_extra(l, base_url) for l in header
               if not l.startswith('#EXT-X-TARGETDURATION')]
        if not out or not out[0].startswith('#EXTM3U'):
            out.insert(0, '#EXTM3U')
        for tag, val in (('#EXT-X-VERSION', '#EXT-X-VERSION:3'),
                         ('#EXT-X-PLAYLIST-TYPE', '#EXT-X-PLAYLIST-TYPE:VOD'),
                         ('#EXT-X-MEDIA-SEQUENCE', '#EXT-X-MEDIA-SEQUENCE:0')):
            if not any(l.startswith(tag) for l in out):
                out.append(val)
        out.append('#EXT-X-TARGETDURATION:%d' % max(1, int(maxdur + 0.999)))
        out.extend(body)
        out.extend(footer if footer else ['#EXT-X-ENDLIST'])

        if self.debug:
            st = self.last_stats
            head = ['# ==== m3u8 去广告调试 ====',
                    '# 总片数 %d  总时长 %.1fs  删除 %d 片 / %.1fs (%.2f%%)' % (
                        st['total_items'], st['total_dur'], st['removed_items'],
                        st['removed_dur'],
                        st['removed_dur'] / st['total_dur'] * 100 if st['total_dur'] else 0),
                    '# 指纹 %d  网格 %d  计数器 %d  路径 %d' % (
                        st['fp_hits'], st['grid_hits'],
                        st['counter_hits'], st['path_hits']),
                    '# 帧网格 %s  组扩展 %s  块吸附 %s  保护线 %s' % (
                        ('%.4g' % st['grid_rate']) if st.get('grid_rate') else 'off',
                        st['group_expanded'], st.get('block_absorbed'), st['over_limit']),
                    '# ==== end ====']
            out = head + out
        return '\n'.join(out) + '\n'

    @staticmethod
    def pick_variant(content, base_url):
        lines = [l.strip() for l in content.splitlines() if l.strip()]
        best, best_bw = None, -1
        for i, line in enumerate(lines):
            if not line.startswith('#EXT-X-STREAM-INF'):
                continue
            m = re.search(r'BANDWIDTH=(\d+)', line)
            bw = int(m.group(1)) if m else 0
            for j in range(i + 1, len(lines)):
                if not lines[j].startswith('#'):
                    if bw >= best_bw:
                        best, best_bw = urljoin(base_url, lines[j]), bw
                    break
        return best

    def clean_url(self, url, fetch_fn=None, max_hops=3):
        if fetch_fn is None:
            fetch_fn = self._default_fetch
        raw = fetch_fn(url)
        if not raw:
            return None, '获取 m3u8 失败'
        if not raw.lstrip().startswith('#EXTM3U'):
            return None, '上游返回非 m3u8: %s' % raw[:120]
        base_url = url.rsplit('/', 1)[0] + '/'
        hops = 0
        while '#EXT-X-STREAM-INF' in raw and hops < max_hops:
            variant = self.pick_variant(raw, base_url)
            if not variant:
                break
            sub = fetch_fn(variant)
            if not sub or not sub.lstrip().startswith('#EXTM3U'):
                break
            raw = sub
            base_url = variant.rsplit('/', 1)[0] + '/'
            hops += 1
        return self.clean_text(raw, base_url), None

    @staticmethod
    def _default_fetch(url):
        try:
            import urllib.request
            ctx = ssl.create_default_context()
            ctx.check_hostname = False
            ctx.verify_mode = ssl.CERT_NONE
            req = urllib.request.Request(url, headers={
                'User-Agent': ('Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
                               'AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36')})
            with urllib.request.urlopen(req, timeout=15, context=ctx) as r:
                if getattr(r, 'status', 200) != 200:
                    return None
                return r.read().decode('utf-8', 'ignore')
        except Exception:
            return None


# ============================================================
# Spider (类式主入口, 对齐量子资源)
# ============================================================
class Spider(BaseSpider):

    def __init__(self):
        try:
            super().__init__()
        except Exception:
            pass

        self._api = API
        self._lock = threading.Lock()
        self._home_cache = {}
        self._cat_cache = {}
        self._detail_cache = {}
        self._search_cache = {}
        self._cleaner = M3U8Cleaner(debug=False)
        # wsyzy 源正片时长高度均匀(2.0s), 少量 1.8/1.9/2.1s 是编码容差而非广告,
        # 禁用多网格择优(避免 GRID_FIT_TOL=0.002 误伤容差片),
        # 直接用单网格 25fps + GRID_TOL=0.5 容差; FP/counter/path 判据仍正常工作
        self._cleaner.USE_MULTI_GRID = False
        self._cleaner.GRID_TOL = 0.5
        self._clean_cache = {'url': None, 'body': None}
        self.DEBUG = False

    def getName(self):
        return '无水印资源'

    def init(self, extend=""):
        if extend:
            ext = str(extend).strip()
            if ext.startswith('http'):
                self._api = ext.rstrip('/')

    def _log(self, *args):
        if self.DEBUG:
            try:
                print('[无水印]', *args)
            except Exception:
                pass

    # ================= SSL 上下文 =================
    @staticmethod
    def _ssl_ctx():
        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
        return ctx

    # ================= HTTP GET =================
    def _get(self, params, timeout=10):
        url = self._api + '?' + urlencode(params)
        try:
            import urllib.request
            req = urllib.request.Request(url, headers={
                'User-Agent': UA,
                'Accept': 'application/json, text/plain, */*',
            }, method='GET')
            with urllib.request.urlopen(req, timeout=timeout, context=self._ssl_ctx()) as r:
                text = r.read().decode('utf-8', 'ignore')
                if getattr(r, 'status', 200) != 200:
                    return {}
                return json.loads(text) or {}
        except Exception as e:
            self._log('请求失败:', repr(e)[:100])
            return {}

    # ================= 缓存工具 =================
    @staticmethod
    def _cache_get(cache, key, ttl):
        item = cache.get(key)
        if item and time.time() - item[0] < ttl:
            return item[1]
        return None

    @staticmethod
    def _cache_set(cache, key, val, ttl):
        if len(cache) > 512:
            cache.clear()
        cache[key] = (time.time(), val)

    # ================= 数据解析 =================
    def _parse_list(self, items):
        return [_norm_list(it) for it in (items or []) if it]

    # ========== 去广告清洗核心 ==========
    def _do_clean(self, src):
        try:
            parsed = urlparse(src)
            q = parse_qs(parsed.query)
            for k in ('_', 't', 'timestamp', 'rand', 'v', 'cb', 'callback'):
                q.pop(k, None)
            norm = urlunparse(parsed._replace(query=urlencode(q, doseq=True)))
        except Exception:
            norm = src

        if self._clean_cache['url'] == norm and self._clean_cache['body']:
            return self._clean_cache['body'], None

        _last_err = ['获取 m3u8 失败']

        def _fetch(u):
            # 通道1: 壳 fetch
            try:
                resp = self.fetch(u, headers={
                    'User-Agent': UA,
                    'Referer': SITE,
                    'Accept': '*/*',
                })
                if resp is not None:
                    if isinstance(resp, str) and resp.strip().startswith('#EXTM3U'):
                        return resp
                    body = getattr(resp, 'text', None)
                    if (getattr(resp, 'status_code', 0) == 200
                            and body and body.strip().startswith('#EXTM3U')):
                        return body
            except Exception:
                pass
            # 通道2: urllib 直连(兜底, 禁用 SSL 证书校验)
            try:
                import urllib.request
                ctx = self._ssl_ctx()
                req = urllib.request.Request(u, headers={
                    'User-Agent': UA,
                    'Referer': SITE,
                    'Accept': '*/*',
                })
                with urllib.request.urlopen(req, timeout=15, context=ctx) as r:
                    if getattr(r, 'status', 200) != 200:
                        return None
                    return r.read().decode('utf-8', 'ignore')
            except Exception:
                pass
            _last_err[0] = '双通道都抓不到: %s' % u[:80]
            return None

        try:
            text, err = self._cleaner.clean_url(src, fetch_fn=_fetch)
        except Exception as e:
            return None, 'clean error: %s' % e
        if err or not text:
            return None, _last_err[0] if _last_err[0] != '获取 m3u8 失败' else (err or 'clean failed')
        if '#EXTINF' not in text or '#EXT-X-STREAM-INF' in text:
            return None, '清洗结果异常(非分片列表): %s' % _last_err[0]
        self._clean_cache['url'] = norm
        self._clean_cache['body'] = text
        return text, None

    # ================= 首页 =================
    def homeContent(self, filter=False):
        classes = [{"type_id": c["type_id"], "type_name": c["type_name"]}
                   for c in CLASSES]
        return {'class': classes, 'list': [], 'filters': ALL_FILTERS}

    def homeVideoContent(self):
        return {'list': []}

    # ================= 分类 =================
    def categoryContent(self, tid, pg="1", filter=None, extend=None):
        try:
            page = int(pg or 1)
        except Exception:
            page = 1
        tid = str(tid or '1')
        if tid not in CATEGORY_MAP:
            tid = '1'

        # 解析 extend（兼容 dict / JSON string）
        ext = extend
        if isinstance(ext, str):
            try:
                ext = json.loads(ext)
            except Exception:
                ext = {}
        if not isinstance(ext, dict):
            ext = {}

        # 主分类 ID 不能直接用于 ac=detail，必须用子分类 ID
        children = CATEGORY_MAP.get(tid, {}).get("children", [])
        child_tid = ext.get("class", "")
        if child_tid:
            child_tid = str(child_tid)
            if child_tid not in [c[0] for c in children]:
                child_tid = ""
        if not child_tid and children:
            child_tid = children[0][0]

        ck = '%s|%s|%d' % (tid, child_tid, page)
        cached = self._cache_get(self._cat_cache, ck, TTL_CAT)
        if cached is not None:
            return cached

        params = {'ac': 'videolist', 't': child_tid, 'pg': str(page), 'pagesize': '20'}
        data = self._get(params)
        videos = self._parse_list(data.get('list') or [])
        try:
            total = int(data.get('total') or 0)
        except Exception:
            total = 0
        try:
            limit = int(data.get('limit') or 20)
        except Exception:
            limit = 20
        try:
            pagecount = int(data.get('pagecount') or 0)
        except Exception:
            pagecount = 0
        if total and not pagecount:
            pagecount = max(1, (total + limit - 1) // limit)
        if not total:
            pagecount = max(pagecount, page)

        result = {'list': videos, 'page': page, 'pagecount': pagecount,
                  'limit': limit, 'total': total}
        self._cache_set(self._cat_cache, ck, result, TTL_CAT)
        return result

    # ================= 详情 =================
    def detailContent(self, ids):
        vod_id = ids[0] if isinstance(ids, list) else ids
        if not vod_id:
            return {'list': []}
        vod_id = str(vod_id)

        cached = self._cache_get(self._detail_cache, vod_id, TTL_DETAIL)
        if cached is not None:
            return cached

        data = self._get({'ac': 'detail', 'ids': vod_id}, timeout=12)
        items = data.get('list') or []
        if not items:
            return {'list': []}

        d = items[0]
        result = {'list': [_norm_detail(d)]}
        self._cache_set(self._detail_cache, vod_id, result, TTL_DETAIL)
        return result

    # ================= 搜索 (suggest → detail 补全) =================
    def searchContent(self, key, quick=False, pg="1"):
        try:
            page = int(pg or 1)
        except Exception:
            page = 1

        kw = str(key or '').strip()
        if not kw:
            return {'list': [], 'page': 1, 'pagecount': 1}

        ck = 'search:%s:%d' % (kw, page)
        cached = self._cache_get(self._search_cache, ck, TTL_SEARCH)
        if cached is not None:
            return cached

        # Step 1: suggest API 获取建议列表
        suggest_url = SITE.rstrip('/') + '/index.php/ajax/suggest?mid=1&wd=' + urlencode({'': kw})[1:]
        try:
            import urllib.request
            req = urllib.request.Request(suggest_url, headers={
                'User-Agent': UA,
                'Accept': 'application/json',
                'Referer': SITE,
            }, method='GET')
            with urllib.request.urlopen(req, timeout=10, context=self._ssl_ctx()) as r:
                if getattr(r, 'status', 200) != 200:
                    suggest_data = {}
                else:
                    suggest_data = json.loads(r.read().decode('utf-8', 'ignore')) or {}
        except Exception:
            suggest_data = {}

        suggest_list = suggest_data.get('list') or []
        if not suggest_list:
            return {'list': [], 'page': 1, 'pagecount': 1}

        # Step 2: 用 suggest 返回的 id 批量调 ac=detail 补全完整字段
        # suggest 返回 id, name, pic; 分页: 每页 20 条
        total = int(suggest_data.get('total') or len(suggest_list))
        limit = int(suggest_data.get('limit') or 20)
        pagecount = max(1, (total + limit - 1) // limit) if total else page

        # 取当前页数据(前端 suggest 已分页, 但为安全取全部 suggest 结果后本地分页)
        start = (page - 1) * limit
        end = start + limit
        page_items = suggest_list[start:end]

        if not page_items:
            return {'list': [], 'page': page, 'pagecount': pagecount,
                    'limit': 0, 'total': total}

        ids = ','.join(str(it.get('id') or it.get('vod_id') or '') for it in page_items if it.get('id') or it.get('vod_id'))
        if ids:
            detail_data = self._get({'ac': 'detail', 'ids': ids}, timeout=12)
            detail_list = detail_data.get('list') or []
        else:
            detail_list = []

        # 构建搜索结果(优先用 detail 字段, 无 detail 用 suggest 字段兜底)
        videos = []
        for it in page_items:
            sid = str(it.get('id') or it.get('vod_id') or '')
            # 在 detail_list 中找匹配
            matched = None
            for d in detail_list:
                if str(d.get('vod_id') or '') == sid:
                    matched = d
                    break
            if matched:
                videos.append(_norm_list(matched))
            else:
                pic = str(it.get('pic') or it.get('vod_pic') or '')
                if pic.startswith("https://img1.wsyzy.org"):
                    pic = pic.replace("https://", "http://", 1)
                videos.append({
                    'vod_id': sid,
                    'vod_name': str(it.get('name') or it.get('vod_name') or ''),
                    'vod_pic': pic,
                    'vod_remarks': '',
                })

        result = {'list': videos, 'page': page, 'pagecount': pagecount,
                  'limit': len(videos), 'total': total}
        self._cache_set(self._search_cache, ck, result, TTL_SEARCH)
        return result

    # ================= 播放 (file:// 预清洗) =================
    def _clean_to_file(self, src):
        try:
            text, err = self._do_clean(src)
            if not text or err or not text.lstrip().startswith('#EXTM3U'):
                return None
            name = 'wsyzy_%s.m3u8' % hashlib.md5(src.encode('utf-8')).hexdigest()[:16]
            path = None
            for d in (tempfile.gettempdir(), '/data/data/com.fongmi.android.tv/cache',
                      '/data/user/0/com.fongmi.android.tv/cache'):
                if not d:
                    continue
                try:
                    test = os.path.join(d, '.wsyzy_wtest')
                    open(test, 'w').close()
                    os.remove(test)
                    path = os.path.join(d, name)
                    break
                except Exception:
                    continue
            if not path:
                return None
            with open(path, 'w', encoding='utf-8') as f:
                f.write(text)
            return 'file://' + path
        except Exception:
            return None

    def playerContent(self, flag, id, vipFlags=None):
        play_url = str(id or '').strip()
        play_url = unquote(play_url) if play_url else ''

        header = {
            "User-Agent": UA,
            "Referer": SITE,
        }

        if play_url and re.match(r'^https?://', play_url, re.I):
            if '.m3u8' in play_url:
                # 先清洗主列表(选最高码率变体)
                furl = self._clean_to_file(play_url)
                if furl:
                    return {
                        "parse": 0,
                        "url": furl,
                        "header": json.dumps(header, ensure_ascii=False)
                    }
                # 清洗异常回退原始直链
                return {
                    "parse": 0,
                    "url": play_url,
                    "header": json.dumps(header, ensure_ascii=False)
                }
            else:
                return {
                    "parse": 0,
                    "url": play_url,
                    "header": json.dumps(header, ensure_ascii=False)
                }

        return {
            "parse": 1,
            "url": play_url or self._api,
            "header": json.dumps(header, ensure_ascii=False)
        }

    def isVideoFormat(self, url):
        return bool(re.search(r'\.(m3u8|mp4|flv|avi|mkv|wmv|ts|m4a|aac)(\?|$)', url, re.I))

    def manualVideoCheck(self):
        return True

    def localProxy(self, param):
        src = None
        if isinstance(param, dict):
            src = param.get('src')
            if not src:
                for _k, _v in param.items():
                    if isinstance(_v, str) and _v.startswith(('http://', 'https://')) and '.m3u8' in _v:
                        src = _v
                        break
            if not src:
                try:
                    _joined = ' '.join(str(_v) for _v in param.values())
                    _mm = re.search(r'https?://[^\s&"\']+\.m3u8[^\s&"\']*', _joined)
                    if _mm:
                        src = _mm.group(0)
                except Exception:
                    src = None
        if not src:
            return ''
        if '://' not in src and '%' in src:
            try:
                src = unquote(src)
            except Exception:
                pass
        for _t in ('&action=', '&src=', '&do='):
            if _t in src:
                src = src.split(_t)[0]
        text, err = self._do_clean(src)
        return text or ''


if __name__ == "__main__":
    print("无水印资源 FongMi site: wsyzy.cc")
