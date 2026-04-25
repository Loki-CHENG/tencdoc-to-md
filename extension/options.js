// options.js — 读写 Native host 配置
//
// 通过 background.js 调用 native host 的 get_config / set_config 命令。

function $(id) { return document.getElementById(id); }

function sendBg(msg) {
  return new Promise((resolve, reject) => {
    chrome.runtime.sendMessage(msg, (r) => {
      if (!r) return reject(new Error('background worker 无响应'));
      if (!r.ok) return reject(new Error(r.error || 'unknown error'));
      resolve(r.res);
    });
  });
}

async function reload() {
  $('status').textContent = '';
  try {
    const cfg = await sendBg({ type: 'get_host_config' });
    $('vault').value = cfg.vault || '';
    $('inbox').value = cfg.inbox || '';
    $('output_dir').value = cfg.output_dir || '';
    $('attachments_dir').value = cfg.attachments_dir || '';
    $('status').textContent = '已从 helper 读取配置';
    $('status').className = 'ok';
  } catch (e) {
    $('status').textContent = '读取配置失败：' + e.message;
    $('status').className = 'bad';
  }

  // 诊断信息
  try {
    const ping = await sendBg({ type: 'ping_host' });
    $('host-info').innerHTML =
      '<span class="ok">✅ Native host 在线</span><br>版本：' + (ping.version || '?');
  } catch (e) {
    $('host-info').innerHTML =
      '<span class="bad">❌ Native host 未连接：' + e.message + '</span><br>' +
      '<div class="hint">请到项目根目录运行 <code>./install.sh</code> 安装 helper，' +
      '并确保扩展 ID 已填入 manifest。</div>';
  }
}

async function save() {
  $('status').textContent = '保存中…';
  $('status').className = '';
  const payload = {
    cmd: 'set_config',
    vault: $('vault').value.trim(),
    inbox: $('inbox').value.trim() || '_tencdoc-inbox',
    output_dir: $('output_dir').value.trim() || 'TencDocs',
    attachments_dir: $('attachments_dir').value.trim(),
  };
  try {
    // 通过专门的 message 转发
    const res = await new Promise((resolve, reject) => {
      chrome.runtime.sendNativeMessage('com.loki.tencdoc_to_md', payload, (r) => {
        if (chrome.runtime.lastError) return reject(new Error(chrome.runtime.lastError.message));
        if (!r || r.ok === false) return reject(new Error(r?.error || 'no response'));
        resolve(r);
      });
    });
    $('status').textContent = '✅ 已保存：' + (res.path || '');
    $('status').className = 'ok';
  } catch (e) {
    $('status').textContent = '保存失败：' + e.message;
    $('status').className = 'bad';
  }
}

$('save').addEventListener('click', save);
$('reload').addEventListener('click', reload);
reload();
