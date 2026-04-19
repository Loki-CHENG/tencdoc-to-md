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

  /** 元素是否"真的可见"：尺寸>0 + 在视口附近（坐标不是负大数 / 超大坐标） */
  function isRealVisible(el) {
    if (!el || !el.getBoundingClientRect) return false;
    const r = el.getBoundingClientRect();
    if (r.width === 0 || r.height === 0) return false;
    // 腾讯文档会把离屏 DOM 放在 x=-9999 / -100000 这种位置，过滤掉
    if (r.x < -1000 || r.y < -1000) return false;
    if (r.x > window.innerWidth + 1000 || r.y > window.innerHeight + 1000) return false;
    const style = window.getComputedStyle(el);
    if (style.display === 'none' || style.visibility === 'hidden' || parseFloat(style.opacity) === 0) {
      return false;
    }
    return true;
  }

  /** 在整个文档里查找文本精确匹配且可见的节点 */
  function findByText(text, root = document) {
    // 1. 用属性快速筛候选（文本可能在 LI / DIV / SPAN / BUTTON 等）
    const candidates = root.querySelectorAll('li, div, span, button, a, [role="menuitem"]');
    const hits = [];
    for (const el of candidates) {
      // 直接文本子节点拼接
      const direct = Array.from(el.childNodes)
        .filter((n) => n.nodeType === 3)
        .map((n) => n.textContent.trim())
        .filter(Boolean)
        .join('');
      const allText = (el.textContent || '').trim();
      // 精确匹配：直接文本 === text，或 整个 textContent === text
      if (direct === text || allText === text) {
        if (isRealVisible(el)) hits.push(el);
      }
    }
    if (!hits.length) return null;
    // 优先选内部 element 最少的（更接近菜单项本体），其次选 y 坐标更小的（更靠上）
    hits.sort((a, b) => {
      const da = a.querySelectorAll('*').length;
      const db = b.querySelectorAll('*').length;
      if (da !== db) return da - db;
      return a.getBoundingClientRect().y - b.getBoundingClientRect().y;
    });
    return hits[0];
  }

  /** 用"包含文本"而不是"精确匹配"找 —— 用于子菜单项可能带图标/扩展名的场景 */
  function findByTextIncludes(substr, maxLen = 30, root = document) {
    const candidates = root.querySelectorAll('li, div, span, button, a, [role="menuitem"]');
    const hits = [];
    for (const el of candidates) {
      const t = (el.textContent || '').trim();
      if (!t || t.length > maxLen) continue;
      if (!t.includes(substr)) continue;
      if (!isRealVisible(el)) continue;
      hits.push(el);
    }
    if (!hits.length) return null;
    hits.sort((a, b) => a.querySelectorAll('*').length - b.querySelectorAll('*').length);
    return hits[0];
  }

  /** hover 一个元素 —— 发完整的 pointer + mouse 事件序列，模拟真实鼠标进入 */
  function hover(el) {
    const rect = el.getBoundingClientRect();
    const x = rect.left + rect.width / 2;
    const y = rect.top + rect.height / 2;
    const opts = {
      bubbles: true,
      cancelable: true,
      view: window,
      clientX: x,
      clientY: y,
      screenX: x,
      screenY: y,
      button: 0,
      buttons: 0,
    };
    // 先触发 body-level 的 pointermove（很多菜单库监听全局 pointermove 来判定 hover）
    document.dispatchEvent(new PointerEvent('pointermove', { ...opts, pointerType: 'mouse' }));
    // 再触发元素本体的 pointerover / pointerenter / mouseover / mouseenter / mousemove
    el.dispatchEvent(new PointerEvent('pointerover', { ...opts, pointerType: 'mouse' }));
    el.dispatchEvent(new PointerEvent('pointerenter', { ...opts, pointerType: 'mouse' }));
    el.dispatchEvent(new MouseEvent('mouseover', opts));
    el.dispatchEvent(new MouseEvent('mouseenter', opts));
    el.dispatchEvent(new MouseEvent('mousemove', opts));
    el.dispatchEvent(new PointerEvent('pointermove', { ...opts, pointerType: 'mouse' }));
  }

  /** 发键盘事件（某些组件用键盘导航更可靠） */
  function pressKey(target, key, keyCode) {
    // 对应 code 映射
    const codeMap = {
      ArrowDown: 'ArrowDown',
      ArrowUp: 'ArrowUp',
      ArrowLeft: 'ArrowLeft',
      ArrowRight: 'ArrowRight',
      Enter: 'Enter',
      Escape: 'Escape',
      Tab: 'Tab',
    };
    const opts = {
      key,
      code: codeMap[key] || key,
      keyCode,
      which: keyCode,
      bubbles: true,
      cancelable: true,
      composed: true,
    };
    target.dispatchEvent(new KeyboardEvent('keydown', opts));
    target.dispatchEvent(new KeyboardEvent('keypress', opts));
    target.dispatchEvent(new KeyboardEvent('keyup', opts));
  }

  /** 给一级菜单里的 LI 打开子菜单
   *  诊断发现：
   *    - pointer 事件触发后会给 LI 加上 "dui-menu-submenu-visible" 类
   *    - 子菜单 DOM 其实已经渲染（实验证明找得到 "本地Word文档(.docx)" 元素）
   *    - 所以核心是：发一次完整的 pointer 序列，然后等 class 变化
   */
  async function openSubMenu(exportItem) {
    // 先 hover 两次，确保 pointerover/enter/mousemove 都被监听到
    hover(exportItem);
    await sleep(30);
    hover(exportItem);

    // 兜底：如果 Dui 内部状态更新失败，手动加 visible 类
    //   （实验验证：即使手动加这个 class，子菜单 DOM 也已经有了可点击的元素）
    exportItem.classList.add('dui-menu-submenu-visible');

    // 给 LI focus（某些实现依赖 focus 激活键盘路径）
    if (typeof exportItem.focus === 'function') {
      try { exportItem.focus({ preventScroll: true }); } catch { /* ignore */ }
    }

    // 让事件在父容器上也发一次（有些菜单组件在 UL/MENU 上做事件代理）
    const ul = exportItem.closest('ul, [role="menu"]');
    if (ul) {
      // 向父 UL 派发 pointermove，让它更新"当前悬浮项"
      const r = exportItem.getBoundingClientRect();
      const x = r.left + r.width / 2, y = r.top + r.height / 2;
      const opts = { bubbles: true, cancelable: true, view: window, clientX: x, clientY: y, screenX: x, screenY: y, button: 0, buttons: 0 };
      ul.dispatchEvent(new PointerEvent('pointermove', { ...opts, pointerType: 'mouse' }));
      ul.dispatchEvent(new MouseEvent('mousemove', opts));
    }
  }

  function sleep(ms) {
    return new Promise((r) => setTimeout(r, ms));
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

  /** 找到右上角"文件操作"按钮 —— 返回元素（不是坐标，留给调用方决定怎么用）
   *
   *  历史变更：
   *    旧版：右上角按钮 id 就是 #headerbar-filemenu，本身就是可点击的汉堡按钮
   *    新版（≥2026-04）：#headerbar-filemenu 退化为外层容器（display: var(--display)），
   *                      真正的可点击触发器是它内部的 #main-menu-file，带 aria-haspopup="true"
   *    两者 getBoundingClientRect() 完全一致（容器和按钮重合），所以只要点中坐标都行；
   *    优先用 main-menu-file 是因为它的语义更明确，未来也更稳定。
   */
  function findMenuButton() {
    const tries = [
      // 新版语义按钮（aria-haspopup="true"，菜单触发器）
      () => document.getElementById('main-menu-file'),
      // 兜底：任何 menu-button-file 类的可见节点
      () => [...document.querySelectorAll('[class*="menu-button-file"]')]
              .find((el) => isRealVisible(el) && el.getAttribute('aria-haspopup') === 'true'),
      // 老版：headerbar-filemenu 本身可点
      () => document.getElementById('headerbar-filemenu'),
      // aria 兜底
      () => [...document.querySelectorAll('[aria-label*="文件操作"]')].find(isRealVisible),
      () => [...document.querySelectorAll('[aria-label="菜单"]')].find((el) => {
        if (!isRealVisible(el)) return false;
        const r = el.getBoundingClientRect();
        return r.x > window.innerWidth / 2;
      }),
    ];
    for (const fn of tries) {
      try {
        const el = fn();
        if (el && isRealVisible(el)) return el;
      } catch { /* ignore */ }
    }
    return null;
  }

  /** 等右上角菜单按钮就绪 —— 用户点扩展按钮时页面可能还没加载完 */
  async function waitForMenuButton(timeout = 8000) {
    return waitFor(() => findMenuButton(), timeout, 150);
  }

  /** 从元素获取可点击的 viewport 坐标（中心点） */
  function centerOf(el) {
    const r = el.getBoundingClientRect();
    return { x: Math.round(r.left + r.width / 2), y: Math.round(r.top + r.height / 2) };
  }

  /**
   * 通过 background service worker + chrome.debugger 发真实鼠标事件。
   * 这是唯一能过 CSS :hover 和 React isTrusted 的方式（content-script 的 dispatchEvent 无效）。
   *
   * session: 'begin' / 'continue' / 'end' —— 让 background 把 debugger attach 维持
   *   一整个导出会话，否则 keepAlive 循环里多次并发 attach 会互相拒绝。
   *   不传 session 则走老行为（每次 attach+detach）。
   */
  async function sendRealMouse(steps, session) {
    return new Promise((resolve, reject) => {
      chrome.runtime.sendMessage({ type: 'real_mouse_export', steps, session }, (resp) => {
        if (chrome.runtime.lastError) return reject(new Error(chrome.runtime.lastError.message));
        if (!resp || !resp.ok) return reject(new Error((resp && resp.error) || 'real_mouse_export 失败'));
        resolve(resp);
      });
    });
  }

  /** 强制清理 debugger 连接（失败恢复用） */
  async function forceDetachMouse() {
    return new Promise((resolve) => {
      chrome.runtime.sendMessage({ type: 'real_mouse_detach' }, () => resolve());
    });
  }

  async function exportToDocx() {
    LOG('开始触发导出…');

    // Step 1：等右上角"文件操作"按钮出现
    //   诊断发现：新版 DOM 里真正的触发器是 #main-menu-file（aria-haspopup="true"），
    //   #headerbar-filemenu 退化成了外层容器（坐标相同），findMenuButton 已优先找前者。
    //   用户点扩展按钮时页面可能还没加载完，给 8s 宽限。
    const menuBtn = await waitForMenuButton(8000).catch(() => null);
    if (!menuBtn) {
      throw new Error('找不到右上角"文件操作"按钮（#main-menu-file / #headerbar-filemenu 都没出现，请等页面加载完再试）');
    }
    const menuBtnPos = centerOf(menuBtn);
    LOG('菜单按钮:', menuBtn, menuBtnPos, 'id:', menuBtn.id, 'aria-label:', menuBtn.getAttribute('aria-label'));

    // Step 2：通过 background 用 chrome.debugger 发真实鼠标点击菜单按钮
    //   —— content-script 的 dispatchEvent 过不了 CSS :hover / React isTrusted，
    //      必须用 chrome.debugger + CDP Input.dispatchMouseEvent。
    //   用 session='begin' 让 background attach debugger 并"保持连接"，
    //   后续 keepAlive 循环 / 点 docx 都复用这个连接，不再重复 attach。
    LOG('→ 真实鼠标点击菜单按钮');
    await sendRealMouse([
      { action: 'move', x: menuBtnPos.x, y: menuBtnPos.y, delay: 100 },
      { action: 'click', x: menuBtnPos.x, y: menuBtnPos.y, delay: 300 },
    ], 'begin');
    // 等菜单动画 + DOM 挂载
    await sleep(300);

    // Step 3：在已展开的菜单里找到 "导出为" LI，拿到屏幕坐标
    const exportItem = await waitFor(() => {
      // 专属 class：mainmenu-submenu-export-as
      const cand = [...document.querySelectorAll('[class*="mainmenu-submenu-export-as"]')]
        .filter((el) => {
          if (!isRealVisible(el)) return false;
          const r = el.getBoundingClientRect();
          // 真正展开后的菜单项 x 不会是 0 或 1（那是初始化位置）
          return r.x > 2 && r.width > 0 && r.height > 0;
        })
        .sort((a, b) => b.getBoundingClientRect().x - a.getBoundingClientRect().x);
      if (cand.length > 0) return cand[0];

      // 退一步：li.dui-menu-submenu + 文本为"导出为"
      for (const el of document.querySelectorAll('li.dui-menu-submenu')) {
        if ((el.textContent || '').trim() !== '导出为') continue;
        if (!isRealVisible(el)) continue;
        const r = el.getBoundingClientRect();
        if (r.x > 2) return el;
      }
      return null;
    }, 4000).catch(() => {
      throw new Error(
        '菜单展开后找不到"导出为" LI（.mainmenu-submenu-export-as）。' +
        '可能原因：一级菜单其实没打开（CDP 点击被拒），或腾讯文档又改了 class。'
      );
    });
    const exportPos = centerOf(exportItem);
    LOG('导出为 LI:', exportItem, exportPos, 'cls:', exportItem.className);

    // Step 4：真实鼠标移到"导出为"（触发 :hover → Dui 才会挂载子菜单 DOM）
    //   诊断证实：没 hover 过时，.mainmenu-item-export-as-docx 节点根本不在 DOM 里，
    //   需要真实鼠标 move 让 Dui React 组件进入 hover 状态后才渲染子菜单。
    //   session='continue' 复用 begin 时的 attach，不再重复 attach。
    LOG('→ 真实鼠标 hover "导出为"');
    await sendRealMouse([
      { action: 'move', x: exportPos.x, y: exportPos.y, delay: 400 },
    ], 'continue');

    // 启动"保活"：周期性地用真实鼠标再 move 到"导出为"坐标，
    // 防止在 DOM 查找的空档里 Dui 认为鼠标离开了而收起子菜单。
    // 以前只 dispatchEvent 合成事件 + classList 兜底 —— 那对 Dui 的 React hover 状态没有用，
    // 只有 CDP 真鼠标才能维持 isTrusted 的 hover state。
    //
    // 全部用 session='continue'，复用同一个 debugger attach，避免重复 attach 自撞。
    let keepAlive = true;
    const keepAliveLoop = (async () => {
      while (keepAlive) {
        try {
          // 真实 CDP move 到"导出为"中心，维持 React hover 状态 → 子菜单保持渲染
          await sendRealMouse([
            { action: 'move', x: exportPos.x, y: exportPos.y, delay: 0 },
          ], 'continue');
          // 同时兜底：加 visible 类 + dispatch 合成事件（双保险）
          hover(exportItem);
          exportItem.classList.add('dui-menu-submenu-visible');
        } catch { /* ignore */ }
        await sleep(200);
      }
    })();

    // Step 5：等子菜单里的 docx 选项出现在 DOM 里（真 hover 后它才渲染）
    //   超时从 4s 延到 8s —— 某些慢文档里 Dui 组件挂载子菜单需要的时间不止 4s。
    const wordItem = await waitFor(() => {
      // 专属 class：mainmenu-item-export-as-docx
      const cand = [...document.querySelectorAll('li.mainmenu-item-export-as-docx, [class*="mainmenu-item-export-as-docx"]')]
        .filter((el) => {
          if (!isRealVisible(el)) return false;
          const r = el.getBoundingClientRect();
          return r.x > 2 && r.width > 0 && r.height > 0;
        });
      if (cand.length > 0) return cand[0];

      // 退一步：文本匹配
      for (const el of document.querySelectorAll('li.dui-menu-item')) {
        const t = (el.textContent || '').trim();
        if (!isRealVisible(el)) continue;
        if (el.classList.contains('dui-menu-submenu')) continue; // 排除 "导出为" 本身
        if (t === '本地Word文档(.docx)' || t === '本地 Word 文档(.docx)' || t === '本地Word文档（.docx）') {
          const r = el.getBoundingClientRect();
          if (r.x > 2) return el;
        }
      }
      return null;
    }, 8000).catch(async () => {
      // 先停 keepAlive 循环并等它退出，让在飞的 CDP 调用落地，
      // 外层 catch 再 forceDetachMouse 时才不会跟循环里的 move 抢连接。
      keepAlive = false;
      try { await keepAliveLoop; } catch { /* ignore */ }
      // 给出可诊断的错误：DOM 里到底有没有 docx 节点
      const hasNode = !!document.querySelector('.mainmenu-item-export-as-docx');
      const nodeInfo = hasNode ? 'DOM 里有 docx 节点但不可见（可能被 opacity/transform 隐藏）' : 'DOM 里根本没有 docx 节点（Dui 没认可 hover 状态）';
      throw new Error(`等 docx 选项超时 8s：${nodeInfo}`);
    });
    const wordPos = centerOf(wordItem);
    LOG('Word 选项:', wordItem, wordPos, 'cls:', wordItem.className);

    // Step 6：真实鼠标移到 docx 选项 + 点击
    //   先停掉 keepAlive 循环，避免它跟最后这次 CDP 调用并发抢连接
    //   session='end' 让 background 在这次调用结束后 detach debugger（收起黄条）
    keepAlive = false;
    await keepAliveLoop;
    LOG('→ 真实鼠标点击 docx 选项');
    await sendRealMouse([
      { action: 'move', x: wordPos.x, y: wordPos.y, delay: 100 },
      { action: 'click', x: wordPos.x, y: wordPos.y, delay: 100 },
    ], 'end');
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

  // 模块级：最近一次成功的 md_path（右键随时能复制，不受 UI 状态影响）
  let lastMdPath = '';

  function injectButton() {
    if (document.getElementById('tencdoc2md-btn')) return;
    const btn = document.createElement('button');
    btn.id = 'tencdoc2md-btn';
    btn.textContent = '→ Obsidian';
    btn.title = 'TencDoc → Obsidian（左键导出 · 右键复制上次路径）';

    btn.addEventListener('click', async () => {
      // done 状态下左键 = 复制路径
      if (btn.dataset.status === 'done' && lastMdPath) {
        try {
          await navigator.clipboard.writeText(lastMdPath);
          const prev = btn.textContent;
          btn.textContent = '📋 路径已复制';
          setTimeout(() => { btn.textContent = prev; }, 1200);
        } catch (err) { console.warn('复制失败', err); }
        return;
      }
      btn.disabled = true;
      btn.dataset.status = 'working';
      btn.textContent = '导出中…';
      try {
        await exportToDocx();
        btn.textContent = '已触发 · 等待转换';
        btn.dataset.status = 'waiting';
      } catch (e) {
        ERR(e);
        // 失败恢复：不管在哪一步挂的，强制 detach debugger，避免黄条一直挂着
        // + 下次点按钮时 attach 失败（"already attached"）。
        try { await forceDetachMouse(); } catch { /* ignore */ }
        btn.textContent = '失败：' + e.message.slice(0, 20);
        btn.dataset.status = 'error';
        alert(
          'TencDoc→MD：无法自动触发导出。\n\n' +
            '可能原因：\n' +
            '  1. 页面还没加载完\n' +
            '  2. 你对这个文档没有导出权限\n' +
            '  3. 腾讯文档 DOM 结构变化了\n' +
            '  4. chrome.debugger 冲突（DevTools 或另一扩展已 attach）\n\n' +
            '错误详情：' + e.message
        );
      }
      // 只在 error/working 状态下才重置；done/waiting 由回调接管
      setTimeout(() => {
        if (btn.dataset.status === 'error' || btn.dataset.status === 'working') {
          btn.disabled = false;
          btn.textContent = '→ Obsidian';
          btn.dataset.status = 'idle';
        }
      }, 3000);
    });

    // 右键：无论当前状态，都复制最近一次路径
    btn.addEventListener('contextmenu', async (e) => {
      e.preventDefault();
      if (!lastMdPath) { alert('还没有成功转换过文档。'); return; }
      try {
        await navigator.clipboard.writeText(lastMdPath);
        const prev = btn.textContent;
        btn.textContent = '📋 已复制';
        setTimeout(() => { btn.textContent = prev; }, 1200);
      } catch (err) { console.warn('复制失败', err); }
    });

    document.body.appendChild(btn);

    // 监听 background 的回调，更新按钮状态
    chrome.runtime.onMessage.addListener((msg) => {
      if (msg.type === 'convert_done') {
        btn.disabled = false;
        btn.dataset.status = 'done';
        lastMdPath = msg.md_path || '';
        btn.textContent = lastMdPath ? '✅ 已转换 · 点此复制路径' : '✅ 已转换';
        if (lastMdPath) {
          btn.title = '已保存到：\n' + lastMdPath + '\n\n左键或右键 = 复制路径';
          LOG('✅ md_path:', lastMdPath);
        } else {
          btn.title = '转换成功，但 host 没回传路径。请打开 options 查看 vault/output_dir。';
        }
        setTimeout(() => {
          if (btn.dataset.status === 'done') {
            btn.textContent = '→ Obsidian';
            btn.dataset.status = 'idle';
            btn.title = 'TencDoc → Obsidian（左键导出 · 右键复制上次路径）';
          }
        }, 8000);
      } else if (msg.type === 'convert_error') {
        btn.disabled = false;
        btn.textContent = '转换失败';
        btn.dataset.status = 'error';
        alert('TencDoc→MD 转换失败：\n' + (msg.error || '未知错误'));
      }
    });
  }

  // ─────────────────────────────────────────────────────────────────────────
  //  Frame 选择：腾讯文档把编辑器渲染在一个 id="very_fast_inner" 的 iframe 里
  //  manifest 用 all_frames: true 注入，但只有"能找到编辑器 DOM 的 frame"才注入按钮，
  //  否则顶层 frame 也会画一个按钮，跟 iframe 里的按钮叠在一起。
  // ─────────────────────────────────────────────────────────────────────────
  function isEditorFrame() {
    // 编辑器 frame 才会有这些 id（即便页面还没完全加载，至少有一个能找到说明结构正确）
    if (document.getElementById('main-menu-file')) return true;
    if (document.getElementById('headerbar-filemenu')) return true;
    if (document.querySelector('[class*="menu-button-file"]')) return true;
    return false;
  }

  /**
   * 等编辑器 DOM 出现，最多等 timeout ms。
   * 用 MutationObserver + 轮询双保险（腾讯文档的菜单挂载时机不稳定）。
   */
  function waitForEditorFrame(timeout = 15000) {
    return new Promise((resolve) => {
      if (isEditorFrame()) return resolve(true);
      const start = Date.now();
      const obs = new MutationObserver(() => {
        if (isEditorFrame()) {
          obs.disconnect();
          clearInterval(timer);
          resolve(true);
        }
      });
      obs.observe(document.documentElement, { subtree: true, childList: true });
      // 兜底轮询（有时 MutationObserver 错过事件）
      const timer = setInterval(() => {
        if (isEditorFrame()) {
          obs.disconnect();
          clearInterval(timer);
          resolve(true);
        } else if (Date.now() - start > timeout) {
          obs.disconnect();
          clearInterval(timer);
          resolve(false);
        }
      }, 300);
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

  // 首次注入：只在编辑器 frame 里注入按钮
  //   非编辑器 frame（顶层壳）静默退出，但 content script 仍然在跑（无害）
  (async () => {
    const ready = await waitForEditorFrame(15000);
    if (!ready) {
      // 不是编辑器 frame —— 比如这是顶层壳 frame，编辑器在子 iframe 里
      // 那个子 iframe 也注入了 content script，按钮会由它来挂
      LOG('当前 frame 不是编辑器（', location.href.slice(0, 80), '），跳过按钮注入');
      return;
    }
    LOG('当前 frame 是编辑器（', location.href.slice(0, 80), '），注入浮动按钮');
    if (document.body) {
      injectButton();
    } else {
      window.addEventListener('DOMContentLoaded', injectButton);
    }
  })();
})();
