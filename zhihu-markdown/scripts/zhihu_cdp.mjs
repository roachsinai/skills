#!/usr/bin/env node
// zhihu_cdp.mjs — 通过 CDP 驱动有头 Chrome 抓取知乎页面 DOM（绕过反爬）
// 用法: node zhihu_cdp.mjs <url> <out.html> [port]
// 环境变量: CDP_TRIES=3 (失败重试次数)
//
// 原理: 无头模式会被知乎服务端识别(sec-ch-ua 含 HeadlessChrome, 返回 40362),
// 必须用有头 Chrome; 先访问首页让 JS 挑战(zse-ck)种下 cookie, 再用
// location.href 跳转到目标页(带 Referer), 等待正文容器渲染后导出 DOM。

import fs from 'fs';

const args = process.argv.slice(2);
const TARGET_URL = args[0];
const OUT = args[1] || '/tmp/zhihu_page.html';
const DEBUG_PORT = parseInt(args[2] || process.env.CDP_PORT || '19222', 10);
const MAX_TRIES = parseInt(process.env.CDP_TRIES || '3', 10);
const HOME = 'https://www.zhihu.com/';

if (!TARGET_URL) {
  console.error('usage: node zhihu_cdp.mjs <url> <out.html> [port]');
  process.exit(1);
}

const sleep = (ms) => new Promise(r => setTimeout(r, ms));

async function getWsUrl() {
  for (let i = 0; i < 40; i++) {
    try {
      const res = await fetch(`http://127.0.0.1:${DEBUG_PORT}/json/list`);
      const targets = await res.json();
      const page = targets.find(t => t.type === 'page');
      if (page) return page.webSocketDebuggerUrl;
    } catch {}
    await sleep(500);
  }
  throw new Error(`cannot connect to CDP port ${DEBUG_PORT} (is Chrome running with --remote-debugging-port?)`);
}

function looksGood(html) {
  if (html.length < 20000) return `too small (${html.length} chars)`;
  if (/"code":40362|您当前请求存在异常/.test(html)) return 'risk-control block 40362';
  if (/id="zh-zse-ck"/.test(html)) return 'js challenge page (zse-ck)';
  if (/need_login/.test(html) && html.length < 60000) return 'login wall';
  return null;
}

async function main() {
  const wsUrl = await getWsUrl();
  const ws = new WebSocket(wsUrl);
  await new Promise((res, rej) => { ws.onopen = res; ws.onerror = rej; });

  let msgId = 0;
  const pending = new Map();
  const listeners = [];
  ws.onmessage = (ev) => {
    const msg = JSON.parse(ev.data);
    if (msg.id && pending.has(msg.id)) {
      const { resolve, reject } = pending.get(msg.id);
      pending.delete(msg.id);
      msg.error ? reject(new Error(JSON.stringify(msg.error))) : resolve(msg.result);
    } else {
      listeners.forEach(l => l(msg));
    }
  };
  const send = (method, params = {}) => new Promise((resolve, reject) => {
    const id = ++msgId;
    pending.set(id, { resolve, reject });
    ws.send(JSON.stringify({ id, method, params }));
  });
  const waitFor = (method, timeoutMs = 60000) => new Promise((resolve) => {
    const timer = setTimeout(() => {
      const i = listeners.indexOf(fn); if (i >= 0) listeners.splice(i, 1);
      resolve(null);
    }, timeoutMs);
    const fn = (msg) => {
      if (msg.method === method) {
        clearTimeout(timer);
        const i = listeners.indexOf(fn); if (i >= 0) listeners.splice(i, 1);
        resolve(msg.params);
      }
    };
    listeners.push(fn);
  });

  await send('Page.enable');
  await send('Runtime.enable');
  await send('Emulation.setDeviceMetricsOverride', {
    width: 1512, height: 982, deviceScaleFactor: 2, mobile: false
  });

  const evalJs = async (expr) => {
    const r = await send('Runtime.evaluate', { expression: expr, returnByValue: true });
    if (r.exceptionDetails) throw new Error(JSON.stringify(r.exceptionDetails));
    return r.result.value;
  };

  const waitForContent = async (timeoutMs = 25000) => {
    const start = Date.now();
    while (Date.now() - start < timeoutMs) {
      if (await evalJs(`!!document.querySelector('.RichContent-inner, .Post-RichTextContainer, .QuestionHeader, .Post-Title')`)) return true;
      await sleep(1000);
    }
    return false;
  };

  let lastHtml = '';
  let lastReason = '';

  for (let attempt = 1; attempt <= MAX_TRIES; attempt++) {
    console.error(`[attempt ${attempt}/${MAX_TRIES}] warming up homepage...`);
    const loaded1 = waitFor('Page.loadEventFired', 45000);
    await send('Page.navigate', { url: HOME });
    await loaded1;
    await sleep(4000);
    // 像真人一样滚动
    await evalJs('window.scrollTo(0, 600)');
    await sleep(1200);
    await evalJs('window.scrollTo(0, 1200)');
    await sleep(1500);

    console.error(`[attempt ${attempt}/${MAX_TRIES}] navigating to target...`);
    const loaded2 = waitFor('Page.loadEventFired', 45000);
    await evalJs(`location.href = '${TARGET_URL.replace(/'/g, "\\'")}'`);
    await loaded2;
    await waitForContent();
    await sleep(5000);

    lastHtml = await evalJs('document.documentElement.outerHTML');
    lastReason = looksGood(lastHtml);
    const title = await evalJs('document.title');
    console.error(`[attempt ${attempt}] title=${JSON.stringify(title)} chars=${lastHtml.length}`);

    if (!lastReason) {
      fs.writeFileSync(OUT, lastHtml);
      console.error(`OK: saved ${lastHtml.length} chars to ${OUT}`);
      ws.close();
      return;
    }
    console.error(`[attempt ${attempt}] not good: ${lastReason}; retrying after backoff...`);
    await sleep(8000 * attempt);
  }

  // 全部失败也把最后一次结果留下供诊断, 退出码 2
  fs.writeFileSync(OUT, lastHtml);
  console.error(`FAILED after ${MAX_TRIES} attempts: ${lastReason}`);
  ws.close();
  process.exit(2);
}

main().catch(e => { console.error('FATAL', e.message); process.exit(1); });
