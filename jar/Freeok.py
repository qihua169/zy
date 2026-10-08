# -*- coding: utf-8 -*-
"""
freeokk.lol - OK影视蜘蛛插件（单文件 Python）

站点特性（2026-09-17 抓包确认）：
1. 苹果CMS v10 + OK 播放模板，整站无图片验证码、无 Cloudflare 滑块，请求稳定。
2. 开放采集 API：/api.php/provide/vod/
   - ac=videolist&t={分类}&wd={关键词}&pg={页码}&year={年份}  列表/搜索（返回含图片与播放）
   - ac=detail&ids={vod_id}                                   详情（vod_play_from/vod_play_url 直链）
   注意：api 的 area/class/lang 参数被源站忽略，地区/剧情/语言筛选必须走前端 /show/ 十二段 URL。
3. 筛选页 /show/ 十二段格式（与壳子一致）：
   {tid}-{地区}-{排序}-{剧情}-{语言}-{字母}-{空}-{空}-{页码}-{空}-{空}-{年份}.html
   每类均提供 剧情/地区/语言/年份/字母 五组筛选，全部组合有数据有图、可翻页（40 条/页）。
4. 播放线路：API 详情直接返回 m3u8/mp4 直链，线路显示名与 /static/js/playerconfig.js 的
   player_list 逐字一致（OK自营Q~M/OK超清/OK极速/OK无广/OK高清/OK高速等），"线路和网址一致"；
   1080zyk 等高码率直链实测 master 1920x1080/2592x1080（OK极速），rym3u8 等为 720P 级（OK高速），
   不虚标"4K"——qq 是腾讯网页源（OK自营Q）。不内置任何第三方解析接口：
   直链线路 parse=0 直接播放；网页线路（qq/爱奇艺/优酷/B站/芒果等）parse=1 交壳子内建播放器处理。
"""
import re
import json
import time
import urllib.parse
import requests
from urllib.parse import quote
from base.spider import Spider

# 站点分类（1电影/2剧集/3综艺/4动漫——与前端导航顺序一致）
CATEGORY_NAMES = {"1": "电影", "2": "剧集", "3": "综艺", "4": "动漫"}

# 线路名映射：API 原始名 -> 源站真实显示名（与站点 /static/js/playerconfig.js 的 player_list 逐字一致）
# 实测各直链分辨率（master 首段 RES）：
#   1080zyk -> cdn.vvvip-plays33.cc/cdn.yzzyvip-29.com：1920x1080 / 2592x1080（OK极速）
#   dyttm3u8 -> play.phimgood.com/vip.dytt-see.com：1920x800；ffm3u8 -> vip.ffzy-play10.com：1920x800
#   rym3u8 -> cdn.ryplay11.com/vip.dytt-cinema.com/play-cdn15.com：1080x608；bfzym3u8 -> fengbao12.com：ts 分片直出
# 线路名跟随网址真实清晰度，不虚标"4K"：qq 实为腾讯网页源（OK自营Q），需解析；1080zyk 才是高码率直链。
SOURCE_MAP = {
    # ---- OK 自营直链（线路名与播放域名同源）----
    "bfzym3u8": "OK超清",   # fengbao12.com（ts 分片列表，直链可播）
    "1080zyk":  "OK极速",   # cdn.vvvip-plays33.cc / cdn.yzzyvip-29.com / player.yzzyvip-35.com：master 1920x1080 / 2592x1080
    "mtv":      "OK极速",   # 源站与 1080zyk 同显"OK极速"（重名线路，按 sid 位置区分）
    "dyttm3u8": "OK无广",   # play.phimgood.com / vip.dytt-see.com / vip.dytt-cinema.com：1920x800 / 1080x608
    "ffm3u8":   "OK高清",   # super.ffzy-online6.com / vip.ffzy-play10.com / vip.ffzy-plays.com：1920x800 / 1920x808
    "rym3u8":   "OK高速",   # cdn.ryplay11.com：1080x608（720P 级）
    # ---- 平台网页线路（返回网页，需走解析）----
    "qq":       "OK自营Q",  # v.qq.com（腾讯网页源；源站真实显示名是 OK自营Q，不是"4K"）
    "qiyi":     "OK自营A",  # www.iqiyi.com
    "youku":    "OK自营K",  # v.youku.com
    "bilibili": "OK自营B",  # bilibili.com
    "mgtv":     "OK自营M",  # mgtv.com
    "JPZY":     "OK自营",   # 源站自营解析（与 NBY 同显"OK自营"）
    "NBY":      "OK自营",   # 源站自营解析
    # ---- 源站 player_list 其余资源线路（未实测出现，忠实保留源站名）----
    "1080zy":   "1080资源",
    "dbm3u8":   "豆瓣在线",
    "tpm3u8":   "淘片播放器",
    "pptv":     "PPTV视频",
    "letv":     "乐视视频",
    "sohu":     "搜狐视频",
    "iqym3u8":  "Y[弹幕]",
    "ruyi":     "如意资源2",
    "yym3u8":   "鸭鸭资源",
    "funshion": "风行视频",
    "wasu":     "华数TV",
    "m1905":    "1905电影网",
    "migu":     "咪咕视频",
}

# 反向映射：显示名 -> API 原始名（仅作 sid 越界时的兜底；
# 源站存在重名线路（OK极速/OK自营），显示名反查不可靠，播放定位以 sid 为准）
SOURCE_MAP_R = {v: k for k, v in SOURCE_MAP.items()}

# 各分类筛选选项（2026-09-17 从 /show/ 页面逐一抓取，保证每个选项都有数据）
FILTERS = {
    "1": [  # 电影
        {"key": "class", "name": "剧情", "value": [
            {"n": "全部", "v": ""}, {"n": "喜剧", "v": "喜剧"}, {"n": "爱情", "v": "爱情"},
            {"n": "恐怖", "v": "恐怖"}, {"n": "动作", "v": "动作"}, {"n": "科幻", "v": "科幻"},
            {"n": "剧情", "v": "剧情"}, {"n": "战争", "v": "战争"}, {"n": "警匪", "v": "警匪"},
            {"n": "犯罪", "v": "犯罪"}, {"n": "动画", "v": "动画"}, {"n": "奇幻", "v": "奇幻"},
            {"n": "武侠", "v": "武侠"}, {"n": "冒险", "v": "冒险"},
            {"n": "悬疑", "v": "悬疑"}, {"n": "惊悚", "v": "惊悚"},
            {"n": "青春", "v": "青春"}, {"n": "文艺", "v": "文艺"},
            {"n": "古装", "v": "古装"}, {"n": "历史", "v": "历史"}, {"n": "运动", "v": "运动"},
            {"n": "儿童", "v": "儿童"},
        ]},
        {"key": "area", "name": "地区", "value": [
            {"n": "全部", "v": ""}, {"n": "大陆", "v": "大陆"}, {"n": "香港", "v": "香港"},
            {"n": "台湾", "v": "台湾"}, {"n": "美国", "v": "美国"}, {"n": "法国", "v": "法国"},
            {"n": "英国", "v": "英国"}, {"n": "日本", "v": "日本"}, {"n": "韩国", "v": "韩国"},
            {"n": "德国", "v": "德国"}, {"n": "泰国", "v": "泰国"}, {"n": "印度", "v": "印度"},
            {"n": "意大利", "v": "意大利"}, {"n": "西班牙", "v": "西班牙"}, {"n": "加拿大", "v": "加拿大"},
            {"n": "其他", "v": "其他"},
        ]},
        {"key": "lang", "name": "语言", "value": [
            {"n": "全部", "v": ""}, {"n": "国语", "v": "国语"}, {"n": "英语", "v": "英语"},
            {"n": "粤语", "v": "粤语"}, {"n": "闽南语", "v": "闽南语"}, {"n": "韩语", "v": "韩语"},
            {"n": "日语", "v": "日语"}, {"n": "法语", "v": "法语"}, {"n": "德语", "v": "德语"},
            {"n": "其它", "v": "其它"},
        ]},
        {"key": "year", "name": "年份", "value": [
            {"n": "全部", "v": ""}, {"n": "2026", "v": "2026"}, {"n": "2025", "v": "2025"},
            {"n": "2024", "v": "2024"}, {"n": "2023", "v": "2023"}, {"n": "2022", "v": "2022"},
            {"n": "2021", "v": "2021"}, {"n": "2020", "v": "2020"}, {"n": "2019", "v": "2019"},
            {"n": "2018", "v": "2018"}, {"n": "2017", "v": "2017"}, {"n": "2016", "v": "2016"},
            {"n": "2015", "v": "2015"}, {"n": "2014", "v": "2014"},
        ]},
        {"key": "letter", "name": "字母", "value": [
            {"n": "全部", "v": ""}, {"n": "A", "v": "A"}, {"n": "B", "v": "B"}, {"n": "C", "v": "C"},
            {"n": "D", "v": "D"}, {"n": "E", "v": "E"}, {"n": "F", "v": "F"}, {"n": "G", "v": "G"},
            {"n": "H", "v": "H"}, {"n": "I", "v": "I"}, {"n": "J", "v": "J"}, {"n": "K", "v": "K"},
            {"n": "L", "v": "L"}, {"n": "M", "v": "M"}, {"n": "N", "v": "N"}, {"n": "O", "v": "O"},
            {"n": "P", "v": "P"}, {"n": "Q", "v": "Q"}, {"n": "R", "v": "R"}, {"n": "S", "v": "S"},
            {"n": "T", "v": "T"}, {"n": "U", "v": "U"}, {"n": "V", "v": "V"}, {"n": "W", "v": "W"},
            {"n": "X", "v": "X"}, {"n": "Y", "v": "Y"}, {"n": "Z", "v": "Z"},
        ]},
    ],
    "2": [  # 剧集
        {"key": "class", "name": "剧情", "value": [
            {"n": "全部", "v": ""}, {"n": "古装", "v": "古装"}, {"n": "战争", "v": "战争"},
            {"n": "喜剧", "v": "喜剧"}, {"n": "家庭", "v": "家庭"},
            {"n": "犯罪", "v": "犯罪"}, {"n": "动作", "v": "动作"}, {"n": "奇幻", "v": "奇幻"},
            {"n": "剧情", "v": "剧情"}, {"n": "历史", "v": "历史"}, {"n": "经典", "v": "经典"},
            {"n": "商战", "v": "商战"},
            {"n": "网剧", "v": "网剧"}, {"n": "其他", "v": "其他"},
        ]},
        {"key": "area", "name": "地区", "value": [
            {"n": "全部", "v": ""}, {"n": "大陆", "v": "大陆"}, {"n": "韩国", "v": "韩国"},
            {"n": "香港", "v": "香港"}, {"n": "台湾", "v": "台湾"}, {"n": "日本", "v": "日本"},
            {"n": "美国", "v": "美国"}, {"n": "泰国", "v": "泰国"}, {"n": "英国", "v": "英国"},
            {"n": "新加坡", "v": "新加坡"},
        ]},
        {"key": "lang", "name": "语言", "value": [
            {"n": "全部", "v": ""}, {"n": "国语", "v": "国语"}, {"n": "英语", "v": "英语"},
            {"n": "粤语", "v": "粤语"}, {"n": "闽南语", "v": "闽南语"}, {"n": "韩语", "v": "韩语"},
            {"n": "日语", "v": "日语"}, {"n": "其它", "v": "其它"},
        ]},
        {"key": "year", "name": "年份", "value": [
            {"n": "全部", "v": ""}, {"n": "2026", "v": "2026"}, {"n": "2025", "v": "2025"},
            {"n": "2024", "v": "2024"}, {"n": "2023", "v": "2023"}, {"n": "2022", "v": "2022"},
            {"n": "2021", "v": "2021"}, {"n": "2020", "v": "2020"}, {"n": "2019", "v": "2019"},
            {"n": "2018", "v": "2018"}, {"n": "2017", "v": "2017"}, {"n": "2016", "v": "2016"},
            {"n": "2015", "v": "2015"}, {"n": "2014", "v": "2014"},
        ]},
        {"key": "letter", "name": "字母", "value": [
            {"n": "全部", "v": ""}, {"n": "A", "v": "A"}, {"n": "B", "v": "B"}, {"n": "C", "v": "C"},
            {"n": "D", "v": "D"}, {"n": "E", "v": "E"}, {"n": "F", "v": "F"}, {"n": "G", "v": "G"},
            {"n": "H", "v": "H"}, {"n": "I", "v": "I"}, {"n": "J", "v": "J"}, {"n": "K", "v": "K"},
            {"n": "L", "v": "L"}, {"n": "M", "v": "M"}, {"n": "N", "v": "N"}, {"n": "O", "v": "O"},
            {"n": "P", "v": "P"}, {"n": "Q", "v": "Q"}, {"n": "R", "v": "R"}, {"n": "S", "v": "S"},
            {"n": "T", "v": "T"}, {"n": "U", "v": "U"}, {"n": "V", "v": "V"}, {"n": "W", "v": "W"},
            {"n": "X", "v": "X"}, {"n": "Y", "v": "Y"}, {"n": "Z", "v": "Z"},
        ]},
    ],
    "3": [  # 综艺
        {"key": "class", "name": "剧情", "value": [
            {"n": "全部", "v": ""}, {"n": "选秀", "v": "选秀"}, {"n": "情感", "v": "情感"},
            {"n": "访谈", "v": "访谈"}, {"n": "旅游", "v": "旅游"},
            {"n": "音乐", "v": "音乐"}, {"n": "美食", "v": "美食"}, {"n": "纪实", "v": "纪实"},
            {"n": "曲艺", "v": "曲艺"}, {"n": "生活", "v": "生活"}, {"n": "游戏互动", "v": "游戏互动"},
            {"n": "财经", "v": "财经"},
        ]},
        {"key": "area", "name": "地区", "value": [
            {"n": "全部", "v": ""}, {"n": "内地", "v": "内地"}, {"n": "港台", "v": "港台"},
            {"n": "日韩", "v": "日韩"},
        ]},
        {"key": "lang", "name": "语言", "value": [
            {"n": "全部", "v": ""}, {"n": "国语", "v": "国语"}, {"n": "英语", "v": "英语"},
            {"n": "粤语", "v": "粤语"}, {"n": "韩语", "v": "韩语"},
            {"n": "日语", "v": "日语"}, {"n": "其它", "v": "其它"},
        ]},
        {"key": "year", "name": "年份", "value": [
            {"n": "全部", "v": ""}, {"n": "2026", "v": "2026"}, {"n": "2025", "v": "2025"},
            {"n": "2024", "v": "2024"}, {"n": "2023", "v": "2023"}, {"n": "2022", "v": "2022"},
            {"n": "2021", "v": "2021"}, {"n": "2020", "v": "2020"}, {"n": "2019", "v": "2019"},
            {"n": "2018", "v": "2018"}, {"n": "2017", "v": "2017"}, {"n": "2016", "v": "2016"},
            {"n": "2015", "v": "2015"}, {"n": "2014", "v": "2014"},
        ]},
        {"key": "letter", "name": "字母", "value": [
            {"n": "全部", "v": ""}, {"n": "A", "v": "A"}, {"n": "B", "v": "B"}, {"n": "C", "v": "C"},
            {"n": "D", "v": "D"}, {"n": "E", "v": "E"}, {"n": "F", "v": "F"}, {"n": "G", "v": "G"},
            {"n": "H", "v": "H"}, {"n": "I", "v": "I"}, {"n": "J", "v": "J"}, {"n": "K", "v": "K"},
            {"n": "L", "v": "L"}, {"n": "M", "v": "M"}, {"n": "N", "v": "N"}, {"n": "O", "v": "O"},
            {"n": "P", "v": "P"}, {"n": "Q", "v": "Q"}, {"n": "R", "v": "R"}, {"n": "S", "v": "S"},
            {"n": "T", "v": "T"}, {"n": "U", "v": "U"}, {"n": "V", "v": "V"}, {"n": "W", "v": "W"},
            {"n": "X", "v": "X"}, {"n": "Y", "v": "Y"}, {"n": "Z", "v": "Z"},
        ]},
    ],
    "4": [  # 动漫
        {"key": "class", "name": "剧情", "value": [
            {"n": "全部", "v": ""}, {"n": "情感", "v": "情感"}, {"n": "科幻", "v": "科幻"},
            {"n": "热血", "v": "热血"}, {"n": "推理", "v": "推理"}, {"n": "搞笑", "v": "搞笑"},
            {"n": "冒险", "v": "冒险"}, {"n": "校园", "v": "校园"},
            {"n": "动作", "v": "动作"}, {"n": "机战", "v": "机战"}, {"n": "运动", "v": "运动"},
            {"n": "战争", "v": "战争"}, {"n": "少女", "v": "少女"},
            {"n": "社会", "v": "社会"}, {"n": "原创", "v": "原创"}, {"n": "亲子", "v": "亲子"},
            {"n": "益智", "v": "益智"}, {"n": "励志", "v": "励志"}, {"n": "其他", "v": "其他"},
        ]},
        {"key": "area", "name": "地区", "value": [
            {"n": "全部", "v": ""}, {"n": "国产", "v": "国产"}, {"n": "日本", "v": "日本"},
            {"n": "欧美", "v": "欧美"},
        ]},
        {"key": "lang", "name": "语言", "value": [
            {"n": "全部", "v": ""}, {"n": "国语", "v": "国语"}, {"n": "英语", "v": "英语"},
            {"n": "粤语", "v": "粤语"}, {"n": "闽南语", "v": "闽南语"}, {"n": "韩语", "v": "韩语"},
            {"n": "日语", "v": "日语"}, {"n": "其它", "v": "其它"},
        ]},
        {"key": "year", "name": "年份", "value": [
            {"n": "全部", "v": ""}, {"n": "2026", "v": "2026"}, {"n": "2025", "v": "2025"},
            {"n": "2024", "v": "2024"}, {"n": "2023", "v": "2023"}, {"n": "2022", "v": "2022"},
            {"n": "2021", "v": "2021"}, {"n": "2020", "v": "2020"}, {"n": "2019", "v": "2019"},
            {"n": "2018", "v": "2018"}, {"n": "2017", "v": "2017"}, {"n": "2016", "v": "2016"},
            {"n": "2015", "v": "2015"}, {"n": "2014", "v": "2014"},
        ]},
        {"key": "letter", "name": "字母", "value": [
            {"n": "全部", "v": ""}, {"n": "A", "v": "A"}, {"n": "B", "v": "B"}, {"n": "C", "v": "C"},
            {"n": "D", "v": "D"}, {"n": "E", "v": "E"}, {"n": "F", "v": "F"}, {"n": "G", "v": "G"},
            {"n": "H", "v": "H"}, {"n": "I", "v": "I"}, {"n": "J", "v": "J"}, {"n": "K", "v": "K"},
            {"n": "L", "v": "L"}, {"n": "M", "v": "M"}, {"n": "N", "v": "N"}, {"n": "O", "v": "O"},
            {"n": "P", "v": "P"}, {"n": "Q", "v": "Q"}, {"n": "R", "v": "R"}, {"n": "S", "v": "S"},
            {"n": "T", "v": "T"}, {"n": "U", "v": "U"}, {"n": "V", "v": "V"}, {"n": "W", "v": "W"},
            {"n": "X", "v": "X"}, {"n": "Y", "v": "Y"}, {"n": "Z", "v": "Z"},
        ]},
    ],
}


class Spider(Spider):
    # ==================== 基础配置 ====================
    name = "freeokk"
    base_url = "https://www.freeokk.lol"
    site_url = "https://www.freeokk.lol"
    api_url = "https://www.freeokk.lol/api.php/provide/vod/"

    # 聚合搜索配置：支持全局搜索、快速搜索、筛选、换源聚合
    searchable = 1
    quickSearch = 1
    filterable = 1
    changeable = 1

    # 详情/播放缓存（壳子可能多次实例化 Spider，用类级缓存）
    _API_DETAIL_CACHE = {}
    _API_DETAIL_TTL = 600          # 秒，10 分钟
    _SEARCH_CACHE = {}
    _SEARCH_CACHE_TTL = 60

    # 请求节流：源站对连发请求有限流，两个请求之间至少间隔该秒数
    _MIN_REQUEST_GAP = 0.5
    _LAST_REQUEST_TS = 0.0

    # ==================== 请求头 ====================
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8",
        "Accept-Language": "zh-CN,zh;q=0.9",
        "Referer": "https://www.freeokk.lol/",
        "Connection": "keep-alive",
    }

    def __init__(self):
        super().__init__()
        self._session = requests.Session()
        self._session.headers.update(self.headers)
        # 复用类级详情缓存
        self._detail_cache = self._API_DETAIL_CACHE
        self._detail_ts = {}
        # 预编译正则
        self._re_detail_title = re.compile(r'<h1>([^<]*)</h1>')
        self._re_name_garbage = re.compile(
            r'[\s\-_]*(?:HD|TC|TS|抢先版|枪版|DVD|BD|1080P|720P|4K|2K|高清|超清|蓝光|国语|粤语|中字|中英双字|完整版|全集|未删减版|(?:第[0-9一二三四五六七八九十]+[集季期]))\s*$',
            re.I
        )

    # ==================== 工具方法 ====================
    def _log(self, msg):
        print(f"[{self.name}] {msg}")

    def _clean_vod_name(self, name):
        if not name:
            return name
        prev = name
        while True:
            cleaned = self._re_name_garbage.sub('', prev).strip()
            if cleaned == prev:
                break
            prev = cleaned
        return prev

    def _clean_vod_pic(self, pic):
        """清洗海报：过滤加载占位图、AVIF 转 WEBP、补全协议头与相对路径"""
        if not pic or 'load.gif' in pic:
            return ''
        if pic.startswith('//'):
            pic = 'https:' + pic
        # 搜索页图片可能是相对路径 /img.php?url=...，补全为站点绝对地址
        if pic.startswith('/'):
            pic = self.base_url + pic
        pic = re.sub(r'\.avif', '.webp', pic, flags=re.I)
        return pic

    def _clean_html(self, text):
        if not text:
            return ""
        text = re.sub(r'<[^>]+>', '', text)
        text = re.sub(r'\s+', ' ', text).strip()
        return text

    # ==================== 请求封装 ====================
    def fetch(self, url, headers=None, timeout=15):
        return self._session.get(url, headers=headers or {}, timeout=timeout)

    def _throttle(self):
        """类级请求节流：距离上次请求不足最小间隔时等待"""
        gap = time.time() - self._LAST_REQUEST_TS
        if gap < self._MIN_REQUEST_GAP:
            time.sleep(self._MIN_REQUEST_GAP - gap)
        type(self)._LAST_REQUEST_TS = time.time()

    def _is_blocked_page(self, text):
        """识别源站限流/风控拦截页（<title>系统提示...）"""
        if not text:
            return False
        return "系统提示" in text[:2000] or "访问过于频繁" in text[:2000] or "请稍后再试" in text[:2000]

    def _get(self, url, max_retry=3, timeout=12):
        """GET 请求封装：节流 + 识别限流页退避重试 + 基本异常处理"""
        h = self.headers.copy()
        for attempt in range(max_retry):
            try:
                self._throttle()
                resp = self.fetch(url, headers=h, timeout=timeout)
                if resp.status_code == 200:
                    text = resp.text
                    if self._is_blocked_page(text):
                        # 限流页：指数退避后重试
                        wait = 1.5 * (attempt + 1)
                        self._log(f"触发限流页，{wait}s 后重试(第{attempt+1}次): {url}")
                        if attempt < max_retry - 1:
                            time.sleep(wait)
                            continue
                        return ""
                    return text
                self._log(f"HTTP {resp.status_code}: {url}")
            except Exception as e:
                self._log(f"请求失败(第{attempt+1}次): {url}, {e}")
            if attempt < max_retry - 1:
                time.sleep(0.6 * (attempt + 1))
        return ""

    def _get_json(self, url, max_retry=2, timeout=12):
        """GET JSON 接口封装"""
        for attempt in range(max_retry):
            try:
                self._throttle()
                resp = self._session.get(url, headers={
                    "User-Agent": self.headers["User-Agent"],
                    "Accept": "application/json, text/plain, */*",
                    "Referer": self.site_url + "/",
                }, timeout=timeout)
                if resp.status_code == 200 and resp.text.strip():
                    return json.loads(resp.text)
            except Exception as e:
                self._log(f"JSON请求失败(第{attempt+1}次): {url}, {e}")
            if attempt < max_retry - 1:
                time.sleep(0.4 * (attempt + 1))
        return None

    # ==================== 解析方法 ====================
    def _extract_img_src(self, img_tag):
        if not img_tag:
            return ''
        m = re.search(r'data-original="([^"]+)"', img_tag)
        if m:
            return m.group(1)
        m = re.search(r'src="([^"]+)"', img_tag)
        return m.group(1) if m else ''

    def _parse_video_list(self, html):
        """通用列表解析（首页/分类/筛选页）——匹配 freeokk 的 module-poster-item 卡片"""
        videos = []
        if not html:
            return videos
        pattern = (
            r'<a[^>]*href="/detail/(\d+)\.html"[^>]*class="[^"]*module-poster-item[^"]*"[^>]*>'
            r'.*?<div[^>]*class="[^"]*module-item-note[^"]*"[^>]*>([^<]*)</div>'
            r'.*?(<img[^>]*>)'
            r'.*?<div[^>]*class="[^"]*module-poster-item-title[^"]*"[^>]*>([^<]*)</div>'
        )
        for m in re.finditer(pattern, html, re.DOTALL):
            vod_id = m.group(1).replace(".html", "")
            vod_note = m.group(2).strip()
            vod_pic = self._clean_vod_pic(self._extract_img_src(m.group(3)))
            vod_name = self._clean_vod_name(m.group(4).strip())
            videos.append({
                "vod_id": vod_id,
                "vod_name": vod_name,
                "vod_pic": vod_pic,
                "vod_remarks": vod_note,
            })
        return self._dedup_videos(videos)

    def _parse_search_list(self, html):
        """搜索页专用解析（module-card-item 卡片，div 深度匹配防嵌套错位）"""
        videos = []
        if not html:
            return videos
        for m in re.finditer(r'<div[^>]*class="(?:[^"]*\s)?module-card-item(?:\s[^"]*)?"[^>]*>', html):
            start = m.start()
            depth = 0
            i = start
            while i < len(html):
                if html[i:i + 5] == '<div ':
                    depth += 1
                    i += 5
                elif html[i:i + 6] == '</div>':
                    depth -= 1
                    i += 6
                    if depth == 0:
                        break
                else:
                    i += 1
            block = html[start:i]

            link = re.search(r'<a[^>]*href="/detail/(\d+)\.html"[^>]*class="[^"]*module-card-item-poster[^"]*"', block)
            if not link:
                continue
            vod_id = link.group(1)

            title = re.search(r'<div[^>]*class="[^"]*module-card-item-title[^"]*"[^>]*>.*?<strong>([^<]*)</strong>', block, re.DOTALL)
            vod_name = self._clean_vod_name(title.group(1).strip()) if title else "未知"

            pic_tag = re.search(r'<img[^>]*>', block)
            vod_pic = self._clean_vod_pic(self._extract_img_src(pic_tag.group(0))) if pic_tag else ""

            note = re.search(r'<div[^>]*class="[^"]*module-item-note[^"]*"[^>]*>([^<]*)</div>', block)
            vod_remarks = note.group(1).strip() if note else ""

            video = {
                "vod_id": vod_id,
                "vod_name": vod_name,
                "vod_pic": vod_pic,
                "vod_remarks": vod_remarks,
            }
            # 补充年份/地区/类型，利于聚合搜索相似度匹配
            info_text = re.sub(r'<[^>]+>', ' ', block)
            year = re.search(r'(\d{4})\s*[\/]?\s*', info_text)
            if year:
                video["vod_year"] = year.group(1)
            area = re.search(r'\/\s*([^\s\/]{2,})\s*\/', info_text)
            if area:
                video["vod_area"] = area.group(1).strip()
            videos.append(video)
        return self._dedup_videos(videos)

    def _dedup_videos(self, videos):
        seen = set()
        unique = []
        for v in videos:
            vid = v.get("vod_id", "")
            if vid and vid not in seen:
                seen.add(vid)
                unique.append(v)
        return unique

    # ==================== API 详情（播放直链来源） ====================
    def _api_detail(self, vod_id):
        """调用采集 API 获取详情，返回 dict；带类级缓存"""
        now = time.time()
        cached = self._detail_cache.get(str(vod_id))
        if cached and now - self._detail_ts.get(str(vod_id), 0) < self._API_DETAIL_TTL:
            return cached
        url = f"{self.api_url}?ac=detail&ids={vod_id}"
        data = self._get_json(url)
        if data and data.get("list"):
            v = data["list"][0]
            self._detail_cache[str(vod_id)] = v
            self._detail_ts[str(vod_id)] = now
            return v
        return None

    # ==================== TVBox 五大核心方法 ====================
    def init(self, extend=''):
        self._log("初始化完成")

    def homeContent(self, filter=False):
        result = {
            "class": [
                {"type_id": tid, "type_name": name}
                for tid, name in CATEGORY_NAMES.items()
            ]
        }
        if filter:
            result["filters"] = FILTERS
            result["filter"] = FILTERS
        return result

    def homeVideoContent(self):
        """首页热门推荐（首页第一个模块区块）"""
        try:
            html = self._get(self.base_url)
            if not html:
                return {"list": []}
            videos = self._parse_video_list(html)
            return {"list": videos[:24]}
        except Exception as e:
            self._log(f"homeVideoContent异常: {e}")
            return {"list": []}

    def _quote_filter_value(self, v):
        if not v:
            return ""
        try:
            return quote(urllib.parse.unquote(str(v)))
        except Exception:
            return quote(str(v))

    def _build_show_url(self, tid, pg, flt):
        """构造分类筛选 URL：12 段格式 = {tid}-{地区}-{排序}-{剧情}-{语言}-{字母}-{}-{}-{页码}-{}-{}-{年份}"""
        area = self._quote_filter_value(flt.get("area", ""))
        sort = self._quote_filter_value(flt.get("sort", ""))      # time/hits/score，可空
        class_ = self._quote_filter_value(flt.get("class", ""))
        lang = self._quote_filter_value(flt.get("lang", ""))
        letter = self._quote_filter_value(flt.get("letter", ""))
        year = self._quote_filter_value(flt.get("year", ""))
        parts = [
            str(tid), area, sort, class_, lang, letter, "", "",
            str(pg) if pg > 1 else "", "", "", year
        ]
        return f"{self.base_url}/show/{'-'.join(parts)}.html"

    def categoryContent(self, tid, pg, filter=False, content=None):
        try:
            pg = int(pg)
            if str(tid) not in CATEGORY_NAMES:
                return {"list": [], "page": pg, "pagecount": 1, "limit": 40, "total": 0}

            flt = {}
            if content:
                try:
                    flt = json.loads(content) if isinstance(content, str) else content
                except Exception:
                    flt = {}

            url = self._build_show_url(tid, pg, flt)
            self._log(f"分类请求: {url}")
            html = self._get(url)
            if not html:
                return {"list": [], "page": pg, "pagecount": 1, "limit": 40, "total": 0}

            videos = self._parse_video_list(html)

            # 从尾页链接提取真实总页数（尾页 URL: /show/...-------278---.html）
            pagecount = 1
            m = re.search(r'<a[^>]*href="/show/[^"]*?-(\d+)---\.html"[^>]*>\s*尾页\s*</a>', html)
            if m:
                pagecount = int(m.group(1))
            if pagecount < 1:
                pagecount = 1

            return {
                "list": videos,
                "page": pg,
                "pagecount": pagecount,
                "limit": 40,
                "total": pagecount * 40,
            }
        except Exception as e:
            self._log(f"categoryContent异常: {e}")
            return {"list": [], "page": int(pg) if str(pg).isdigit() else 1, "pagecount": 1, "limit": 40, "total": 0}

    def searchContent(self, key, quick=False, pg="1"):
        """站点搜索：/search/{关键词}----------{页}---.html（无验证码）"""
        try:
            pg = max(1, int(pg or 1))
        except (TypeError, ValueError):
            pg = 1
        keyword = str(key or "").strip()
        if not keyword:
            return {"page": pg, "pagecount": 1, "limit": 40, "total": 0, "list": []}
        is_quick = bool(quick)

        cache_key = f"{keyword}_{pg}_{is_quick}"
        now = time.time()
        cached = self._SEARCH_CACHE.get(cache_key)
        if cached and now - cached[0] < self._SEARCH_CACHE_TTL:
            return cached[1]

        encoded_key = quote(keyword)
        page_part = str(pg) if pg > 1 else ""
        url = f"{self.base_url}/search/{encoded_key}----------{page_part}---.html"
        self._log(f"搜索请求: {url}, quick={is_quick}")

        html = self._get(url, max_retry=3, timeout=10)
        if not html:
            # 兜底：走采集 API（resp.total 可用于换算总页数）
            api_data = self._get_json(f"{self.api_url}?ac=videolist&wd={quote(keyword)}&pg={pg}")
            videos = []
            api_total = 0
            if api_data and api_data.get("list"):
                api_total = int(api_data.get("total") or 0)
                for v in api_data["list"]:
                    videos.append({
                        "vod_id": str(v.get("vod_id", "")),
                        "vod_name": self._clean_vod_name(v.get("vod_name", "")),
                        "vod_pic": self._clean_vod_pic(v.get("vod_pic", "")),
                        "vod_remarks": v.get("vod_remarks", "") or v.get("vod_remarks", ""),
                    })
            pagecount = max(1, -(-api_total // 40)) if api_total > 0 else 1
            result = {"list": videos, "page": pg, "pagecount": pagecount, "limit": 40,
                      "total": api_total if api_total > 0 else len(videos)}
            self._SEARCH_CACHE[cache_key] = (time.time(), result)
            return result

        videos = self._parse_search_list(html)

        if not is_quick:
            key_lower = keyword.lower()
            def _sort_score(v):
                name = v.get('vod_name', '').lower()
                if name == key_lower:
                    return 0
                if name.startswith(key_lower):
                    return 1
                if key_lower in name:
                    return 2
                return 3
            videos = sorted(videos, key=_sort_score)

        result = {
            "list": videos,
            "page": pg,
            "pagecount": 1 if not videos else max(pg, 1),
            "limit": 40,
            "total": len(videos),
        }
        # 从搜索页分页结构提取真实总页数（尾页链接 title="尾页"，URL 为 ----------{页}---.html）
        pb = re.search(r'href="/search/[^"]*?-(\d+)---\.html"[^>]*title="尾页"', html)
        if not pb:
            pb = re.search(r'href="/search/[^"]*?-(\d+)---\.html"[^>]*>\s*尾页\s*<', html)
        if pb:
            pagecount = int(pb.group(1))
            if pagecount >= 1:
                result["pagecount"] = max(pagecount, pg)
                result["total"] = max(len(videos), pagecount * 40)
        self._SEARCH_CACHE[cache_key] = (time.time(), result)
        return result

    def detailContent(self, ids):
        """详情：优先采集 API（返回图片/演员/导演/简介/线路直链），失败再解析 HTML"""
        try:
            if not ids:
                return {"list": []}
            vod_id = ids[0] if isinstance(ids, list) else str(ids)
            v = self._api_detail(str(vod_id))
            if v:
                return self._build_detail_from_api(v)

            # 兜底：HTML 详情页
            url = f"{self.base_url}/detail/{vod_id}.html"
            self._log(f"详情请求(HTML兜底): {url}")
            html = self._get(url)
            if not html:
                return {"list": []}
            return self._build_detail_from_html(html, vod_id)
        except Exception as e:
            self._log(f"detailContent异常: {e}")
            return {"list": []}

    # ---------- 详情组装：API 直链方案 ----------
    def _build_detail_from_api(self, v):
        vod_id = str(v.get("vod_id", ""))
        vod_name = self._clean_vod_name(v.get("vod_name", "") or v.get("vod_name", "未知"))
        vod_pic = self._clean_vod_pic(v.get("vod_pic", ""))

        play_from_raw = v.get("vod_play_from", "") or ""
        play_url_raw = str(v.get("vod_play_url", "") or "")

        # 线路名列表（API 分隔符为 $$$），映射为前端显示名
        from_list_raw = [s for s in re.split(r'\$\$\$', play_from_raw) if s]
        from_list = [SOURCE_MAP.get(s, s) for s in from_list_raw]
        # 各线路集数块（每块内 # 分隔集数，每集 "名称$URL"）
        url_blocks = re.split(r'\$\$\$', play_url_raw)
        if len(url_blocks) < len(from_list):
            url_blocks = url_blocks + [""] * (len(from_list) - len(url_blocks))

        if from_list:
            vod_play_from = "$$$".join(from_list)
            play_url_parts = []
            for idx, src_name in enumerate(from_list):
                eps = []
                block = url_blocks[idx] if idx < len(url_blocks) else ""
                for ep in block.split("#"):
                    if not ep or "$" not in ep:
                        continue
                    ep_name, _ep_url = ep.split("$", 1)
                    # 占位链接：{vod_id}-{sid}-{nid}，sid 从 1 开始
                    eps.append(f"{ep_name.strip()}${vod_id}-{idx + 1}-{len(eps) + 1}")
                play_url_parts.append("#".join(eps))

            # 无第三方解析线路：直链线路按 sid 序号原样返回，网页线路播放时 parse=1 交壳子
            vod_play_from = "$$$".join(from_list)
            vod_play_url = "$$$".join(play_url_parts)
        else:
            vod_play_from = ""
            vod_play_url = ""

        video = {
            "vod_id": vod_id,
            "vod_name": vod_name,
            "vod_pic": vod_pic,
            "vod_year": str(v.get("vod_year", "") or ""),
            "vod_area": str(v.get("vod_area", "") or ""),
            "vod_actor": str(v.get("vod_actor", "") or ""),
            "vod_director": str(v.get("vod_director", "") or ""),
            "vod_content": str(v.get("vod_content", "") or ""),
            "vod_remarks": str(v.get("vod_remarks", "") or ""),
            "vod_play_from": vod_play_from,
            "vod_play_url": vod_play_url,
        }
        self._log(f"API详情解析成功: {vod_name}, 线路: {vod_play_from}")
        return {"list": [video]}

    # ---------- 详情组装：HTML 兜底 ----------
    def _build_detail_from_html(self, html, vod_id):
        title = self._re_detail_title.search(html)
        vod_name = self._clean_vod_name(title.group(1).strip()) if title else "未知"

        vod_pic = ""
        img_tag = re.search(r'<img[^>]*class="[^"]*lazyload[^"]*"[^>]*>', html)
        if not img_tag:
            img_tag = re.search(r'<img[^>]*>', html)
        if img_tag:
            vod_pic = self._clean_vod_pic(self._extract_img_src(img_tag.group(0)))

        desc = re.search(r'<div[^>]*class="[^"]*module-info-introduction-content[^"]*"[^>]*>(.*?)</div>', html, re.DOTALL)
        vod_content = self._clean_html(desc.group(1)) if desc else ""

        actor = re.search(r'主演：</span>.*?<div[^>]*class="[^"]*module-info-item-content[^"]*"[^>]*>(.*?)</div>', html, re.DOTALL)
        vod_actor = self._clean_html(actor.group(1)) if actor else ""

        director = re.search(r'导演：</span>.*?<div[^>]*class="[^"]*module-info-item-content[^"]*"[^>]*>(.*?)</div>', html, re.DOTALL)
        vod_director = self._clean_html(director.group(1)) if director else ""

        year = re.search(r'年份[:：]?\s*(\d{4})', html)
        vod_year = year.group(1) if year else ""

        # 播放线路：复用 API（HTML 兜底时也尝试 API 拿直链）
        v = self._api_detail(str(vod_id))
        if v:
            return self._build_detail_from_api(v)
        return {
            "list": [{
                "vod_id": vod_id, "vod_name": vod_name, "vod_pic": vod_pic,
                "vod_year": vod_year, "vod_area": "", "vod_actor": vod_actor,
                "vod_director": vod_director, "vod_content": vod_content,
                "vod_remarks": "", "vod_play_from": "", "vod_play_url": "",
            }]
        }

    def playerContent(self, flag, id, vipFlags=None):
        """播放：flag 为显示名（OK超清/OK极速/OK自营Q...），id = {vod_id}-{sid}-{nid}"""
        try:
            parts = str(id).split("-")
            if len(parts) != 3:
                return {"parse": 0, "url": "", "header": ""}
            vod_id, sid, nid = parts
            sid = int(sid)
            nid = int(nid)
            if sid < 1 or nid < 1:
                return {"parse": 0, "url": "", "header": ""}

            v = self._api_detail(str(vod_id))
            if not v:
                return {"parse": 0, "url": "", "header": ""}

            hdr = {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
                "Referer": f"{self.site_url}/play/{vod_id}-{sid}-{nid}.html",
                "Accept": "*/*",
            }

            # ===== 普通线路 =====
            # sid 由详情页按线路顺序编号（idx+1），直接对应 url_blocks 的位置；
            # 源站存在重名线路（OK极速=1080zyk/mtv、OK自营=JPZY/NBY），因此以 sid 定位，
            # 不依赖显示名反查原始名。
            play_url_raw = str(v.get("vod_play_url", "") or "")
            url_blocks = re.split(r'\$\$\$', play_url_raw)
            real_sid = sid
            if real_sid - 1 >= len(url_blocks):
                # 兜底：sid 越界时按显示名反查原始名重新定位（兼容线路顺序异常）
                raw_flag = SOURCE_MAP_R.get(flag, flag)
                play_from_raw = v.get("vod_play_from", "") or ""
                from_list_raw = [s for s in re.split(r'\$\$\$', play_from_raw) if s]
                try:
                    real_sid = from_list_raw.index(raw_flag) + 1
                except ValueError:
                    return {"parse": 0, "url": "", "header": ""}
            if real_sid - 1 >= len(url_blocks):
                return {"parse": 0, "url": "", "header": ""}
            block = url_blocks[real_sid - 1]
            eps = [ep for ep in block.split("#") if ep and "$" in ep]
            if nid - 1 >= len(eps):
                return {"parse": 0, "url": "", "header": ""}
            # 集名可能包含 $？只 split 一次
            _ep_name, ep_url = eps[nid - 1].split("$", 1)
            ep_url = ep_url.strip()

            is_direct = bool(re.search(r'\.(m3u8|mp4|flv|ts|mkv)([?#&]|$)', ep_url, re.I))
            if is_direct:
                self._log(f"播放直链: {ep_url[:90]}")
                return {"parse": 0, "url": ep_url, "header": json.dumps(hdr, ensure_ascii=False)}
            # 非直链（平台网页，如 v.qq.com/爱奇艺/优酷/B站/芒果）：
            # 不内置任何解析接口，parse=1 交回壳子内建播放器/浏览器/用户自配解析处理
            if ep_url.startswith("http"):
                self._log(f"网页线路(parse=1): {ep_url[:90]}")
                return {"parse": 1, "url": ep_url, "header": json.dumps(hdr, ensure_ascii=False)}
            return {"parse": 0, "url": "", "header": ""}
        except Exception as e:
            self._log(f"playerContent异常: {e}")
            return {"parse": 0, "url": "", "header": ""}

    # ---------- 解析接口已全部移除（2026-09-17）：不内置任何第三方解析 ----------
    # 直链线路 parse=0 直接播放；网页线路（qq/爱奇艺/优酷/B站/芒果等）parse=1 交壳子处理。

    # ==================== 壳协议兼容 ====================
    def getName(self):
        return self.name

    def isVideoFormat(self, url):
        pass

    def manualVideoCheck(self):
        pass

    def destroy(self):
        pass

    def localProxy(self, param):
        pass

    def getDependence(self):
        return {}

    def __getattr__(self, name):
        """壳安全兜底：未知探测返回空 stub"""
        if name.startswith('get') and name[3:4].isupper():
            method_name = name[3:]
            if hasattr(self, method_name):
                return getattr(self, method_name)
        if name.startswith('get'):
            return {}
        return None