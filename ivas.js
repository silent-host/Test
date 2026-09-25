const WebSocket = require('ws');
const http = require('http');

const CDP_PORT = 9222;
const FORWARD_PORT = 8080;             // 👈 Port (80 nahi, 8080 use karo)
const MIN_REFRESH_MS = 8 * 60 * 1000;  // 8 min
const MAX_REFRESH_MS = 12 * 60 * 1000; // 12 min
const CAPTCHA_DELAY_MS = 5000;         // refresh ke 5 sec baad captcha check

const trackedTabs = new Map();  // tabId -> {cdp, url, isVisible}

function log(...args) {
    const t = new Date().toLocaleTimeString();
    console.log('[' + t + ']', ...args);
}

// ── WebSocket server (Go bot yahan aayega) ──
const wss = new WebSocket.Server({ port: FORWARD_PORT, path: '/ivas' });
const clients = new Set();

wss.on('connection', (ws) => {
    log('✅ Go bot connected');
    clients.add(ws);
    ws.on('message', () => {});
    ws.on('close', () => clients.delete(ws));
});

function broadcast(payload) {
    for (const c of clients) {
        if (c.readyState === 1) c.send(payload);
    }
}

// ── CDP command helper ──
function cdpSend(cdp, method, params = {}) {
    return new Promise((resolve) => {
        const id = Math.floor(Math.random() * 1000000);
        const handler = (raw) => {
            try {
                const msg = JSON.parse(raw);
                if (msg.id === id) {
                    cdp.off('message', handler);
                    resolve(msg.result || msg.error);
                }
            } catch (e) {}
        };
        cdp.on('message', handler);
        cdp.send(JSON.stringify({ id, method, params }));
        setTimeout(() => {
            cdp.off('message', handler);
            resolve(null);
        }, 5000);
    });
}

// ── Attach to a tab ──
function attachToTab(tabInfo) {
    if (trackedTabs.has(tabInfo.id)) return;
    const shortId = tabInfo.id.slice(0, 6);
    log('🎯 Attached [' + shortId + ']:', tabInfo.url.slice(0, 70));

    const cdp = new WebSocket(tabInfo.webSocketDebuggerUrl);
    const tabData = { cdp, url: tabInfo.url, isVisible: false };
    trackedTabs.set(tabInfo.id, tabData);

    cdp.on('open', () => {
        log('✅ CDP [' + shortId + '] ready');
        cdp.send(JSON.stringify({ id: 1, method: 'Page.enable' }));
        cdp.send(JSON.stringify({ id: 2, method: 'Runtime.enable' }));
        cdp.send(JSON.stringify({ id: 3, method: 'Network.enable' }));
    });

    cdp.on('message', (raw) => {
        try {
            const msg = JSON.parse(raw);
            if (msg.method === 'Network.webSocketFrameReceived') {
                const payload = msg.params?.response?.payloadData;
                if (!payload || payload.length < 8) return;
                if (payload.indexOf('livesms') !== -1 || payload.indexOf('42/') === 0) {
                    log('📩 [' + shortId + ']', payload.slice(0, 80));
                    broadcast(payload);
                }
            }
        } catch (e) {}
    });

    cdp.on('close', () => {
        log('🔌 [' + shortId + '] closed');
        trackedTabs.delete(tabInfo.id);
    });

    cdp.on('error', () => trackedTabs.delete(tabInfo.id));
}

// ── Scan tabs from CDP ──
function scanTabs() {
    return new Promise((resolve) => {
        const req = http.get('http://localhost:' + CDP_PORT + '/json', { timeout: 2000 }, (res) => {
            let data = '';
            res.on('data', (c) => data += c);
            res.on('end', () => {
                try {
                    const pages = JSON.parse(data);
                    resolve(pages.filter(p =>
                        p.type === 'page' &&
                        !p.url.startsWith('edge://') &&
                        !p.url.startsWith('chrome://') &&
                        !p.url.startsWith('about:') &&
                        !p.url.startsWith('devtools://') &&
                        p.webSocketDebuggerUrl
                    ));
                } catch (e) { resolve([]); }
            });
        });
        req.on('error', () => resolve([]));
        req.on('timeout', () => { req.destroy(); resolve([]); });
    });
}

// ── Detect which tab is currently ACTIVE (focused) ──
async function updateVisibility() {
    for (const [tabId, tabData] of trackedTabs) {
        try {
            const res = await cdpSend(tabData.cdp, 'Runtime.evaluate', {
                expression: 'document.visibilityState',
                returnByValue: true,
            });
            tabData.isVisible = res?.result?.value === 'visible';
        } catch (e) {}
    }
}

// ── Auto-click Cloudflare checkbox ──
async function trySolveCaptcha(tabId, tabData) {
    const shortId = tabId.slice(0, 6);

    const checkScript = `
        (function(){
            const iframes = document.querySelectorAll('iframe');
            for (const f of iframes) {
                const src = f.src || '';
                if (src.includes('challenges.cloudflare.com') || src.includes('turnstile')) {
                    const r = f.getBoundingClientRect();
                    return JSON.stringify({found:true,x:r.left,y:r.top,w:r.width,h:r.height});
                }
            }
            return JSON.stringify({found:false});
        })();
    `;

    const res = await cdpSend(tabData.cdp, 'Runtime.evaluate', {
        expression: checkScript, returnByValue: true,
    });
    if (!res?.result?.value) return false;

    let info;
    try { info = JSON.parse(res.result.value); } catch (e) { return false; }
    if (!info.found || info.w < 20) return false;

    log('🛡️  Cloudflare detected [' + shortId + ']: ' + info.w + 'x' + info.h);

    const x = Math.round(info.x + 30);
    const y = Math.round(info.y + info.h / 2);

    for (let attempt = 1; attempt <= 3; attempt++) {
        log('🖱️  Click attempt ' + attempt + ' at (' + x + ',' + y + ')');

        await cdpSend(tabData.cdp, 'Input.dispatchMouseEvent', {
            type: 'mousePressed', x, y, button: 'left', clickCount: 1,
        });
        await new Promise(r => setTimeout(r, 100));
        await cdpSend(tabData.cdp, 'Input.dispatchMouseEvent', {
            type: 'mouseReleased', x, y, button: 'left', clickCount: 1,
        });
        await new Promise(r => setTimeout(r, 3000));

        const r2 = await cdpSend(tabData.cdp, 'Runtime.evaluate', {
            expression: checkScript, returnByValue: true,
        });
        try {
            const info2 = JSON.parse(r2.result.value);
            if (!info2.found || info2.w < 20) {
                log('🎉 Cloudflare SOLVED [' + shortId + ']');
                return true;
            }
        } catch (e) {}
    }
    log('⚠️  Cloudflare still present after 3 attempts [' + shortId + ']');
    return false;
}

// ── Refresh ONLY active tab ──
async function refreshActiveTab() {
    await updateVisibility();

    const activeTabs = [];
    for (const [id, d] of trackedTabs) {
        if (d.isVisible) activeTabs.push([id, d]);
    }

    if (activeTabs.length === 0) {
        log('⚠️  Koi active tab nahi mila. Skip.');
        return;
    }

    for (const [tabId, tabData] of activeTabs) {
        const shortId = tabId.slice(0, 6);
        log('🔄 Refreshing ACTIVE tab [' + shortId + ']: ' + tabData.url.slice(0, 60));
        await cdpSend(tabData.cdp, 'Page.reload', { ignoreCache: false });

        setTimeout(() => {
            trySolveCaptcha(tabId, tabData);
        }, CAPTCHA_DELAY_MS);
    }
}

// ── Random refresh scheduler ──
function scheduleRefresh() {
    const delay = MIN_REFRESH_MS + Math.random() * (MAX_REFRESH_MS - MIN_REFRESH_MS);
    const sec = Math.round(delay / 1000);
    log('⏰ Next refresh in ' + Math.floor(sec / 60) + 'm ' + (sec % 60) + 's');

    setTimeout(async () => {
        await refreshActiveTab();
        scheduleRefresh();
    }, delay);
}

// ── Auto-scan naye tabs ──
setInterval(async () => {
    const tabs = await scanTabs();
    for (const tab of tabs) {
        if (!trackedTabs.has(tab.id)) attachToTab(tab);
    }
}, 10000);

// ── Visibility updater (har 3 sec) ──
setInterval(updateVisibility, 3000);

// ── Startup ──
console.log('');
console.log('═══════════════════════════════════════════════════');
console.log('🚀 Forward:        ws://0.0.0.0:' + FORWARD_PORT + '/ivas');
console.log('🔄 Auto-refresh:   ONLY active tab');
console.log('⏰ Interval:       8-12 minutes (random)');
console.log('🛡️  Cloudflare:     auto-click enabled (3 tries)');
console.log('📥 Multi-tab:      auto-attach on open');
console.log('═══════════════════════════════════════════════════');
console.log('');

scheduleRefresh();
