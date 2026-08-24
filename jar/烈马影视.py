# coding=utf-8
"""
目标站: kosungames (https://www.kosungames.com/)
实际站点: 烈马影院（苹果CMS 影视站）
模板: TVBox 爬虫框架
"""
import re
import sys
import json
import gzip
import html as html_mod
import time
import ssl
import urllib.parse
import urllib.request
import urllib.error

sys.path.append('..')
try:
    from base.spider import Spider as _BaseSpider
except ImportError:
    class _BaseSpider(object):
        def fetch(self, url, headers=None): return None
        def post(self, url, headers=None, data=None): return None
    import types
    sys.modules.setdefault('base', types.ModuleType('base'))
    sys.modules['base'].spider = types.ModuleType('base.spider')
    sys.modules['base'].spider.Spider = _BaseSpider


class Spider(_BaseSpider):

    def init(self, extend=""):
        self.site_url = "https://www.kosungames.com"
        # 必须用移动端 UA，PC 端会触发 HTTP 103 Early Hints
        self.ua = 'Mozilla/5.0 (Linux; Android 10; K) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Mobile Safari/537.36'
        self.headers = {
            'User-Agent': self.ua,
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8',
            'Accept-Language': 'zh-CN,zh;q=0.9',
            'Referer': self.site_url + '/',
        }
        self.default_pic = "https://pic.rmb.bdstatic.com/bjh/user/default.png"
        self.timeout = 10

        # SSL 免验证，减少握手开销
        self._ssl_ctx = ssl.create_default_context()
        self._ssl_ctx.check_hostname = False
        self._ssl_ctx.verify_mode = ssl.CERT_NONE

        # ========== 预编译正则 ==========

        # 列表页视频卡片
        # 修复：img 属性顺序不固定（分类页 src 在前，data-original 在后），用 ([^>]*) 整体捕获属性
        self._card_item_re = re.compile(
            r'<a\s+class="rajsb-obely cover-img"[^>]*href="(/liema/(\d+)\.html)"[^>]*title="([^"]*)"[^>]*>'
            r'\s*<img\s+class="etqpi-bu-psbyny lazyload"([^>]*)>'
            r'\s*<span[^>]*class="[^"]*pic-text[^"]*"[^>]*>([^<]*)</span>',
            re.DOTALL,
        )

        self._pagecount_re = re.compile(r'/vodshow/[a-zA-Z0-9]+--------(\d+)---\.html"[^{]*>尾页</a>')

        # 详情页
        self._title_re = re.compile(r'<h1[^>]*>(.*?)</h1>', re.DOTALL)
        self._pic_re = re.compile(r'<img[^>]*data-original="([^"]+)"', re.DOTALL)
        self._info_re = re.compile(
            r'<(?:span|div)[^>]*>(主演|导演|更新|类型|地区|语言|年份)[：:]?</[^>]*>(.*?)</(?:p|div|span)>',
            re.DOTALL | re.IGNORECASE,
        )
        self._desc_re = re.compile(
            r'(?:剧情简介|简介)[^<]*</h[23]>.*?<div[^>]*>(.*?)</div>',
            re.DOTALL | re.IGNORECASE,
        )
        self._playlist_re = re.compile(
            r'<ul[^>]*class="[^"]*shoutu-playlist[^"]*"[^>]*>(.*?)</ul>',
            re.DOTALL,
        )
        self._play_link_re = re.compile(
            r'<a[^>]*href="(/liemaplay/(\d+)-(\d+)-(\d+)\.html)"[^>]*>([^<]*)</a>',
        )
        self._player_json_re = re.compile(r'var player_aaaa=(\{.*?\})\s*</script>', re.DOTALL)

    # ========== 工具方法 ==========

    def _fix_url(self, url):
        if not url:
            return ""
        url = url.strip()
        if url.startswith("//"):
            return "https:" + url
        if not url.startswith("http"):
            return urllib.parse.urljoin(self.site_url, url)
        return url

    def _get(self, url, retries=1, backoff=0.3):
        """GET 请求，支持 gzip 解压与重试（减少重试次数提升速度）"""
        for attempt in range(retries + 1):
            try:
                req = urllib.request.Request(url, headers=self.headers, method='GET')
                with urllib.request.urlopen(req, timeout=self.timeout, context=self._ssl_ctx) as resp:
                    if resp.status != 200:
                        raise urllib.error.HTTPError(url, resp.status, 'HTTP %d' % resp.status, resp.headers, None)
                    raw = resp.read()
                    if resp.headers.get('Content-Encoding') == 'gzip':
                        raw = gzip.decompress(raw)
                    return raw.decode('utf-8', errors='ignore')
            except Exception as e:
                if attempt == retries:
                    print(f"[ERR] GET {url} failed: {e}")
            if attempt < retries:
                time.sleep(backoff)
                backoff = min(backoff * 2, 2)
        return ""

    def _get_json(self, url):
        """直接获取 JSON，减少解码开销"""
        try:
            req = urllib.request.Request(url, headers=self.headers, method='GET')
            with urllib.request.urlopen(req, timeout=self.timeout, context=self._ssl_ctx) as resp:
                if resp.status == 200:
                    raw = resp.read()
                    if resp.headers.get('Content-Encoding') == 'gzip':
                        raw = gzip.decompress(raw)
                    return json.loads(raw.decode('utf-8', errors='ignore'))
        except Exception as e:
            print(f"[ERR] JSON GET {url} failed: {e}")
        return None

    def _post(self, url, data, headers=None):
        try:
            post_headers = headers or dict(self.headers)
            post_headers['Content-Type'] = 'application/x-www-form-urlencoded'
            post_data = urllib.parse.urlencode(data).encode('utf-8')
            req = urllib.request.Request(url, data=post_data, headers=post_headers, method='POST')
            with urllib.request.urlopen(req, timeout=self.timeout, context=self._ssl_ctx) as resp:
                raw = resp.read()
                if resp.headers.get('Content-Encoding') == 'gzip':
                    raw = gzip.decompress(raw)
                return raw.decode('utf-8', errors='ignore')
        except Exception as e:
            print(f"[ERR] POST {url} error: {e}")
            return ""

    def _strip_tags(self, s):
        if not s:
            return ""
        s = re.sub(r'<br\s*/?>', '\n', s, flags=re.IGNORECASE)
        s = re.sub(r'<[^>]+>', '', s)
        s = html_mod.unescape(s)
        s = re.sub(r'\s+', ' ', s).strip()
        return s

    def _extract_pic_from_attrs(self, attrs):
        """从 img 属性字符串中提取图片，优先 data-original"""
        do = re.search(r'data-original="([^"]*)"', attrs)
        if do:
            pic = do.group(1)
            if pic and not pic.endswith('/load.png'):
                return pic
        src = re.search(r'src="([^"]*)"', attrs)
        if src:
            pic = src.group(1)
            if pic and not pic.endswith('/load.png'):
                return pic
        return ""

    # ========== 首页 ==========

    def homeContent(self, filter):
        html = self._get(self.site_url + '/')
        videos = self._extract_videos(html) if html else []

        categories = [
            {
                "type_id": "J7777J",
                "type_name": "电影",
                "sub": [
                    {"type_id": "J7777J", "type_name": "全部电影"},
                    {"type_id": "p7777J", "type_name": "喜剧片"},
                    {"type_id": "u7777J", "type_name": "动作片"},
                    {"type_id": "B7777J", "type_name": "爱情片"},
                    {"type_id": "57777J", "type_name": "科幻片"},
                    {"type_id": "v7777J", "type_name": "恐怖片"},
                    {"type_id": "A7777J", "type_name": "剧情片"},
                    {"type_id": "j7777J", "type_name": "战争片"},
                    {"type_id": "P7777J", "type_name": "纪录片"},
                    {"type_id": "Y7777J", "type_name": "电影解说"},
                ],
            },
            {
                "type_id": "K7777J",
                "type_name": "电视剧",
                "sub": [
                    {"type_id": "K7777J", "type_name": "全部电视剧"},
                    {"type_id": "G7777J", "type_name": "国产剧"},
                    {"type_id": "L7777J", "type_name": "港台剧"},
                    {"type_id": "X7777J", "type_name": "韩剧"},
                    {"type_id": "Z7777J", "type_name": "欧美剧"},
                    {"type_id": "m7777J", "type_name": "日剧"},
                    {"type_id": "y7777J", "type_name": "泰剧"},
                    {"type_id": "87777J", "type_name": "海外剧"},
                ],
            },
            {"type_id": "r7777J", "type_name": "综艺"},
            {"type_id": "97777J", "type_name": "动漫"},
            {"type_id": "O7777J", "type_name": "短剧"},
        ]

        filters = {}
        for c in categories:
            sub = c.get("sub", [])
            if sub:
                filters[c["type_id"]] = [
                    {
                        "key": "channel",
                        "name": "二级分类",
                        "value": [{"n": s["type_name"], "v": s["type_id"]} for s in sub],
                    }
                ]

        return {
            "class": [{"type_id": c["type_id"], "type_name": c["type_name"]} for c in categories],
            "list": videos[:30],
            "filters": filters,
        }

    def homeVideoContent(self):
        return self.homeContent(False)

    # ========== 列表解析 ==========

    def _extract_videos(self, html):
        """提取视频列表卡片（修复 img 属性顺序问题）"""
        if not html:
            return []
        videos = []
        seen = set()

        for href, vid, title, img_attrs, status in self._card_item_re.findall(html):
            if vid in seen:
                continue
            seen.add(vid)
            pic = self._extract_pic_from_attrs(img_attrs)
            videos.append({
                "vod_id": vid,
                "vod_name": self._strip_tags(title) or vid,
                "vod_pic": self._fix_url(pic) if pic else self.default_pic,
                "vod_remarks": self._strip_tags(status),
            })

        # 兜底：按 li 块解析
        if not videos:
            for li in re.findall(r'<li[^>]*class="uv-yjgh-erobmb[^"]*"[^>]*>(.*?)</li>', html, re.DOTALL):
                href_m = re.search(r'href="(/liema/(\d+)\.html)"', li)
                if not href_m:
                    continue
                vid = href_m.group(2)
                if vid in seen:
                    continue
                seen.add(vid)
                title_m = re.search(r'title="([^"]*)"', li)
                pic = self._extract_pic_from_attrs(li)
                status_m = re.search(r'<span[^>]*class="[^"]*pic-text[^"]*"[^>]*>([^<]*)</span>', li)
                videos.append({
                    "vod_id": vid,
                    "vod_name": self._strip_tags(title_m.group(1)) if title_m else vid,
                    "vod_pic": self._fix_url(pic) if pic else self.default_pic,
                    "vod_remarks": self._strip_tags(status_m.group(1)) if status_m else '',
                })

        return videos

    # ========== 分类 ==========

    def categoryContent(self, tid, pg, filter, extend):
        page = int(pg) if pg else 1
        real_tid = extend.get('channel') if extend else tid
        if not real_tid:
            real_tid = tid
        url = f"{self.site_url}/vodshow/{real_tid}--------{page}---.html"
        html = self._get(url)
        videos = self._extract_videos(html) if html else []

        pagecount = 1
        if html:
            m = self._pagecount_re.search(html)
            if m:
                pagecount = int(m.group(1))
        return {
            "list": videos,
            "page": page,
            "pagecount": pagecount,
            "limit": 30,
            "total": pagecount * 30,
        }

    # ========== 搜索（修复：使用苹果CMS搜索建议JSON接口）==========

    def searchContent(self, key, quick, pg="1"):
        page = int(pg) if pg else 1
        limit = 10
        # 苹果CMS 搜索建议接口，比解析 HTML 快且不会被 403
        url = f"{self.site_url}/index.php/ajax/suggest?mid=1&wd={urllib.parse.quote(key)}&page={page}&limit={limit}"
        data = self._get_json(url)
        if not data or data.get('code') != 1:
            return {"list": [], "page": page, "pagecount": 1, "limit": limit, "total": 0}

        videos = []
        for item in data.get('list', []):
            videos.append({
                "vod_id": str(item.get('id', '')),
                "vod_name": item.get('name', ''),
                "vod_pic": self._fix_url(item.get('pic', '')),
                "vod_remarks": '',
            })

        total = data.get('total', 0)
        pagecount = data.get('pagecount', 1)
        return {
            "list": videos,
            "page": page,
            "pagecount": pagecount,
            "limit": limit,
            "total": total,
        }

    # ========== 详情 ==========

    def detailContent(self, ids):
        if not ids:
            return {"list": []}
        vid = str(ids[0])
        url = f"{self.site_url}/liema/{vid}.html"
        html = self._get(url)
        if not html:
            return {"list": []}

        name = vid
        title_m = self._title_re.search(html)
        if title_m:
            name = self._strip_tags(title_m.group(1))

        pic = self.default_pic
        for p in self._pic_re.findall(html):
            if p and not p.endswith('/load.png'):
                pic = self._fix_url(p)
                break

        type_name = ""
        year = ""
        area = ""
        lang = ""
        actor = ""
        director = ""
        content = ""
        update = ""

        for label, val_html in self._info_re.findall(html):
            val = self._strip_tags(val_html)
            label = label.strip()
            if '主演' in label:
                actor = val
            elif '导演' in label:
                director = val
            elif '更新' in label or '状态' in label:
                update = val
            elif '类型' in label:
                type_name = val
            elif '地区' in label:
                area = val
            elif '语言' in label:
                lang = val
            elif '年份' in label:
                year = val

        # 从 tag 链接补全
        tag_re = re.compile(r'<a[^>]*href="/search/(class|year|area|lang)/[^"]*"[^>]*>([^<]*)</a>', re.IGNORECASE)
        for kind, val in tag_re.findall(html):
            if kind == 'class' and not type_name:
                type_name = val
            elif kind == 'year' and not year:
                year = val
            elif kind == 'area' and not area:
                area = val
            elif kind == 'lang' and not lang:
                lang = val

        # 简介
        desc_m = self._desc_re.search(html)
        if desc_m:
            content = self._strip_tags(desc_m.group(1))

        # 播放列表
        play_from = []
        play_url = []

        playlist_m = self._playlist_re.search(html)
        if playlist_m:
            links = self._play_link_re.findall(playlist_m.group(1))
            if links:
                items = [f"{n.strip()}${h}" for h, v2, s, n_, n in links]
                play_from.append("默认线路")
                play_url.append('#'.join(items))

        if not play_url:
            play_link = re.search(r'href="(/liemaplay/(\d+)-(\d+)-(\d+)\.html)"', html)
            if play_link:
                play_from.append("默认线路")
                play_url.append(f"立即播放${play_link.group(1)}")

        result = [{
            "vod_id": vid,
            "vod_name": name,
            "vod_pic": pic,
            "type_name": type_name,
            "vod_year": year,
            "vod_area": area,
            "vod_lang": lang,
            "vod_actor": actor,
            "vod_director": director,
            "vod_remarks": update,
            "vod_content": content,
            "vod_play_from": '$$$'.join(play_from),
            "vod_play_url": '$$$'.join(play_url),
        }]
        return {"list": result}

    # ========== 播放 ==========

    def playerContent(self, flag, id, vipFlags):
        if id.startswith('/'):
            play_url = self.site_url + id
        elif id.startswith('http'):
            play_url = id
        else:
            play_url = f"{self.site_url}/liemaplay/{id}"
        html = self._get(play_url, retries=1)
        if html:
            m = self._player_json_re.search(html)
            if m:
                try:
                    data = json.loads(m.group(1))
                    real = data.get('url', '')
                    if real:
                        return {
                            "parse": 0,
                            "url": real,
                            "header": self.headers,
                        }
                except Exception as e:
                    print(f"[WARN] player JSON parse error: {e}")
        return {
            "parse": 1,
            "url": play_url,
            "header": self.headers,
        }

    # ========== 辅助 ==========

    def isVideoFormat(self, url):
        return '.m3u8' in url or '.mp4' in url

    def manualVideoCheck(self):
        return False


# ========== 本地测试入口 ==========
if __name__ == '__main__':
    s = Spider()
    s.init()
    print("===== 首页 =====")
    home = s.homeContent(True)
    print(f"分类数: {len(home.get('class', []))}")
    print(f"视频数: {len(home.get('list', []))}")
    if home.get('list'):
        v = home['list'][0]
        print(f"样本: {v['vod_name']} | ID={v['vod_id']} | 图={v['vod_pic'][:60]}... | 状态={v['vod_remarks']}")

    print("\n===== 分类（电影第1页）=====")
    cat = s.categoryContent('J7777J', '1', False, {})
    print(f"分类视频数: {len(cat.get('list', []))}, 总页数: {cat.get('pagecount', 0)}")

    print("\n===== 二级分类（喜剧片）=====")
    cat2 = s.categoryContent('J7777J', '1', False, {'channel': 'p7777J'})
    print(f"二级分类视频数: {len(cat2.get('list', []))}, 总页数: {cat2.get('pagecount', 0)}")
    if cat2.get('list'):
        print(f"样本: {cat2['list'][0]['vod_name']} | {cat2['list'][0]['vod_pic'][:60]}...")

    print("\n===== 搜索 =====")
    sr = s.searchContent('海绵宝宝', False, '1')
    print(f"搜索结果数: {len(sr.get('list', []))}, 总页数: {sr.get('pagecount', 0)}")
    if sr.get('list'):
        print(f"样本: {sr['list'][0]['vod_name']} | ID={sr['list'][0]['vod_id']}")

    print("\n===== 详情 =====")
    det = s.detailContent(['61854'])
    if det.get('list'):
        d = det['list'][0]
        print(f"标题: {d['vod_name']}")
        print(f"图片: {d['vod_pic'][:60]}...")
        print(f"播放: {d.get('vod_play_url', '')[:80]}...")

    print("\n===== 播放 =====")
    play = s.playerContent('默认线路', '/liemaplay/61854-1-1.html', [])
    print(f"parse={play.get('parse')}, url={play.get('url', '')[:80]}...")
