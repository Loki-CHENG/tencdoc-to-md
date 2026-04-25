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
    // msg.session: 'begin' / 'continue' / 'end' —— 控制 attach/detach 生命周期，
    //              避免 keepAlive 循环重复 attach 自撞（"already attached"）
    realMouseExport(sender.tab.id, msg.steps, msg.session)
      .then((r) => sendResponse({ ok: true, ...r }))
      .catch((e) => {
        console.error('[TencDoc→MD] realMouseExport 失败:', e);
        sendResponse({ ok: false, error: e.message });
      });
    return true;
  } else if (msg.type === 'real_mouse_detach') {
    // 失败恢复：不管什么状态，强制 detach，避免黄条卡着 / 下次无法 attach
    forceDetachTab(sender.tab.id)
      .then(() => sendResponse({ ok: true }))
      .catch((e) => sendResponse({ ok: false, error: e.message }));
    return true;
  }
});

// ─────────────────────────────────────────────────────────────────────────────
// 用 chrome.debugger 发真实鼠标事件（走浏览器原生输入管线，跟真手一样）
// ─────────────────────────────────────────────────────────────────────────────

/**
 * 真实鼠标事件执行器。
 *
 * 【为什么要用 session 协议】
 *   keepAlive 循环每 200ms 调一次 realMouseExport，如果每次都 attach/detach，
 *   会出现竞态：第一次还没 detach 完，第二次 attach 就被拒（"already attached"），
 *   导致整个导出流程崩在"无法启动 debugger"。
 *
 *   所以引入 session：attach 在"begin"时只做一次，所有"continue"调用复用连接，
 *   "end"时统一 detach。这样黄条只挂一次，不再互相打架。
 *
 * steps 格式：[
 *   { action: 'move', x, y, delay: 150 },   // 鼠标移到 (x,y) 然后等 delay ms
 *   { action: 'click', x, y, delay: 300 },  // 鼠标移到 + down + up
 * ]
 * 坐标是相对 tab viewport 的（对 iframe 铺满 tab 的场景，iframe 内坐标 = tab 坐标）。
 *
 * session 可选值：
 *   'begin'    - attach debugger（如果还没 attach），执行 steps
 *   'continue' - 复用已有 attach，执行 steps，不 attach 不 detach
 *   'end'      - 执行 steps，然后 detach
 *   undefined  - 向后兼容：attach → 执行 → detach（老行为）
 */

// 已 attach 的 tab 集合（key: tabId）
const attachedTabs = new Set();

async function _attachIfNeeded(target) {
  if (attachedTabs.has(target.tabId)) return; // 已 attach，跳过
  await new Promise((resolve, reject) => {
    chrome.debugger.attach(target, '1.3', () => {
      if (chrome.runtime.lastError) {
        const raw = chrome.runtime.lastError.message || '';
        // "already attached" 其实不是错 —— 可能前一次导出 detach 没跑到（tab 关了等）
        // 把它当成"已 attach"处理，并补登记一下
        if (/already attached/i.test(raw)) {
          attachedTabs.add(target.tabId);
          return resolve();
        }
        if (/Another debugger/i.test(raw)) {
          return reject(new Error(
            '无法启动 debugger：另一个调试器已附加到这个 tab。\n' +
            '请关闭 DevTools（F12 关掉），或禁用其他正在调试的扩展后重试。\n' +
            '原始错误: ' + raw
          ));
        }
        return reject(new Error('chrome.debugger.attach 失败: ' + raw));
      }
      attachedTabs.add(target.tabId);
      resolve();
    });
  });
}

async function _detachIfAttached(target) {
  if (!attachedTabs.has(target.tabId)) return;
  try {
    await new Promise((resolve) => chrome.debugger.detach(target, () => resolve()));
  } catch { /* ignore */ }
  attachedTabs.delete(target.tabId);
}

// detach 时清理登记（用户手动关闭调试 / tab 关闭）
chrome.debugger.onDetach.addListener((source, reason) => {
  if (source.tabId !== undefined) {
    attachedTabs.delete(source.tabId);
    console.log('[TencDoc→MD] debugger detach:', source.tabId, 'reason:', reason);
  }
});

async function realMouseExport(tabId, steps, session) {
  const target = { tabId };
  const mode = session || 'legacy'; // 'begin' / 'continue' / 'end' / 'legacy'

  // legacy / begin：attach
  if (mode === 'begin' || mode === 'legacy') {
    await _attachIfNeeded(target);
  } else if (mode === 'continue' || mode === 'end') {
    // continue/end 期望连接已存在；万一 tab 被 detach（reason="canceled_by_user"），补一次
    if (!attachedTabs.has(tabId)) {
      await _attachIfNeeded(target);
    }
  }

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
    // legacy / end：detach
    if (mode === 'end' || mode === 'legacy') {
      await _detachIfAttached(target);
    }
    // begin / continue：保持连接给后续调用
  }
}

/** 强制清理一个 tab 的 debugger 连接（失败恢复用） */
async function forceDetachTab(tabId) {
  await _detachIfAttached({ tabId });
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
