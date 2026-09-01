# -*- coding: utf-8 -*-
"""
TVBox / 猫影视 Spider —— 360zy 资源站（MacCMS JSON API 提供者）
================================================================

站点性质：MacCMS「纯 JSON 提供者 API」（`/api.php/provide/vod`）。
  - 不解析 HTML，全部走 JSON 接口（`ac=videolist` / `ac=detail` / `ac=type` / `wd=` 搜索）。
  - `vod_play_url` 已是标准 TVBox 格式「集名$完整 m3u8 直链#...」，detailContent 直接透传；
    playerContent 直接返回直链（`parse:0`），无需抓播放页 / 无加密 / 无 sign。
  - 播放 CDN 域名（如 vod1.maowushi.com）与站不同，Referer 动态取自直链域名（实测无 Referer 也 200，
    带上仅作防盗链兜底，无害）。
  - API 仅支持 `t=`（分类/子分类）过滤，**不支持 year/area 筛选**（实测 total=0），故只暴露「类型」二级筛选。

部署规范（遵循技能 spider_tvbox_deploy 模板）：
  1. 继承 base.spider.Spider，网络统一走基类 self.fetch（TVBox 环境）。
  2. init 极简 pass，不绕过基类 __init__。
  3. playerContent 的 header 为 json.dumps(str)，非裸 dict。
  4. 所有接口 try/except 兜底返回合法结构，异常不外抛。
  5. 模块级别名 Spider = Zy360Spider，兼容 module.Spider 加载变体。
  6. PC 端无 base.spider 时，下方 _TVBase 桩用 urllib 提供 fetch，__main__ 可直接自检。

本地自检：  python sp_360zy_tvbox.py
离线校验：  python test_360zy.py   （基于 fixtures/ 桩，无需联网）
"""

import re
import json
from urllib.parse import urlencode, quote

try:
    from base.spider import Spider as _TVBase
except Exception:
    # ── 本地调试桩（PC 端无 base.spider）：urllib 实现 fetch ──
    class _TVBase(object):
        def fetch(self, url, headers=None, timeout=15, **kwargs):
            from urllib.request import Request, urlopen
            try:
                r = urlopen(Request(url, headers=headers or {}), timeout=timeout)
                raw = r.read()
            except Exception as e:
                # 返回空对象，调用方自行 json.loads 会抛异常并被 try 兜住
                class _E(object):
                    text = ""
                return _E()
            class _R(object):
                @property
                def text(self):
                    return raw.decode("utf-8", errors="ignore") if isinstance(raw, bytes) else raw
            return _R()
    # ── 桩结束 ──


# ════════════ 站点配置 ════════════
SITE_NAME = "360zy"
API = "https://360zy.com/api.php/provide/vod"   # 注意：无末尾斜杠，参数以 ? 拼接
UA = ("Mozilla/5.0 (Linux; Android 12) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/125.0.0.0 Mobile Safari/537.36")

# ⚠ 关键约束（实测）：本站影片只挂在「叶子子类」tid 下，父分类 tid（1/2/3…）与
# 多 tid（逗号/竖线）均返回 total=0；year/area 筛选也不支持。因此 TVBox 的 class
# 列表直接展开为全部叶子子类（每个都能返回真实数据），不做二级筛选，避免空分类。
#
# 父分类 -> 叶子子类（来自 ac=type 实测 type_pid 映射，硬编码白名单最稳）
_SUB_CATE = {
    "1":  [("动作片","6"),("喜剧片","7"),("爱情片","8"),("科幻片","9"),("恐怖片","10"),
           ("剧情片","11"),("战争片","12"),("惊悚片","20"),("家庭篇","21"),("古装片","22"),
           ("历史片","23"),("悬疑片","24"),("犯罪片","25"),("灾难片","26"),("纪录片","27"),
           ("短片","28"),("动画片","29"),("未分类","43"),("西部片","45")],
    "2":  [("国产剧","13"),("香港剧","14"),("韩国剧","15"),("欧美剧","16"),("台湾剧","30"),
           ("日本剧","31"),("海外剧","32"),("泰国剧","33")],
    "3":  [("大陆综艺","34"),("港台综艺","35"),("日韩综艺","36"),("欧美综艺","37")],
    "4":  [("国产动漫","38"),("欧美动漫","39"),("日韩动漫","40")],
    "5":  [],  # 伦理片无二级子分类，直接使用父 tid
    "17": [("NBA","18"),("足球","41"),("篮球","42")],
    "46": [("现代都市","47"),("脑洞悬疑","48"),("年代穿越","49"),("古装仙侠","50"),
           ("反转爽剧","51"),("女频恋爱","52"),("成长逆袭","53")],
}

# 父分类名称（用于无子类的父分类，如伦理片）
_PARENT_NAME = {"1":"电影","2":"连续剧","3":"综艺","4":"动漫","5":"伦理片","17":"体育","46":"爽文短剧"}

# 展开为 TVBox 可用 class 列表（叶子子类；伦理片无子类则保留父 tid=5 本身）
HOME_CLASSES = []
for _pid, _subs in _SUB_CATE.items():
    if _subs:
        for _name, _tid in _subs:
            HOME_CLASSES.append({"type_id": _tid, "type_name": _name})
    else:
        HOME_CLASSES.append({"type_id": _pid, "type_name": _PARENT_NAME.get(_pid, _pid)})


# ════════════ 工具函数 ════════════
def _clean_play_url(raw):
    """把 API 返回的 vod_play_url 清洗为标准 TVBox 格式。

    API 已是「集名$直链#集名$直链」，但可能带结尾 '#' 产生空段；
    逐源清洗，丢弃空段 / 空直链。
    """
    if not raw:
        return ""
    out_sources = []
    for src in raw.split("$$$"):
        eps = []
        for seg in src.split("#"):
            seg = seg.strip()
            if not seg or "$" not in seg:
                continue
            name, url = seg.split("$", 1)
            if not url.strip():
                continue
            eps.append("%s$%s" % (name.strip(), url.strip()))
        if eps:
            out_sources.append("#".join(eps))
    return "$$$".join(out_sources)


def _list_item(it):
    """从 API 列表项映射为 TVBox vod 卡片。"""
    return {
        "vod_id": str(it.get("vod_id", "")),
        "vod_name": it.get("vod_name", "") or "",
        "vod_pic": it.get("vod_pic", "") or "",
        "vod_remarks": it.get("vod_remarks", "") or "",
    }


def _detail_item(it):
    """从 API 详情项映射为完整 TVBox vod。"""
    vod = {
        "vod_id": str(it.get("vod_id", "")),
        "vod_name": it.get("vod_name", "") or "",
        "vod_pic": it.get("vod_pic", "") or "",
        "vod_remarks": it.get("vod_remarks", "") or "",
        "vod_year": str(it.get("vod_year", "") or ""),
        "vod_area": it.get("vod_area", "") or "",
        "vod_lang": it.get("vod_lang", "") or "",
        "vod_actor": it.get("vod_actor", "") or "",
        "vod_director": it.get("vod_director", "") or "",
        "vod_content": (it.get("vod_content", "") or "").strip(),
    }
    # 播放源：from / url 均为标准格式，直接透传（from 多源用 $$$ 连接）
    play_from = it.get("vod_play_from", "") or ""
    play_url = _clean_play_url(it.get("vod_play_url", "") or "")
    if play_from and play_url:
        vod["vod_play_from"] = "$$$".join([s for s in play_from.split("$$$") if s.strip()])
        vod["vod_play_url"] = play_url
    return vod


# ══════════════════════════════════════════════════
class Zy360Spider(_TVBase):

    def getName(self):
        return SITE_NAME

    def init(self, extend=""):
        # 极简 pass：让基类 __init__ 自然初始化（基类 fetch 依赖的 session 才就绪）
        pass

    # ── 网络封装 ──
    def _headers(self):
        return {"User-Agent": UA, "Referer": "https://360zy.com/"}

    def _api(self, params):
        """统一 JSON 请求。TVBox 走基类 self.fetch；本地桩走 urllib。"""
        url = API + "?" + urlencode(params)
        r = self.fetch(url, headers=self._headers(), timeout=15)
        text = getattr(r, "text", r)
        if isinstance(text, bytes):
            text = text.decode("utf-8", errors="ignore")
        return json.loads(text or "{}")

    def _header_json(self, referer="https://360zy.com/"):
        return json.dumps({"User-Agent": UA, "Referer": referer})

    # ── TVBox 接口 ──
    def homeContent(self, filter):
        # class 已是叶子子类，每个都能返回真实数据；站点不支持 year/area，且父分类/多 tid
        # 过滤均返回 0，故不提供二级筛选（filters 留空，避免筛选后空结果）。
        return {"class": HOME_CLASSES, "filters": {}}

    def homeVideoContent(self):
        try:
            d = self._api({"ac": "videolist", "pg": 1})
            items = [_list_item(x) for x in (d.get("list") or [])]
            return {"list": items}
        except Exception:
            return {"list": []}

    def categoryContent(self, tid, pg, filter, extend):
        page = int(pg) if str(pg).isdigit() else 1
        try:
            # tid 已是叶子子类 id，直接用于过滤
            final_tid = str(tid)
            d = self._api({"ac": "videolist", "t": final_tid, "pg": page})
            items = [_list_item(x) for x in (d.get("list") or [])]
            return {
                "list": items,
                "page": page,
                "pagecount": int(d.get("pagecount", 1) or 1),
                "limit": int(d.get("limit", 20) or 20),
                "total": int(d.get("total", 0) or 0),
            }
        except Exception:
            return {"list": [], "page": page, "pagecount": 1, "limit": 20, "total": 0}

    def detailContent(self, ids):
        vid = str(ids[0]) if ids else ""
        try:
            d = self._api({"ac": "detail", "ids": vid})
            lst = d.get("list") or []
            if not lst:
                return {"list": [{"vod_id": vid, "vod_name": "暂无数据"}]}
            return {"list": [_detail_item(lst[0])]}
        except Exception as e:
            return {"list": [{"vod_id": vid, "vod_name": "解析异常",
                              "vod_content": str(e)[:200]}]}

    def searchContent(self, key, quick, pg="1"):
        page = int(pg) if str(pg).isdigit() else 1
        try:
            d = self._api({"ac": "videolist", "wd": key, "pg": page})
            items = [_list_item(x) for x in (d.get("list") or [])]
            return {
                "list": items,
                "page": page,
                "pagecount": int(d.get("pagecount", 1) or 1),
                "limit": int(d.get("limit", 20) or 20),
                "total": int(d.get("total", 0) or 0),
            }
        except Exception:
            return {"list": [], "page": page, "pagecount": 1, "limit": 20, "total": 0}

    def playerContent(self, flag, id, vipFlags):
        hd = self._header_json()
        try:
            # id 已是完整 m3u8 直链（来自 vod_play_url）
            play_url = id if id.startswith("http") else (API + id)
            # 后缀判定必须先去 query（避免 ?sign= 干扰 endswith）
            suffix = play_url.split("?")[0].lower()
            if suffix.endswith((".m3u8", ".mp4", ".flv", ".ts")):
                # Referer 动态取自直链域名（兜底防盗链，无害）
                referer = play_url.split("/")[0] + "//" + play_url.split("/")[2] + "/"
                hd = self._header_json(referer)
                return {"parse": 0, "playUrl": "", "url": play_url, "header": hd}
            # 非直链形态兜底交给框架二次解析
            return {"parse": 1, "playUrl": "", "url": play_url, "header": hd}
        except Exception:
            return {"parse": 1, "playUrl": "", "url": id, "header": hd}

    def isVideoFormat(self, url):
        return any(url.lower().split("?")[0].endswith(s)
                   for s in (".m3u8", ".mp4", ".flv", ".ts"))

    def manualVideoCheck(self):
        pass

    def localProxy(self, param):
        # 直链站点无需代理；保留 stub 不触发
        return [200, "video/MP2T", "", ""]


# 兼容按 module.Spider 类名加载的 TVBox 变体
Spider = Zy360Spider


if __name__ == "__main__":
    s = Zy360Spider()
    s.init()
    print("== homeContent(filter=True) ==")
    h = s.homeContent(True)
    print("class count:", len(h["class"]), "| filters keys:", list(h["filters"].keys()))
    print("== homeVideoContent ==")
    hv = s.homeVideoContent()
    print("home list len:", len(hv["list"]), "| sample:", hv["list"][0] if hv["list"] else None)
    print("== categoryContent(tid=13 国产剧, pg=1) ==")
    c = s.categoryContent("13", "1", False, {})
    print("cat list len:", len(c["list"]), "pagecount:", c["pagecount"], "total:", c["total"])
    print("== detailContent(ids=['74340']) ==")
    dt = s.detailContent(["74340"])
    v = dt["list"][0]
    print("name:", v.get("vod_name"), "| from:", v.get("vod_play_from"),
          "| url head:", (v.get("vod_play_url", "") or "")[:80])
    print("== searchContent('庆余年') ==")
    sr = s.searchContent("庆余年", False, "1")
    print("search list len:", len(sr["list"]), "total:", sr["total"],
          "| sample:", sr["list"][0] if sr["list"] else None)
    print("== playerContent(m3u8) ==")
    sample_url = "https://vod1.maowushi.com/20250628/h7WxvnAk/index.m3u8"
    pc = s.playerContent("360zy", sample_url, "")
    print(pc)
