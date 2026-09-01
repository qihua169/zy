# -*- coding: utf-8 -*-
"""
电影天堂资源 API · TVBox / 猫影视 数据源 Spider
================================================
站点类型：MacCMS 纯 JSON 提供者 API（`api.php/provide/vod/`）。
实测要点（2026-08 逆向）：
  - `ac=list` 字段精简（无 vod_pic）；`ac=videolist` 含完整字段（封面/选集）。
    首页 / 分类 / 搜索统一用 `ac=videolist`，否则列表无封面。
  - `ac=class` 返回完整分类树（含 type_pid 父子关系）。父级聚合分类（电影片/连续剧/
    综艺片/动漫片）查询返回空，故 TVBox 一级分类只取「子分类」（type_pid != 0）。
  - 分类过滤 `t={tid}`、搜索 `wd={kw}`、分页 `pg={n}`；`total/pagecount` 取响应。
  - 详情 `ac=detail&ids={id}`：`vod_play_from` 用 `$$$` 多源、`vod_play_url` 形如
    `第01集$https://...` —— 已是 TVBox 直链形态，直接透传。
  - 播放源双路：
      · dyttm3u8 源：每集已是直链 m3u8（无 sign，CDN 直出，无需解析）。
      · dytt 源：每集是 share 页 `https://{host}/share/{hash}`，页面内嵌
        `const url = "/path/index.m3u8?sign=..."`，需解析为绝对 m3u8。
  - 年份 / 地区筛选服务端支持（`year` / `area` 参数），已实测组合有效。

部署：TVBox / 猫影视加载本文件，类继承 base.spider.Spider，网络走 self.fetch。
PC 端无 base.spider 时下方 _TVBase 桩用 urllib（失败再退 curl）提供 fetch，
保证 `python sp_dyttzy_tvbox.py` 可直接跑 __main__ 自检。
"""

import re
import json
from urllib.parse import urlsplit

try:
    from base.spider import Spider as _TVBase
except Exception:
    # ── 本地调试桩（PC 端无 base.spider）──
    import subprocess
    from urllib.request import Request, urlopen

    class _TVBase(object):
        def _resp(self, raw):
            class _R(object):
                encoding = "utf-8"
                apparent_encoding = "utf-8"

                @property
                def text(self):
                    if isinstance(raw, (bytes, bytearray)):
                        return raw.decode(self.encoding or "utf-8", errors="ignore")
                    return raw
            return _R()

        def fetch(self, url, headers=None, timeout=15):
            h = headers or {}
            # 1) urllib 优先
            try:
                r = urlopen(Request(url, headers=h), timeout=timeout)
                return self._resp(r.read())
            except Exception:
                pass
            # 2) 部分主机 urllib 在本机拉空（环境偶发），退 curl 兜底
            try:
                cmd = ["curl", "-s", "-L", "--max-time", str(timeout)]
                for k, v in h.items():
                    cmd += ["-H", "%s: %s" % (k, v)]
                cmd.append(url)
                out = subprocess.run(cmd, capture_output=True,
                                     timeout=timeout + 5)
                return self._resp(out.stdout or b"")
            except Exception:
                return self._resp(b"")
    # ── 桩结束 ──


# ═══════════ 站点配置 ═══════════
SITE_NAME = "电影天堂资源"
API_BASE = "https://caiji.dyttzyapi.com/api.php/provide/vod/"
UA = ("Mozilla/5.0 (Linux; Android 12) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/125.0.0.0 Mobile Safari/537.36")

# 二级筛选：年份 / 地区（服务端均支持，实测组合有效）。首项必为「全部」。
YEAR_FILTERS = [{"n": "全部", "v": ""}] + [
    {"n": y, "v": y} for y in
    ["2026", "2025", "2024", "2023", "2022", "2021", "2020",
     "2019", "2018", "2017", "2016", "2015", "2010", "2000"]
]
AREA_FILTERS = [{"n": "全部", "v": ""}] + [
    {"n": a, "v": a} for a in
    ["大陆", "香港", "台湾", "美国", "韩国", "日本",
     "英国", "法国", "德国", "泰国", "印度", "俄罗斯",
     "加拿大", "意大利", "西班牙", "其他"]
]

# share 播放页：const url = "/path/index.m3u8?sign=..." 提取
RE_SHARE_URL = re.compile(r'const\s+url\s*=\s*"([^"]+)"')
# 共享缓存：share 解析结果按集 URL 缓存，避免重复解析
_M3U8_SUFFIX = (".m3u8", ".mp4", ".flv", ".ts")


def _clean(s):
    s = re.sub(r'<[^>]+>', '', s or "")
    s = s.replace("&nbsp;", " ").replace("&amp;", "&")
    return re.sub(r'\s+', ' ', s).strip()


class DyttzySpider(_TVBase):

    def getName(self):
        return SITE_NAME

    def init(self, extend=""):
        self._m3u8_cache = {}
        pass   # 让基类 __init__ 自然初始化

    # ── 网络 ──
    def _api(self, params):
        from urllib.parse import urlencode
        url = API_BASE + "?" + urlencode(params)
        try:
            rsp = self.fetch(url, headers={"User-Agent": UA}, timeout=20)
            return json.loads(rsp.text or "{}")
        except Exception:
            return {}

    def _header_json(self, referer):
        return json.dumps({"User-Agent": UA, "Referer": referer})

    # ── vod 字段映射（API 字段已兼容 TVBox 形态，直接透传播放信息）──
    def _map_vod(self, it):
        return {
            "vod_id": str(it.get("vod_id", "")),
            "vod_name": it.get("vod_name", "") or it.get("vod_en", ""),
            "vod_pic": it.get("vod_pic", "") or "",
            "vod_remarks": it.get("vod_remarks", "") or "",
            "vod_year": it.get("vod_year", "") or "",
            "vod_area": it.get("vod_area", "") or "",
            "vod_lang": it.get("vod_lang", "") or "",
            "vod_actor": it.get("vod_actor", "") or "",
            "vod_director": it.get("vod_director", "") or "",
            "vod_class": it.get("vod_class", "") or "",
            "vod_content": _clean(it.get("vod_content", "")) or "",
            "vod_play_from": it.get("vod_play_from", "") or "",
            "vod_play_url": it.get("vod_play_url", "") or "",
        }

    def _map_list(self, items):
        return [self._map_vod(it) for it in (items or [])]

    # ═══════════ TVBox 接口契约 ═══════════
    def homeContent(self, filter):
        d = self._api({"ac": "class"})
        classes = []
        for c in d.get("class", []):
            # 仅取子分类（父级聚合分类查询为空）
            if str(c.get("type_pid", "0")) == "0":
                continue
            classes.append({"type_id": str(c["type_id"]),
                            "type_name": c["type_name"]})
        filters = {}
        if filter:
            for c in classes:
                filters[c["type_id"]] = [
                    {"key": "year", "name": "年份", "value": YEAR_FILTERS},
                    {"key": "area", "name": "地区", "value": AREA_FILTERS},
                ]
        return {"class": classes, "filters": filters}

    def homeVideoContent(self):
        try:
            d = self._api({"ac": "videolist", "pg": "1"})
            return {"list": self._map_list(d.get("list"))}
        except Exception:
            return {"list": []}

    def categoryContent(self, tid, pg, filter, extend):
        page = int(pg) if pg else 1
        params = {"ac": "videolist", "t": str(tid), "pg": page}
        if extend:
            if extend.get("year"):
                params["year"] = extend["year"]
            if extend.get("area"):
                params["area"] = extend["area"]
        try:
            d = self._api(params)
            items = self._map_list(d.get("list"))
            total = int(d.get("total", len(items)) or len(items))
            pagecount = int(d.get("pagecount", 1) or 1)
            limit = int(d.get("limit", 20) or 20)
            return {"list": items, "page": page, "pagecount": pagecount,
                    "limit": limit, "total": total}
        except Exception:
            return {"list": [], "page": page, "pagecount": 1,
                    "limit": 20, "total": 0}

    def detailContent(self, ids):
        vid = str(ids[0]) if ids else ""
        try:
            d = self._api({"ac": "detail", "ids": vid})
            items = self._map_list(d.get("list"))
            if not items:
                items = [{"vod_id": vid, "vod_name": vid}]
            return {"list": items}
        except Exception:
            return {"list": [{"vod_id": vid, "vod_name": vid}]}

    def searchContent(self, key, quick, pg="1"):
        page = int(pg) if pg else 1
        try:
            d = self._api({"ac": "videolist", "wd": key, "pg": page})
            items = self._map_list(d.get("list"))
            total = int(d.get("total", len(items)) or len(items))
            pagecount = int(d.get("pagecount", 1) or 1)
            return {"list": items, "page": page, "pagecount": pagecount,
                    "limit": 20, "total": total}
        except Exception:
            return {"list": [], "page": page, "pagecount": 1,
                    "limit": 20, "total": 0}

    def playerContent(self, flag, id, vipFlags):
        # id 为 vod_play_url 中每集 URL
        if id in self._m3u8_cache:
            m3u8 = self._m3u8_cache[id]
            return {"parse": 0, "url": m3u8,
                    "header": self._header_json(urlsplit(m3u8).netloc and
                                                ("https://" + urlsplit(m3u8).netloc + "/"))}
        try:
            # 直链 m3u8（dyttm3u8 源）：直接返回
            if id.lower().split("?")[0].endswith(_M3U8_SUFFIX):
                ref = "https://" + urlsplit(id).netloc + "/"
                self._m3u8_cache[id] = id
                return {"parse": 0, "url": id, "header": self._header_json(ref)}
            # share 播放页（dytt 源）：解析 const url
            if "/share/" in id:
                rsp = self.fetch(id, headers={"User-Agent": UA,
                                              "Referer": "https://" +
                                              urlsplit(id).netloc + "/"},
                                 timeout=20)
                html = rsp.text or ""
                m = RE_SHARE_URL.search(html)
                if m:
                    rel = m.group(1)
                    domain = urlsplit(id).netloc
                    m3u8 = "https://" + domain + rel if rel.startswith("/") \
                        else rel
                    ref = "https://" + domain + "/"
                    self._m3u8_cache[id] = m3u8
                    return {"parse": 0, "url": m3u8,
                            "header": self._header_json(ref)}
            # 兜底：交给框架二次解析
            return {"parse": 1, "playUrl": "", "url": id,
                    "header": self._header_json("https://" +
                                                (urlsplit(id).netloc or "") + "/")}
        except Exception:
            return {"parse": 1, "playUrl": "", "url": id,
                    "header": self._header_json("")}

    def isVideoFormat(self, url):
        return any(url.lower().split("?")[0].endswith(s) for s in _M3U8_SUFFIX)

    def manualVideoCheck(self):
        pass

    def localProxy(self, param):
        # 直链站点无需代理；保留 stub
        return [200, "video/MP2T", "", ""]


# 兼容按 module.Spider 类名加载的 TVBox 变体
Spider = DyttzySpider


if __name__ == "__main__":
    s = DyttzySpider()
    s.init()
    print("== homeContent ==")
    hc = s.homeContent(True)
    print("classes:", len(hc["class"]), "first:", hc["class"][:3])
    print("filters sample (tid %s):" % hc["class"][0]["type_id"],
          hc["filters"].get(hc["class"][0]["type_id"]))
    print("\n== categoryContent (t=%s pg=1) ==" % hc["class"][0]["type_id"])
    cc = s.categoryContent(hc["class"][0]["type_id"], 1, False, {})
    print("list:", len(cc["list"]), "pagecount:", cc["pagecount"],
          "total:", cc["total"])
    if cc["list"]:
        v = cc["list"][0]
        print("sample:", v["vod_name"], "|", v["vod_remarks"],
              "| pic?", bool(v["vod_pic"]))
    print("\n== detailContent (ids=8165) ==")
    dc = s.detailContent(["8165"])
    print("list:", len(dc["list"]), "play_from:",
          dc["list"][0].get("vod_play_from"))
    print("\n== searchContent (wd=流浪地球) ==")
    sc = s.searchContent("流浪地球", False, "1")
    print("list:", len(sc["list"]), "total:", sc["total"])
    print("\n== playerContent (share ep) ==")
    pc = s.playerContent("dytt",
                         "https://vip.dytt-cinema.com/share/bf2fb7d1825a1df3ca308ad0bf48591e",
                         "")
    print(pc)
    print("\n== playerContent (direct m3u8 ep) ==")
    pc2 = s.playerContent("dyttm3u8",
                          "https://vip.dytt-cinema.com/20250215/2843_bf2fb7d1/index.m3u8",
                          "")
    print(pc2)
