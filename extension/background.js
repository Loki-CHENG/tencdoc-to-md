// background.js — Service Worker
//
// 职责：
//   1. content.js 发来 "export_triggered" 后记录一次 "expected download"（带 URL、标题、时间戳）
//   2. 监听 chrome.downloads.onCreated → 如果文件是 .docx 且在 expected 窗口内，
//      记录 downloadId
//   3. 监听 chrome.downloads.onChanged → state=complete 时，拿到本地绝对路径，
//      通过 Native Messaging 发给 helper 做转换
//   4. helper 返回结果 → 通知 content.js 更新按钮状态
//
// 配置：vault / inbox / output / attachments 路径存在 chrome.storage.sync 里，
//      options.html 提供 UI；首次安装时 helper 也可以从它的 config 返回默认值。

const HOST_NAME = 'com.loki.tencdoc_to_md';
const EXPECT_WINDOW_MS = 30_000; // 触发后 30 秒内出现的 .docx 下载视为我们的

// 队列版：支持用户快速连续点击多次按钮 / 多 tab 并行
// 早期实现只有一个 pendingExport 变量，第二次点击会覆盖第一次的 tabId，
// 导致第一次的 convert_done 回不到对应 tab。FIFO 匹配就够用。
const pendingQueue = []; // [{ url, title, tabId, timestamp }, ...]

function reapExpiredPending() {
  const now = Date.now();
  while (pendingQueue.length && now - pendingQueue[0].timestamp > EXPECT_WINDOW_MS) {
    pendingQueue.shift();
  }
}

// ─────────────────────────────────────────────────────────────────────────────
// 来自 content.js 的消息
// ─────────────────────────────────────────────────────────────────────────────
chrome.runtime.onMessage.addListener((msg, sender, sendResponse) => {
  if (msg.type === 'export_triggered') {
    reapExpiredPending();
    const entry = {
      url: msg.url,
      title: msg.title,
      tabId: sender.tab?.id,
      timestamp: Date.now(),
    };
    pendingQueue.push(entry);
    console.log('[TencDoc→MD] 入队 export, queue size =', pendingQueue.length, entry);
    sendResponse({ ok: true });
  } else if (msg.type === 'ping_host') {
    sendNative({ cmd: 'ping' })
      .then((res) => sendResponse({ ok: true, res }))
      .catch((e) => sendResponse({ ok: false, error: e.message }));
    return true; // async
  } else if (msg.type === 'get_host_config') {
    sendNative({ cmd: 'get_config' })
      .then((res) => sendResponse({ ok: true, res }))
      .catch((e) => sendResponse({ ok: false, error: e.message }));
    return true;
  } else if (msg.type === 'doctor') {
    sendNative({ cmd: 'doctor' })
      .then((res) => sendResponse({ ok: true, res }))
      .catch((e) => sendResponse({ ok: false, error: e.message }));
    return true;
  } else if (msg.type === 'real_mouse_export') {
    // content.js 发来一组坐标：菜单按钮 → 导出为 → docx 选项
    // 我们用 chrome.debugger 发真实鼠标事件触发 CSS :hover 和 React isTrusted 检查
    realMouseExport(sender.tab.id, msg.steps)
      .then((r) => sendResponse({ ok: true, ...r }))
      .catch((e) => {
        console.error('[TencDoc→MD] realMouseExport 失败:', e);
        sendResponse({ ok: false, error: e.message });
      });
    return true;
  }
});

// ─────────────────────────────────────────────────────────────────────────────
// 用 chrome.debugger 发真实鼠标事件（走浏览器原生输入管线，跟真手一样）
// ─────────────────────────────────────────────────────────────────────────────

/**
 * steps 格式：[
 *   { action: 'move', x, y, delay: 150 },   // 鼠标移到 (x,y) 然后等 delay ms
 *   { action: 'click', x, y, delay: 300 },  // 鼠标移到 + down + up
 * ]
 * 坐标是相对 viewport 的（content.js 的 getBoundingClientRect 返回的就是这种）
 */
async function realMouseExport(tabId, steps) {
  const target = { tabId };
  // attach —— 常见错误：DevTools 已打开 / 另一扩展已 attach。给出可操作提示。
  await new Promise((resolve, reject) => {
    chrome.debugger.attach(target, '1.3', () => {
      if (chrome.runtime.lastError) {
        const raw = chrome.runtime.lastError.message || '';
        if (/already attached|Another debugger/i.test(raw)) {
          return reject(new Error(
            '无法启动 debugger：另一个调试器已附加到这个 tab。\n' +
            '请关闭 DevTools（F12 关掉），或禁用其他正在调试的扩展后重试。\n' +
            '原始错误: ' + raw
          ));
        }
        return reject(new Error('chrome.debugger.attach 失败: ' + raw));
      }
      resolve();
    });
  });

  // Chrome 会在 tab 顶部显示一条黄色警告："...正在调试此浏览器" —— 这是正常的
  // 我们执行完后立刻 detach 把它关掉

  try {
    for (const step of steps) {
      const { action, x, y, delay = 100 } = step;
      if (action === 'move') {
        await cdpSend(target, 'Input.dispatchMouseEvent', {
          type: 'mouseMoved', x, y, button: 'none', buttons: 0, clickCount: 0,
        });
      } else if (action === 'click') {
        // 先 move 到位（让 CSS :hover 更新）
        await cdpSend(target, 'Input.dispatchMouseEvent', {
          type: 'mouseMoved', x, y, button: 'none', buttons: 0, clickCount: 0,
        });
        await sleep(30);
        await cdpSend(target, 'Input.dispatchMouseEvent', {
          type: 'mousePressed', x, y, button: 'left', buttons: 1, clickCount: 1,
        });
        await sleep(30);
        await cdpSend(target, 'Input.dispatchMouseEvent', {
          type: 'mouseReleased', x, y, button: 'left', buttons: 0, clickCount: 1,
        });
      }
      if (delay > 0) await sleep(delay);
    }
    return { ok: true };
  } finally {
    // 一定要 detach，否则黄条永远挂着
    try {
      await new Promise((resolve) => chrome.debugger.detach(target, () => resolve()));
    } catch { /* ignore */ }
  }
}

function cdpSend(target, method, params) {
  return new Promise((resolve, reject) => {
    chrome.debugger.sendCommand(target, method, params, (result) => {
      if (chrome.runtime.lastError) return reject(new Error(chrome.runtime.lastError.message));
      resolve(result);
    });
  });
}

function sleep(ms) {
  return new Promise((r) => setTimeout(r, ms));
}

// ─────────────────────────────────────────────────────────────────────────────
// 下载监听
// ─────────────────────────────────────────────────────────────────────────────
chrome.downloads.onChanged.addListener(async (delta) => {
  if (delta.state?.current !== 'complete') return;
  reapExpiredPending();
  if (!pendingQueue.length) return;

  let item;
  try {
    const [it] = await chrome.downloads.search({ id: delta.id });
    item = it;
  } catch (e) {
    console.error('[TencDoc→MD] downloads.search 失败:', e);
    return;
  }
  if (!item || !item.filename.toLowerCase().endsWith('.docx')) return;

  // FIFO 出队：最早触发的那次对应当前最早完成的下载
  const meta = pendingQueue.shift();

  console.log('[TencDoc→MD] 下载完成:', item.filename, 'for', meta.url, '剩余队列:', pendingQueue.length);

  // 调 native host 做转换
  try {
    const res = await sendNative({
      cmd: 'convert',
      docx_path: item.filename,
      source_url: meta.url,
      doc_title: meta.title,
    });
    console.log('[TencDoc→MD] 转换完成:', res);
    if (meta.tabId !== undefined) {
      chrome.tabs.sendMessage(meta.tabId, { type: 'convert_done', ...res });
    }
  } catch (e) {
    console.error('[TencDoc→MD] 转换失败:', e);
    if (meta.tabId !== undefined) {
      chrome.tabs.sendMessage(meta.tabId, { type: 'convert_error', error: e.message });
    }
  }
});

// ─────────────────────────────────────────────────────────────────────────────
// Native Messaging 封装
// ─────────────────────────────────────────────────────────────────────────────
function sendNative(msg) {
  return new Promise((resolve, reject) => {
    try {
      chrome.runtime.sendNativeMessage(HOST_NAME, msg, (response) => {
        if (chrome.runtime.lastError) {
          return reject(new Error(chrome.runtime.lastError.message));
        }
        if (!response) {
          return reject(new Error('native host 无响应（可能未安装或崩溃）'));
        }
        if (response.ok === false) {
          return reject(new Error(response.error || 'native host 返回错误'));
        }
        resolve(response);
      });
    } catch (e) {
      reject(e);
    }
  });
}
