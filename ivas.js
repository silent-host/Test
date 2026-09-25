const puppeteer = require('puppeteer-core');
const WebSocket = require('ws');

// ================== سیٹنگز ==================
const EDGE_PORT = process.argv[2] || "9222"; // ایج کا ڈیبگنگ پورٹ
const botId = process.argv[3] || "1";        // بوٹ کا نمبر (1, 2, 3...)
const WS_URL = `ws://0.0.0.0:8800/ivas${botId}`; // پورٹ 8800 پر ویب ساکٹ
const TARGET_URL = 'https://www.ivasms.com/portal/live/my_sms';

// ⚠️ اہم: نیچے والی لائن میں اپنے چیک باکس کا صحیح سلیکٹر لکھو
// مثال کے طور پر: '#checkbox-id' یا '.captcha-checkbox' یا 'input[type="checkbox"]'
const CHECKBOX_SELECTOR = 'input[type="checkbox"]'; 
// =============================================

console.log(`=========================================`);
console.log(`🤖 Bot ID: ${botId} | Edge Port: ${EDGE_PORT}`);
console.log(`🔗 WebSocket: ${WS_URL}`);
console.log(`=========================================`);

let ws;

// ویب ساکٹ کنکشن بنانے کا فنکشن (خود بخود دوبارہ جڑے گا)
function connectWebSocket() {
    ws = new WebSocket(WS_URL);
    ws.on('open', () => console.log(`✅ [Bot ${botId}] WebSocket Connected to Port 8800!`));
    ws.on('close', () => {
        console.log(`❌ [Bot ${botId}] WS Disconnected. Reconnecting in 5s...`);
        setTimeout(connectWebSocket, 5000);
    });
    ws.on('error', (err) => console.error(`⚠️ [Bot ${botId}] WS Error:`, err.message));
}

// چیک باکس / کیپچا پر کلک کرنے کا فنکشن
async function handleCheckbox(page) {
    try {
        // چیک کرو کہ چیک باکس موجود ہے یا نہیں
        const checkbox = await page.$(CHECKBOX_SELECTOR);
        if (checkbox) {
            // چیک کرو کہ پہلے سے ٹک تو نہیں ہے
            const isChecked = await page.evaluate(el => el.checked, checkbox);
            if (!isChecked) {
                await checkbox.click();
                console.log(`☑️ [Bot ${botId}] Checkbox/Captcha clicked successfully.`);
            } else {
                console.log(`✅ [Bot ${botId}] Checkbox already checked.`);
            }
        } else {
            console.log(`ℹ️ [Bot ${botId}] No checkbox found on this page. Skipping.`);
        }
    } catch (error) {
        console.log(`⚠️ [Bot ${botId}] Error clicking checkbox:`, error.message);
    }
}

// ڈیٹا نکالنے اور بھیجنے کا فنکشن
async function extractAndSendData(page) {
    try {
        // صفحے سے سارا ٹیکسٹ نکالو (تم اپنی مرضی سے کسی خاص ڈیو کا سلیکٹر بھی لگا سکتے ہو)
        const pageData = await page.evaluate(() => {
            // اگر پورا صفحہ چاہیے تو document.body.innerText
            // یا کسی خاص باکس کا ڈیٹا چاہیے تو document.querySelector('#id').innerText
            return document.body.innerText; 
        });

        if (ws && ws.readyState === WebSocket.OPEN) {
            const payload = {
                botId: botId,
                timestamp: new Date().toISOString(),
                data: pageData
            };
            ws.send(JSON.stringify(payload));
            console.log(`📤 [Bot ${botId}] Data sent to WS (Port 8800).`);
        }
    } catch (error) {
        console.error(`❌ [Bot ${botId}] Error extracting data:`, error.message);
    }
}

// مین بوٹ فنکشن
async function startBot() {
    connectWebSocket();

    try {
        // ایج براؤزر سے جڑو (نیا براؤزر نہیں کھلے گا)
        const browser = await puppeteer.connect({
            browserURL: `http://localhost:${EDGE_PORT}`,
            defaultViewport: null
        });
        console.log(`🔗 [Bot ${botId}] Connected to Edge successfully!`);

        const pages = await browser.pages();
        let targetPage = pages.find(p => p.url().includes('ivasms.com'));

        // اگر ٹیب پہلے سے کھلا ہے تو اسے استعمال کرو، ورنہ نیا کھولو
        if (targetPage) {
            console.log(`🎯 [Bot ${botId}] Target tab found!`);
        } else {
            console.log(`🔍 [Bot ${botId}] Target tab not found. Opening new one...`);
            targetPage = await browser.newPage();
            await targetPage.goto(TARGET_URL, { waitUntil: 'domcontentloaded' });
            // نیا ٹیب کھلنے پر ایک بار چیک باکس چیک کرو
            await new Promise(r => setTimeout(r, 3000)); // 3 سیکنڈ رکو
            await handleCheckbox(targetPage);
        }

        // لامحدود ریفریش لوپ
        async function refreshLoop() {
            // 8 سے 12 منٹ کا رینڈم وقت
            const randomMinutes = Math.floor(Math.random() * (12 - 8 + 1)) + 8;
            const waitTimeMs = randomMinutes * 60 * 1000;

            console.log(`⏳ [Bot ${botId}] Next refresh in ${randomMinutes} minutes...`);
            await new Promise(resolve => setTimeout(resolve, waitTimeMs));

            console.log(`🔄 [Bot ${botId}] Refreshing target tab...`);
            try {
                // ٹیب ایکٹو ہو یا نہ ہو، صرف اسی ٹیب کو ریفریش کرو
                await targetPage.reload({ waitUntil: 'domcontentloaded' });
                console.log(`✅ [Bot ${botId}] Refreshed successfully.`);

                // ریفریش کے بعد تھوڑا انتظار کرو تاکہ صفحہ لوڈ ہو جائے
                await new Promise(r => setTimeout(r, 5000)); // 5 سیکنڈ

                // ریفریش کے بعد دوبارہ چیک باکس چیک کرو (اگر آ جائے تو)
                await handleCheckbox(targetPage);

                // ڈیٹا نکالو اور ویب ساکٹ پر بھیجو
                await extractAndSendData(targetPage);

            } catch (error) {
                console.error(`❌ [Bot ${botId}] Refresh error:`, error.message);
            }
            refreshLoop(); // دوبارہ لوپ چلاؤ
        }

        refreshLoop();

    } catch (error) {
        console.error(`❌ [Bot ${botId}] Could not connect to Edge. Make sure Edge is running on port ${EDGE_PORT}.`);
        console.error(error.message);
    }
}

startBot();
