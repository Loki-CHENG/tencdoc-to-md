// popup.js — 显示 Native host 状态和当前配置
async function refresh() {
  const hostEl = document.getElementById('host-status');
  hostEl.textContent = '检测中…';
  hostEl.className = 'value';

  try {
    const pingRes = await new Promise((resolve, reject) => {
      chrome.runtime.sendMessage({ type: 'ping_host' }, (r) => {
        if (!r) return reject(new Error('SW 无响应'));
        if (!r.ok) return reject(new Error(r.error));
        resolve(r.res);
      });
    });
    hostEl.textContent = 'v' + (pingRes.version || '?');
    hostEl.className = 'value status-ok';
  } catch (e) {
    hostEl.textContent = '未安装 / 失联';
    hostEl.className = 'value status-bad';
    hostEl.title = e.message;
    return;
  }

  try {
    const cfgRes = await new Promise((resolve, reject) => {
      chrome.runtime.sendMessage({ type: 'get_host_config' }, (r) => {
        if (!r || !r.ok) return reject(new Error(r?.error || 'no response'));
        resolve(r.res);
      });
    });
    document.getElementById('vault').textContent = cfgRes.vault || '—';
    document.getElementById('inbox').textContent = cfgRes.inbox || '—';
    document.getElementById('output').textContent = cfgRes.output_dir || '—';
  } catch (e) {
    console.error(e);
  }
}

document.getElementById('open-options').addEventListener('click', () => {
  chrome.runtime.openOptionsPage();
});
document.getElementById('retry').addEventListener('click', refresh);

refresh();
