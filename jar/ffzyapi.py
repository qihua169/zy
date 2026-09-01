# -*- coding: utf-8 -*-
"""
sp_ffzyapi_tvbox.py — 非凡资源 API（ffzyapi.com）TVBox / 猫影视 数据源
======================================================================
接口形态：MacCMS 提供者 JSON API（非 HTML 页面站），实测契约：
  - 列表/搜索:  {API}?ac=videolist&t={tid}&pg={n}      （完整字段，含 vod_pic）
               {API}?ac=videolist&wd={kw}&pg={n}        （搜索）
               {API}?ac=videolist&pg={n}                （全站最新）
  - 详情:      {API}?ac=detail&ids={vod_id}
               -> list[0].vod_play_from = "feifan$$$ffm3u8"
               -> list[0].vod_play_url  = "第01集$https://vip.ffzy-xxx.com/share/{hash}#第02集$..."
  - 播放:      https://vip.ffzy-xxx.com/share/{hash} 返回 HTML 播放页，内嵌
               const url = "/20221102/xxx/index.m3u8?sign=..."（相对路径）
               m3u8 完整地址 = share 链接域名 + url（master playlist，干净无广告）
  - 分类列表:  仅搜索响应携带 class 字段；此处按用户白名单硬编码（更稳）。

分类白名单（用户指定，仅保留 12 个）：
  动作片6 / 喜剧片7 / 爱情片8 / 科幻片9 / 恐怖片10 / 剧情片11 / 战争片12 /
  国产剧13 / 记录片20 / 大陆综艺25 / 国产动漫29 / 动画片(特殊)
  ⚠ "动画片"：站内无此分类名，动漫按地区拆分（29国产/30日韩/31欧美/32港台/33海外）。
   本实现将「动画片」合并 30+31+32+33 四个子分类（每页各取 5 条凑 20 条）。
   如需调整，改 ANIME_SUBS 即可（如改为 ("30",) 仅日韩动漫）。

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
SITE_NAME = "非凡资源"
API = "http://api.ffzyapi.com/api.php/provide/vod"
UA = ("Mozilla/5.0 (Linux; Android 12) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/125.0.0.0 Mobile Safari/537.36")

# 分类白名单（type_id, 显示名）。"anime" 为特殊合并分类，见 ANIME_SUBS
CATS = [
    ("6", "动作片"), ("7", "喜剧片"), ("8", "爱情片"), ("9", "科幻片"),
    ("10", "恐怖片"), ("11", "剧情片"), ("12", "战争片"), ("13", "国产剧"),
    ("20", "记录片"), ("25", "大陆综艺"), ("29", "国产动漫"),
    ("anime", "动画片"),
]
# 「动画片」= 日韩动漫30 + 欧美动漫31 + 港台动漫32 + 海外动漫33（站内无"动画片"分类）
ANIME_SUBS = (30, 31, 32, 33)
ANIME_PER = 5  # 每子分类每页取 5 条，4 个共 20 条

# share 播放页内 m3u8 相对路径：const url = "/path/index.m3u8?sign=..."
RE_M3U8 = re.compile(r'const\s+url\s*=\s*"([^"]+)"')
# 播放页里偶发的双引号变体兜底
RE_M3U8_2 = re.compile(r'url\s*[:=]\s*"([^"]*\.m3u8[^"]*)"', re.I)


def _clean_html(s):
    s = re.sub(r'<[^>]+>', '', s or "")
    return re.sub(r'\s+', ' ', s.replace("&nbsp;", " ").replace("\u3000", " ")).strip()


class FfzySpider(_TVBase):

    def getName(self):
        return SITE_NAME

    def init(self, extend=""):
        pass  # 让基类 __init__ 自然初始化

    # ── 网络辅助 ──
    def _headers(self):
        return {"User-Agent": UA, "Referer": "http://api.ffzyapi.com/",
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
        """调用提供者 API，返回 dict；失败返回 {}。"""
        try:
            txt = self._fetch_text(API + "?" + urlencode(params))
            return json.loads(txt or "{}")
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
            if tid == "anime":
                items, total = self._anime_page(page)
            else:
                data = self._api({"ac": "videolist", "t": tid, "pg": page})
                items, total = self._vods(data), data.get("total") or 0
            pc = max(1, (int(total) + 19) // 20) if total else 1
            return {"list": items, "page": page, "pagecount": pc,
                    "limit": 20, "total": int(total)}
        except Exception:
            return {"list": [], "page": page, "pagecount": 1,
                    "limit": 20, "total": 0}

    def _anime_page(self, pg):
        """「动画片」合并分类：30/31/32/33 各取 ANIME_PER 条凑一页。

        每个子分类独立分页（20/页）：全局第 pg 页时，子分类偏移
        base=(pg-1)*5，子页 = base//20+1，页内截取 base%20 起 5 条。
        """
        items, total = [], 0
        for tid in ANIME_SUBS:
            base = (pg - 1) * ANIME_PER
            sub_pg = base // 20 + 1
            off = base % 20
            data = self._api({"ac": "videolist", "t": tid, "pg": sub_pg})
            total += data.get("total") or 0
            items.extend(self._vods(data)[off:off + ANIME_PER])
        return items, total

    def detailContent(self, ids):
        vid = str(ids[0]) if isinstance(ids, (list, tuple)) and ids else str(ids or "")
        try:
            data = self._api({"ac": "detail", "ids": vid})
            lst = data.get("list") or []
            if not lst:
                return {"list": [{"vod_id": vid, "vod_name": vid,
                                  "vod_play_from": "ff", "vod_play_url": ""}]}
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
                "vod_play_from": v.get("vod_play_from", "") or "ff",
                "vod_play_url": v.get("vod_play_url", "") or "",
            }
            return {"list": [vod]}
        except Exception:
            return {"list": [{"vod_id": vid, "vod_name": vid,
                              "vod_play_from": "ff", "vod_play_url": ""}]}

    def searchContent(self, key, quick, pg="1"):
        page = int(pg) if str(pg).isdigit() else 1
        try:
            data = self._api({"ac": "videolist", "wd": key, "pg": page})
            items = self._vods(data)
            total = data.get("total") or 0
            pc = max(1, (int(total) + 19) // 20) if total else 1
            return {"list": items, "page": page, "pagecount": pc,
                    "limit": 20, "total": int(total)}
        except Exception:
            return {"list": [], "page": page, "pagecount": 1,
                    "limit": 20, "total": 0}

    def playerContent(self, flag, id, vipFlags):
        hd = json.dumps({"User-Agent": UA, "Referer": "https://vip.ffzy-play5.com/"})
        try:
            play_url = id if id.startswith("http") else ("http://" + id)
            html = self._fetch_text(play_url)
            m = RE_M3U8.search(html or "") or RE_M3U8_2.search(html or "")
            if not m:
                return {"parse": 1, "url": play_url, "header": hd}
            rel = m.group(1).strip()
            # 注意 rel 常带 ?sign= 查询串，须去掉后再判后缀
            if not rel.split("?")[0].lower().endswith((".m3u8", ".mp4", ".flv")):
                return {"parse": 1, "url": play_url, "header": hd}
            if rel.startswith("http"):
                url = rel
            else:
                ps = urlsplit(play_url)
                url = "%s://%s%s" % (ps.scheme, ps.netloc,
                                     rel if rel.startswith("/") else "/" + rel)
            # m3u8 走播放域名防盗链 Referer
            ps2 = urlsplit(url)
            hd = json.dumps({"User-Agent": UA,
                             "Referer": "%s://%s/" % (ps2.scheme, ps2.netloc)})
            return {"parse": 0, "url": url, "header": hd}
        except Exception:
            return {"parse": 1, "url": id, "header": hd}

    # ── stub ──
    def isVideoFormat(self, url):
        pass

    def manualVideoCheck(self):
        pass

    def localProxy(self, param):
        return [200, "video/MP2T", "", ""]


# 兼容按 module.Spider 类名加载的 TVBox 变体
Spider = FfzySpider


if __name__ == "__main__":
    s = FfzySpider()
    s.init()
    print("==> homeContent:", json.dumps(s.homeContent(False), ensure_ascii=False)[:500])
    print("==> category(国产剧13):", json.dumps(s.categoryContent("13", 1, False, {}), ensure_ascii=False)[:400])
    print("==> category(动画片anime):", json.dumps(s.categoryContent("anime", 1, False, {}), ensure_ascii=False)[:400])
    d = s.detailContent(["98592"])
    print("==> detail:", json.dumps({k: (v[:120] if isinstance(v, str) else v)
                                     for k, v in d["list"][0].items()}, ensure_ascii=False)[:800])
    print("==> search(喜羊羊):", json.dumps(s.searchContent("喜羊羊", False, "1"), ensure_ascii=False)[:300])
    if d.get("list") and d["list"][0].get("vod_play_url"):
        first_ep = d["list"][0]["vod_play_url"].split("#")[0].split("$")[-1]
        print("==> player:", json.dumps(s.playerContent("ff", first_ep, ""), ensure_ascii=False)[:400])
