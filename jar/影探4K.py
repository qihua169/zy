import re, sys, json, base64, time, random
from Crypto.Cipher import AES
from urllib.parse import urljoin, quote
from Crypto.Util.Padding import unpad
from base.spider import Spider

sys.path.append('..')


class Spider(Spider):
    headers = {'User-Agent': 'okhttp/4.12.0'}
    # 解析接口请求头(与 PHP 端一致)
    parse_headers = {'User-Agent': 'okhttp-okgo/jeasonlzy'}

    FIXED_CONFIG = {
        'host': 'http://cms.lyyytv.cn',
        'cmskey': 'wP5bvxoc3yv7FoBQENFZuAF0EUYr4LTy',
        'RawPlayUrl': 0,
        # ldmax 内置解析接口
        'parse_api': 'http://61.184.23.217:6163/api/index?parsesId=4&appid=10001&videoUrl=',
        # 可选: 给解析请求单独走一个出口,留空则使用本机直连
        # 例: {'http': 'http://127.0.0.1:7890', 'https': 'http://127.0.0.1:7890'}
        # 注意: 基类 fetch 若不支持 proxies 参数会自动降级为直连,不报错
        'proxies': {}
    }

    # ===== 解析服务防封策略参数 =====
    # 解析服务按出口 IP 封禁(实测换 appid / parsesId 均返回 403),唯一有效的
    # 降低手段是把单 IP 的请求次数与突发频率压下来,而不是换参数重试。
    PARSE_CACHE_TTL = 6 * 3600      # 真实地址缓存 6 小时,同一集不重复解析
    PARSE_CACHE_MAX = 300           # 缓存条目上限,超出先清过期再整体清空
    PARSE_MIN_INTERVAL = 1.2        # 两次解析请求最小间隔(秒),避免突发
    PARSE_COOLDOWN = 1800           # 失败/被封后熔断 30 分钟,期间不再打接口
    PARSE_COOLDOWN_MAX = 7200       # 连续失败时熔断上限

    # 类级共享: TVBox 可能为每次调用重建实例,状态必须挂在类上才能生效
    _pcache = {}
    _pstate = {'last': 0.0, 'blocked_until': 0.0, 'fail': 0}

    def init(self, extend=''):
        self.host = self.FIXED_CONFIG['host']
        self.cmskey = self.FIXED_CONFIG.get('cmskey', '')
        self.parse_api = self.FIXED_CONFIG.get('parse_api', '')
        self.proxies = self.FIXED_CONFIG.get('proxies') or {}
        raw_play_url = self.FIXED_CONFIG.get('RawPlayUrl', 0)
        if raw_play_url == 1:
            self.raw_play_url = 1
        else:
            self.raw_play_url = 0

    def ldmax_decrypt(self, encrypted_base64, depth=0):
        # 对应 PHP 的 LdmaxDecryptor::decrypt,递归解密 ldmax.cooom 加密链接
        if depth > 5:
            return None
        # 严格 base64 解码(对应 PHP base64_decode 第二参 true),
        # 非法 base64(如明文URL)直接原样返回
        cleaned = re.sub(r'\s+', '', encrypted_base64)
        try:
            decoded = base64.b64decode(cleaned, validate=True).decode('utf-8', errors='ignore')
        except Exception:
            return encrypted_base64
        url = re.sub(r'\s+', '', decoded)
        if 'ldmax.cooom' not in url:
            return url
        path = re.sub(r'https?://ldmax\.cooom/', '', url)
        if len(path) < 16:
            return None
        key = path[:16][::-1].encode('utf-8')
        ciphertext_b64 = re.sub(r'\s+', '', path[16:])
        try:
            ciphertext = base64.b64decode(ciphertext_b64, validate=True)
        except Exception:
            return None
        try:
            cipher = AES.new(key, AES.MODE_CBC, key)
            decrypted = cipher.decrypt(ciphertext)
        except Exception:
            return None
        if decrypted:
            pad = decrypted[-1]
            if 0 < pad <= 16:
                decrypted = decrypted[:-pad]
        result = decrypted.decode('utf-8', errors='ignore').strip()
        if 'ldmax.cooom' in result:
            return self.ldmax_decrypt(base64.b64encode(result.encode('utf-8')).decode('utf-8'), depth + 1)
        return result

    def _parse_fetch(self, url):
        # 统一出口: 配了代理就走代理,基类不支持 proxies 时静默降级为直连
        if self.proxies:
            try:
                return self.fetch(url, headers=self.parse_headers, timeout=30, proxies=self.proxies)
            except TypeError:
                pass
        return self.fetch(url, headers=self.parse_headers, timeout=30)

    def _pcache_put(self, key, url):
        cache = self._pcache
        if len(cache) >= self.PARSE_CACHE_MAX:
            now = time.time()
            for k in [k for k, v in cache.items() if v[0] <= now]:
                cache.pop(k, None)
            if len(cache) >= self.PARSE_CACHE_MAX:
                cache.clear()
        cache[key] = (time.time() + self.PARSE_CACHE_TTL, url)

    def ldmax_parse(self, video_url):
        # 对应 PHP 主流程:解密 -> 调用解析接口 -> 二次解密
        # 增加三层保护,减少单 IP 请求暴露: 缓存复用 -> 熔断跳过 -> 节流抖动
        now = time.time()
        hit = self._pcache.get(video_url)
        if hit and hit[0] > now:
            return {'url': hit[1], 'type': 'video'}

        st = self._pstate
        if now < st['blocked_until']:
            remain = int(st['blocked_until'] - now)
            print(f"[影探4K] 解析接口冷却中,{remain}s 内跳过请求: {video_url[:60]}")
            return None

        decrypted = self.ldmax_decrypt(video_url)
        if not decrypted or not re.match(r'^https?://', decrypted):
            return None

        wait = self.PARSE_MIN_INTERVAL - (now - st['last'])
        if wait > 0:
            time.sleep(wait + random.uniform(0, 0.6))
        st['last'] = time.time()

        try:
            parse_url = self.parse_api + quote(decrypted, safe='')
            resp = self._parse_fetch(parse_url).json()
        except Exception:
            self._cooldown(st, '请求异常')
            return None

        if not isinstance(resp, dict) or resp.get('code') != 200 or not resp.get('url'):
            msg = str(resp.get('msg', '')) if isinstance(resp, dict) else ''
            # 命中封禁关键字直接长熔断,不再重试(重试只会维持封禁状态)
            if '封' in msg or '禁' in msg:
                st['blocked_until'] = time.time() + self.PARSE_COOLDOWN_MAX
                print(f"[影探4K] 解析接口返回封禁,冷却 {self.PARSE_COOLDOWN_MAX}s: {msg}")
            else:
                self._cooldown(st, msg or '返回异常')
            return None

        final_url = self.ldmax_decrypt(resp['url'])
        if not final_url or not re.match(r'^https?://', final_url):
            self._cooldown(st, '二次解密失败')
            return None

        st['fail'] = 0
        self._pcache_put(video_url, final_url)
        return {'url': final_url, 'type': resp.get('type', 'video')}

    def _cooldown(self, st, reason):
        # 连续失败按次数递增熔断时长,避免失败重试把风控越惹越重
        st['fail'] += 1
        span = min(self.PARSE_COOLDOWN * st['fail'], self.PARSE_COOLDOWN_MAX)
        st['blocked_until'] = time.time() + span
        print(f"[影探4K] 解析失败({reason}),冷却 {int(span)}s")

    def homeVideoContent(self):
        data = self.fetch(f"{self.host}/api.php/app/index_video?token=", headers=self.headers).json()
        videos = []
        for item in data['list']:
            videos.extend(item['vlist'])
        return {'list': videos}

    def homeContent(self, filter):
        data = self.fetch(f"{self.host}/api.php/app/nav?token=", headers=self.headers).json()
        keys = ["class", "area", "lang", "year", "letter", "by", "sort"]
        filters = {}
        classes = []

        for item in data['list']:
            has_non_empty_field = False
            jsontype_extend = item["type_extend"]
            classes.append({"type_name": item["type_name"], "type_id": item["type_id"]})

            for key in keys:
                if key in jsontype_extend and jsontype_extend[key].strip() != "":
                    has_non_empty_field = True
                    break

            if has_non_empty_field:
                filters[str(item["type_id"])] = []

            for dkey in jsontype_extend:
                if dkey in keys and jsontype_extend[dkey].strip() != "":
                    values = jsontype_extend[dkey].split(",")
                    value_array = []
                    for value in values:
                        if value.strip() != "":
                            value_array.append({"n": value.strip(), "v": value.strip()})
                    filters[str(item["type_id"])].append({"key": dkey, "name": dkey, "value": value_array})

        return {"class": classes, "filters": filters}

    def categoryContent(self, tid, pg, filter, extend):
        # 构建URL查询参数
        query_params = [
            f"tid={tid}",
            f"pg={pg}",
            f"limit=18"
        ]
        if extend.get('class'):
            query_params.append(f"class={extend.get('class')}")
        if extend.get('area'):
            query_params.append(f"area={extend.get('area')}")
        if extend.get('lang'):
            query_params.append(f"lang={extend.get('lang')}")
        if extend.get('year'):
            query_params.append(f"year={extend.get('year')}")

        url = f"{self.host}/api.php/app/video?" + "&".join(query_params)
        data = self.fetch(url, headers=self.headers).json()
        return data

    def searchContent(self, key, quick, pg="1"):
        data = self.fetch(f"{self.host}/api.php/app/search?text={key}&pg={pg}", headers=self.headers).json()
        videos = data['list']
        for item in data['list']:
            item.pop('type', None)
        return {'list': videos, 'page': pg}

    def detailContent(self, ids):
        data = self.fetch(f"{self.host}/api.php/app/video_detail?id={ids[0]}", headers=self.headers).json()['data']
        show, paly_urls = [], []

        for i in data.get('vod_url_with_player') or []:
            urls = (i.get('url') or '').split('#')
            urls2 = []
            for j in urls:
                if not j:
                    continue
                # 用 partition 代替 split,避免某路地址没有 '$' 时抛 IndexError 导致整页白屏
                name, sep, raw = j.partition('$')
                if not sep:
                    urls2.append(name)
                    continue
                try:
                    urls2.append(f"{name}${self.lvdou(raw)}")
                except Exception:
                    urls2.append(f"{name}${raw}")
            paly_urls.append('#'.join(urls2))
            show.append((i.get('name') or '').strip())

        data.pop('vod_url_with_player', None)
        data['vod_play_from'] = '$$$'.join(show)
        data['vod_play_url'] = '$$$'.join(paly_urls)
        return {'list': [data]}

    def playerContent(self, flag, video_id, vipFlags):
        # 注意: 不要删除或解码 URL 里的 %XX。
        # 本站片源大量是中文文件名(如 %E7%A7%98%E5%AE%A4...mp4),删掉 %XX 会把
        # 路径拆成残缺字符串(→ 4K.mp4),必然 404。
        video_id = (video_id or '').strip()
        is_plain_url = video_id.startswith(('http://', 'https://'))
        # 本站域名(lyyytv.cn)的 /d/ 是伪直链,必须经 parse_api 还原真实地址,当直链播必 404
        need_parse = (not is_plain_url) or ('lyyytv.cn' in video_id)
        if need_parse:
            parsed = self.ldmax_parse(video_id)
            if parsed and parsed.get('url'):
                return {'parse': 0, 'jx': 0, 'playUrl': '', 'url': parsed['url'], 'header': self.headers}
            # 解析失败:如实交给外置解析,不要把它当直链谎报(否则播放器直接 404 黑屏)
            return {'parse': 1, 'jx': 1, 'playUrl': '', 'url': video_id, 'header': self.headers}
        # 真正的直链(mp4/m3u8 等)直接播放
        if self.check_paly_url(video_id):
            return {'parse': 0, 'jx': 0, 'playUrl': '', 'url': video_id, 'header': self.headers}
        # 其他情况(腾讯/爱奇艺/优酷等网页地址)交给 tvbox 外置解析
        return {'parse': 1, 'jx': 1, 'playUrl': '', 'url': video_id, 'header': self.headers}

    def lvdou(self, text):
        key = self.cmskey[:16].encode("utf-8")
        iv = self.cmskey[-16:].encode("utf-8")
        original_text = text
        url_prefix = "lvdou+"

        if original_text.startswith(url_prefix):
            ciphertext_b64 = original_text[len(url_prefix):]
            try:
                cipher = AES.new(key, AES.MODE_CBC, iv)
                ct_bytes = base64.b64decode(ciphertext_b64)
                pt_bytes = cipher.decrypt(ct_bytes)
                return unpad(pt_bytes, AES.block_size).decode('utf-8')
            except Exception:
                return original_text
        else:
            return original_text

    def raw_url(self, original_url):
        try:
            response = self.fetch(original_url, allow_redirects=False, stream=True, timeout=20)
            if 300 <= response.status_code < 400:
                redirect_location = response.headers.get('Location')
                if redirect_location:
                    real_url = urljoin(original_url, redirect_location)
                    return real_url
            return original_url
        except Exception:
            return original_url

    def check_paly_url(self, content):
        # 只认真正的媒体文件后缀;lyyytv.cn 的 /d/ 是伪直链,不能算直链
        pattern = r"https?://[^\s\"'<>]+\.(?:mp4|m3u8|flv|avi|mkv|ts|mov|wmv|webm)(?:\?[^\s\"'<>]*)?$"
        return bool(re.search(pattern, content.strip(), re.IGNORECASE))

    def getName(self):
        pass

    def localProxy(self, param):
        pass

    def isVideoFormat(self, url):
        pass

    def manualVideoCheck(self):
        pass

    def destroy(self):
        pass