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

// 最近一次 "导出触发" 的元信息（内存即可；SW 被 kill 后丢失也无碍，只影响未完成的那一次）
let pendingExport = null;

// ─────────────────────────────────────────────────────────────────────────────
// 来自 content.js 的消息
// ─────────────────────────────────────────────────────────────────────────────
chrome.runtime.onMessage.addListener((msg, sender, sendResponse) => {
  if (msg.type === 'export_triggered') {
    pendingExport = {
      url: msg.url,
      title: msg.title,
      tabId: sender.tab?.id,
      timestamp: Date.now(),
    };
    console.log('[TencDoc→MD] pending export:', pendingExport);
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
  }
});

// ─────────────────────────────────────────────────────────────────────────────
// 下载监听
// ─────────────────────────────────────────────────────────────────────────────
chrome.downloads.onChanged.addListener(async (delta) => {
  if (delta.state?.current !== 'complete') return;
  if (!pendingExport) return;
  // 过期就丢掉
  if (Date.now() - pendingExport.timestamp > EXPECT_WINDOW_MS) {
    pendingExport = null;
    return;
  }

  let item;
  try {
    const [it] = await chrome.downloads.search({ id: delta.id });
    item = it;
  } catch (e) {
    console.error('[TencDoc→MD] downloads.search 失败:', e);
    return;
  }
  if (!item || !item.filename.toLowerCase().endsWith('.docx')) return;

  const meta = pendingExport;
  pendingExport = null; // 消费掉

  console.log('[TencDoc→MD] 下载完成:', item.filename, 'for', meta.url);

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
