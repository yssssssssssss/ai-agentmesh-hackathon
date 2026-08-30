---
name: plugin-api-key-ai
description: 为 Relay/Zero 插件接入用户自定义 API Key 调用 AI（LLM）的完整实现方案。覆盖 clientStorage 跨会话持久化 Key、ui.html/code.ts 通过 postMessage 通信、本地
  CORS 代理解决浏览器跨域。当用户想给自己的 Relay/Zero 插件加 AI 能力、让用户填自己的 Claude/GPT API Key、需要持久化密钥或解决插件调 LLM 的跨域限制时触发。
metadata:
  author: 2C-DesignWiki
  source: 2C-DesignWiki/.agents/skills/plugin-api-key-ai/SKILL.md
  agentmesh-wiki-import: 'true'
  agentmesh-stage: during_design
  agentmesh-activation: explicit_only
  short-description: 为 Relay/Zero 插件接入用户自定义 API Key 调用 AI（LLM）的完整实现方案。覆盖 clientStorage 跨会话持久化 Key、ui.html/code.ts 通过 pos…
disable-model-invocation: true
---

# Skill: 为 Relay/Zero 插件添加用户自定义 API Key 连接 AI

> 当用户想给自己的 Relay/Zero 插件接入 AI 能力（通过用户输入自己的 API Key 调用 LLM），调用本 skill 获得完整实现方案。

---

## 适用场景

- 插件需要调用外部 LLM API（如 Claude / GPT）
- 每个用户使用自己的 API Key，不共享密钥
- 需要跨会话持久化 Key（关闭重开不用重输）
- 需要本地 CORS 代理解决浏览器跨域限制

---

## 架构概览

```
┌─────────────────────────────────────────────────────┐
│  Relay 插件                                          │
│                                                     │
│  ┌──────────┐   postMessage    ┌──────────────┐    │
│  │ code.ts  │ ◄──────────────► │   ui.html    │    │
│  │          │                  │              │    │
│  │ clientStorage              │ fetch + Key   │    │
│  │ (持久化 Key)               │ (调 AI API)   │    │
│  └──────────┘                  └──────┬───────┘    │
└───────────────────────────────────────┼────────────┘
                                        │ HTTP
                                        ▼
                              ┌──────────────────┐
                              │ proxy.cjs (本地)  │
                              │  localhost:3456   │
                              │  加 CORS 头       │
                              │  转发到 LLM 网关   │
                              └──────────────────┘
                                        │
                                        ▼
                              ┌──────────────────┐
                              │  LLM API 网关     │
                              │  (如 llm-gw.jd.  │
                              │   local 或公网)   │
                              └──────────────────┘
```

**关键设计决策：**
1. API Key 存储在 `figma.clientStorage`（等同 Relay clientStorage），跨会话持久化
2. AI 请求从 `ui.html`（iframe）发出，因为 `code.ts`（sandbox）没有 `fetch`
3. 本地 CORS 代理解决跨域问题（插件 iframe → localhost → LLM 网关）
4. manifest.json 需声明 `"networkAccess": { "allowedDomains": ["*"] }`
5. 代理文件使用 `.cjs` 扩展名，避免 ESM/CommonJS 冲突

---

## 双模式设计（推荐）

基于 ai-friendly-design 实际接入经验，推荐「内置 AI 为主 + 个人 Key 为备」的双模式架构：

- **默认模式**：使用 Zero/Relay 内置 AI 接口（pluginLLM），零配置即用
- **回退模式**：用户自带 API Key + 本地代理，不依赖平台 AI 能力

**入口设计原则：**
- **不要用启动页全屏拦截**（用户大部分时候用默认模式，全屏拦截打断正常流程）
- **用标题右侧齿轮按钮 → 覆盖层设置面板**（非侵入，按需打开）
- 面板内用 Radio 切换 `zero` / `custom` 模式，选 `custom` 才展开 Key 输入框
- 切回 `zero` 时已保存的 Key 不清除（方便来回切）

---

## 实现步骤

### 第 1 步：manifest.json 配置网络权限

```json
{
  "name": "你的插件名",
  "id": "your-plugin-id",
  "api": "1.0.0",
  "main": "code.js",
  "ui": "ui.html",
  "editorType": ["figma"],
  "networkAccess": {
    "allowedDomains": ["*"]
  }
}
```

**说明：**
- `"allowedDomains": ["*"]` 最省事，允许 ui.html 中的 fetch 访问任何域名
- 若需精确控制，`localhost` 必须显式列出（部分平台版本默认拒绝 localhost）
- 缺少此配置时 fetch 静默失败，无任何报错——这是最常见的坑

---

### 第 2 步：code.ts — clientStorage 读写 AI 配置

在 `figma.ui.onmessage` 中添加消息处理。**键名必须加插件前缀**，避免多插件共存踩踏：

```typescript
const STORAGE_PREFIX = 'your-plugin-id';  // 用 manifest.json 中的 id

figma.ui.onmessage = async (msg: { type: string; mode?: string; key?: string; [k: string]: any }) => {
  if (msg.type === 'get-ai-config') {
    const mode = await figma.clientStorage.getAsync(`${STORAGE_PREFIX}:ai-mode`)
    const key = await figma.clientStorage.getAsync(`${STORAGE_PREFIX}:ai-api-key`)
    figma.ui.postMessage({ type: 'ai-config-loaded', mode: mode || 'zero', key: key || '' })
    return
  }

  if (msg.type === 'save-ai-config') {
    await figma.clientStorage.setAsync(`${STORAGE_PREFIX}:ai-mode`, msg.mode || 'zero')
    await figma.clientStorage.setAsync(`${STORAGE_PREFIX}:ai-api-key`, msg.key || '')
    figma.ui.postMessage({ type: 'ai-config-saved' })
    return
  }

  // ... 你的其他消息处理
}
```

**要点：**
- `figma.clientStorage` 是每用户、每插件的本地持久存储，异步 API
- 键名格式 `<plugin-id>:ai-api-key`，多插件共存时不会互相覆盖
- Zero/Relay 若不支持 clientStorage，需用 `try {} catch(_) {}` 包起来退化到 pluginData

---

### 第 3 步：ui.html — 设置面板模式（推荐）

#### 3.1 设置按钮 + 覆盖层 DOM

```html
<!-- 主面板标题区（设置齿轮内联在标题右侧） -->
<h1 class="title">你的插件名 <button id="btnSettings" class="settings-btn" title="设置">⚙</button></h1>

<!-- API Key 覆盖层（初始隐藏） -->
<div class="key-page hidden" id="keyPage">
  <div class="key-page-inner">
    <div class="key-page-header">
      <h2>AI 接入设置</h2>
      <button id="btnKeyClose" class="key-close">✕</button>
    </div>

    <div class="key-mode-switch">
      <label><input type="radio" name="aiMode" value="zero" checked> 使用 Zero 内置 AI（推荐）</label>
      <label><input type="radio" name="aiMode" value="custom"> 使用个人 API Key</label>
    </div>

    <div class="key-custom-wrap hidden" id="keyCustomWrap">
      <p>输入你的 API Key，AI 请求将走本地代理转发到 LLM 网关。</p>
      <input type="password" id="keyPageInput" placeholder="请输入 API Key">
      <div class="key-hint">代理地址：<code>http://localhost:3456</code>，需本地运行 <code>node proxy.cjs</code></div>
    </div>

    <div class="key-btn-group">
      <button class="btn btn-primary" id="btnKeySave">保存</button>
      <button class="btn" id="btnKeyTestConnect">测试连接</button>
      <button class="btn" id="btnKeyCancel">取消</button>
    </div>
    <div class="key-warning hidden" id="keyWarning"></div>
  </div>
</div>
```

#### 3.2 样式

```css
.settings-btn {
  display: inline-flex; align-items: center; justify-content: center;
  width: 24px; height: 24px; border: none; background: transparent;
  cursor: pointer; font-size: 14px; color: #666; vertical-align: middle;
  margin-left: 6px; border-radius: 4px;
}
.settings-btn:hover { color: #2563eb; }

.key-page {
  position: fixed; inset: 0; background: rgba(0,0,0,0.35); z-index: 100;
  display: flex; align-items: center; justify-content: center;
}
.key-page.hidden { display: none !important; }
.key-page-inner {
  width: 380px; background: #fff; border-radius: 8px; padding: 20px;
  box-shadow: 0 8px 24px rgba(0,0,0,0.15);
}
.key-page-header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 16px; }
.key-page-header h2 { font-size: 14px; font-weight: 700; margin: 0; }
.key-close { border: none; background: none; cursor: pointer; font-size: 16px; color: #999; }
.key-mode-switch { display: flex; flex-direction: column; gap: 8px; margin-bottom: 16px; }
.key-mode-switch label { font-size: 12px; cursor: pointer; }
.key-custom-wrap { margin-bottom: 16px; }
.key-custom-wrap.hidden { display: none; }
.key-custom-wrap p { font-size: 11px; color: #666; margin-bottom: 8px; }
.key-custom-wrap input {
  width: 100%; height: 32px; padding: 0 10px;
  border: 1px solid #ddd; border-radius: 4px; font-size: 12px; outline: none;
}
.key-custom-wrap input:focus { border-color: #2563eb; }
.key-hint { font-size: 10px; color: #999; margin-top: 6px; }
.key-hint code { background: #f5f5f5; padding: 1px 4px; border-radius: 2px; }
.key-btn-group { display: flex; gap: 8px; }
.key-btn-group button { flex: 1; height: 32px; border-radius: 8px; font-weight: 700; }
.key-warning {
  margin-top: 12px; padding: 8px 12px; border-radius: 4px;
  background: #fffbeb; border: 1px solid #fde68a; font-size: 11px; color: #92400e;
}
.key-warning.hidden { display: none; }
.key-warning.success { background: #f0fdf4; border-color: #bbf7d0; color: #166534; }
```

#### 3.3 设置面板逻辑

```javascript
const AI_PROXY_URL = 'http://localhost:3456/anthropic/v1/messages';
const AI_MODEL = 'Claude-Opus-4.7-joybuilder';

let aiMode = 'zero';   // 'zero' | 'custom'
let aiApiKey = '';

// 启动时向 code.js 请求已保存的设置
parent.postMessage({ pluginMessage: { type: 'get-ai-config' } }, '*');

// 打开设置面板
document.getElementById('btnSettings').onclick = () => {
  document.querySelector(`input[name="aiMode"][value="${aiMode}"]`).checked = true;
  document.getElementById('keyPageInput').value = aiApiKey;
  document.getElementById('keyCustomWrap').classList.toggle('hidden', aiMode !== 'custom');
  document.getElementById('keyPage').classList.remove('hidden');
  document.getElementById('keyWarning').classList.add('hidden');
};

// 关闭/取消
document.getElementById('btnKeyClose').onclick =
document.getElementById('btnKeyCancel').onclick = () => {
  document.getElementById('keyPage').classList.add('hidden');
};

// 切换模式
document.querySelectorAll('input[name="aiMode"]').forEach(r => {
  r.onchange = (e) => {
    document.getElementById('keyCustomWrap').classList.toggle('hidden', e.target.value !== 'custom');
  };
});

// 保存
document.getElementById('btnKeySave').onclick = () => {
  const mode = document.querySelector('input[name="aiMode"]:checked').value;
  const key = document.getElementById('keyPageInput').value.trim();
  if (mode === 'custom' && !key) {
    showKeyWarning('请输入 API Key', 'error');
    return;
  }
  aiMode = mode;
  aiApiKey = key;
  parent.postMessage({ pluginMessage: { type: 'save-ai-config', mode, key } }, '*');
  document.getElementById('keyPage').classList.add('hidden');
};

// 接收 code.js 回传
window.addEventListener('message', (event) => {
  const msg = event.data && event.data.pluginMessage;
  if (!msg) return;
  if (msg.type === 'ai-config-loaded') {
    aiMode = msg.mode || 'zero';
    aiApiKey = msg.key || '';
  }
});

function showKeyWarning(text, type) {
  const el = document.getElementById('keyWarning');
  el.textContent = text;
  el.className = 'key-warning' + (type === 'success' ? ' success' : '');
  setTimeout(() => el.classList.add('hidden'), 4000);
}
```

#### 3.4 AI API 调用函数

```javascript
async function callAI(systemPrompt, userPrompt) {
  if (aiMode === 'custom') {
    return callAICustom(systemPrompt, userPrompt);
  }
  // 默认走 Zero 内置 AI（由 code.js 侧的 pluginLLM 处理）
  return null;
}

async function callAICustom(systemPrompt, userPrompt) {
  if (!aiApiKey) throw new Error('未设置 API Key');

  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), 120000);

  try {
    const response = await fetch(AI_PROXY_URL, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'Authorization': 'Bearer ' + aiApiKey
      },
      body: JSON.stringify({
        model: AI_MODEL,
        system: systemPrompt,
        messages: [{ role: 'user', content: userPrompt }],
        max_tokens: 4096,
        stream: false  // 必须 false，iframe 沙箱不支持流式
      }),
      signal: controller.signal
    });

    clearTimeout(timeout);

    if (!response.ok) {
      const errBody = await response.text();
      throw new Error(`${response.status}: ${errBody}`);
    }

    const data = await response.json();
    return data.content.map(c => c.text || '').join('');
  } catch (error) {
    clearTimeout(timeout);
    if (error.name === 'AbortError') throw new Error('请求超时（120s）');
    throw error;
  }
}
```

#### 3.5 测试连接按钮

保存后没验证 = 排查成本极高。必须提供测试连接能力：

```javascript
document.getElementById('btnKeyTestConnect').onclick = async () => {
  const mode = document.querySelector('input[name="aiMode"]:checked').value;
  if (mode !== 'custom') {
    showKeyWarning('当前为 Zero 内置模式，无需测试代理连接', 'success');
    return;
  }

  // 使用临时变量，不污染已保存配置
  const testKey = document.getElementById('keyPageInput').value.trim();
  if (!testKey) {
    showKeyWarning('请先输入 API Key', 'error');
    return;
  }

  const btn = document.getElementById('btnKeyTestConnect');
  btn.disabled = true;
  btn.textContent = '连接中...';
  const el = document.getElementById('keyWarning');
  el.classList.add('hidden');

  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), 30000);

  try {
    const resp = await fetch(AI_PROXY_URL, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'Authorization': 'Bearer ' + testKey
      },
      body: JSON.stringify({
        model: AI_MODEL,
        system: '回复 pong，不要说其他任何内容。',
        messages: [{ role: 'user', content: 'ping' }],
        max_tokens: 16,
        stream: false
      }),
      signal: controller.signal
    });

    clearTimeout(timeout);

    if (resp.status === 401 || resp.status === 403) {
      showKeyWarning('❌ API Key 无效（401/403）', 'error');
    } else if (resp.status === 502) {
      showKeyWarning('❌ 代理连不上 LLM 网关（502）——检查 VPN 或网关地址', 'error');
    } else if (!resp.ok) {
      showKeyWarning(`❌ 请求失败：${resp.status}`, 'error');
    } else {
      showKeyWarning('✅ 连接成功', 'success');
    }
  } catch (err) {
    clearTimeout(timeout);
    if (err.name === 'AbortError') {
      showKeyWarning('❌ 超时（30s）——检查 VPN 或网关是否可达', 'error');
    } else if (err.message && err.message.includes('Failed to fetch')) {
      showKeyWarning('❌ 无法连接代理——确认 proxy.cjs 已运行且端口未被占用，manifest 含 networkAccess', 'error');
    } else {
      showKeyWarning('❌ ' + err.message, 'error');
    }
  } finally {
    btn.disabled = false;
    btn.textContent = '测试连接';
  }
};
```

**错误分类提示：**
| 错误 | 含义 | 排查方向 |
|------|------|---------|
| `Failed to fetch` | 代理不可达 | proxy.cjs 没跑 / 端口被占用 / 缺 networkAccess |
| `AbortError` | 30s 超时 | VPN 未连 / 网关地址不对 |
| `401` / `403` | Key 无效 | 换一个有效的 Key |
| `502` | 代理 → 网关失败 | 网关地址错误 / 网关挂了 |

---

### 第 4 步：proxy.cjs — 本地 CORS 代理

**文件名必须是 `.cjs`**，避免项目 package.json 含 `"type": "module"` 时 Node 把 `.js` 当 ESM 导致 `require` 报错。

```javascript
const http = require('http');

const TARGET = 'http://llm-gw.jd.local'; // 替换为你的 LLM 网关地址
const PORT = 3456;

const server = http.createServer((req, res) => {
  res.setHeader('Access-Control-Allow-Origin', '*');
  res.setHeader('Access-Control-Allow-Methods', 'POST, OPTIONS');
  res.setHeader('Access-Control-Allow-Headers', 'Content-Type, Authorization');

  if (req.method === 'OPTIONS') {
    res.writeHead(204);
    res.end();
    return;
  }

  let body = '';
  req.on('data', chunk => { body += chunk; });
  req.on('end', () => {
    const url = new URL(req.url, TARGET);
    const options = {
      hostname: url.hostname,
      port: url.port || 80,
      path: url.pathname + url.search,
      method: req.method,
      headers: {
        'Content-Type': req.headers['content-type'] || 'application/json',
        'Authorization': req.headers['authorization'] || ''
      }
    };

    const proxyReq = http.request(options, (proxyRes) => {
      res.writeHead(proxyRes.statusCode, {
        ...proxyRes.headers,
        'Access-Control-Allow-Origin': '*'
      });
      proxyRes.pipe(res);
    });

    proxyReq.on('error', (e) => {
      res.writeHead(502);
      res.end('Proxy error: ' + e.message);
    });

    if (body) proxyReq.write(body);
    proxyReq.end();
  });
});

server.listen(PORT, () => {
  console.log(`Proxy running at http://localhost:${PORT}`);
  console.log(`Forwarding to ${TARGET}`);
});
```

**启动方式：**
```bash
node proxy.cjs
```

---

## 踩坑记录

| 问题 | 原因 | 解决方案 |
|------|------|---------|
| Mixed Content 报错 | HTTPS 页面不能 fetch HTTP | Zero/Relay 桌面客户端实际不存在此限制，直接用 HTTP 代理即可。若在纯 Web 环境遇到，需改为 HTTPS 代理（mkcert 本地证书） |
| localStorage 跨会话丢失 | 插件 iframe 每次重建，localStorage 作用域不稳定 | 改用 `figma.clientStorage`（通过 code.ts postMessage 中转） |
| 流式响应无法解析 | iframe 沙箱对 ReadableStream 支持有限 | 请求中设置 `stream: false`，使用完整 JSON 响应 |
| fetch 静默失败 | 未设置 manifest.json 的 networkAccess | 必须添加 `"networkAccess": { "allowedDomains": ["*"] }`；精确控制时 localhost 必须显式列出 |
| API Key 安全 | Key 存在客户端本地 | 这是"用户自己的 Key"模式的固有特性，无需额外加密 |
| ESM/CommonJS 冲突 | 父目录 package.json 含 `"type": "module"` 时 `.js` 被当 ESM，`require` 报错 | 代理文件使用 `.cjs` 扩展名 |
| 多插件 Key 互踩 | clientStorage 键名相同导致覆盖 | 键名加插件前缀：`<plugin-id>:ai-api-key` |
| 保存后不确定是否通 | 无验证环节，出问题排查成本高 | 必须提供「测试连接」按钮，ping 模型返回 pong |

---

## 进阶：迁移到 pluginLLM（无需 API Key）

如果目标平台提供了内置 LLM API（如 Relay 的 `figma.pluginLLM.chat`），可以完全去掉 API Key 页面和代理：

```typescript
// code.ts 中直接调用（无需 Key、无需代理）
const response = await figma.pluginLLM.chat({
  model: 'Claude-Opus-4.7-joybuilder',
  messages: [
    { role: 'system', content: systemPrompt },
    { role: 'user', content: userPrompt }
  ],
  max_tokens: 4096
})
```

这是更简洁的方案，但依赖平台支持。API Key 方案作为通用回退始终可用。

---

## 备选方案：启动页全屏拦截模式

适用于**插件功能完全依赖 AI、没有非 AI 功能**的场景。用户打开插件时必须先配置 Key 才能进入主界面。

```html
<div class="key-page" id="keyPage">
  <h2>你的插件名</h2>
  <p>输入 API Key 以启用 AI 能力</p>
  <input type="password" id="keyPageInput" placeholder="请输入 API Key">
  <button id="btnKeySave">保存并进入</button>
  <button class="key-skip" id="btnKeySkip">跳过，不使用 AI</button>
</div>
<div id="mainPanel" class="hidden">
  <!-- 主界面 -->
</div>
```

**何时用启动页而非设置面板：**
- 插件无法在没有 AI 的情况下正常工作
- 不存在内置 AI 回退
- 用户群体明确知道自己需要配 Key

**推荐设置面板模式的理由：**
- 大部分用户走内置 AI，无需看到 Key 配置
- 非侵入，不打断首次使用体验
- 切换方便，调试时可来回切

---

## 文件清单

实现完成后，你的插件目录应包含：

```
your-plugin/
├── manifest.json    ← 含 networkAccess
├── code.ts          ← clientStorage 读写配置（键名含插件前缀）
├── code.js          ← 编译产物
├── ui.html          ← 设置面板 + AI fetch + 测试连接
└── proxy.cjs        ← 本地 CORS 代理（用户本机运行）
```
