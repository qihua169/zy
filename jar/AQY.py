#!/usr/bin/env python3
# -*- coding: utf-8 -*-
from bs4 import BeautifulSoup
import urllib.parse
import requests
import json
import time
import re
import sys

sys.path.append('../../')
try:
    from base.spider import Spider
except ImportError:
    class Spider:
        def init(self, extend=""):
            pass

class Spider(Spider):
    def __init__(self):
        self.siteUrl = 'https://m.iqiyi.com'
        self.pcwApi = 'https://pcw-api.iqiyi.com'
        self.searchApi = 'https://search.video.iqiyi.com/o'
        self.cacheApi = 'https://cache.video.iqiyi.com'
        self.userAgent = 'Mozilla/5.0 (iPhone; CPU iPhone OS 16_6 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.6 Mobile/15E148 Safari/604.1'
        
        self.channels = {
            '1': {'name': '电影', 'channel_id': '1'},
            '2': {'name': '电视剧', 'channel_id': '2'},
            '3': {'name': '动漫', 'channel_id': '3'},
            '4': {'name': '综艺', 'channel_id': '4'},
            '6': {'name': '纪录片', 'channel_id': '6'},
            '7': {'name': '短片', 'channel_id': '7'},
            '8': {'name': '少儿', 'channel_id': '8'},
        }
        
        self.filters = {
            "1": [
                {"key": "mode", "name": "排序", "value": [
                    {"n": "综合排序", "v": "24"},
                    {"n": "热播榜", "v": "11"},
                    {"n": "新上线", "v": "8"}
                ]},
                {"key": "area", "name": "地区", "value": [
                    {"n": "全部地区", "v": "0"},
                    {"n": "内地", "v": "1"},
                    {"n": "香港", "v": "2"},
                    {"n": "台湾", "v": "3"},
                    {"n": "美国", "v": "4"},
                    {"n": "韩国", "v": "5"},
                    {"n": "日本", "v": "6"},
                    {"n": "泰国", "v": "7"},
                    {"n": "英国", "v": "8"},
                    {"n": "其它", "v": "9"}
                ]},
                {"key": "type", "name": "类型", "value": [
                    {"n": "全部类型", "v": "0"},
                    {"n": "动作", "v": "1"},
                    {"n": "喜剧", "v": "2"},
                    {"n": "爱情", "v": "3"},
                    {"n": "科幻", "v": "4"},
                    {"n": "恐怖", "v": "5"},
                    {"n": "剧情", "v": "6"},
                    {"n": "战争", "v": "7"},
                    {"n": "悬疑", "v": "8"},
                    {"n": "动画", "v": "9"},
                    {"n": "奇幻", "v": "10"},
                    {"n": "冒险", "v": "11"},
                    {"n": "犯罪", "v": "12"},
                    {"n": "惊悚", "v": "13"}
                ]},
                {"key": "year", "name": "年份", "value": [
                    {"n": "全部年份", "v": "0"},
                    {"n": "2026", "v": "2026"},
                    {"n": "2025", "v": "2025"},
                    {"n": "2024", "v": "2024"},
                    {"n": "2023", "v": "2023"},
                    {"n": "2022", "v": "2022"},
                    {"n": "2021", "v": "2021"},
                    {"n": "2020", "v": "2020"},
                    {"n": "2019", "v": "2019"},
                    {"n": "2018", "v": "2018"},
                    {"n": "2017", "v": "2017"},
                    {"n": "2016", "v": "2016"},
                    {"n": "2015", "v": "2015"},
                    {"n": "2011-2014", "v": "2011_2014"},
                    {"n": "2000-2010", "v": "2000_2010"},
                    {"n": "90年代", "v": "1990_1999"},
                    {"n": "80年代", "v": "1980_1989"},
                    {"n": "更早", "v": "-1980"}
                ]},
                {"key": "pay", "name": "资费", "value": [
                    {"n": "全部资费", "v": "0"},
                    {"n": "免费", "v": "1"},
                    {"n": "付费", "v": "2"}
                ]}
            ],
            "2": [
                {"key": "mode", "name": "排序", "value": [
                    {"n": "综合排序", "v": "24"},
                    {"n": "热播榜", "v": "11"},
                    {"n": "新上线", "v": "8"}
                ]},
                {"key": "area", "name": "地区", "value": [
                    {"n": "全部地区", "v": "0"},
                    {"n": "内地", "v": "1"},
                    {"n": "港剧", "v": "2"},
                    {"n": "韩剧", "v": "5"},
                    {"n": "美剧", "v": "4"},
                    {"n": "日剧", "v": "6"},
                    {"n": "泰剧", "v": "7"},
                    {"n": "台湾地区", "v": "3"},
                    {"n": "英剧", "v": "8"},
                    {"n": "其它", "v": "9"}
                ]},
                {"key": "type", "name": "类型", "value": [
                    {"n": "全部类型", "v": "0"},
                    {"n": "自制", "v": "1"},
                    {"n": "古装", "v": "2"},
                    {"n": "言情", "v": "3"},
                    {"n": "武侠", "v": "4"},
                    {"n": "偶像", "v": "5"},
                    {"n": "家庭", "v": "6"},
                    {"n": "青春", "v": "7"},
                    {"n": "都市", "v": "8"},
                    {"n": "喜剧", "v": "9"},
                    {"n": "战争", "v": "10"},
                    {"n": "军旅", "v": "11"},
                    {"n": "谍战", "v": "12"},
                    {"n": "悬疑", "v": "13"},
                    {"n": "罪案", "v": "14"},
                    {"n": "穿越", "v": "15"},
                    {"n": "宫廷", "v": "16"},
                    {"n": "历史", "v": "17"},
                    {"n": "神话", "v": "18"},
                    {"n": "科幻", "v": "19"},
                    {"n": "年代", "v": "20"},
                    {"n": "农村", "v": "21"},
                    {"n": "商战", "v": "22"},
                    {"n": "剧情", "v": "23"},
                    {"n": "奇幻", "v": "24"},
                    {"n": "网剧", "v": "25"},
                    {"n": "竖短片", "v": "26"}
                ]},
                {"key": "year", "name": "年份", "value": [
                    {"n": "全部年份", "v": "0"},
                    {"n": "2026", "v": "2026"},
                    {"n": "2025", "v": "2025"},
                    {"n": "2024", "v": "2024"},
                    {"n": "2023", "v": "2023"},
                    {"n": "2022", "v": "2022"},
                    {"n": "2021", "v": "2021"},
                    {"n": "2020", "v": "2020"},
                    {"n": "2019", "v": "2019"},
                    {"n": "2018", "v": "2018"},
                    {"n": "2017", "v": "2017"},
                    {"n": "2016", "v": "2016"},
                    {"n": "2015", "v": "2015"},
                    {"n": "2011-2014", "v": "2011_2014"},
                    {"n": "2000-2010", "v": "2000_2010"},
                    {"n": "90年代", "v": "1990_1999"},
                    {"n": "80年代", "v": "1980_1989"},
                    {"n": "更早", "v": "-1980"}
                ]},
                {"key": "pay", "name": "资费", "value": [
                    {"n": "全部资费", "v": "0"},
                    {"n": "免费", "v": "1"},
                    {"n": "付费", "v": "2"}
                ]}
            ],
            "3": [
                {"key": "mode", "name": "排序", "value": [
                    {"n": "综合排序", "v": "24"},
                    {"n": "热播榜", "v": "11"},
                    {"n": "新上线", "v": "8"}
                ]},
                {"key": "area", "name": "地区", "value": [
                    {"n": "全部地区", "v": "0"},
                    {"n": "国产", "v": "1"},
                    {"n": "日本", "v": "6"},
                    {"n": "欧美", "v": "4"},
                    {"n": "韩国", "v": "5"},
                    {"n": "其它", "v": "9"}
                ]},
                {"key": "type", "name": "类型", "value": [
                    {"n": "全部类型", "v": "0"},
                    {"n": "热血", "v": "1"},
                    {"n": "恋爱", "v": "2"},
                    {"n": "科幻", "v": "3"},
                    {"n": "奇幻", "v": "4"},
                    {"n": "冒险", "v": "5"},
                    {"n": "搞笑", "v": "6"},
                    {"n": "战斗", "v": "7"},
                    {"n": "神魔", "v": "8"},
                    {"n": "竞技", "v": "9"},
                    {"n": "日常", "v": "10"},
                    {"n": "校园", "v": "11"},
                    {"n": "治愈", "v": "12"},
                    {"n": "悬疑", "v": "13"}
                ]},
                {"key": "year", "name": "年份", "value": [
                    {"n": "全部年份", "v": "0"},
                    {"n": "2026", "v": "2026"},
                    {"n": "2025", "v": "2025"},
                    {"n": "2024", "v": "2024"},
                    {"n": "2023", "v": "2023"},
                    {"n": "2022", "v": "2022"},
                    {"n": "2021", "v": "2021"},
                    {"n": "2020", "v": "2020"},
                    {"n": "2019", "v": "2019"},
                    {"n": "2018", "v": "2018"},
                    {"n": "2017", "v": "2017"},
                    {"n": "更早", "v": "-2017"}
                ]},
                {"key": "pay", "name": "资费", "value": [
                    {"n": "全部资费", "v": "0"},
                    {"n": "免费", "v": "1"},
                    {"n": "付费", "v": "2"}
                ]}
            ],
            "4": [
                {"key": "mode", "name": "排序", "value": [
                    {"n": "综合排序", "v": "24"},
                    {"n": "热播榜", "v": "11"},
                    {"n": "新上线", "v": "8"}
                ]},
                {"key": "area", "name": "地区", "value": [
                    {"n": "全部地区", "v": "0"},
                    {"n": "内地", "v": "1"},
                    {"n": "港台", "v": "2"},
                    {"n": "日韩", "v": "5"},
                    {"n": "欧美", "v": "4"},
                    {"n": "其它", "v": "9"}
                ]},
                {"key": "type", "name": "类型", "value": [
                    {"n": "全部类型", "v": "0"},
                    {"n": "真人秀", "v": "1"},
                    {"n": "脱口秀", "v": "2"},
                    {"n": "选秀", "v": "3"},
                    {"n": "访谈", "v": "4"},
                    {"n": "情感", "v": "5"},
                    {"n": "生活", "v": "6"},
                    {"n": "美食", "v": "7"},
                    {"n": "旅游", "v": "8"},
                    {"n": "游戏", "v": "9"},
                    {"n": "音乐", "v": "10"},
                    {"n": "时尚", "v": "11"},
                    {"n": "文化", "v": "12"},
                    {"n": "搞笑", "v": "13"}
                ]},
                {"key": "year", "name": "年份", "value": [
                    {"n": "全部年份", "v": "0"},
                    {"n": "2026", "v": "2026"},
                    {"n": "2025", "v": "2025"},
                    {"n": "2024", "v": "2024"},
                    {"n": "2023", "v": "2023"},
                    {"n": "2022", "v": "2022"},
                    {"n": "2021", "v": "2021"},
                    {"n": "2020", "v": "2020"},
                    {"n": "2019", "v": "2019"},
                    {"n": "更早", "v": "-2019"}
                ]},
                {"key": "pay", "name": "资费", "value": [
                    {"n": "全部资费", "v": "0"},
                    {"n": "免费", "v": "1"},
                    {"n": "付费", "v": "2"}
                ]}
            ],
            "6": [
                {"key": "mode", "name": "排序", "value": [
                    {"n": "综合排序", "v": "24"},
                    {"n": "热播榜", "v": "11"},
                    {"n": "新上线", "v": "8"}
                ]},
                {"key": "area", "name": "地区", "value": [
                    {"n": "全部地区", "v": "0"},
                    {"n": "内地", "v": "1"},
                    {"n": "国外", "v": "9"}
                ]},
                {"key": "type", "name": "类型", "value": [
                    {"n": "全部类型", "v": "0"},
                    {"n": "自然", "v": "1"},
                    {"n": "历史", "v": "2"},
                    {"n": "人文", "v": "3"},
                    {"n": "社会", "v": "4"},
                    {"n": "科技", "v": "5"},
                    {"n": "探险", "v": "6"},
                    {"n": "军事", "v": "7"},
                    {"n": "传记", "v": "8"}
                ]},
                {"key": "year", "name": "年份", "value": [
                    {"n": "全部年份", "v": "0"},
                    {"n": "2026", "v": "2026"},
                    {"n": "2025", "v": "2025"},
                    {"n": "2024", "v": "2024"},
                    {"n": "2023", "v": "2023"},
                    {"n": "2022", "v": "2022"},
                    {"n": "2021", "v": "2021"},
                    {"n": "2020", "v": "2020"},
                    {"n": "更早", "v": "-2020"}
                ]},
                {"key": "pay", "name": "资费", "value": [
                    {"n": "全部资费", "v": "0"},
                    {"n": "免费", "v": "1"},
                    {"n": "付费", "v": "2"}
                ]}
            ],
            "7": [
                {"key": "mode", "name": "排序", "value": [
                    {"n": "综合排序", "v": "24"},
                    {"n": "热播榜", "v": "11"},
                    {"n": "新上线", "v": "8"}
                ]},
                {"key": "year", "name": "年份", "value": [
                    {"n": "全部年份", "v": "0"},
                    {"n": "2026", "v": "2026"},
                    {"n": "2025", "v": "2025"},
                    {"n": "2024", "v": "2024"},
                    {"n": "2023", "v": "2023"},
                    {"n": "2022", "v": "2022"}
                ]},
                {"key": "pay", "name": "资费", "value": [
                    {"n": "全部资费", "v": "0"},
                    {"n": "免费", "v": "1"},
                    {"n": "付费", "v": "2"}
                ]}
            ],
            "8": [
                {"key": "mode", "name": "排序", "value": [
                    {"n": "综合排序", "v": "24"},
                    {"n": "热播榜", "v": "11"},
                    {"n": "新上线", "v": "8"}
                ]},
                {"key": "type", "name": "类型", "value": [
                    {"n": "全部类型", "v": "0"},
                    {"n": "动画", "v": "1"},
                    {"n": "儿歌", "v": "2"},
                    {"n": "早教", "v": "3"},
                    {"n": "益智", "v": "4"},
                    {"n": "故事", "v": "5"},
                    {"n": "科普", "v": "6"}
                ]},
                {"key": "year", "name": "年份", "value": [
                    {"n": "全部年份", "v": "0"},
                    {"n": "2026", "v": "2026"},
                    {"n": "2025", "v": "2025"},
                    {"n": "2024", "v": "2024"},
                    {"n": "2023", "v": "2023"},
                    {"n": "2022", "v": "2022"},
                    {"n": "2021", "v": "2021"},
                    {"n": "更早", "v": "-2021"}
                ]},
                {"key": "pay", "name": "资费", "value": [
                    {"n": "全部资费", "v": "0"},
                    {"n": "免费", "v": "1"},
                    {"n": "付费", "v": "2"}
                ]}
            ]
        }

    def getName(self):
        return "爱奇艺影视"

    def init(self, extend=""):
        pass

    def fetch(self, url, headers=None, params=None):
        if headers is None:
            headers = {
                'User-Agent': self.userAgent,
                'Referer': self.siteUrl,
                'Accept': 'application/json, text/plain, */*',
                'Accept-Language': 'zh-CN,zh;q=0.9',
            }
        try:
            if params:
                response = requests.get(url, headers=headers, params=params, timeout=10)
            else:
                response = requests.get(url, headers=headers, timeout=10)
            response.raise_for_status()
            return response
        except Exception as e:
            print(f"请求失败: {url}, 错误: {e}")
            return None

    def homeContent(self, filter):
        result = {}
        classes = []
        for k, v in self.channels.items():
            classes.append({
                'type_id': k,
                'type_name': v['name']
            })
        result['class'] = classes
        if filter:
            result['filters'] = self.filters
        return result

    def homeVideoContent(self):
        result = {}
        videos = []
        try:
            for channel_id in ['2', '1', '3', '4']:
                url = f'{self.pcwApi}/search/recommend/list'
                params = {
                    'channel_id': self.channels[channel_id]['channel_id'],
                    'data_type': '1',
                    'mode': '11',
                    'page_id': '1',
                    'ret_num': '12',
                    'session': ''
                }
                response = self.fetch(url, params=params)
                if response:
                    data = response.json()
                    if data.get('code') == 'A00000' and data.get('data', {}).get('list'):
                        for item in data['data']['list'][:6]:
                            videos.append(self._parseVideoItem(item))
                if len(videos) >= 24:
                    break
        except Exception as e:
            print(f"获取首页视频失败: {e}")
        result['list'] = videos
        return result

    def categoryContent(self, tid, pg, filter, extend):
        result = {}
        videos = []
        try:
            channel_info = self.channels.get(tid, {})
            channel_id = channel_info.get('channel_id', '2')
            
            mode = extend.get('mode', '24') if extend else '24'
            
            url = f'{self.pcwApi}/search/recommend/list'
            params = {
                'channel_id': channel_id,
                'data_type': '1',
                'mode': mode,
                'page_id': str(pg),
                'ret_num': '48',
                'session': ''
            }
            
            response = self.fetch(url, params=params)
            if response:
                data = response.json()
                if data.get('code') == 'A00000' and data.get('data', {}).get('list'):
                    for item in data['data']['list']:
                        videos.append(self._parseVideoItem(item))
                    
                    has_next = data['data'].get('has_next', 0)
                    pagecount = pg + 1 if has_next else pg
                    total = len(videos) * pg
                else:
                    pagecount = pg
                    total = len(videos)
            else:
                pagecount = pg
                total = len(videos)
        except Exception as e:
            print(f"获取分类内容失败: {e}")
            pagecount = pg
            total = len(videos)
        
        result['list'] = videos
        result['page'] = pg
        result['pagecount'] = pagecount
        result['limit'] = 48
        result['total'] = total
        return result

    def detailContent(self, ids):
        result = {}
        try:
            video_id = ids[0]
            album_id = video_id.split('_')[0] if '_' in video_id else video_id
            
            url = f'{self.pcwApi}/albums/album/avlistinfo'
            params = {
                'aid': album_id,
                'page': '1',
                'size': '30'
            }
            response = self.fetch(url, params=params)
            
            if response:
                data = response.json()
                if data.get('code') == 'A00000' and data.get('data', {}).get('epsodelist'):
                    album_data = data['data']
                    episodes = album_data['epsodelist']
                    
                    first_ep = episodes[0] if episodes else {}
                    
                    play_from = ['爱奇艺']
                    play_urls = []
                    
                    for ep in episodes:
                        ep_name = ep.get('shortTitle', ep.get('name', ''))
                        ep_url = ep.get('playUrl', '')
                        if ep_url:
                            play_urls.append(f"{ep_name}${ep_url}")
                    
                    play_url = '#'.join(play_urls)
                    
                    vod = {
                        "vod_id": video_id,
                        "vod_name": first_ep.get('name', '').split('第')[0] if first_ep.get('name') else '',
                        "vod_pic": first_ep.get('imageUrl', ''),
                        "vod_remarks": f"共{len(episodes)}集",
                        "vod_content": first_ep.get('description', ''),
                        "vod_play_from": "$$$".join(play_from),
                        "vod_play_url": "$$$".join([play_url])
                    }
                    result['list'] = [vod]
                else:
                    result['list'] = []
            else:
                result['list'] = []
        except Exception as e:
            print(f"获取详情失败: {e}")
            result['list'] = []
        return result

    def searchContent(self, key, quick, pg=1):
        videos = []
        try:
            url = self.searchApi
            params = {
                'if': 'html5',
                'key': key,
                'pageNum': str(pg),
                'pageSize': '25'
            }
            response = self.fetch(url, params=params)
            if response:
                data = response.json()
                if data.get('data', {}).get('docinfos'):
                    for item in data['data']['docinfos']:
                        album_info = item.get('albumDocInfo', {})
                        if album_info:
                            videos.append({
                                "vod_id": str(album_info.get('albumId', '')),
                                "vod_name": album_info.get('albumTitle', ''),
                                "vod_pic": album_info.get('albumVImage', ''),
                                "vod_remarks": album_info.get('tvFocus', '') or f"{album_info.get('itemTotalNumber', 0)}集"
                            })
        except Exception as e:
            print(f"搜索失败: {e}")
        return videos

    def searchContentPage(self, key, quick, pg=1):
        return self.searchContent(key, quick, pg)

    def playerContent(self, flag, id, vipFlags):
        result = {}
        try:
            if self.isVideoFormat(id):
                result["parse"] = 0
                result["url"] = id
            else:
                result["parse"] = 1
                result["url"] = id
                result["jx"] = "1"
            
            result["header"] = {
                "User-Agent": self.userAgent,
                "Referer": self.siteUrl
            }
        except Exception as e:
            print(f"获取播放内容失败: {e}")
        return result

    def isVideoFormat(self, url):
        video_formats = ['.mp4', '.m3u8', '.ts', '.mkv', '.avi', '.flv', '.webm']
        if url and url.startswith('http'):
            for fmt in video_formats:
                if url.lower().find(fmt) > -1:
                    return True
        return False

    def manualVideoCheck(self):
        return False

    def localProxy(self, param):
        return None

    def _parseVideoItem(self, item):
        return {
            "vod_id": str(item.get('albumId', '')),
            "vod_name": item.get('name', ''),
            "vod_pic": item.get('imageUrl', ''),
            "vod_remarks": item.get('focus', '') or f"更新至{item.get('latestOrder', 0)}集",
            "vod_year": str(item.get('period', ''))[:4] if item.get('period') else '',
            "vod_area": ','.join(item.get('categories', []))
        }

if __name__ == '__main__':
    spider = Spider()
    print(json.dumps(spider.homeContent(True), ensure_ascii=False, indent=2))
