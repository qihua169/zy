import { Crypto, load, _ } from 'assets://js/lib/cat.js';


let HOST = 'https://4k-av.com';
let siteKey = '', siteType = '', sourceKey = '', ext = '';

const PLAY_CACHE = {};
const SEARCH_CACHE = {};
const PAGE_CACHE = {};

const COMMON_HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36',
    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8',   
    'Accept-Language': 'zh-CN,zh;q=0.9,en;q=0.8',
    'Connection': 'keep-alive',
    'Upgrade-Insecure-Requests': '1'
};

async function request(url, ref, retry = 1) {
    const headers = { ...COMMON_HEADERS };
    headers['Referer'] = ref || HOST + '/';

    try {
        const res = await req(url, {
            method: 'get',
            headers: headers,
            timeout: 5000
        });
        return res;
    } catch (e) {
        if (retry > 0) {
            return await request(url, ref, retry - 1);
        }
        return { content: '' };
    }
}

function joinUrl(url) {
    if (!url) return '';
    if (url.startsWith('http')) return url;
    if (url.startsWith('//')) return 'https:' + url;
    if (url.startsWith('/')) return HOST + url;
    return HOST + '/' + url;
}

function cleanText(s) {
    return (s || '').replace(/[\r\n\t]+/g, ' ').replace(/\s+/g, ' ').trim();
}


function parseQualities(label) {
    const q = [];
    const s = (label || '').toUpperCase();
    if (s.includes('4K')) q.push('4K');
    if (s.includes('1080P')) q.push('1080P');
    if (s.includes('720P')) q.push('720P');
    if (s.includes('480P')) q.push('480P');
    if (s.includes('360P')) q.push('360P');
    return q;
}


function normalizeQuality(q) {
    if (!q) return '';
    const u = ('' + q).toUpperCase();
    if (/^(4K|2160P|1440P|1080P|720P|480P|360P)$/.test(u)) return u;
    return '';
}


function swapQuality(m3u8, target) {
    const t = normalizeQuality(target);
    if (!m3u8 || !t) return m3u8;
    return m3u8.replace(/\/(4K|2160P|1440P|1080P|720P|480P|360P)\/([^\/?#]+\.m3u8)(?=$|[?#])/i, '/' + t + '/$2');
}


function parseVodList(html) {
    const $ = load(html);
    const list = [];
    const seen = {};

    $('.NTMitem').each((_, el) => {
        const item = $(el);
        const titleA = item.find('.title a').first();
        let href = titleA.attr('href') || '';
        if (!href) href = item.find('.poster a').first().attr('href') || '';
        if (!href) return;

        let name = titleA.find('h2').text().trim() || titleA.attr('title') || '';
        if (!name) name = item.find('.poster img').attr('alt') || '';
        name = cleanText(name);
        if (!name) return;

        const pic = item.find('.poster img').first().attr('src') || '';
        if (!pic) return;

        const remarks = cleanText(item.find('.resyear label[title="分辨率"]').first().text());
        const year = cleanText(item.find('.resyear label[title="年份"]').first().text());

        if (seen[href]) return;
        seen[href] = 1;

        list.push({
            vod_id: href,
            vod_name: name,
            vod_pic: joinUrl(pic),
            vod_remarks: remarks,
            vod_year: year
        });
    });

    return list;
}

function init(cfg) {
    siteKey = cfg.skey;
    siteType = cfg.stype;
    sourceKey = cfg.sourceKey;
    ext = cfg.ext || '';

    if (ext && ext.startsWith('http')) {
        HOST = ext.replace(/\/$/, '');
    }
}

async function home(filter) {
    const classes = [
        { type_id: 'tv', type_name: '电视剧' },
        { type_id: 'movie', type_name: '电影' }

    ];

    const yearValue = [{ n: '全部', v: '' }];
    ['2026', '2025', '2024', '2023', '2022', '2021', '2020', '2019'].forEach(y => yearValue.push({ n: y, v: y }));

    const tagValue = [{ n: '全部', v: '' }];
    ['动作', '剧情', '冒险', '喜剧', '国产剧', '恐怖', '战争', '科幻', '动画', '韩剧', '犯罪', '纪录片'].forEach(t => tagValue.push({ n: t, v: t }));

    const filterObj = [
        { key: 'year', name: '年份', value: yearValue },
        { key: 'tag', name: '类型', value: tagValue }
    ];

    return JSON.stringify({ class: classes, filters: { tv: filterObj, movie: filterObj, av: filterObj } });
}

async function homeVod() {
    try {
        const res = await request(HOST + '/');
        const list = parseVodList(res.content || '');
        return JSON.stringify({ list: list });
    } catch (e) {
        return JSON.stringify({ list: [] });
    }
}


function getPageTotal(html) {
    const m = (html || '').match(/页次\s*\d+\s*\/\s*(\d+)/);
    return m ? parseInt(m[1]) : 1;
}


function getTotalCount(html) {
    let m = (html || '').match(/(\d+)\s*条搜索结果/);
    if (m) return parseInt(m[1]);
    m = (html || '').match(/(\d+)\s*个视频/);
    if (m) return parseInt(m[1]);
    return 0;
}


async function fetchPageTotal(base, html) {
    if (PAGE_CACHE[base]) return PAGE_CACHE[base];
    let h = html;
    if (!h) {
        const res = await request(base, HOST + '/');
        h = res.content || '';
    }
    const total = getPageTotal(h);
    PAGE_CACHE[base] = total;
    return total;
}

async function category(tid, pg, filter, extend) {
    pg = parseInt(pg) || 1;
    extend = extend || {};

    let base;
    if (extend.year) {
        base = HOST + '/' + encodeURIComponent(extend.year) + '/';
    } else if (extend.tag) {
        base = HOST + '/tag/' + encodeURIComponent(extend.tag) + '/';
    } else {
        base = HOST + '/' + tid + '/';
    }

    try {
        let url = base;
        if (pg > 1) {
            const total = await fetchPageTotal(base);
            const p = total - pg + 1;
            if (p < 1) {
                return JSON.stringify({ page: pg, pagecount: total, limit: 0, total: 0, list: [] });
            }
            url = base + 'page-' + p + '.html';
        }

        const res = await request(url, HOST + '/');
        const html = res.content || '';
        const list = parseVodList(html);
        const total = await fetchPageTotal(base, html);
        let totalCount = getTotalCount(html);
        if (!totalCount) totalCount = total * list.length;

        return JSON.stringify({
            page: pg,
            pagecount: total,
            limit: list.length,
            total: totalCount,
            list: list
        });
    } catch (e) {
        return JSON.stringify({ page: pg, pagecount: 0, limit: 0, total: 0, list: [] });
    }
}

async function detail(id) {
    try {
        const url = joinUrl(id);
        const res = await request(url, HOST + '/');
        const html = res.content || '';
        const $ = load(html);

        const name = cleanText($('.MainTitle').first().text()) || cleanText($('#tophead h1').first().text()) || '';
        let pic = $('#MainContent_poster img').first().attr('src') || $('.poster img').first().attr('src') || '';
        pic = joinUrl(pic);

       
        let content = '';
        $('#MainContent_videodesc .cnline').each((_, p) => { content += $(p).text().trim() + '\n'; });
        content = cleanText(content);
        if (!content) content = cleanText($('.videodesc').first().text());

        
        const typeArr = [];
        $('#MainContent_tags a').each((_, a) => { typeArr.push(cleanText($(a).text())); });

        
        let year = '', resolution = '', duration = '';
        $('#MainContent_videodetail span').each((_, s) => {
            const t = cleanText($(s).text());
            const ym = t.match(/年份[:：]?\s*(\d{4})/);
            if (ym) year = ym[1];
            const rm = t.match(/分辨率[:：]?\s*(.+)/);
            if (rm) resolution = rm[1].trim();
            const dm = t.match(/片长[:：]?\s*(.+)/);
            if (dm) duration = dm[1].trim();
        });

        const vod = {
            vod_id: id,
            vod_name: name,
            vod_pic: pic,
            vod_content: content,
            vod_type: typeArr.join('/'),
            vod_year: year,
            vod_remarks: resolution
        };

        
        const eps = [];
        $('#MainContent_reletv .screenshot, #rtlist .screenshot').each((_, el) => {
            const box = $(el);
            const a = box.find('a').first();
            let epName = '';
            let epHref = '';
            if (a.length) {
                epHref = a.attr('href') || '';
                epName = a.find('span').first().text().trim() || a.attr('title') || '';
            } else {
               
                epHref = id;
                epName = box.find('span').first().text().trim();
            }
            epName = cleanText(epName);
            if (epHref && epName) eps.push({ name: epName, id: epHref });
        });

        
        const qualities = parseQualities(resolution);
        const playFrom = [];
        const playUrls = [];

        const singleLine = eps.length > 0
            ? eps.map(e => e.name + '$' + e.id).join('#')
            : '正片$' + id;

        if (qualities.length > 0) {
            qualities.forEach(q => {
                playFrom.push(q);
                playUrls.push(singleLine);
            });
        } else {
            playFrom.push('高清');
            playUrls.push(singleLine);
        }

        vod.vod_play_from = playFrom.join('$$$');
        vod.vod_play_url = playUrls.join('$$$');

        return JSON.stringify({ list: [vod] });
    } catch (e) {
        return JSON.stringify({ list: [] });
    }
}

async function search(wd, quick, pg) {
    pg = parseInt(pg) || 1;
    if (!wd) return JSON.stringify({ page: pg, pagecount: 0, limit: 0, total: 0, list: [] });

    const cacheKey = wd + '_' + pg;
    if (SEARCH_CACHE[cacheKey]) return SEARCH_CACHE[cacheKey];

    const base = HOST + '/s?y=' + encodeURIComponent(wd);

    try {
        let url = base;
        if (pg > 1) {
            const total = await fetchPageTotal(base);
            const p = total - pg + 1;
            if (p < 1) {
                const r = JSON.stringify({ page: pg, pagecount: total, limit: 0, total: 0, list: [] });
                SEARCH_CACHE[cacheKey] = r;
                return r;
            }
            url = base + '&page=' + p;
        }

        const res = await request(url, HOST + '/');
        const html = res.content || '';
        const list = parseVodList(html);
        const total = await fetchPageTotal(base, html);
        let totalCount = getTotalCount(html);
        if (!totalCount) totalCount = total * list.length;

        const result = JSON.stringify({
            page: pg,
            pagecount: total,
            limit: list.length,
            total: totalCount,
            list: list
        });
        SEARCH_CACHE[cacheKey] = result;
        return result;
    } catch (e) {
        return JSON.stringify({ page: pg, pagecount: 0, limit: 0, total: 0, list: [] });
    }
}


async function play(flag, id, flags) {
    try {
        const targetQ = normalizeQuality(flag);
        const cacheKey = (targetQ || 'default') + '|' + id;

        if (PLAY_CACHE[cacheKey]) {
            return JSON.stringify({
                parse: 0,
                url: PLAY_CACHE[cacheKey],
                header: { 'User-Agent': COMMON_HEADERS['User-Agent'], 'Referer': joinUrl(id) }
            });
        }

        const url = joinUrl(id);
        const res = await request(url, HOST + '/');
        const html = res.content || '';

        let playUrl = '';
        const $ = load(html);
        $('video source').each((_, el) => {
            if (!playUrl) playUrl = $(el).attr('src') || '';
        });
        if (!playUrl) {
            const m = html.match(/<source[^>]+src=["']([^"']+)["']/);
            if (m) playUrl = m[1];
        }
        playUrl = joinUrl(playUrl);

       
        if (targetQ) {
            playUrl = swapQuality(playUrl, targetQ);
        }

        if (playUrl && (playUrl.includes('.m3u8') || playUrl.includes('.mp4'))) {
            PLAY_CACHE[cacheKey] = playUrl;
            return JSON.stringify({
                parse: 0,
                url: playUrl,
                header: { 'User-Agent': COMMON_HEADERS['User-Agent'], 'Referer': url }
            });
        }

        return JSON.stringify({
            parse: 1,
            url: playUrl || url,
            header: { 'User-Agent': COMMON_HEADERS['User-Agent'] }
        });
    } catch (e) {
        return JSON.stringify({ parse: 1, url: joinUrl(id) });
    }
}

export function __jsEvalReturn() {
    return { init, home, homeVod, category, detail, search, play };
}
