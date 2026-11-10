# -*- coding: utf-8 -*-
# 奇迹云 (cmsyun2.qijiyun.vip) - FongMi 影视壳 Python 源
# 接口来源：站点 App 接口 http://cmsyun2.qijiyun.vip/api.php/app
#   /nav                 分类列表
#   /video?tid=&pg=      分类列表（真实翻页）
#   /search?text=        搜索（服务端按片名匹配，单页返回）
#   /video_detail?id=    详情，vod_play_url 内为可直连的 .mp4 / .mkv 地址
# 播放：直链 -> 302 到移动云 EOS 签名地址 -> 206 video/* ，无需解析、无需 Referer/UA 限制
import json
from urllib.parse import urlencode
from base.spider import Spider


class Spider(Spider):
    def init(self, extend=''):
        pass

    host = 'http://cmsyun2.qijiyun.vip'
    api = host + '/api.php/app'

    headers = {
        'User-Agent': 'okhttp/4.12.0',
        'Accept': 'application/json, text/plain, */*',
    }

    # nav 拉取失败时的兜底分类
    DEFAULT_CLASS = [
        {'type_id': '21', 'type_name': '体验新4k-剧集—试玩'},
        {'type_id': '20', 'type_name': '体验新4k-电影—试玩'},
        {'type_id': '1', 'type_name': '体验新4k-国漫—试玩'},
    ]

    def _get(self, path, params=None):
        url = self.api + path
        if params:
            url = url + '?' + urlencode(params)
        try:
            r = self.fetch(url, headers=self.headers, timeout=15)
            return json.loads(r.text)
        except Exception:
            return None

    def _list_item(self, v):
        item = {
            'vod_id': str(v.get('vod_id', '')),
            'vod_name': v.get('vod_name', ''),
            'vod_pic': v.get('vod_pic', ''),
        }
        if v.get('vod_remarks'):
            item['vod_remarks'] = v.get('vod_remarks')
        if v.get('vod_score'):
            item['vod_score'] = str(v.get('vod_score'))
        return item

    def homeContent(self, filter):
        classes = []
        d = self._get('/nav')
        if d and d.get('list'):
            for it in d['list']:
                classes.append({
                    'type_id': str(it.get('type_id', '')),
                    'type_name': it.get('type_name', ''),
                })
        if not classes:
            classes = [dict(c) for c in self.DEFAULT_CLASS]
        return {'class': classes, 'filters': {}}

    def homeVideoContent(self):
        return {'list': []}

    def categoryContent(self, tid, pg, filter, extend):
        d = self._get('/video', {'tid': tid, 'pg': pg})
        if not d:
            return {'list': [], 'page': pg}
        videos = [self._list_item(v) for v in (d.get('list') or [])]
        return {
            'list': videos,
            'page': str(d.get('page') or pg),
            'pagecount': str(d.get('pagecount') or 1),
            'limit': str(d.get('limit') or len(videos)),
            'total': str(d.get('total') or len(videos)),
        }

    def searchContent(self, key, quick, pg='1'):
        # 搜索接口按片名子串匹配，服务端不分页，一次返回全部命中
        d = self._get('/search', {'text': key})
        videos = [self._list_item(v) for v in ((d or {}).get('list') or [])]
        return {
            'list': videos,
            'page': '1',
            'pagecount': '1',
            'limit': str(len(videos)),
            'total': str(len(videos)),
        }

    def detailContent(self, ids):
        vid = str(ids[0])
        d = self._get('/video_detail', {'id': vid})
        if not d or not d.get('data'):
            return {'list': []}
        v = d['data']
        dm = {
            'vod_id': str(v.get('vod_id', vid)),
            'vod_name': v.get('vod_name', ''),
            'vod_pic': v.get('vod_pic', ''),
            'vod_content': v.get('vod_content') or v.get('vod_blurb') or '',
            'vod_remarks': v.get('vod_remarks', ''),
            'vod_year': str(v.get('vod_year') or ''),
            'vod_area': v.get('vod_area', ''),
            'vod_type': v.get('vod_class', ''),
            'vod_actor': v.get('vod_actor', ''),
            'vod_director': v.get('vod_director', ''),
            'vod_play_from': v.get('vod_play_from') or 'qijiyun4k',
            'vod_play_url': v.get('vod_play_url') or '',
        }
        return {'list': [dm]}

    def playerContent(self, flag, video_id, vipFlags):
        url = (video_id or '').strip()
        if url.startswith('$'):
            url = url[1:]
        return {'jx': 0, 'parse': 0, 'playUrl': '', 'url': url, 'header': self.headers}