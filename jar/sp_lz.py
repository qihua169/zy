# -*- coding: utf-8 -*-
"""
sp_lz_tvbox.py — 蓝奏资源（cj.lziapi.com）TVBox / 猫影视 数据源
================================================================
接口形态：MacCMS 提供者 JSON API（非 HTML 页面站），实测契约（2026-08）：
  - 列表/分类:  {API}?ac=videolist&t={tid}&pg={n}   （完整字段，含 vod_pic，20/页）
  - 首页:       {API}?ac=videolist&pg={n}           （全站最新）
  - 搜索:       {API}?ac=videolist&wd={kw}&pg={n}
  - 详情:       {API}?ac=detail&ids={vod_id}
               -> list[0].vod_play_from = "liangzi$$$lzm3u8"
               -> list[0].vod_play_url  = "HD中字$https://{cdn}/share/{hash}$$$HD中字$https://{cdn}/.../index.m3u8"
                 ★ lzm3u8 源直接给 m3u8 直链（parse:0 直播放）；liangzi 源是 share 页需再解析
  - 播放(share): https://{cdn}/share/{hash} 返回 HTML 播放页，内嵌
               var main = "/20250923/xxx/index.m3u8?sign=..."（相对路径）
               m3u8 完整地址 = share 链接域名 + main
  - code: 1 = 成功；total/pagecount 响应自带（无需自行计算）
  - 分类树：ac=list 响应附带 class（含 type_pid 层级），此处按白名单硬编码更稳

分类白名单（直接使用有数据的子分类 tid，均可独立分页）：
  电影：动作片6 喜剧片7 爱情片8 科幻片9 恐怖片10 剧情片11 战争片12 记录片20 动画片49 预告片45
  剧集：国产剧13 香港剧14 韩国剧15 欧美剧16 日本剧22 台湾剧21 海外剧23 泰国剧24
  综艺：大陆综艺25 港台综艺26 日韩综艺27 欧美综艺28
  动漫：国产动漫29 日韩动漫30 欧美动漫31
  其它：电影解说35 短剧46 AI漫剧52
  ⚠ 父分类（电影片1/连续剧2/综艺片3/动漫片4）直接挂载数据极少（实测 t=1 仅 1 条），
    故 TVBox 一级分类直接用子分类 tid。如需增删，改 CATS 即可。

部署规范（TVBox Spider 接口）：
  1. 继承 base.spider.Spider，网络统一走 self.fetch（本文件已带本地 urllib 桩，PC 可自检）。
  2. playerContent 的 header 为 json.dumps(dict) 字符串。
  3. 所有接口 try/except 兜底返回合法结构，异常不外抛。
"""

import re
import json
from urllib.parse import urlencode, urlsplit

try:
    from base.spider import Spider as _TVBase
except Exception:
    # ── 本地调试桩（PC 端无 base.spider）：urllib 实现 fetch/post ──
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
            body = urlencode(data or {}).encode()
            r = urlopen(Request(url, data=body, headers=headers or {},
                                method="POST"), timeout=timeout)
            return self._resp(r.read())
    # ── 桩结束 ──


# ═══════════ 站点配置 ═══════════
SITE_NAME = "蓝奏资源"
API = "https://cj.lziapi.com/api.php/provide/vod"
UA = ("Mozilla/5.0 (Linux; Android 12) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/125.0.0.0 Mobile Safari/537.36")

# 分类白名单（type_id, 显示名）——直接用有数据的子分类 tid
CATS = [
    # 电影
    ("6", "动作片"), ("7", "喜剧片"), ("8", "爱情片"), ("9", "科幻片"),
    ("10", "恐怖片"), ("11", "剧情片"), ("12", "战争片"), ("20", "记录片"),
    ("49", "动画片"), ("45", "预告片"),
    # 剧集
    ("13", "国产剧"), ("14", "香港剧"), ("15", "韩国剧"), ("16", "欧美剧"),
    ("22", "日本剧"), ("21", "台湾剧"), ("23", "海外剧"), ("24", "泰国剧"),
    # 综艺
    ("25", "大陆综艺"), ("26", "港台综艺"), ("27", "日韩综艺"), ("28", "欧美综艺"),
    # 动漫
    ("29", "国产动漫"), ("30", "日韩动漫"), ("31", "欧美动漫"),
    # 其它
    ("35", "电影解说"), ("46", "短剧"), ("52", "AI漫剧"),
]

# share 播放页内 m3u8 相对路径：var main = "/path/index.m3u8?sign=..."
RE_M3U8 = re.compile(r'var\s+main\s*=\s*"([^"]+)"')
# 兜底：任意 m3u8 引用
RE_M3U8_2 = re.compile(r'["\']([^"\']*\.m3u8[^"\']*)["\']', re.I)

DIRECT_SUFFIX = (".m3u8", ".mp4", ".flv", ".ts")


def _clean_html(s):
    s = re.sub(r'<[^>]+>', '', s or "")
    return re.sub(r'\s+', ' ', s.replace("&nbsp;", " ").replace("\u3000", " ")).strip()


class LzSpider(_TVBase):

    def getName(self):
        return SITE_NAME

    def init(self, extend=""):
        pass  # 让基类 __init__ 自然初始化

    # ── 网络辅助 ──
    def _headers(self):
        return {"User-Agent": UA, "Referer": API.rsplit("/", 1)[0] + "/",
                "Accept": "application/json,text/plain,*/*"}

    def _fetch_text(self, url, headers=None, timeout=15):
        rsp = self.fetch(url, headers=headers or self._headers(), timeout=timeout)
        if isinstance(rsp, bytes):
            return rsp.decode("utf-8", errors="ignore")
        if isinstance(rsp, str):
            return rsp
        try:
            return rsp.text
        except Exception:
            return str(rsp)

    def _api(self, params):
        """调用提供者 API，返回 dict；失败/非成功返回 {}。"""
        try:
            txt = self._fetch_text(API + "?" + urlencode(params))
            data = json.loads(txt or "{}")
            if data.get("code") != 1:
                return {}
            return data
        except Exception:
            return {}

    def _vods(self, data):
        """API list -> TVBox vod 列表（精简字段）。"""
        out = []
        for v in data.get("list") or []:
            out.append({
                "vod_id": str(v.get("vod_id", "")),
                "vod_name": v.get("vod_name", "") or "",
                "vod_pic": v.get("vod_pic", "") or "",
                "vod_remarks": v.get("vod_remarks", "") or "",
                "vod_year": v.get("vod_year", "") or "",
            })
        return out

    # ── TVBox 接口 ──
    def homeContent(self, filter):
        return {"class": [{"type_id": tid, "type_name": name}
                          for tid, name in CATS], "filters": {}}

    def homeVideoContent(self):
        try:
            return {"list": self._vods(self._api({"ac": "videolist", "pg": 1}))}
        except Exception:
            return {"list": []}

    def categoryContent(self, tid, pg, filter, extend):
        page = int(pg) if str(pg).isdigit() else 1
        try:
            data = self._api({"ac": "videolist", "t": tid, "pg": page})
            items = self._vods(data)
            total = int(data.get("total") or 0)
            pc = int(data.get("pagecount") or (max(1, (total + 19) // 20) if total else 1))
            return {"list": items, "page": page, "pagecount": pc,
                    "limit": 20, "total": total}
        except Exception:
            return {"list": [], "page": page, "pagecount": 1,
                    "limit": 20, "total": 0}

    def detailContent(self, ids):
        vid = str(ids[0]) if isinstance(ids, (list, tuple)) and ids else str(ids or "")
        try:
            data = self._api({"ac": "detail", "ids": vid})
            lst = data.get("list") or []
            if not lst:
                return {"list": [{"vod_id": vid, "vod_name": vid,
                                  "vod_play_from": "lzm3u8", "vod_play_url": ""}]}
            v = lst[0]
            vod = {
                "vod_id": str(v.get("vod_id", vid)),
                "vod_name": v.get("vod_name", "") or "",
                "vod_pic": v.get("vod_pic", "") or "",
                "vod_remarks": v.get("vod_remarks", "") or "",
                "vod_year": v.get("vod_year", "") or "",
                "vod_area": v.get("vod_area", "") or "",
                "vod_lang": v.get("vod_lang", "") or "",
                "vod_actor": v.get("vod_actor", "") or "",
                "vod_director": v.get("vod_director", "") or "",
                "vod_class": v.get("vod_class", "") or "",
                "vod_content": _clean_html(v.get("vod_content", "")),
                "vod_play_from": v.get("vod_play_from", "") or "liangzi",
                "vod_play_url": v.get("vod_play_url", "") or "",
            }
            # 过滤不可播源：lzm3u8 源给的是无 sign 直链（实测请求返回空 body），
            # 只保留 share 链接线路（可解析出带 sign 的 m3u8）或已带 sign 的直链。
            pf = (vod.get("vod_play_from") or "").split("$$$")
            pu = (vod.get("vod_play_url") or "").split("$$$")
            keep = [(n, u) for n, u in zip(pf, pu)
                    if u and ("/share/" in u.split("#")[0].split("$")[-1]
                              or "sign=" in u.split("#")[0].split("$")[-1])]
            if keep:
                vod["vod_play_from"] = "$$$".join(n for n, _ in keep)
                vod["vod_play_url"] = "$$$".join(u for _, u in keep)
            return {"list": [vod]}
        except Exception:
            return {"list": [{"vod_id": vid, "vod_name": vid,
                              "vod_play_from": "lzm3u8", "vod_play_url": ""}]}

    def searchContent(self, key, quick, pg="1"):
        page = int(pg) if str(pg).isdigit() else 1
        try:
            data = self._api({"ac": "videolist", "wd": key, "pg": page})
            items = self._vods(data)
            total = int(data.get("total") or 0)
            pc = int(data.get("pagecount") or (max(1, (total + 19) // 20) if total else 1))
            return {"list": items, "page": page, "pagecount": pc,
                    "limit": 20, "total": total}
        except Exception:
            return {"list": [], "page": page, "pagecount": 1,
                    "limit": 20, "total": 0}

    def playerContent(self, flag, id, vipFlags):
        hd = json.dumps({"User-Agent": UA})
        try:
            play_url = id if id.startswith("http") else ("https://" + id)
            low = play_url.lower()
            # 形态一：m3u8/mp4 直链（lzm3u8 源直接给直链）→ parse:0 直播放
            if low.split("?")[0].endswith(DIRECT_SUFFIX):
                ps = urlsplit(play_url)
                hd = json.dumps({"User-Agent": UA,
                                 "Referer": "%s://%s/" % (ps.scheme, ps.netloc)})
                return {"parse": 0, "url": play_url, "header": hd}
            # 形态二：share 播放页 → 抓页取 var main 相对路径拼绝对 m3u8
            html = self._fetch_text(play_url)
            m = RE_M3U8.search(html or "") or RE_M3U8_2.search(html or "")
            if not m:
                return {"parse": 1, "url": play_url, "header": hd}
            rel = m.group(1).strip()
            if not rel.split("?")[0].lower().endswith(DIRECT_SUFFIX):
                return {"parse": 1, "url": play_url, "header": hd}
            if rel.startswith("http"):
                url = rel
            else:
                ps = urlsplit(play_url)
                url = "%s://%s%s" % (ps.scheme, ps.netloc,
                                     rel if rel.startswith("/") else "/" + rel)
            # CDN 防盗链：Referer 指向播放域名
            ps2 = urlsplit(url)
            hd = json.dumps({"User-Agent": UA,
                             "Referer": "%s://%s/" % (ps2.scheme, ps2.netloc)})
            return {"parse": 0, "url": url, "header": hd}
        except Exception:
            return {"parse": 1, "url": id, "header": hd}

    # ── stub ──
    def isVideoFormat(self, url):
        u = (url or "").lower().split("?")[0]
        return any(u.endswith(s) for s in DIRECT_SUFFIX)

    def manualVideoCheck(self):
        pass

    def localProxy(self, param):
        return [200, "video/MP2T", "", ""]


# 兼容按 module.Spider 类名加载的 TVBox 变体
Spider = LzSpider


if __name__ == "__main__":
    s = LzSpider()
    s.init()
    print("==> homeContent:", json.dumps(s.homeContent(False), ensure_ascii=False)[:400])
    print("==> category(动作片6):", json.dumps(s.categoryContent("6", 1, False, {}), ensure_ascii=False)[:400])
    d = s.detailContent(["154130"])
    print("==> detail:", json.dumps({k: (v[:150] if isinstance(v, str) else v)
                                     for k, v in d["list"][0].items()}, ensure_ascii=False)[:900])
    print("==> search(战争):", json.dumps(s.searchContent("战争", False, "1"), ensure_ascii=False)[:300])
    if d.get("list") and d["list"][0].get("vod_play_url"):
        eps = d["list"][0]["vod_play_url"].split("$$$")
        for ep in eps:
            link = ep.split("#")[0].split("$")[-1]
            print("==> player(%s):" % link[:60], json.dumps(s.playerContent("lzm3u8", link, ""), ensure_ascii=False)[:300])
