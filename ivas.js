const WebSocket = require('ws');
const http = require('http');

const CDP_PORT = 9222;
const REFRESH_INTERVAL = 8 * 60 * 1000;  // 8 minutes
const CAPTCHA_CHECK_DELAY = 5 * 1000;    // 5 seconds after refresh

const trackedTabs = new Map();

function log(...args) {
    const t = new Date().toLocaleTimeString();
    console.log('[' + t + ']', ...args);
}

// ── Send CDP command and wait for response ──
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

        // timeout
        setTimeout(() => {
            cdp.off('message', handler);
            resolve(null);
        }, 5000);
    });
}

// ── Try to click Cloudflare Turnstile checkbox ──
async function tryClickCloudflare(cdp, tabId) {
    const shortId = tabId.slice(0, 6);

    // 1) Check if Cloudflare iframe exists
    const checkScript = `
        (function() {
            const iframes = document.querySelectorAll('iframe');
            for (const f of iframes) {
                const src = f.src || '';
                if (src.includes('challenges.cloudflare.com') || src.includes('turnstile')) {
                    const r = f.getBoundingClientRect();
                    return JSON.stringify({
                        found: true,
                        x: r.left,
                        y: r.top,
                        w: r.width,
                        h: r.height
                    });
                }
            }
            return JSON.stringify({ found: false });
        })();
    `;

    const result = await cdpSend(cdp, 'Runtime.evaluate', {
        expression: checkScript,
        returnByValue: true,
    });

    if (!result || !result.result || !result.result.value) {
        return false;
    }

    let info;
    try {
        info = JSON.parse(result.result.value);
    } catch (e) {
        return false;
    }

    if (!info.found || info.w < 20) {
        return false;
    }

    log('🛡️  [' + shortId + '] Cloudflare iframe detected: ' + info.w + 'x' + info.h);

    // 2) The checkbox is typically at:
    //    - x = iframe.left + ~30px
    //    - y = iframe.top + iframe.height/2
    const clickX = Math.round(info.x + 30);
    const clickY = Math.round(info.y + info.h / 2);

    log('🖱️  [' + shortId + '] Clicking checkbox at (' + clickX + ', ' + clickY + ')');

    // 3) Send real mouse click via CDP (bypasses cross-origin)
    await cdpSend(cdp, 'Input.dispatchMouseEvent', {
        type: 'mousePressed',
        x: clickX,
        y: clickY,
        button: 'left',
        clickCount: 1,
    });

    await new Promise(r => setTimeout(r, 100));

    await cdpSend(cdp, 'Input.dispatchMouseEvent', {
        type: 'mouseReleased',
        x: clickX,
        y: clickY,
        button: 'left',
        clickCount: 1,
    });

    log('✅ [' + shortId + '] Click sent');

    // 4) Wait a bit and check if still there (maybe re-try)
    await new Promise(r => setTimeout(r, 3000));

    const recheck = await cdpSend(cdp, 'Runtime.evaluate', {
        expression: checkScript,
        returnByValue: true,
    });

    try {
        const info2 = JSON.parse(recheck.result.value);
        if (info2.found && info2.w > 20) {
            log('⚠️  [' + shortId + '] Cloudflare still present, retrying...');
            // retry once
            await cdpSend(cdp, 'Input.dispatchMouseEvent', {
                type: 'mousePressed',
                x: clickX, y: clickY,
                button: 'left', clickCount: 1,
            });
            await new Promise(r => setTimeout(r, 100));
            await cdpSend(cdp, 'Input.dispatchMouseEvent', {
                type: 'mouseReleased',
                x: clickX, y: clickY,
                button: 'left', clickCount: 1,
            });
            return true;
        } else {
            log('🎉 [' + shortId + '] Cloudflare solved!');
            return true;
        }
    } catch (e) {
        return false;
    }
}

// ── Attach to a tab ──
function attachToTab(tabInfo) {
    if (trackedTabs.has(tabInfo.id)) return;

    const shortId = tabInfo.id.slice(0, 6);
    log('🎯 Attached [' + shortId + ']:', tabInfo.url.slice(0, 70));

    const cdp = new WebSocket(tabInfo.webSocketDebuggerUrl);
    const tabData = { cdp, url: tabInfo.url, lastRefresh: Date.now() };
    trackedTabs.set(tabInfo.id, tabData);

    cdp.on('open', () => {
        log('✅ CDP [' + shortId + '] connected');
        cdp.send(JSON.stringify({ id: 1, method: 'Page.enable' }));
        cdp.send(JSON.stringify({ id: 2, method: 'Runtime.enable' }));
        cdp.send(JSON.stringify({ id: 3, method: 'DOM.enable' }));
        cdp.send(JSON.stringify({ id: 4, method: 'Network.enable' }));
    });

    cdp.on('close', () => {
        log('🔌 CDP [' + shortId + '] disconnected');
        trackedTabs.delete(tabInfo.id);
    });

    cdp.on('error', (err) => {
        log('❌ CDP [' + shortId + '] error:', err.message);
        trackedTabs.delete(tabInfo.id);
    });
}

// ── Refresh a tab and try to solve Cloudflare ──
async function refreshTab(tabId, tabData) {
    const shortId = tabId.slice(0, 6);
    log('🔄 Refreshing [' + shortId + ']...');

    try {
        await cdpSend(tabData.cdp, 'Page.reload', { ignoreCache: false });
        tabData.lastRefresh = Date.now();
        log('✅ Reload sent [' + shortId + ']');

        // Wait then check for Cloudflare
        setTimeout(async () => {
            await tryClickCloudflare(tabData.cdp, tabId);
        }, CAPTCHA_CHECK_DELAY);

    } catch (e) {
        log('❌ Refresh failed [' + shortId + ']:', e.message);
    }
}

// ── Scan tabs ──
function scanTabs() {
    return new Promise((resolve) => {
        const req = http.get('http://localhost:' + CDP_PORT + '/json', { timeout: 2000 }, (res) => {
            let data = '';
            res.on('data', (c) => data += c);
            res.on('end', () => {
                try {
                    const pages = JSON.parse(data);
                    const targets = pages.filter(p =>
                        p.type === 'page' &&
                        !p.url.startsWith('edge://') &&
                        !p.url.startsWith('chrome://') &&
                        !p.url.startsWith('about:') &&
                        !p.url.startsWith('devtools://') &&
                        p.webSocketDebuggerUrl
                    );
                    resolve(targets);
                } catch (e) { resolve([]); }
            });
        });
        req.on('error', () => resolve([]));
        req.on('timeout', () => { req.destroy(); resolve([]); });
    });
}

// ── Main loops ──
let cycleCount = 0;

// Attach to new tabs every 10 sec
setInterval(async () => {
    const tabs = await scanTabs();
    for (const tab of tabs) {
        if (!trackedTabs.has(tab.id)) {
            attachToTab(tab);
        }
    }
}, 10000);

// Refresh every 8 min
setInterval(async () => {
    cycleCount++;
    log('');
    log('═══════════════════════════════════════');
    log('🔃 Refresh Cycle #' + cycleCount + ' | Tabs: ' + trackedTabs.size);
    log('═══════════════════════════════════════');

    for (const [tabId, tabData] of trackedTabs) {
        await refreshTab(tabId, tabData);
        await new Promise(r => setTimeout(r, 500));
    }
}, REFRESH_INTERVAL);

// Startup
console.log('');
console.log('═══════════════════════════════════════════════════');
console.log('🔄 Auto-Refresh + Auto-Click Active');
console.log('✅ Original Edge browser refresh karega');
console.log('✅ Har 8 min me refresh');
console.log('✅ Cloudflare checkbox auto-click karega');
console.log('✅ Naye tabs auto-track honge');
console.log('═══════════════════════════════════════════════════');
console.log('');
