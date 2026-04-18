// content.js — 注入浮动按钮，模拟点击官方"菜单 → 导出为 → 本地 Word 文档(.docx)"
//
// 策略：
//   1. 在页面右下角注入一个浮动按钮 "→ Obsidian"
//   2. 点击后执行 exportToDocx()：
//        a. 找到右上角"菜单"按钮（三横线图标）并点击
//        b. 等待菜单展开后，找到"导出为"菜单项，hover 触发子菜单
//        c. 在子菜单里点击"本地Word文档(.docx)"
//   3. 通知 background.js 当前 URL / 标题，以便它在下载完成事件里匹配
//
// DOM 选择策略：腾讯文档/企业微信文档的 DOM 没有稳定的 class / id，所以用
//   "包含特定中文文字的节点" 来匹配（最鲁棒的方案）。
//
(() => {
  'use strict';

  const LOG = (...args) => console.log('[TencDoc→MD]', ...args);
  const ERR = (...args) => console.error('[TencDoc→MD]', ...args);

  // ─────────────────────────────────────────────────────────────────────────
  //  工具函数
  // ─────────────────────────────────────────────────────────────────────────

  /** 等待 predicate() 为真，最多 timeout 毫秒，每 step 毫秒检查一次 */
  function waitFor(predicate, timeout = 5000, step = 100) {
    return new Promise((resolve, reject) => {
      const start = Date.now();
      const tick = () => {
        try {
          const v = predicate();
          if (v) return resolve(v);
        } catch (e) {
          /* ignore */
        }
        if (Date.now() - start > timeout) {
          return reject(new Error(`waitFor 超时：${timeout}ms`));
        }
        setTimeout(tick, step);
      };
      tick();
    });
  }

  /** 在整个文档里查找文本精确匹配且可见的节点（返回最深的那个） */
  function findByText(text, root = document) {
    const walker = document.createTreeWalker(root, NodeFilter.SHOW_ELEMENT, {
      acceptNode(node) {
        if (!node || node.nodeType !== 1) return NodeFilter.FILTER_REJECT;
        // 过滤隐藏节点
        const style = window.getComputedStyle(node);
        if (style.display === 'none' || style.visibility === 'hidden') {
          return NodeFilter.FILTER_REJECT;
        }
        // 只取 "直接文本子节点" 等于目标的
        const direct = Array.from(node.childNodes)
          .filter((n) => n.nodeType === 3)
          .map((n) => n.textContent.trim())
          .join('');
        if (direct === text) return NodeFilter.FILTER_ACCEPT;
        return NodeFilter.FILTER_SKIP;
      },
    });
    const hits = [];
    let cur;
    while ((cur = walker.nextNode())) hits.push(cur);
    // 取最深的（子节点少的）
    hits.sort((a, b) => a.querySelectorAll('*').length - b.querySelectorAll('*').length);
    return hits[0] || null;
  }

  /** hover 一个元素（触发 mouseover + mousemove） */
  function hover(el) {
    const opts = { bubbles: true, cancelable: true, view: window };
    el.dispatchEvent(new MouseEvent('mouseover', opts));
    el.dispatchEvent(new MouseEvent('mousemove', opts));
    el.dispatchEvent(new MouseEvent('mouseenter', opts));
  }

  /** 点击一个元素 */
  function click(el) {
    const rect = el.getBoundingClientRect();
    const opts = {
      bubbles: true,
      cancelable: true,
      view: window,
      clientX: rect.left + rect.width / 2,
      clientY: rect.top + rect.height / 2,
    };
    el.dispatchEvent(new MouseEvent('mousedown', opts));
    el.dispatchEvent(new MouseEvent('mouseup', opts));
    el.dispatchEvent(new MouseEvent('click', opts));
  }

  // ─────────────────────────────────────────────────────────────────────────
  //  核心流程：触发导出
  // ─────────────────────────────────────────────────────────────────────────

  async function exportToDocx() {
    LOG('开始触发导出…');

    // Step 1：点击右上角"菜单"按钮
    //   菜单按钮是一个 aria-label 或 title 为 "菜单" 的按钮，或者有三横线 icon
    const menuBtn =
      document.querySelector('[aria-label="菜单"]') ||
      document.querySelector('[title="菜单"]') ||
      findByText('菜单');
    if (!menuBtn) throw new Error('找不到"菜单"按钮，页面结构可能已变化');
    LOG('菜单按钮:', menuBtn);
    click(menuBtn);

    // Step 2：等菜单展开，找到 "导出为"
    const exportItem = await waitFor(() => findByText('导出为'), 3000);
    LOG('导出为:', exportItem);
    hover(exportItem);
    // hover 后子菜单通常会自动弹出；如果不弹出则强行点击
    await new Promise((r) => setTimeout(r, 200));

    // Step 3：等子菜单，找到 "本地Word文档(.docx)"
    const wordItem = await waitFor(() => {
      // 腾讯文档的文本可能是 "本地Word文档(.docx)" 或 "本地 Word 文档(.docx)"
      const candidates = ['本地Word文档(.docx)', '本地 Word 文档(.docx)', '本地Word文档（.docx）'];
      for (const c of candidates) {
        const el = findByText(c);
        if (el) return el;
      }
      // 退而求其次：包含 "docx" 的节点
      const all = document.querySelectorAll('li, div, span, button');
      for (const el of all) {
        const t = (el.textContent || '').trim();
        if (
          t.length < 30 &&
          t.toLowerCase().includes('docx') &&
          t.includes('Word')
        ) {
          return el;
        }
      }
      return null;
    }, 3000);
    LOG('Word 选项:', wordItem);
    click(wordItem);
    LOG('✅ 已触发导出');

    // 通知 background：这次下载属于我们
    chrome.runtime.sendMessage({
      type: 'export_triggered',
      url: location.href,
      title: document.title.replace(/\s*-\s*(腾讯文档|企业微信文档).*$/, '').trim(),
    });
  }

  // ─────────────────────────────────────────────────────────────────────────
  //  注入浮动按钮
  // ─────────────────────────────────────────────────────────────────────────

  function injectButton() {
    if (document.getElementById('tencdoc2md-btn')) return;
    const btn = document.createElement('button');
    btn.id = 'tencdoc2md-btn';
    btn.textContent = '→ Obsidian';
    btn.title = 'TencDoc → Obsidian Markdown（导出 docx 并转换）';
    btn.addEventListener('click', async () => {
      btn.disabled = true;
      btn.dataset.status = 'working';
      btn.textContent = '导出中…';
      try {
        await exportToDocx();
        btn.textContent = '已触发 · 等待转换';
        btn.dataset.status = 'waiting';
      } catch (e) {
        ERR(e);
        btn.textContent = '失败：' + e.message.slice(0, 20);
        btn.dataset.status = 'error';
        alert(
          'TencDoc→MD：无法自动触发导出。\n\n' +
            '可能原因：\n' +
            '  1. 页面还没加载完\n' +
            '  2. 你对这个文档没有导出权限\n' +
            '  3. 腾讯文档 DOM 结构变化了\n\n' +
            '错误详情：' + e.message
        );
      }
      // 3 秒后恢复
      setTimeout(() => {
        btn.disabled = false;
        btn.textContent = '→ Obsidian';
        btn.dataset.status = 'idle';
      }, 3000);
    });
    document.body.appendChild(btn);

    // 监听 background 的回调，更新按钮状态
    chrome.runtime.onMessage.addListener((msg) => {
      if (msg.type === 'convert_done') {
        btn.textContent = '✅ 已转换';
        btn.dataset.status = 'done';
        setTimeout(() => {
          btn.textContent = '→ Obsidian';
          btn.dataset.status = 'idle';
        }, 4000);
      } else if (msg.type === 'convert_error') {
        btn.textContent = '转换失败';
        btn.dataset.status = 'error';
        alert('TencDoc→MD 转换失败：\n' + (msg.error || '未知错误'));
      }
    });
  }

  // URL 变化时（SPA 切换文档）重新注入
  let lastHref = location.href;
  new MutationObserver(() => {
    if (location.href !== lastHref) {
      lastHref = location.href;
      setTimeout(injectButton, 1000);
    }
  }).observe(document, { subtree: true, childList: true });

  // 首次注入
  if (document.body) {
    injectButton();
  } else {
    window.addEventListener('DOMContentLoaded', injectButton);
  }
})();
