# -*- coding: utf-8 -*-
"""
TVBox / 猫影视 Spider —— 新浪API (xinlangapi.com) MacCMS 提供者 JSON API
=========================================================================

站点形态：MacCMS 提供者 JSON API（ac=videolist / ac=detail / ac=list）。
  - ac=list      : 精简字段（无 vod_pic），用于快速翻页/分类/搜索计数
  - ac=videolist : 完整字段（含 vod_pic / vod_play_url），列表与搜索统一用它，保证封面
  - ac=detail    : 单/批量详情（ids 逗号分隔），含完整 vod_play_url
  - ac=class     : 该站【未实现】（返回视频列表），分类树由离线扫描硬编码（见 CLASSES）

播放链路：
  vod_play_from = "xlyun$$$xlm3u8"
  vod_play_url  = "第1集$https://play.xluuss.com/play/xxx#...$$$第1集$https://play.xluuss.com/play/xxx/index.m3u8#..."
  - xlm3u8 源：直链 m3u8（playerContent 直接 parse:0 投放）
  - xlyun   源：播放页，需抓页提取 .m3u8（已验证页内嵌直链）
  m3u8 为 AES-128 加密（EXT-X-KEY URI="enc.key" 相对路径），TVBox 内置 HLS 播放器原生解密。

接口约束（TVBox 规范）：
  - 继承 base.spider.Spider；网络统一走 self.fetch（禁止自写 urllib/requests 发请求）
  - init 极简 pass；所有方法 try/except 兜底返回合法结构，异常不外抛
  - playerContent 的 header 字段 = json.dumps(dict) 字符串
  - 模块别名 Spider = XinLangSpider（兼容按 module.Spider 加载的变体）

本地调试：PC 端无 base.spider 时，下方 _TVBase 桩用 urllib 提供 fetch，
  `python sp_xinlang_tvbox.py` 直接跑线上自检；设 TVBOX_FIXTURES 指向 fixtures 目录可跑离线校验。
"""
import re
import json

try:
    from base.spider import Spider as _TVBase
except Exception:
    # ── 本地 PC 调试桩（无 base.spider）：urllib 实现 fetch，返回带 .text 的对象 ──
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
    # ── 桩结束 ──


# ════════════ 站点配置 ════════════
SITE_NAME = "新浪API"
API = "http://api.xinlangapi.com/xinlangapi.php/provide/vod"
UA = ("Mozilla/5.0 (Linux; Android 12) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/125.0.0.0 Mobile Safari/537.36")
PLAY_HOST = "https://play.xluuss.com/"      # 播放/CDN 域名（Referer 防盗链用）

# 分类树：该站 ac=class 未实现，以下为由全库扫描得到的 36 个真实叶子分类
# （每个 type_id 都可直接作为 t= 过滤参数；无年份/地区服务端筛选，filters 留空）
CLASSES = [
    {"type_id": "6",  "type_name": "动作片"},
    {"type_id": "7",  "type_name": "爱情片"},
    {"type_id": "8",  "type_name": "科幻片"},
    {"type_id": "9",  "type_name": "战争片"},
    {"type_id": "10", "type_name": "剧情片"},
    {"type_id": "11", "type_name": "恐怖片"},
    {"type_id": "12", "type_name": "喜剧片"},
    {"type_id": "22", "type_name": "伦理片"},
    {"type_id": "42", "type_name": "悬疑片"},
    {"type_id": "43", "type_name": "犯罪片"},
    {"type_id": "44", "type_name": "奇幻片"},
    {"type_id": "5",  "type_name": "纪录片"},
    {"type_id": "13", "type_name": "大陆剧"},
    {"type_id": "14", "type_name": "港澳剧"},
    {"type_id": "15", "type_name": "台湾剧"},
    {"type_id": "16", "type_name": "欧美剧"},
    {"type_id": "17", "type_name": "动画片"},
    {"type_id": "18", "type_name": "韩剧"},
    {"type_id": "20", "type_name": "日剧"},
    {"type_id": "21", "type_name": "泰剧"},
    {"type_id": "38", "type_name": "中国动漫"},
    {"type_id": "39", "type_name": "日本动漫"},
    {"type_id": "40", "type_name": "欧美动漫"},
    {"type_id": "26", "type_name": "足球"},
    {"type_id": "27", "type_name": "篮球"},
    {"type_id": "45", "type_name": "大陆综艺"},
    {"type_id": "46", "type_name": "日韩综艺"},
    {"type_id": "47", "type_name": "港台综艺"},
    {"type_id": "49", "type_name": "古装仙侠"},
    {"type_id": "50", "type_name": "现代都市"},
    {"type_id": "51", "type_name": "穿越年代"},
    {"type_id": "52", "type_name": "言情总裁"},
    {"type_id": "53", "type_name": "重生民国"},
    {"type_id": "54", "type_name": "反转爽剧"},
    {"type_id": "55", "type_name": "脑洞悬疑"},
    {"type_id": "56", "type_name": "擦边短剧"},
]

# m3u8 直链特征（播放页内嵌提取用）
RE_M3U8 = re.compile(r'https?://[^\s"\'\)]+?\.m3u8(?:\?[^"\'\s)]*)?', re.I)


def _clean(s):
    if not s:
        return ""
    s = re.sub(r'<[^>]+>', '', s)
    s = s.replace("&nbsp;", " ").replace("\u3000", " ").replace("&amp;", "&")
    return re.sub(r'\s+', ' ', s).strip()


class XinLangSpider(_TVBase):

    def getName(self):
        return SITE_NAME

    def init(self, extend=""):
        pass   # 让基类 __init__ 自然初始化（不要跳过 super().__init__）

    # ── 网络辅助 ──
    def _headers(self):
        return {"User-Agent": UA, "Referer": API + "/",
                "Accept": "application/json,text/html,*/*"}

    def _fetch_text(self, url):
        r = self.fetch(url, headers=self._headers(), timeout=15)
        if isinstance(r, str):
            return r
        if hasattr(r, "text"):
            return r.text
        if hasattr(r, "content"):
            return r.content.decode("utf-8", "ignore")
        return str(r)

    def _fetch_json(self, url):
        return json.loads(self._fetch_text(url))

    def _api(self, **params):
        from urllib.parse import urlencode
        return API + "?" + urlencode(params)

    # ── 列表条目映射（videolist / detail 字段兼容） ──
    def _map_vod(self, v):
        return {
            "vod_id": str(v.get("vod_id")),
            "vod_name": v.get("vod_name", ""),
            "vod_pic": v.get("vod_pic") or "",
            "vod_remarks": v.get("vod_remarks", ""),
        }

    def _detail_vod(self, v):
        item = {
            "vod_id": str(v.get("vod_id")),
            "vod_name": v.get("vod_name", ""),
            "vod_pic": v.get("vod_pic") or "",
            "vod_remarks": v.get("vod_remarks", ""),
            "vod_year": v.get("vod_year", ""),
            "vod_area": v.get("vod_area", ""),
            "vod_lang": v.get("vod_lang", ""),
            "vod_actor": v.get("vod_actor", ""),
            "vod_director": v.get("vod_director", ""),
            "vod_content": _clean(v.get("vod_content", "")),
        }
        pf = v.get("vod_play_from", "")
        pu = v.get("vod_play_url", "")
        if pf and pu:
            # 已是 TVBox 格式：源间 $$$，集间 #，集名$URL —— 原样透传
            item["vod_play_from"] = pf
            item["vod_play_url"] = pu
        return item

    # ── TVBox 接口（保持契约，勿改签名） ──
    def homeContent(self, filter):
        # 分类树硬编码，filters 留空（该站无服务端年份/地区筛选）
        return {"class": CLASSES, "filters": {}}

    def homeVideoContent(self):
        try:
            d = self._fetch_json(self._api(ac="videolist", pg=1))
            items = [self._map_vod(v) for v in d.get("list", [])]
            return {"list": items}
        except Exception:
            return {"list": []}

    def categoryContent(self, tid, pg, filter, extend):
        page = int(pg) if pg else 1
        try:
            d = self._fetch_json(self._api(ac="videolist", t=tid, pg=page))
            items = [self._map_vod(v) for v in d.get("list", [])]
            return {"list": items, "page": page,
                    "pagecount": int(d.get("pagecount", 1) or 1),
                    "limit": int(d.get("limit", 20) or 20),
                    "total": int(d.get("total", 0) or 0)}
        except Exception:
            return {"list": [], "page": page, "pagecount": 1, "limit": 20, "total": 0}

    def detailContent(self, ids):
        try:
            vid = str(ids[0]) if ids else ""
            d = self._fetch_json(self._api(ac="detail", ids=vid))
            lst = d.get("list", [])
            if not lst:
                return {"list": [{"vod_id": vid, "vod_name": "无数据"}]}
            return {"list": [self._detail_vod(lst[0])]}
        except Exception as e:
            vid = str(ids[0]) if ids else ""
            return {"list": [{"vod_id": vid, "vod_name": "解析异常",
                              "vod_content": str(e)[:200]}]}

    def searchContent(self, key, quick, pg="1"):
        page = int(pg) if pg else 1
        try:
            d = self._fetch_json(self._api(ac="videolist", wd=key, pg=page))
            items = [self._map_vod(v) for v in d.get("list", [])]
            return {"list": items, "page": page,
                    "pagecount": int(d.get("pagecount", 1) or 1),
                    "limit": int(d.get("limit", 20) or 20),
                    "total": int(d.get("total", 0) or 0)}
        except Exception:
            return {"list": [], "page": page, "pagecount": 1, "limit": 20, "total": 0}

    def playerContent(self, flag, id, vipFlags):
        hd = json.dumps({"User-Agent": UA, "Referer": PLAY_HOST})
        try:
            url = (id or "").strip()
            if not url.startswith("http"):
                url = PLAY_HOST.rstrip("/") + "/" + url.lstrip("/")
            # 直链 m3u8：去掉查询串再判断后缀（sign 参数会干扰 endswith）
            if url.split("?")[0].lower().endswith(".m3u8"):
                return {"parse": 0, "playUrl": "", "url": url, "header": hd}
            # 否则视为播放页，抓页提取内嵌 m3u8
            html = self._fetch_text(url)
            m = RE_M3U8.search(html or "")
            if m:
                return {"parse": 0, "playUrl": "", "url": m.group(0), "header": hd}
            # 兜底：交给框架二次解析
            return {"parse": 1, "playUrl": "", "url": url, "header": hd}
        except Exception:
            return {"parse": 1, "playUrl": "", "url": id, "header": hd}

    def isVideoFormat(self, url):
        return (url or "").split("?")[0].lower().endswith((".m3u8", ".mp4", ".ts", ".flv"))

    def manualVideoCheck(self):
        pass

    def localProxy(self, param):
        # 直链 m3u8，无需代理转发；返回空壳占位
        return [200, "video/MP2T", "", ""]


# 兼容按 module.Spider 类名加载的 TVBox 变体
Spider = XinLangSpider


# ════════════ 自检（PC 端直接运行；TVBox 环境不执行） ════════════
if __name__ == "__main__":
    import os, glob

    def install_offline(sp):
        """若设 TVBOX_FIXTURES 且目录存在，monkeypatch fetch 走 fixtures（离线校验）。"""
        fx = os.environ.get("TVBOX_FIXTURES")
        if not fx or not os.path.isdir(fx):
            return False

        def fake_fetch(url, headers=None, timeout=15):
            cand = None
            if "play.xluuss.com" in url:
                cand = "play.html"
            elif "ids=" in url:
                m = re.search(r"ids=(\d+)", url)
                cand = "detail_%s.json" % m.group(1) if m else None
            elif "wd=" in url:
                cand = "search.json"
            elif "t=" in url:
                m = re.search(r"t=(\d+)", url)
                cand = "cat_%s.json" % m.group(1) if m else None
            elif "ac=videolist" in url:
                cand = "videolist_home.json"
            if cand and os.path.exists(os.path.join(fx, cand)):
                with open(os.path.join(fx, cand), "r", encoding="utf-8", errors="ignore") as f:
                    return f.read()
            return '{"code":1,"msg":"数据列表","page":1,"pagecount":1,"limit":20,"total":0,"list":[]}'

        sp.fetch = fake_fetch
        return True

    s = XinLangSpider()
    s.init()
    offline = install_offline(s)
    print("[mode]", "OFFLINE" if offline else "LIVE")

    print("==> homeContent:", {"class_count": len(s.homeContent(False)["class"])})
    cat = s.categoryContent("13", "1", False, {})
    print("==> categoryContent(大陆剧): items=%d pagecount=%s total=%s"
          % (len(cat["list"]), cat.get("pagecount"), cat.get("total")))
    if cat["list"]:
        vid = cat["list"][0]["vod_id"]
        det = s.detailContent([vid])
        v0 = det["list"][0]
        print("==> detailContent:", {
            "vod_name": v0.get("vod_name"),
            "play_from": v0.get("vod_play_from"),
            "play_url_head": v0.get("vod_play_url", "")[:120],
        })
        pu = v0.get("vod_play_url", "").split("$$$")
        if len(pu) > 1:
            first_ep = pu[1].split("#")[0].split("$")[1]
            print("==> playerContent(m3u8 ep):", s.playerContent("xlm3u8", first_ep, ""))
        if len(pu) > 0:
            cloud_ep = pu[0].split("#")[0].split("$")[1]
            print("==> playerContent(cloud ep):", s.playerContent("xlyun", cloud_ep, ""))
    print("==> searchContent(测试):", s.searchContent("测试", False, "1"))
