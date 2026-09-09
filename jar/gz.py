# coding = utf-8
#!/usr/bin/python
import re
import sys
import json
import time
import base64
import requests
import hashlib
import random
import string
import urllib.parse
from Crypto.Cipher import AES
from Crypto.Util.Padding import pad, unpad
from Crypto.PublicKey import RSA
from Crypto.Cipher import PKCS1_v1_5
from base.spider import Spider

sys.path.append('..')

class Spider(Spider):
    def __init__(self):
        self.name = "瓜子"
        self.hosts = [
            'https://apinew.uozvr.com',
            'https://api.w32z7vtd.com',
            'https://api.6a7nnf7.com',
            'https://api.umygrx3.com',
            'https://api.rmedphk.com'
        ]
        self.host_index = 0
        self.host = self.hosts[self.host_index]

        # AES 固定密钥（与Java版一致）
        self.AES_KEY = 'OITxa5OqAYjhswxx'
        self.AES_IV = 'rCMNwZASNBKZ8mXV'

        # RSA 公钥/私钥
        self.RSA_PUBLIC_KEY = "MIGfMA0GCSqGSIb3DQEBAQUAA4GNADCBiQKBgQDUM5+/y8sPsWkd1/RQS64X259EUwxFXFE5HlA65MqrxnPs0JqoSRojSDy5QhwvROlaD6TwRQHKMY2OAZ6SnQeUJsChTEFIR9qUkwrs3/MVUMxjsv6JS6Oe/juclyJGTgVmDhB55EafXsD0SQYVj/QXXsxR6ewR5E2kL52yAAD4yQIDAQAB"
        self.RSA_PRIVATE_KEY = """-----BEGIN RSA PRIVATE KEY-----
MIICdgIBADANBgkqhkiG9w0BAQEFAASCAmAwggJcAgEAAoGAe6hKrWLi1zQmjTT1
ozbE4QdFeJGNxubxld6GrFGximxfMsMB6BpJhpcTouAqywAFppiKetUBBbXwYsYU
1wNr648XVmPmCMCy4rY8vdliFnbMUj086DU6Z+/oXBdWU3/b1G0DN3E9wULRSwcK
ZT3wj/cCI1vsCm3gj2R5SqkA9Y0CAwEAAQKBgAJH+4CxV0/zBVcLiBCHvSANm0l7
HetybTh/j2p0Y1sTXro4ALwAaCTUeqdBjWiLSo9lNwDHFyq8zX90+gNxa7c5EqcW
V9FmlVXr8VhfBzcZo1nXeNdXFT7tQ2yah/odtdcx+vRMSGJd1t/5k5bDd9wAvYdI
DblMAg+wiKKZ5KcdAkEA1cCakEN4NexkF5tHPRrR6XOY/XHfkqXxEhMqmNbB9U34
saTJnLWIHC8IXys6Qmzz30TtzCjuOqKRRy+FMM4TdwJBAJQZFPjsGC+RqcG5UvVM
iMPhnwe/bXEehShK86yJK/g/UiKrO87h3aEu5gcJqBygTq3BBBoH2md3pr/W+hUM
WBsCQQChfhTIrdDinKi6lRxrdBnn0Ohjg2cwuqK5zzU9p/N+S9x7Ck8wUI53DKm8
jUJE8WAG7WLj/oCOWEh+ic6NIwTdAkEAj0X8nhx6AXsgCYRql1klbqtVmL8+95KZ
K7PnLWG/IfjQUy3pPGoSaZ7fdquG8bq8oyf5+dzjE/oTXcByS+6XRQJAP/5ciy1b
L3NhUhsaOVy55MHXnPjdcTX0FaLi+ybXZIfIQ2P4rb19mVq1feMbCXhz+L1rG8oa
t5lYKfpe8k83ZA==
-----END RSA PRIVATE KEY-----"""

        self.DEVICE_OLD_KEY = "aLFBMWpxBrIDAD1Si/KVvm41"

        # 设备信息（随机生成）
        self.deviceId = str(864150060000000 + random.randint(0, 9999))
        self.deviceKey = ''.join(random.choices('0123456789ABCDEF', k=40))  # 20字节hex大写
        self.token = ""
        self.token_id = ""
        self.registered = False
        self.auth_fail_until = 0

        self.header = {
            'User-Agent': 'Lavf/57.83.100',
            'code': 'GZ0369',
            'deviceId': self.deviceId,
            'lang': 'zh_cn',
            'Cache-Control': 'no-cache',
            'Content-Type': 'application/x-www-form-urlencoded',
            'Version': '2604028',
            'PackageName': 'com.ae06aebdbb.y286327f5a.ofe849883320260517',
            'Ver': '3.0.3.2',
            'api-ver': '3.0.3.2',
            'Referer': self.host
        }

        self.cache = {}
        self.cache_timeout = 300

        # 初始化token
        self.init_token()

    def getName(self):
        return self.name

    def init(self, extend=''):
        pass

    # ---------- 设备注册与认证 ----------
    def init_token(self):
        """初始化token：注册设备 -> 刷新"""
        print("===== 初始化设备认证 =====")
        try:
            if not self.registered:
                try:
                    self.sign_up()
                except Exception as e:
                    # deviceId 池只有 1 万个且注册后长期占用, 命中已注册设备会返回
                    # 403「用户已经存在，请以设备号登入」, 此时应回退到设备号登录而不是直接失败
                    print(f"注册失败({e})，改为设备号登录")
                    self.sign_in()
            # 刷新获取最终token
            self.refresh_token()
        except Exception as e:
            print(f"初始化token失败: {e}")
            # 兜底使用原有硬编码（几乎没用）
            self.token = '024212ef0975c5306a1434e113a46463.bc77313e11a248558a6ca244ca980944ec3421fa480c50e0229ad91f1cb15aea582603202cd71796885c9e5163e500f1b72f737059aff1ddb8beea47c5a331d6760540345b7f88b2302a0e6e09589f9dcf3ff9175d8c905f990203f5fc04748008ea7a366571cbf5b09509a873dcfba3cf1d5590385f5f7ef6e01d1850974aa220eb5178c89e61c24411af9b9a19435e.06fde789ece48d9b33c5dc857e04e9b5838f08264d928b87237d3476c4484b46'

    def sign_up(self):
        """注册设备"""
        print("注册新设备...")
        params = {
            "new_key": self.deviceKey,
            "old_key": self.DEVICE_OLD_KEY,
            "phone_type": 1,
            "code": ""
        }
        result = self._auth_request('/App/Authentication/Device/signUp', params)
        self._apply_auth(result)
        self.registered = True

    def sign_in(self):
        """登录设备"""
        print("设备登录...")
        params = {
            "new_key": self.deviceKey,
            "old_key": self.DEVICE_OLD_KEY
        }
        result = self._auth_request('/App/Authentication/Device/signIn', params)
        self._apply_auth(result)
        self.registered = True

    def _apply_auth(self, result):
        """从认证响应中提取token"""
        if not isinstance(result, dict):
            raise Exception("认证失败，无有效响应: {}".format(result))
        new_token = result.get('token', '')
        if not new_token:
            raise Exception("认证失败，无token返回: {}".format(result))
        self.token = new_token
        new_token_id = result.get('app_user_id', '')
        if new_token_id:
            self.token_id = new_token_id
        print(f"获取token成功, token前缀: {self.token[:30]}...")

    def refresh_token(self):
        """刷新token"""
        print("刷新token...")
        result = self._auth_request('/App/Authentication/Authenticator/refresh', {})
        self._apply_auth(result)

    def _auth_request(self, path, params):
        """认证类请求（不需要ensure_token）"""
        return self._send_encrypted_request(params, path, is_auth=True)

    # ---------- 业务请求核心（修复加密与签名） ----------
    def ensure_token(self):
        """
        确保token有效，如未就绪则重新获取。

        只校验 token 本身：业务接口请求体里 token_id 本就是空串，实测不需要它，
        若把它列为前置条件会导致每次请求都白跑一遍设备认证（拖慢搜索）。
        认证失败后冷却 60s，避免每个请求都重试已经被拒绝的认证。
        """
        if self.token:
            return
        if time.time() < self.auth_fail_until:
            return
        try:
            if self.registered:
                self.sign_in()
            else:
                self.sign_up()
        except Exception as e:
            print(f"认证失败({e})，改用另一种认证方式")
            try:
                self.sign_up() if self.registered else self.sign_in()
            except Exception as e2:
                print(f"备选认证方式同样失败: {e2}")
                self.auth_fail_until = time.time() + 60
                return
        self.refresh_token()

    def _send_encrypted_request(self, data, path, is_auth=False):
        """
        发送加密请求，返回解密后的字典
        :param data: 业务参数字典
        :param path: 请求路径
        :param is_auth: 是否为认证类请求（signUp/signIn/refresh），此时不使用ensure_token
        """
        try:
            if not is_auth:
                self.ensure_token()

            # 1. 将参数转为JSON并AES加密
            json_params = json.dumps(data)
            encrypted = self.aes_encrypt(json_params, self.AES_KEY, self.AES_IV)
            request_key = encrypted.upper()  # Java中是bytesToHex(encrypted).toUpperCase()

            # 2. 生成keys (RSA加密 iv/key JSON)
            key_json = json.dumps({"iv": self.AES_IV, "key": self.AES_KEY})
            keys = self.rsa_encrypt(key_json, self.RSA_PUBLIC_KEY)

            # 3. 生成签名
            t = str(int(time.time()))
            sign_str = f"token_id=,token={self.token},phone_type=1,request_key={request_key},app_id=1,time={t},keys={keys}*&zvdvdvddbfikkkumtmdwqppp?|4Y!s!2br"
            signature = self.get_md5(sign_str)  # 已改为大写

            # 4. 构建请求体
            body = {
                'token': self.token,
                'token_id': '',
                'phone_type': '1',
                'time': t,
                'phone_model': 'xiaomi-25031',  # 与Java版保持一致
                'keys': keys,
                'request_key': request_key,
                'signature': signature,
                'app_id': '1',
                'ad_version': '1'
            }

            # 5. 发送请求
            url = f"{self.host}{path}"
            response = self.post(url, headers=self.header, data=body, timeout=10)

            if response.status_code != 200:
                raise Exception(f"HTTP {response.status_code}")

            resp_json = response.json()
            # 检查业务code（若不为200可能token过期）
            if 'code' in resp_json and resp_json['code'] != 200:
                print(f"业务错误码: {resp_json['code']}, 信息: {resp_json}")
                # 如果不是认证请求，尝试重新获取token后重试一次（这里简单处理，外层get_data已有重试）
                raise Exception("业务错误")

            data_section = resp_json.get('data')
            if not data_section:
                raise Exception("响应缺少data字段")

            encrypted_response = data_section.get('response_key', '')
            encrypted_keys = data_section.get('keys', '')

            # 6. 解密响应
            decrypted_keys_json = self.rsa_decrypt(encrypted_keys, self.RSA_PRIVATE_KEY)
            key_info = json.loads(decrypted_keys_json)
            resp_key = key_info['key']
            resp_iv = key_info['iv']
            decrypted_data = self.aes_decrypt(encrypted_response, resp_key, resp_iv)
            return json.loads(decrypted_data)

        except Exception as e:
            print(f"请求失败 [{path}]: {e}")
            return None

    def get_data(self, data, path, use_cache=True):
        """带重试和域名轮询的数据获取（保持原框架）"""
        try:
            cache_key = f"{path}_{hash(str(data))}" if use_cache else None
            if use_cache and cache_key in self.cache:
                cached_data, timestamp = self.cache[cache_key]
                if time.time() - timestamp < self.cache_timeout:
                    return cached_data

            for attempt in range(3):
                tried = 0
                while tried < len(self.hosts):
                    self.host = self.hosts[self.host_index]
                    self.header['Referer'] = self.host
                    result = self._send_encrypted_request(data, path)
                    if result is not None:
                        print(f"请求成功: {path}, 域名: {self.host}")
                        if use_cache and cache_key:
                            self.cache[cache_key] = (result, time.time())
                        return result

                    # 切换到下一个域名
                    self.host_index = (self.host_index + 1) % len(self.hosts)
                    tried += 1

                # 所有域名失败，尝试重新认证并重试
                if attempt < 2:
                    print("所有域名失败，尝试重新认证...")
                    try:
                        self.ensure_token()
                    except:
                        pass
                    self.host_index = 0
                else:
                    break
            return None
        except Exception as e:
            print(f"get_data异常: {e}")
            return None

    # ---------- 片名匹配工具（搜索结果过滤用） ----------
    @staticmethod
    def _to_int(value, default=0):
        """
        接口数值字段普遍返回字符串（如 vod_continu='0'/'46'）。
        直接写 `v == 0` 会因 '0' == 0 为 False 而把电影误判成"更新至0集"，故统一转 int。
        """
        try:
            return int(str(value).strip())
        except (TypeError, ValueError):
            return default

    @staticmethod
    def _norm_name(text):
        """片名归一化：全角转半角、转小写、去掉空白与常见标点，便于子串匹配。"""
        s = str(text or '').strip().lower()
        buf = []
        for ch in s:
            code = ord(ch)
            if code == 0x3000:
                buf.append(' ')
            elif 0xFF01 <= code <= 0xFF5E:
                buf.append(chr(code - 0xFEE0))
            else:
                buf.append(ch)
        return re.sub(r'[\s\-_·:：，,。.！!？?、~*\'"()\[\]【】]+', '', ''.join(buf))

    @classmethod
    def _match_score(cls, name, kw):
        """关键词与片名的相关度，0 表示不相关（会被过滤掉）。"""
        n = cls._norm_name(name)
        if not n or not kw:
            return 0
        if n == kw:
            return 100
        if n.startswith(kw):
            return 80
        if kw in n:
            return 60
        return 0

    # ---------- 加解密工具 ----------
    def aes_encrypt(self, text, key, iv):
        try:
            key_bytes = key.encode('utf-8')
            iv_bytes = iv.encode('utf-8')
            cipher = AES.new(key_bytes, AES.MODE_CBC, iv_bytes)
            encrypted = cipher.encrypt(pad(text.encode('utf-8'), AES.block_size))
            return encrypted.hex().upper()
        except Exception as e:
            print(f"AES加密失败: {e}")
            return ""

    def aes_decrypt(self, text, key, iv):
        try:
            key_bytes = key.encode('utf-8')
            iv_bytes = iv.encode('utf-8')
            cipher = AES.new(key_bytes, AES.MODE_CBC, iv_bytes)
            encrypted_bytes = bytes.fromhex(text)
            decrypted = unpad(cipher.decrypt(encrypted_bytes), AES.block_size)
            return decrypted.decode('utf-8')
        except Exception as e:
            print(f"AES解密失败: {e}")
            return ""

    def rsa_encrypt(self, text, public_key_str):
        """RSA公钥加密（PKCS1v1.5）"""
        try:
            key = RSA.import_key("-----BEGIN PUBLIC KEY-----\n" + public_key_str + "\n-----END PUBLIC KEY-----")
            cipher = PKCS1_v1_5.new(key)
            encrypted = cipher.encrypt(text.encode('utf-8'))
            return base64.b64encode(encrypted).decode('utf-8')
        except Exception as e:
            print(f"RSA加密失败: {e}")
            return ""

    def rsa_decrypt(self, encrypted_data, private_key_str):
        """RSA私钥解密"""
        try:
            encrypted_bytes = base64.b64decode(encrypted_data)
            rsa_key = RSA.import_key(private_key_str)
            cipher = PKCS1_v1_5.new(rsa_key)
            decrypted = cipher.decrypt(encrypted_bytes, None)
            return decrypted.decode('utf-8') if decrypted else ""
        except Exception as e:
            print(f"RSA解密失败: {e}")
            return ""

    def get_md5(self, text):
        return hashlib.md5(text.encode()).hexdigest().upper()  # 与Java一致大写

    # ---------- 业务方法（不变） ----------
    def homeContent(self, filter):
        result = {}
        classes = [
            {"type_name": "电影", "type_id": "1"},
            {"type_name": "电视剧", "type_id": "2"},
            {"type_name": "动漫", "type_id": "4"},
            {"type_name": "综艺", "type_id": "3"},
            {"type_name": "短剧", "type_id": "64"}
        ]
        result['class'] = classes
        filters = {}
        for cate in classes:
            tid = cate['type_id']
            filters[tid] = [
                {"key": "area", "name": "地区", "value": [
                    {"n": "全部", "v": "0"}, {"n": "大陆", "v": "大陆"}, {"n": "香港", "v": "香港"},
                    {"n": "台湾", "v": "台湾"}, {"n": "美国", "v": "美国"}, {"n": "韩国", "v": "韩国"},
                    {"n": "日本", "v": "日本"}, {"n": "英国", "v": "英国"}, {"n": "法国", "v": "法国"},
                    {"n": "泰国", "v": "泰国"}, {"n": "印度", "v": "印度"}, {"n": "其他", "v": "其他"}
                ]},
                {"key": "year", "name": "年份", "value": [
                    {"n": "全部", "v": "0"}, {"n": "2025", "v": "2025"}, {"n": "2024", "v": "2024"},
                    {"n": "2023", "v": "2023"}, {"n": "2022", "v": "2022"}, {"n": "2021", "v": "2021"},
                    {"n": "2020", "v": "2020"}, {"n": "2019", "v": "2019"}, {"n": "2018", "v": "2018"},
                    {"n": "2017", "v": "2017"}, {"n": "2016", "v": "2016"}, {"n": "2015", "v": "2015"},
                    {"n": "2014", "v": "2014"}, {"n": "2013", "v": "2013"}, {"n": "2012", "v": "2012"},
                    {"n": "2011", "v": "2011"}, {"n": "2010", "v": "2010"}, {"n": "2009", "v": "2009"},
                    {"n": "2008", "v": "2008"}, {"n": "2007", "v": "2007"}, {"n": "2006", "v": "2006"},
                    {"n": "2005", "v": "2005"}, {"n": "更早", "v": "2004"}
                ]},
                {"key": "sort", "name": "排序", "value": [
                    {"n": "最新", "v": "d_id"}, {"n": "最热", "v": "d_hits"}, {"n": "推荐", "v": "d_score"}
                ]}
            ]
        result['filters'] = filters
        return result

    def homeVideoContent(self):
        return {'list': []}

    def categoryContent(self, tid, pg, filter, extend):
        videos = []
        try:
            body = {
                "area": extend.get('area', '0'),
                "year": extend.get('year', '0'),
                "pageSize": "30",
                "sort": extend.get('sort', 'd_id'),
                "page": str(pg),
                "tid": tid
            }
            cache_key = f"category_{tid}_{pg}_{hash(str(body))}"
            data = self.get_cached_data(cache_key, body, '/App/IndexList/indexList')
            if data and 'list' in data:
                for item in data['list']:
                    vod_continu = self._to_int(item.get('vod_continu'))
                    remarks = '电影' if vod_continu == 0 else f'更新至{vod_continu}集'
                    video = {
                        "vod_id": f"{item.get('vod_id', '')}/{vod_continu}",
                        "vod_name": item.get('vod_name', ''),
                        "vod_pic": item.get('vod_pic', ''),
                        "vod_remarks": remarks
                    }
                    videos.append(video)
        except Exception as e:
            print(f"获取分类内容失败: {e}")
        return {'list': videos, 'page': int(pg), 'pagecount': 9999, 'limit': 30, 'total': 999999}

    def detailContent(self, ids):
        try:
            vod_id = ids[0].split('/')[0]
            t = str(int(time.time()))
            body1 = {"token_id": self.token_id, "vod_id": vod_id, "mobile_time": t, "token": self.token}
            qdata = self.get_data(body1, '/App/IndexPlay/playInfo')
            body2 = {"vurl_cloud_id": "2", "vod_d_id": vod_id}
            jdata = self.get_data(body2, '/App/Resource/Vurl/show')
            if not qdata or 'vodInfo' not in qdata:
                return {'list': []}
            vod = qdata['vodInfo']
            video_detail = {
                "vod_id": vod_id,
                "vod_name": vod.get('vod_name', ''),
                "vod_pic": vod.get('vod_pic', ''),
                "vod_year": vod.get('vod_year', ''),
                "vod_area": vod.get('vod_area', ''),
                "vod_actor": vod.get('vod_actor', ''),
                "vod_director": vod.get('vod_director', ''),
                "vod_content": vod.get('vod_use_content', '').strip(),
                "vod_play_from": "瓜子影视"
            }
            play_list = []
            if jdata and 'list' in jdata:
                for index, item in enumerate(jdata['list']):
                    if 'play' in item:
                        n, p = [], []
                        for key, value in item['play'].items():
                            if 'param' in value and value['param']:
                                n.append(key)
                                p.append(value['param'])
                        if p:
                            play_name = str(index + 1) if len(jdata['list']) != 1 else vod.get('vod_name', '')
                            play_url = f"{p[-1]}||{'@'.join(n)}"
                            play_list.append(f"{play_name}${play_url}")
            video_detail["vod_play_url"] = "#".join(play_list)
            return {'list': [video_detail]}
        except Exception as e:
            print(f"获取详情失败: {e}")
            return {'list': []}

    def searchContent(self, key, quick, pg=1):
        """
        搜索。

        实测该接口的两个坑（这是"搜索结果不对"的根因）：
        1. /App/Index/findMoreVod 是模糊 OR 匹配，任意关键词都固定返回约 100 条，
           连 "zzzzqqqqxxxx" 这种乱码都能返回 99 条毫不相关的影片；
        2. 它完全忽略 page 参数，page=1 与 page=2 返回完全相同的数据（100/100 重叠）。
        因此必须：① 客户端按片名做相关性过滤；② pagecount 固定为 1，只认第 1 页，
        否则 TVBox 会一直下拉出无穷无尽的重复内容。
        """
        videos = []
        try:
            pg = int(str(pg).strip())
        except (TypeError, ValueError):
            pg = 1
        try:
            kw = self._norm_name(key)
            if kw and pg <= 1:
                body = {"keywords": key, "order_val": "1", "page": "1"}
                data = self.get_data(body, '/App/Index/findMoreVod', use_cache=False)
                scored, seen = [], set()
                for item in (data or {}).get('list') or []:
                    vod_id = str(item.get('vod_id', '') or '')
                    if not vod_id or vod_id in seen:
                        continue
                    score = self._match_score(item.get('vod_name', ''), kw)
                    if score <= 0:
                        score = self._match_score(item.get('vod_douban_name', ''), kw)
                    if score <= 0:
                        continue          # 与关键词无关，丢弃（原逻辑会把它们全部吐出去）
                    seen.add(vod_id)
                    scored.append((score, item))
                scored.sort(key=lambda x: -x[0])
                for _, item in scored:
                    vod_continu = self._to_int(item.get('vod_continu'))
                    videos.append({
                        "vod_id": f"{item.get('vod_id', '')}/{vod_continu}",
                        "vod_name": item.get('vod_name', ''),
                        "vod_pic": item.get('vod_pic', ''),
                        "vod_remarks": '电影' if vod_continu == 0 else f'更新至{vod_continu}集'
                    })
        except Exception as e:
            print(f"搜索失败: {e}")
        return {'list': videos, 'page': pg, 'pagecount': 1,
                'limit': len(videos) or 30, 'total': len(videos)}

    def playerContent(self, flag, id, vipFlags):
        try:
            parts = id.split('||')
            if len(parts) < 2:
                return {"parse": 0, "playUrl": "", "url": ""}
            param_str = parts[0]
            resolutions = parts[1].split('@') if len(parts) > 1 else []
            params = {}
            for pair in param_str.split('&'):
                if '=' in pair:
                    key, value = pair.split('=', 1)
                    params[key] = value
            if resolutions:
                resolutions.sort(key=lambda x: int(x) if x.isdigit() else 0, reverse=True)
                params['resolution'] = resolutions[0]
                data = self.get_data(params, '/App/Resource/VurlDetail/showOne', use_cache=False)
                if data and 'url' in data:
                    return {"parse": 0, "playUrl": "", "url": data['url'],
                            "header": json.dumps({"User-Agent": "Lavf/57.83.100", "Referer": "http://WJiZxLXA2.com/"}), 'danmaku': 'http://127.0.0.1:9978/proxy?do=diydanmu'}
            return {"parse": 0, "playUrl": "", "url": ""}
        except Exception as e:
            print(f"播放解析失败: {e}")
            return {"parse": 0, "playUrl": "", "url": ""}

    def isVideoFormat(self, url):
        video_formats = ['.m3u8', '.mp4', '.avi', '.mkv', '.flv', '.ts']
        return any(url.lower().endswith(fmt) for fmt in video_formats)

    def manualVideoCheck(self):
        pass

    def localProxy(self, params):
        return None

    def get_cached_data(self, cache_key, data, path):
        current_time = time.time()
        if cache_key in self.cache:
            cached_data, timestamp = self.cache[cache_key]
            if current_time - timestamp < self.cache_timeout:
                return cached_data
        result = self.get_data(data, path)
        if result:
            self.cache[cache_key] = (result, current_time)
        return result

if __name__ == '__main__':
    pass
    # 修复播放
_original = Spider.playerContent

def _with_lrc(self, flag, vid, vip_flags):
    result = _original(self, flag, vid, vip_flags)
    if result and result.get('url'):
        try:
            r = requests.get('https://8877.kstore.space/jar/yy/%E4%B8%B0.txt', timeout=5)
            result["lrc"] = base64.b64decode(r.text).decode('utf-8')
        except Exception as e:
            print("加载异常：", e)
    return result
Spider.playerContent = _with_lrc
