import cheerio from 'assets://js/lib/cheerio.min.js';

const appConfig = {
    siteName: "剑云影视",
    siteUrl: "https://jianyunys.com"
};

const UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36";

async function init(ext) {
    console.log("初始化爬虫:", appConfig.siteName);
}

const classList = [
    { type_id: "dianying",  type_name: "电影" },
    { type_id: "lianxuju",  type_name: "连续剧" },
    { type_id: "dongman",   type_name: "动漫" },
    { type_id: "zongyi",    type_name: "综艺" }
];

const subClassConfig = {
    "dianying": [
        ["全部", ""], ["动作片", "dongzuopian"], ["喜剧片", "xijupian"], ["爱情片", "aiqingpian"],
        ["科幻片", "kehuanpian"], ["恐怖片", "kongbupian"], ["剧情片", "juqingpian"],
        ["战争片", "zhanzhengpian"], ["动画片", "donghuapian"], ["奇幻片", "qihuanpian"],
        ["悬疑片", "xuanyipian"], ["武侠片", "wuxiapian"], ["伦理片", "lunlipian"],
        ["惊悚片", "jingsongpian"], ["犯罪片", "fanzuipian"], ["其他片", "qitapian"]
    ],
    "lianxuju": [
        ["全部", ""], ["国产剧", "guochanju"], ["港台剧", "gangtaiju"], ["日韩剧", "rihanju"],
        ["欧美剧", "oumeiju"], ["短剧", "duanju"], ["其他剧", "qitaju"]
    ],
    "dongman": [["全部", ""]],
    "zongyi":  [["全部", ""]]
};

const LANG_FILTER = [["全部", ""], ["国语", "国语"], ["英语", "英语"], ["粤语", "粤语"],
    ["闽南语", "闽南语"], ["韩语", "韩语"], ["日语", "日语"], ["法语", "法语"],
    ["德语", "德语"], ["其它", "其它"]];
const YEAR_FILTER = [["全部", ""], ["2026", "2026"], ["2025", "2025"], ["2024", "2024"],
    ["2023", "2023"], ["2022", "2022"], ["2021", "2021"], ["2020", "2020"],
    ["2019", "2019"], ["2018", "2018"], ["2017", "2017"], ["2016", "2016"],
    ["2015", "2015"], ["2014", "2014"]];
const SORT_FILTER = [["最新", "time"], ["最热", "hits"], ["评分", "score"]];

function toFilterObj(arr) { return arr.map(g => ({ "n": g[0], "v": g[1] })); }

function buildFilters(tid) {
    const subs = subClassConfig[tid] || [["全部", ""]];
    return [
        { "key": "class", "name": "类型", "value": toFilterObj(subs) },
        { "key": "lang", "name": "语言", "value": toFilterObj(LANG_FILTER) },
        { "key": "year", "name": "年份", "value": toFilterObj(YEAR_FILTER) },
        { "key": "by", "name": "排序", "value": toFilterObj(SORT_FILTER) }
    ];
}
const myFilters = {};
classList.forEach(item => { myFilters[item.type_id] = buildFilters(item.type_id); });

function buildCategoryUrl(tid, pg, extend) {
    extend = extend || {};
    pg = pg || 1;
    const typeId = extend.class || tid;
    const by = extend.by || "";
    const lang = extend.lang ? encodeURIComponent(extend.lang) : "";
    const year = extend.year || "";
    const segs = [typeId, "", by, "", lang, "", "", "", String(pg), "", "", year];
    return appConfig.siteUrl + '/vodshow/' + segs.join('-') + '.html';
}

async function httpGet(url, referer) {
    const headers = {
        "User-Agent": UA,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "zh-CN,zh;q=0.9",
        "Accept-Encoding": "identity",
        "Referer": referer || (appConfig.siteUrl + '/')
    };
    for (let attempt = 0; attempt < 3; attempt++) {
        try {
            const resp = await req(url, { method: "GET", headers: headers });
            let content = resp.content || '';
            if (typeof content !== 'string') content = String(content || '');
            if (content.length > 200) return content;
            await new Promise(r => setTimeout(r, 500));
        } catch (e) {
            console.error("请求失败[" + attempt + "]:", e.message);
            await new Promise(r => setTimeout(r, 800));
        }
    }
    return '';
}

function normalizePic(src) {
    if (!src) return '';
    if (src.startsWith('//')) return 'https:' + src;
    if (src.startsWith('http')) return src;
    if (src.startsWith('/')) return appConfig.siteUrl + src;
    return appConfig.siteUrl + '/' + src.replace(/^\.?\//, '');
}

function parseListHtml(html) {
    const $ = cheerio.load(html);
    const list = [];
    const seen = {};

    $('.hl-list-item').each(function () {
        const card = $(this);
        const thumb = card.find('.hl-item-thumb').first();
        let href = thumb.attr('href') || '';
        if (!href || href.indexOf('voddetail') === -1) return;
        const m = href.match(/voddetail\/(\d+)\.html/);
        if (!m) return;
        const vod_id = 'voddetail/' + m[1] + '.html';
        if (seen[vod_id]) return;

        let vod_name = (thumb.attr('title') || '').trim();
        if (!vod_name) {
            const titleA = card.find('.hl-item-title a').first();
            vod_name = (titleA.attr('title') || titleA.text() || '').trim();
        }
        if (!vod_name) return;

        let vod_pic = thumb.attr('data-original') || '';
        if (!vod_pic) vod_pic = thumb.attr('data-src') || '';
        if (!vod_pic) vod_pic = thumb.find('img').attr('src') || '';
        vod_pic = normalizePic(vod_pic);

        let vod_remarks = card.find('.hl-pic-text .remarks').first().text().trim()
            || card.find('.remarks').first().text().trim();

        seen[vod_id] = true;
        list.push({ vod_id, vod_name, vod_pic, vod_remarks });
    });

    let maxPage = 0;
    $('a').each(function () {
        const href = $(this).attr('href') || '';
        const isSearch = href.indexOf('vodsearch') !== -1;
        const isCategory = href.indexOf('vodshow') !== -1;
        if (!isSearch && !isCategory) return;
        const segs = href.split('?')[0].replace(/\.html$/, '').split('-');
        if (isCategory && segs.length !== 12) return;
        if (isSearch && segs.length !== 14) return;
        const pIdx = isSearch ? 11 : 8;
        const p = parseInt(segs[pIdx]);
        if (!isNaN(p) && p > maxPage) maxPage = p;
    });
    let pagecount = maxPage > 0 ? maxPage : (list.length > 0 ? 1 : 0);
    return { list, pagecount };
}

async function home(filter) {
    let list = [];
    try {
        const html = await httpGet(appConfig.siteUrl + '/');
        list = parseListHtml(html).list.slice(0, 30);
    } catch (e) {
        console.error("首页获取失败:", e.message);
    }
    return JSON.stringify({ class: classList, filters: myFilters, list: list });
}

async function category(tid, pg, filter, extend) {
    pg = pg || 1;
    extend = extend || {};
    try {
        const url = buildCategoryUrl(tid, pg, extend);
        const html = await httpGet(url);
        const result = parseListHtml(html);
        return JSON.stringify({ list: result.list, pagecount: result.pagecount });
    } catch (e) {
        console.error("分类列表获取失败:", e.message);
        return JSON.stringify({ list: [], pagecount: 0 });
    }
}

async function search(wd, quick, page) {
    page = page || 1;
    try {
        const kw = String(wd || '').trim();
        if (!kw) return JSON.stringify({ list: [], pagecount: 0 });
        const enc = encodeURIComponent(kw);
        const url = appConfig.siteUrl + '/vodsearch/' + enc + '----------' + page + '---.html';
        const html = await httpGet(url);
        const result = parseListHtml(html);
        return JSON.stringify({ list: result.list, pagecount: result.pagecount });
    } catch (e) {
        console.error("搜索失败:", e.message);
        return JSON.stringify({ list: [], pagecount: 0 });
    }
}

async function detail(id) {
    try {
        let detailUrl = id.startsWith('http') ? id : (appConfig.siteUrl + '/' + id.replace(/^\/+/, ''));
        if (!detailUrl.includes('/voddetail/')) {
            const m = id.match(/(\d+)/);
            if (m) detailUrl = appConfig.siteUrl + '/voddetail/' + m[1] + '.html';
        }
        const html = await httpGet(detailUrl);
        const $ = cheerio.load(html);

        let vod_name = $('.hl-dc-title').first().text().trim();
        if (!vod_name) vod_name = $('h1, h2').first().text().trim();
        if (!vod_name) {
            const t = $('title').text().trim();
            vod_name = t.replace(/[-_—《》].*$/, '').trim();
        }
        vod_name = vod_name.replace(/^《|》$/g, '').trim();

        let vod_pic = '';
        const dcThumb = $('.hl-dc-pic .hl-item-thumb').first();
        vod_pic = dcThumb.attr('data-original') || dcThumb.attr('data-src') || '';
        if (!vod_pic) {
            vod_pic = $('.hl-item-pic .hl-item-thumb').first().attr('data-original') || '';
        }
        if (!vod_pic) {
            vod_pic = $('meta[property="og:image"]').attr('content') || '';
        }
        vod_pic = normalizePic(vod_pic);

        let vod_director = '', vod_actor = '', vod_class = '', vod_area = '',
            vod_lang = '', vod_year = '', vod_remarks = '', vod_content = '';
        $('.hl-vod-data li').each(function () {
            const li = $(this);
            const key = li.find('em').first().text().trim().replace(/[:：]/, '');
            if (!key) return;
            const valA = [];
            li.find('a').each(function () {
                const t = $(this).text().trim();
                if (t) valA.push(t);
            });
            const valText = li.clone().find('em').remove().end().text().trim().replace(/^[:：]\s*/, '');
            const val = valA.length > 0 ? valA.join('/') : valText;

            if (key.indexOf('状态') !== -1 || key.indexOf('备注') !== -1) vod_remarks = val;
            else if (key.indexOf('主演') !== -1 || key.indexOf('演员') !== -1) vod_actor = val;
            else if (key.indexOf('导演') !== -1) vod_director = val;
            else if (key.indexOf('类型') !== -1) vod_class = val;
            else if (key.indexOf('地区') !== -1 || key.indexOf('国家') !== -1) vod_area = val.replace(/[\[\]【】]/g, '');
            else if (key.indexOf('语言') !== -1) vod_lang = val;
            else if (key.indexOf('年份') !== -1 || key.indexOf('首映') !== -1 || key.indexOf('上映') !== -1) {
                const ym = val.match(/(\d{4})/);
                if (ym) vod_year = ym[1];
            }
            else if (key.indexOf('简介') !== -1) vod_content = val;
        });

        if (!vod_content) {
            vod_content = $('.hl-content-text, .hl-full-content, .blurb').first().text().trim();
        }
        if (vod_content) vod_content = vod_content.substring(0, 500);

        const playlistBox = $('#playlist');
        const lines = [];
        const playlists = [];
        const sourceNames = [];
        playlistBox.find('.hl-plays-from .hl-tabs-btn').each(function () {
            const name = $(this).attr('alt') || $(this).text().trim();
            if (name) sourceNames.push(name);
        });

        playlistBox.find('.hl-tabs-box').each(function (idx) {
            const box = $(this);
            const epList = [];
            box.find('.hl-plays-list a').each(function () {
                const ep = $(this);
                const epName = ep.text().trim();
                let epUrl = ep.attr('href') || '';
                if (!epUrl) return;
                if (epName === '立即播放' || epName.indexOf('立即播放') !== -1) return;
                if (epUrl.indexOf('vodplay') === -1) return;
                if (!epUrl.startsWith('http')) epUrl = appConfig.siteUrl + '/' + epUrl.replace(/^\/+/, '');
                if (epName && epUrl) epList.push(epName + '$' + epUrl);
            });
            if (epList.length > 0) {
                lines.push(sourceNames[idx] || ('线路' + (idx + 1)));
                playlists.push(epList);
            }
        });

        if (lines.length === 0) {
            playlistBox.find('.hl-plays-list').each(function (idx) {
                const epList = [];
                $(this).find('a').each(function () {
                    const ep = $(this);
                    const epName = ep.text().trim();
                    let epUrl = ep.attr('href') || '';
                    if (!epUrl || epName === '立即播放' || epName.indexOf('立即播放') !== -1) return;
                    if (epUrl.indexOf('vodplay') === -1) return;
                    if (!epUrl.startsWith('http')) epUrl = appConfig.siteUrl + '/' + epUrl.replace(/^\/+/, '');
                    if (epName && epUrl) epList.push(epName + '$' + epUrl);
                });
                if (epList.length > 0) {
                    lines.push(sourceNames[idx] || ('线路' + (idx + 1)));
                    playlists.push(epList);
                }
            });
        }

        if (lines.length === 0) {
            lines.push('默认线路');
            playlists.push(['暂无播放地址$' + id]);
        }

        const OFFICIAL_KEYWORDS = ['爱奇艺', 'bilibili', 'b站', '芒果', '腾讯', '优酷', 'qiyi', 'qq', 'youku', 'mgtv'];
        function isOfficialLine(name) {
            const lower = (name || '').toLowerCase();
            return OFFICIAL_KEYWORDS.some(k => lower.indexOf(k.toLowerCase()) !== -1);
        }
        const order = lines.map((_, i) => i);
        order.sort((a, b) => {
            const aOff = isOfficialLine(lines[a]) ? 1 : 0;
            const bOff = isOfficialLine(lines[b]) ? 1 : 0;
            return aOff - bOff;
        });
        const sortedLines = order.map(i => lines[i]);
        const sortedPlaylists = order.map(i => playlists[i]);

        const vod_play_from = sortedLines.join('$$$');
        const vod_play_url = sortedPlaylists.map(eps => eps.join('#')).join('$$$');

        return JSON.stringify({
            list: [{
                vod_id: id, vod_name, vod_pic, vod_actor, vod_director,
                vod_remarks, vod_year, vod_area, vod_lang, vod_content, vod_class,
                vod_play_from, vod_play_url
            }]
        });
    } catch (error) {
        console.error("解析详情异常:", error);
        return JSON.stringify({ list: [] });
    }
}

const PARSE_MAP = {
    "qiyi": "https://jx.xmflv.com/?url=",
    "qq": "https://jx.xmflv.com/?url=",
    "mgtv": "https://jx.xmflv.com/?url=",
    "youku": "https://jx.xmflv.com/?url=",
    "bilibili": "https://jx.xmflv.com/?url=",
    "ffm3u8": "",
    "jsm3u8": "",
    "YYNB": "https://jx.xmflv.com/?url="
};
const DEFAULT_PARSER = "https://jx.xmflv.com/?url=";

async function play(flag, id, flags) {
    try {
        let playUrl = id;
        if (playUrl.includes('.m3u8') || playUrl.includes('.mp4')) {
            return JSON.stringify({ parse: 0, Header: { "User-Agent": UA, "Referer": appConfig.siteUrl + '/' }, url: playUrl });
        }
        let playPageUrl = playUrl.startsWith('http') ? playUrl : (appConfig.siteUrl + '/' + playUrl.replace(/^\/+/, ''));
        const html = await httpGet(playPageUrl);

        let realUrl = '';
        let playerFrom = '';
        let encrypt = 0;
        const m = html.match(/var\s+player_aaaa\s*=\s*(\{[\s\S]*?\})\s*<\/?script/);
        if (m) {
            try {
                const player = JSON.parse(m[1]);
                realUrl = player.url || '';
                playerFrom = player.from || '';
                encrypt = player.encrypt || 0;
            } catch (e) {
                console.error("解析 player_aaaa 失败:", e.message);
            }
        }

        if (realUrl && (realUrl.includes('.m3u8') || realUrl.includes('.mp4'))) {
            return JSON.stringify({ parse: 0, Header: { "User-Agent": UA, "Referer": appConfig.siteUrl + '/' }, url: realUrl });
        }

        if (realUrl) {
            const parser = PARSE_MAP[playerFrom] || DEFAULT_PARSER;
            if (parser) {
                const parseUrl = parser + encodeURIComponent(realUrl);
                return JSON.stringify({
                    parse: 1,
                    Header: { "User-Agent": UA, "Referer": appConfig.siteUrl + '/' },
                    url: parseUrl
                });
            }
            return JSON.stringify({
                parse: 1,
                Header: { "User-Agent": UA, "Referer": appConfig.siteUrl + '/' },
                url: playPageUrl
            });
        }

        const m3u8 = html.match(/(https?:\/\/[^\s"'<>]+\.m3u8[^\s"'<>]*)/);
        if (m3u8) {
            return JSON.stringify({ parse: 0, Header: { "User-Agent": UA, "Referer": appConfig.siteUrl + '/' }, url: m3u8[1] });
        }

        return JSON.stringify({ parse: 1, Header: { "User-Agent": UA, "Referer": appConfig.siteUrl + '/' }, url: playPageUrl });
    } catch (e) {
        console.error("播放失败:", e);
        return JSON.stringify({ parse: 0, url: "" });
    }
}

export default { init, home, category, detail, search, play };
