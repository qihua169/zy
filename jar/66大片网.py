# -*- coding: utf-8 -*-
"""
66大片网 爬虫（派生基类 Python 版本）
移植自 drpy2 JS 规则 [66大片网.js]（原 Python 爬虫 [影]66大网片.py）
站点: https://www.77dpw.vip

接口对照：
  首页/列表 -> /vodtype/{tid}.html 或 /vodtype/{tid}-{pg}.html（HTML 卡片解析）
  详情     -> /voddetail/{id}.html
  播放页   -> /vodplay/{id}-{sid}-{nid}.html（解析 player_ 变量 -> base64 解码）
  搜索     -> /index.php/ajax/suggest（JSON，失败降级 /vodsearch/）
  官源解析 -> 第三方 jiexi 接口
"""

import re
import sys
import json

from base64 import b64decode
from urllib.parse import quote, unquote

sys.path.append('..')
from base.spider import Spider


# ============================================================
# 常量
# ============================================================
DOMAINS = [
    'https://www.77dpw.vip',
    'https://www.66dpw.vip',
]
HOST = DOMAINS[0]

UA = ('Mozilla/5.0 (Linux; Android 13; Pixel 7) AppleWebKit/537.36 '
      '(KHTML, like Gecko) Chrome/120.0.0.0 Mobile Safari/537.36')
UA_PC = ('Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
         '(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36')
UA_M3U8 = ('Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
           '(KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36 Edg/121.0.0.0')

HEADERS = {
    'User-Agent': UA,
    'Referer': HOST + '/',
    'Accept': 'text/html,application/xhtml+xml,application/json,*/*',
    'Accept-Language': 'zh-CN,zh;q=0.9',
}

URL_INDEX = HOST + '/'
URL_DETAIL = HOST + '/voddetail/%s.html'
URL_PLAY = HOST + '/vodplay/%s-%s-%s.html'
URL_SEARCH = HOST + '/index.php/ajax/suggest'
URL_SEARCH_LIST = HOST + '/vodsearch/%s----------%s---.html'


def _url_type(tid):
    return HOST + '/vodtype/' + str(tid) + '.html'


def _url_type_pg(tid, pg):
    return HOST + '/vodtype/' + str(tid) + '-' + str(pg) + '.html'


def _url_detail(vid):
    return HOST + '/voddetail/' + str(vid) + '.html'


def _url_play(a, b, c):
    return HOST + '/vodplay/' + str(a) + '-' + str(b) + '-' + str(c) + '.html'


def _url_search_list(kw, pg):
    return HOST + '/vodsearch/' + quote(str(kw), safe='') + '----------' + str(pg) + '---.html'


# ============================================================
# 一级分类（站点真实导航共 5 个：电影1 / 动漫2 / 剧集3 / 短剧4 / 综艺5）
# ============================================================
CATS = [
    {'id': '1', 'name': '电影'},
    {'id': '3', 'name': '电视剧'},
    {'id': '2', 'name': '动漫'},
    {'id': '5', 'name': '综艺'},
    {'id': '4', 'name': '短剧'},
]


# ============================================================
# 二级筛选
# ============================================================
_SORT_ITEMS = [
    {'n': '综合', 'v': ''}, {'n': '最新', 'v': 'time'},
    {'n': '最热', 'v': 'hits'}, {'n': '评分', 'v': 'score'},
]

_YEAR_CHOICES = [
    {'n': '全部', 'v': ''}, {'n': '2025', 'v': '2025'}, {'n': '2024', 'v': '2024'},
    {'n': '2023', 'v': '2023'}, {'n': '2022', 'v': '2022'}, {'n': '2021', 'v': '2021'},
    {'n': '2020', 'v': '2020'}, {'n': '2019', 'v': '2019'}, {'n': '2018', 'v': '2018'},
    {'n': '2017', 'v': '2017'}, {'n': '2016', 'v': '2016'}, {'n': '2015', 'v': '2015'},
    {'n': '2014', 'v': '2014'}, {'n': '2013', 'v': '2013'}, {'n': '2012', 'v': '2012'},
    {'n': '2011', 'v': '2011'}, {'n': '2010', 'v': '2010'},
    {'n': '2010年代', 'v': '2010-2019'}, {'n': '2000年代', 'v': '2000-2009'},
    {'n': '90年代', 'v': 'lt2000'}, {'n': '更早', 'v': 'lt1990'},
]

_AREA_ITEMS = [
    {'n': '全部', 'v': ''}, {'n': '大陆', 'v': '大陆'}, {'n': '香港', 'v': '香港'},
    {'n': '台湾', 'v': '台湾'}, {'n': '美国', 'v': '美国'}, {'n': '韩国', 'v': '韩国'},
    {'n': '日本', 'v': '日本'}, {'n': '法国', 'v': '法国'}, {'n': '英国', 'v': '英国'},
    {'n': '德国', 'v': '德国'}, {'n': '泰国', 'v': '泰国'}, {'n': '印度', 'v': '印度'},
    {'n': '西班牙', 'v': '西班牙'}, {'n': '意大利', 'v': '意大利'},
    {'n': '加拿大', 'v': '加拿大'}, {'n': '巴西', 'v': '巴西'},
    {'n': '俄罗斯', 'v': '俄罗斯'}, {'n': '印尼', 'v': '印尼'},
]

_LANG_ITEMS = [
    {'n': '全部', 'v': ''}, {'n': '国语', 'v': '国语'}, {'n': '粤语', 'v': '粤语'},
    {'n': '英语', 'v': '英语'}, {'n': '日语', 'v': '日语'}, {'n': '韩语', 'v': '韩语'},
    {'n': '法语', 'v': '法语'}, {'n': '德语', 'v': '德语'}, {'n': '泰语', 'v': '泰语'},
    {'n': '俄语', 'v': '俄语'},
]

_PLOT_ITEMS = [
    {'n': '全部', 'v': ''}, {'n': '喜剧', 'v': '喜剧'}, {'n': '爱情', 'v': '爱情'},
    {'n': '动作', 'v': '动作'}, {'n': '科幻', 'v': '科幻'}, {'n': '悬疑', 'v': '悬疑'},
    {'n': '惊悚', 'v': '惊悚'}, {'n': '恐怖', 'v': '恐怖'}, {'n': '战争', 'v': '战争'},
    {'n': '犯罪', 'v': '犯罪'}, {'n': '冒险', 'v': '冒险'}, {'n': '动画', 'v': '动画'},
    {'n': '家庭', 'v': '家庭'}, {'n': '古装', 'v': '古装'}, {'n': '武侠', 'v': '武侠'},
    {'n': '奇幻', 'v': '奇幻'}, {'n': '青春', 'v': '青春'}, {'n': '校园', 'v': '校园'},
    {'n': '都市', 'v': '都市'}, {'n': '谍战', 'v': '谍战'}, {'n': '军旅', 'v': '军旅'},
    {'n': '历史', 'v': '历史'}, {'n': '纪录', 'v': '纪录'}, {'n': '真人', 'v': '真人秀'},
]

_TYPE_MOVIE = [
    {'n': '全部', 'v': ''}, {'n': '科幻片', 'v': '8'}, {'n': '恐怖片', 'v': '9'},
    {'n': '动作片', 'v': '10'}, {'n': '战争片', 'v': '11'}, {'n': '爱情片', 'v': '12'},
    {'n': '喜剧片', 'v': '13'}, {'n': '剧情片', 'v': '14'}, {'n': '记录片', 'v': '15'},
]

_TYPE_TV = [
    {'n': '全部', 'v': ''}, {'n': '大陆剧', 'v': '22'}, {'n': '日本剧', 'v': '23'},
    {'n': '韩国剧', 'v': '24'}, {'n': '香港剧', 'v': '25'}, {'n': '台湾剧', 'v': '26'},
    {'n': '欧美剧', 'v': '27'},
]

_TYPE_ANIME = [
    {'n': '全部', 'v': ''}, {'n': '大陆番', 'v': '16'},
    {'n': '日本番', 'v': '17'}, {'n': '欧美番', 'v': '21'},
]

_TYPE_ZY = [
    {'n': '全部', 'v': ''}, {'n': '大陆综艺', 'v': '28'}, {'n': '港台综艺', 'v': '29'},
    {'n': '日韩综艺', 'v': '30'}, {'n': '欧美综艺', 'v': '31'},
]

_AREA_ANIME = [
    {'n': '全部', 'v': ''}, {'n': '大陆', 'v': '大陆'}, {'n': '日本', 'v': '日本'},
    {'n': '美国', 'v': '美国'}, {'n': '韩国', 'v': '韩国'},
]

_AREA_ZY = [
    {'n': '全部', 'v': ''}, {'n': '大陆', 'v': '大陆'}, {'n': '香港', 'v': '香港'},
    {'n': '台湾', 'v': '台湾'}, {'n': '日本', 'v': '日本'}, {'n': '韩国', 'v': '韩国'},
    {'n': '美国', 'v': '美国'},
]

_PLOT_ZY = [
    {'n': '全部', 'v': ''}, {'n': '真人', 'v': '真人秀'}, {'n': '脱口秀', 'v': '脱口秀'},
    {'n': '音乐', 'v': '音乐'}, {'n': '舞蹈', 'v': '舞蹈'}, {'n': '搞笑', 'v': '搞笑'},
    {'n': '美食', 'v': '美食'}, {'n': '旅游', 'v': '旅游'}, {'n': '竞技', 'v': '竞技'},
    {'n': '访谈', 'v': '访谈'}, {'n': '纪录', 'v': '纪录'},
]


def _letter_items():
    arr = [{'n': '全部', 'v': ''}]
    for c in range(65, 91):
        ch = chr(c)
        arr.append({'n': ch, 'v': ch})
    return arr


def _fgroup(key, name, values):
    return {'key': key, 'name': name, 'value': values}


def _build_filters():
    f = {}
    f['1'] = [
        _fgroup('genre', '类型', _TYPE_MOVIE),
        _fgroup('plot', '剧情', _PLOT_ITEMS),
        _fgroup('area', '地区', _AREA_ITEMS),
        _fgroup('lang', '语言', _LANG_ITEMS),
        _fgroup('year', '年份', _YEAR_CHOICES),
        _fgroup('letter', '字母', _letter_items()),
        _fgroup('by', '排序', _SORT_ITEMS),
    ]
    f['3'] = [
        _fgroup('genre', '类型', _TYPE_TV),
        _fgroup('plot', '剧情', _PLOT_ITEMS),
        _fgroup('area', '地区', _AREA_ITEMS),
        _fgroup('lang', '语言', _LANG_ITEMS),
        _fgroup('year', '年份', _YEAR_CHOICES),
        _fgroup('letter', '字母', _letter_items()),
        _fgroup('by', '排序', _SORT_ITEMS),
    ]
    f['2'] = [
        _fgroup('genre', '类型', _TYPE_ANIME),
        _fgroup('plot', '剧情', _PLOT_ITEMS),
        _fgroup('area', '地区', _AREA_ANIME),
        _fgroup('lang', '语言', _LANG_ITEMS),
        _fgroup('year', '年份', _YEAR_CHOICES),
        _fgroup('letter', '字母', _letter_items()),
        _fgroup('by', '排序', _SORT_ITEMS),
    ]
    f['5'] = [
        _fgroup('genre', '类型', _TYPE_ZY),
        _fgroup('plot', '剧情', _PLOT_ZY),
        _fgroup('area', '地区', _AREA_ZY),
        _fgroup('lang', '语言', _LANG_ITEMS),
        _fgroup('year', '年份', _YEAR_CHOICES),
        _fgroup('letter', '字母', _letter_items()),
        _fgroup('by', '排序', _SORT_ITEMS),
    ]
    # 短剧(4)：站点无可靠子类型 id，类型仅留「全部」
    f['4'] = [
        _fgroup('genre', '类型', [{'n': '全部', 'v': ''}]),
        _fgroup('area', '地区', _AREA_ITEMS),
        _fgroup('year', '年份', _YEAR_CHOICES),
        _fgroup('lang', '语言', _LANG_ITEMS),
        _fgroup('by', '排序', _SORT_ITEMS),
    ]
    return f


CAT_FILTERS = _build_filters()


# ============================================================
# 播放线路 / 官源识别
# ============================================================
LINE_NAMES = {
    'qq': '腾讯视频', 'bilibili': '哔哩哔哩', 'qiyi': '爱奇艺',
    'youku': '优酷', 'mgtv': '芒果TV', 'jsm3u8': '极速',
}

_OFFICIAL_KEYS = [
    'mgtv.com', 'youku.com', 'iqiyi.com', 'qiyi.com', 'v.qq.com',
    'qq.com', 'bilibili.com', 'sohu.com', 'le.com',
]

# 第三方解析接口（VIP 解析：官源网页地址 -> 直链 m3u8）
PARSE_API_MAIN = 'http://nm.4688888.xyz/jiexi.php?data=2464fd167213bb8a26c1427c31da8c59&url={URL}'
PARSE_APIS = [PARSE_API_MAIN]


# ============================================================
# 通用工具
# ============================================================
def _clean(txt):
    return re.sub(r'\s+', ' ', txt or '').strip()


def _b64decode(s):
    """base64 解码（带补齐与容错）"""
    s = re.sub(r'[^A-Za-z0-9+/=]', '', str(s or ''))
    s += '=' * ((4 - len(s) % 4) % 4)
    try:
        return b64decode(s).decode('utf-8', 'ignore')
    except Exception:
        return ''


def _decode_play_url(s):
    try:
        d = _b64decode(s or '')
        try:
            d = unquote(d)
        except Exception:
            pass
        return d
    except Exception:
        return s or ''


def _extract_json_obj(text, start):
    """平衡括号提取 JSON 对象（适配 var player_xxx = {...}）"""
    depth = 0
    in_str = False
    esc = False
    i = start
    n = len(text or '')
    while i < n:
        ch = text[i]
        if in_str:
            if esc:
                esc = False
            elif ch == '\\':
                esc = True
            elif ch == '"':
                in_str = False
        else:
            if ch == '"':
                in_str = True
            elif ch == '{':
                depth += 1
            elif ch == '}':
                depth -= 1
                if depth == 0:
                    return text[start:i + 1]
        i += 1
    return None


def _is_direct_media(url):
    low = (url or '').lower()
    return ('.m3u8' in low or '.mp4' in low or '.flv' in low or '.mkv' in low)


def _is_official_source(url):
    low = (url or '').lower()
    hit = any(k in low for k in _OFFICIAL_KEYS)
    return hit and not _is_direct_media(low)


def _extract_referer(url):
    try:
        if '://' in url:
            scheme = url.split('://')[0]
            host = url.split('://')[1].split('/')[0]
            return scheme + '://' + host + '/'
    except Exception:
        pass
    return HOST + '/'


def _build_media_headers(url, referer=None):
    """媒体直链请求头补全（m3u8 用桌面 UA；.ts 加 Range）"""
    low = (url or '').lower()
    is_m3u8 = '.m3u8' in low
    is_ts = '.ts' in low
    h = {
        'User-Agent': UA_M3U8 if is_m3u8 else UA_PC,
        'Accept': '*/*',
        'Accept-Language': 'zh-CN,zh;q=0.9',
        'Connection': 'keep-alive',
        'Referer': referer or _extract_referer(url),
    }
    if is_ts:
        h['Range'] = 'bytes=0-'
    return h


# ---- 图片压缩（探测图床，白名单直出） ----
_PASS_THROUGH_HOSTS = [
    'pic.img.', 'img.66dpw', 'img.77dpw', 'doubanio.com', 'douban.com',
    'img.jisuimage.com', 'hdslb.com', 'bilibili.com',
]


def _opt_image(url):
    if not url:
        return ''
    url = url.strip()
    if url.startswith('//'):
        url = 'https:' + url
    if not url.startswith('http'):
        return url
    for h in _PASS_THROUGH_HOSTS:
        if h in url:
            return url
    if ('img-cdn' in url or 'qn.cache' in url or '.qiniucdn.' in url
            or '.clouddn.' in url or '.bkt.clouddn.' in url):
        opt = 'imageView2/1/w/240/q/60/format/webp'
    elif '.oss-' in url or '.aliyuncs.' in url:
        opt = 'x-oss-process=image/resize,w_240/quality,q_60/format,webp'
    else:
        opt = 'w=240&q=60&f=webp'
    url = re.sub(r'[?&](imageView2[^&]*|x-oss-process[^&]*|w=\d+[^&]*|f=webp[^&]*)', '', url)
    sep = '&' if '?' in url else '?'
    return url + sep + opt


# ============================================================
# 列表卡片解析（module-poster-item）
# ============================================================
_RE_CARD = re.compile(
    r'<a\s+href="/voddetail/(\d+)\.html"\s+title="([^"]*)"[^>]*>(.*?)</a>',
    re.S
)
_RE_PIC = re.compile(r'data-original="([^"]+)"')
_RE_NOTE = re.compile(r'class="module-item-note"[^>]*>\s*([^<]*)<')


def _parse_list_html(html):
    if not html:
        return []
    out = []
    seen = set()
    for m in _RE_CARD.finditer(html):
        vod_id = m.group(1)
        name = m.group(2)
        body = m.group(3)
        if not vod_id or not name or vod_id in seen:
            continue
        seen.add(vod_id)
        img = _RE_PIC.search(body)
        note = _RE_NOTE.search(body)
        out.append({
            'vod_id': vod_id,
            'vod_name': _clean(name),
            'vod_pic': _opt_image(img.group(1) if img else ''),
            'vod_remarks': _clean(note.group(1)) if note else 'HD',
        })
    return out


def _to_list_item(it):
    return {
        'vod_id': it.get('vod_id', ''),
        'vod_name': it.get('vod_name', ''),
        'vod_pic': it.get('vod_pic', ''),
        'vod_remarks': it.get('vod_remarks', ''),
    }


def _direct_result(url):
    is_m3u8 = bool(re.search(r'\.m3u8', url or '', re.I))
    res = {
        'parse': 0,
        'url': url,
        'header': _build_media_headers(url),
    }
    if is_m3u8:
        res['format'] = 'application/x-mpegURL'
        res['contentType'] = 'application/x-mpegURL'
    return res


# ============================================================
# Spider 类
# ============================================================
class Spider(Spider):

    # ---------------- 基础 ----------------
    def getName(self):
        return "66大片网"

    def init(self, extend=""):
        try:
            self.extend = extend
        except Exception:
            pass
        self.host = HOST
        self.headers = dict(HEADERS)
        return

    def isVideoFormat(self, url):
        return _is_direct_media(url)

    def manualVideoCheck(self):
        return False

    def destroy(self):
        return

    # ---------------- 网络请求 ----------------
    def _get(self, url, timeout=8):
        for _ in range(2):
            try:
                try:
                    rsp = self.fetch(url, headers=self.headers, timeout=timeout)
                except TypeError:
                    rsp = self.fetch(url, headers=self.headers)
                if rsp is None:
                    continue
                if hasattr(rsp, 'text'):
                    text = rsp.text or ''
                elif isinstance(rsp, bytes):
                    text = rsp.decode('utf-8', 'ignore')
                elif isinstance(rsp, str):
                    text = rsp
                else:
                    text = str(rsp)
                if text:
                    return text
            except Exception:
                pass
        return ''

    def _get_json(self, url, timeout=8):
        text = self._get(url, timeout)
        if not text:
            return None
        try:
            return json.loads(text)
        except Exception:
            return None

    # ---------------- 首页 / 推荐 ----------------
    def _get_home_list(self):
        html = self._get(URL_INDEX, 12)
        raw = _parse_list_html(html)
        return [_to_list_item(it) for it in raw[:72]]

    def homeVideoContent(self):
        lst = []
        try:
            lst = self._get_home_list()
        except Exception as e:
            print('[66大片网] 推荐失败: %s' % e)
        print('[66大片网] 推荐 %d 条' % len(lst))
        return {'list': lst}

    def homeContent(self, filter):
        result = {
            'class': [{'type_id': c['id'], 'type_name': c['name']} for c in CATS],
        }
        if filter:
            result['filters'] = CAT_FILTERS
        return result

    # ---------------- 一级分类列表 ----------------
    def _get_category_list(self, tid, page, filt, extend):
        try:
            page = int(page or 1)
        except Exception:
            page = 1

        ext = {}
        if isinstance(filt, dict):
            for k, v in filt.items():
                if v not in ('', None):
                    ext[k] = v
        if extend:
            if isinstance(extend, str):
                try:
                    e2 = json.loads(extend)
                except Exception:
                    e2 = {}
            else:
                e2 = extend
            if isinstance(e2, dict):
                for k, v in e2.items():
                    if v not in ('', None):
                        ext[k] = v

        # 仅 genre(类型子分类 id) 影响请求 tid
        genre = str(ext.get('genre') or ext.get('type') or '').strip()
        real_tid = str(tid or '1')
        if genre and re.match(r'^\d+$', genre):
            real_tid = genre

        url = _url_type(real_tid) if page <= 1 else _url_type_pg(real_tid, page)
        html = self._get(url, 12)
        raw = _parse_list_html(html)
        return [_to_list_item(it) for it in raw[:96]]

    def categoryContent(self, tid, pg, filter, extend):
        lst = []
        try:
            lst = self._get_category_list(tid, pg, filter, extend)
        except Exception as e:
            print('[66大片网] 一级失败: %s' % e)
        print('[66大片网] 一级 tid=%s 解析 %d 条' % (tid, len(lst)))
        try:
            page = int(pg or 1)
        except Exception:
            page = 1
        return {
            'list': lst,
            'page': page,
            'pagecount': 9999,
            'limit': 96,
            'total': 999999,
        }

    # ---------------- 详情页解析 ----------------
    def _get_detail(self, vid):
        if not vid:
            return None
        vid = str(vid).strip()
        html = self._get(_url_detail(vid), 12)
        if not html:
            return None

        vod = {'vod_id': vid}

        m = (re.search(r'<h1[^>]*>\s*<a[^>]*>([^<]+)</a>', html)
             or re.search(r'<h1[^>]*>([^<]+)</h1>', html))
        vod['vod_name'] = _clean(m.group(1)) if m else vid

        # 封面
        pic = ''
        cm = re.search(r'class="module-info-cover[^"]*"[^>]*>(.*?)</div>', html, re.S)
        if cm:
            pm = re.search(r'data-original="([^"]+)"|src="([^"]+)"', cm.group(1))
            if pm:
                pic = pm.group(1) or pm.group(2)
        if pic.startswith('//'):
            pic = 'https:' + pic
        vod['vod_pic'] = _opt_image(pic)

        # 年份 / 类型
        year = ''
        types = []
        for tm in re.finditer(r'<a[^>]*title="([^"]{2,20})"[^>]*href="[^"]*vodshow[^"]*"', html):
            tag = tm.group(1)
            if re.match(r'^20\d{2}$', tag):
                year = tag
            elif re.match(r'^[\u4e00-\u9fa5]{2,6}$', tag) and tag not in types:
                types.append(tag)
        rm = re.search(
            r'中国大陆|中国香港|中国台湾|日本|韩国|美国|英国|法国|德国|泰国|印度|新加坡|马来西亚|俄罗斯',
            html
        )
        vod['vod_year'] = year
        vod['vod_area'] = rm.group(0) if rm else ''
        vod['type_name'] = ','.join(types[:3])

        # 备注
        rem = (re.search(r'class="module-info-tag-link"[^>]*>\s*<a[^>]*title="(已完结|更新至[^"]*|第[^"]*集[^"]*)"', html)
               or re.search(r'(已完结|更新至[^"]{0,12}|全\d+集)', html))
        vod['vod_remarks'] = _clean(rem.group(1)) if rem else 'HD'

        # 导演 / 主演
        vod['vod_actor'] = ''
        vod['vod_director'] = ''
        for label, key in (('导演：', 'vod_director'), ('主演：', 'vod_actor')):
            pat = (r'class="module-info-item-title">\s*' + label +
                   r'\s*</span>\s*<div[^>]*class="module-info-item-content"[^>]*>(.*?)</div>')
            lm = re.search(pat, html, re.S)
            if lm:
                names = re.findall(r'<a[^>]*>([^<]+)</a>', lm.group(1))
                vod[key] = ' / '.join([_clean(n) for n in names])

        # 简介
        im = (re.search(r'class="module-info-content[^"]*"[^>]*>(.*?)</div>', html, re.S)
              or re.search(r'class="module-info-item module-info-introduction[^"]*"[^>]*>(.*?)</div>', html, re.S))
        intro = ''
        if im:
            intro = _clean(re.sub(r'<[^>]+>', '', im.group(1)))
        vod['vod_content'] = intro[:500] if len(intro) > 500 else intro

        # ---- 播放线路：极速(m3u8) 排前，官源排后 ----
        tabs = []
        for tbm in re.finditer(r'module-tab-item[^>]*data-dropdown-value="([^"]+)"[^>]*>', html):
            tabs.append(_clean(tbm.group(1)))
        if not tabs:
            for tbm in re.finditer(r'class="module-tab-item[^"]*"[^>]*>\s*([^<]+?)\s*<', html):
                tabs.append(_clean(tbm.group(1)))

        blocks = []
        for bm in re.finditer(
                r'<div class="module-play-list">(.*?)(?:<!-- 新增备用播放源 -->|</div>\s*</div>\s*</div>)',
                html, re.S):
            blocks.append(bm.group(1))
        if len(blocks) > len(tabs):
            blocks = blocks[:len(tabs)]

        direct_from, direct_url = [], []
        official_from, official_url = [], []

        for idx, blk in enumerate(blocks):
            line_name = tabs[idx] if idx < len(tabs) else ('线路' + str(idx + 1))
            eps = []
            for em in re.finditer(r'href="/vodplay/(\d+)-(\d+)-(\d+)\.html"[^>]*>\s*<span>([^<]*)</span>', blk):
                ep_name = _clean(em.group(4)) or ('第' + em.group(3) + '集')
                eps.append(ep_name + '$' + _url_play(em.group(1), em.group(2), em.group(3)))
            if not eps:
                for em in re.finditer(r'href="/vodplay/(\d+)-(\d+)-(\d+)\.html"[^>]*>([^<]{0,20})</a>', blk):
                    ep_name = _clean(em.group(4)) or ('第' + em.group(3) + '集')
                    eps.append(ep_name + '$' + _url_play(em.group(1), em.group(2), em.group(3)))
            if not eps:
                continue
            joined = '#'.join(eps)
            if re.search(r'极速|jsm3u8|m3u8', line_name):
                direct_from.append(line_name)
                direct_url.append(joined)
            else:
                official_from.append(line_name)
                official_url.append(joined)

        play_from = direct_from + official_from
        play_url = direct_url + official_url
        vod['vod_play_from'] = '$$$'.join(play_from) if play_from else '66大片网'
        vod['vod_play_url'] = '$$$'.join(play_url)
        return vod

    def detailContent(self, ids):
        vid = ''
        try:
            vid = str(ids[0] if isinstance(ids, (list, tuple)) else ids)
            vid = vid.split('@@')[0].split('#')[0]
        except Exception:
            vid = ''
        if not vid:
            return {'list': []}
        detail = self._get_detail(vid)
        if not detail:
            detail = {
                'vod_id': vid,
                'vod_name': '未知影片',
                'vod_content': '获取失败或影片不存在',
            }
        return {'list': [detail]}

    # ---------------- 搜索 ----------------
    def _search_page(self, kw, page):
        try:
            page = int(page or 1)
        except Exception:
            page = 1
        lst = []

        # 1) JSON suggest 接口
        try:
            surl = URL_SEARCH + '?mid=1&wd=' + quote(str(kw), safe='') + '&limit=30'
            data = self._get_json(surl, 8)
            if data and data.get('code') == 1:
                seen = set()
                for item in (data.get('list') or []):
                    if len(lst) >= 30:
                        break
                    vid = str(item.get('id') or '')
                    if not vid or vid in seen:
                        continue
                    seen.add(vid)
                    lst.append({
                        'vod_id': vid,
                        'vod_name': item.get('name') or '',
                        'vod_pic': _opt_image(item.get('pic') or ''),
                        'vod_remarks': '',
                    })
        except Exception:
            pass

        # 2) 降级：HTML 搜索页
        if not lst:
            try:
                h2 = self._get(_url_search_list(kw, page), 10)
                seen2 = set()
                for it in _parse_list_html(h2):
                    if len(lst) >= 30:
                        break
                    if it['vod_id'] in seen2:
                        continue
                    seen2.add(it['vod_id'])
                    lst.append(_to_list_item(it))
            except Exception:
                pass

        if not lst:
            lst.append({
                'vod_id': '0',
                'vod_name': kw,
                'vod_pic': '',
                'vod_remarks': '',
            })
        return lst

    def searchContent(self, key, quick, pg="1"):
        keyword = str(key or '').strip()
        if not keyword:
            return {'list': []}
        lst = []
        try:
            lst = self._search_page(keyword, pg)
        except Exception as e:
            print('[66大片网] 搜索失败: %s' % e)
        print('[66大片网] 搜索 "%s" %d 条' % (keyword, len(lst)))
        return {'list': lst}

    # ---------------- 播放解析 ----------------
    def _parse_official(self, official_url):
        """第三方解析官源 -> 直链（按顺序抢答）"""
        if not official_url:
            return None
        for api in PARSE_APIS:
            try:
                parse_url = api.replace('{URL}', quote(official_url, safe=''))
                html = self._get(parse_url, 6)
                if not html:
                    continue
                try:
                    obj = json.loads(html)
                    if isinstance(obj, dict):
                        # 解析失败（含 error 字段，或 code 非成功值）时不采用返回地址
                        if obj.get('error'):
                            continue
                        code = obj.get('code')
                        if code is not None and str(code) not in ('1', '200'):
                            continue
                        for k in ('url', 'data', 'playUrl', 'src'):
                            v = obj.get(k)
                            if (isinstance(v, str) and v
                                    and (re.search(r'\.m3u8', v, re.I)
                                         or re.match(r'^https?:', v, re.I))):
                                return _direct_result(v)
                except Exception:
                    pass
                mm = (re.search(r'https?://[^\s"\'<>]+\.m3u8[^\s"\'<>]*', html)
                      or re.search(r'https?://[^\s"\'<>]+\.mp4[^\s"\'<>]*', html))
                if mm:
                    return _direct_result(mm.group(0))
            except Exception:
                pass
        return None

    def _get_play(self, flag, pid):
        raw = str(pid or '').replace('\\/', '/').strip()
        if not raw:
            return {'parse': 0, 'url': '', 'header': dict(HEADERS)}

        if _is_direct_media(raw):
            return {'parse': 0, 'url': raw, 'header': _build_media_headers(raw)}

        m = re.search(r'vodplay/(\d+)-(\d+)-(\d+)', raw)
        if not m:
            if re.match(r'^https?:', raw, re.I):
                return {'parse': 0, 'url': raw, 'header': _build_media_headers(raw)}
            return {'parse': 0, 'url': raw,
                    'header': {'User-Agent': UA, 'Referer': HOST + '/'}}

        html = self._get(_url_play(m.group(1), m.group(2), m.group(3)), 10)
        play_url = ''
        seg = None
        if html:
            pm = re.search(r'var\s+player_\w+\s*=\s*', html)
            if pm:
                seg = _extract_json_obj(html, pm.end())
                if seg:
                    try:
                        obj = json.loads(seg)
                        play_url = _decode_play_url(obj.get('url') or '')
                    except Exception:
                        pass
            if not play_url and seg:
                # 兜底：宽松正则提取 url 字段
                mm = re.search(r'["\']?url["\']?\s*:\s*["\']([^"\']+)', seg)
                if mm:
                    play_url = _decode_play_url(mm.group(1))

        if not play_url:
            return {'parse': 0, 'url': raw,
                    'header': {'User-Agent': UA, 'Referer': HOST + '/'}}

        src = play_url.replace('\\/', '/').strip()
        if _is_direct_media(src):
            return {'parse': 0, 'url': src, 'header': _build_media_headers(src)}

        if _is_official_source(src):
            parsed = self._parse_official(src)
            if parsed:
                return parsed
            # jiexi 失败：交给播放器内置解析，避免把网页当直链硬放
            return {'parse': 1, 'url': src, 'header': _build_media_headers(src)}

        if re.match(r'^https?:', src, re.I):
            return {'parse': 1, 'url': src, 'header': _build_media_headers(src)}

        return {'parse': 0, 'url': src,
                'header': {'User-Agent': UA, 'Referer': HOST + '/'}}

    def playerContent(self, flag, id, vipFlags):
        try:
            return self._get_play(flag, id)
        except Exception as e:
            print('[66大片网] playerContent 失败: %s' % e)
            return {'parse': 0, 'url': '', 'header': dict(HEADERS)}