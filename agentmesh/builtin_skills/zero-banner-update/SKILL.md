---
name: zero-banner-update
description: 对 Zero(Relay) Banner 文件批量执行三项操作：①把指定标题画板内的手机/平板截图替换为本地新图（手机直接等比压缩，平板按目标比例裁顶部后压缩）；②把文件内所有匹配的标题文案替换为新文案；③按页面顶部设备分组标签，将所有画板导出为
  PNG，在桌面按分组建文件夹、按画板名命名。用户给出 Zero 文件链接 + 新截图路径 + 原标题文案 + 新标题文案时使用。
allowed-tools:
- mcp__zero-design__use_design_script
- mcp__zero-design__get_screenshot
- mcp__zero-design__export_image
- mcp__zero-design__get_design_metadata
- Bash(curl *)
- Bash(python3 *)
- Read
- Write
metadata:
  author: 2C-DesignWiki
  source: 2C-DesignWiki/jd-design-system-md-v16/product-architecture/search-recommend-foundation/skills&tools/zero-banner/SKILL.md
  agentmesh-wiki-import: 'true'
  agentmesh-stage: during_design
  agentmesh-activation: explicit_only
  short-description: 对 Zero(Relay) Banner 文件批量执行三项操作：①把指定标题画板内的手机/平板截图替换为本地新图（手机直接等比压缩，平板按目标比例裁顶部后压缩）；②把文件内所有匹配的标题文案替换为新…
disable-model-invocation: true
---

# zero-banner-update

对京东 Zero(Relay) Banner 设计文件批量执行：替换截图、修改标题文案、导出所有画板到桌面。

## 触发条件

用户给出以下全部或部分信息时调用：
- Zero 文件链接（`relay.jd.com/file/design?id=...`）
- 新截图本地路径（手机截图，PNG/JPG 均可）
- 要替换的画板标题关键字（如"秒送全新改版"）
- 新标题文案（如"秒送体验升级"）
- 是否导出全部画板

> 三项操作可单独执行，用户只说"替换截图"就只做 Phase 1，只说"改标题"就只做 Phase 2，只说"导出"就只做 Phase 3。

## 前置依赖

- Zero 桌面端已打开并**聚焦到目标文件**（MCP 始终操作当前聚焦窗口）
- `http://127.0.0.1:27618/mcp` 可访问（Zero MCP 已启动）
- `PIL/Pillow` 已安装（`pip3 install Pillow -q`）

---

## Phase 1 · 替换截图

### 1.1 压缩源图

```python
from PIL import Image
import os

src = "/path/to/source.png"   # 用户提供的本地图片

# === 手机版 ===
img = Image.open(src).convert("RGB")
# 缩放到合理宽度（约 904px），保持原始比例
out_w = 904
out_h = int(out_w * img.height / img.width)
resized = img.resize((out_w, out_h), Image.LANCZOS)
resized.save("/tmp/banner_phone.jpg", "JPEG", quality=82, optimize=True)

# === 平板版（按平板比例裁顶部） ===
# 平板典型比例约 0.688 (宽/高)，从源图顶部裁切
TAB_RATIO = 0.688
w, h = img.size
crop_h = int(w / TAB_RATIO)
cropped = img.crop((0, 0, w, min(crop_h, h)))
tab_w = 920
tab_h = int(tab_w / TAB_RATIO)
tab_img = cropped.resize((tab_w, tab_h), Image.LANCZOS)
tab_img.save("/tmp/banner_tablet.jpg", "JPEG", quality=82, optimize=True)
```

> ⚠️ 如果实际平板节点比例与 0.688 差异较大，先用 `use_design_script` 查平板节点尺寸后重新计算：
> `TAB_RATIO = node_width / node_height`

### 1.2 找到目标节点

用 `use_design_script` 在主容器（通常是"大陆版"）内查找目标画板：

```javascript
// 找主容器：通常是页面第一层最大的 FRAME
const page = relay.root.children[0];
const container = page.children.find(n => n.type === 'FRAME' && n.width > 10000);

// 找手机截图节点（IMAGE fill，节点名含"手机"关键字）
const phoneNodes = container.findAll(n =>
  n.type === 'RECTANGLE' &&
  n.fills.some(f => f.type === 'IMAGE') &&
  n.name.includes('手机')   // 根据实际节点名调整
);
return JSON.stringify(phoneNodes.map(n => ({id:n.id, name:n.name, w:Math.round(n.width), h:Math.round(n.height)})));
```

> **节点名规律**：手机截图节点名通常含"手机"，平板含"平板"。若不确定，先 `findAll` 找所有 IMAGE fill 节点，按尺寸比例区分（手机比例 <0.55，平板比例 0.6-0.75）。

### 1.3 分块上传图片

脚本大小限制 50,000 字符，图片通过 `pluginData` 分块传输：

```python
import base64, json, subprocess, re

def call_script(code, desc):
    payload = json.dumps({
        "jsonrpc":"2.0","id":1,"method":"tools/call",
        "params":{"name":"use_design_script","arguments":{"description":desc,"code":code}}
    })
    r = subprocess.run(
        ["curl","-s","-X","POST","http://127.0.0.1:27618/mcp",
         "-H","Content-Type: application/json",
         "-H","Accept: application/json, text/event-stream","-d",payload],
        capture_output=True, text=True
    )
    m = re.search(r'"text":"(.*?)"(?=,"type")', r.stdout, re.DOTALL)
    return m.group(1).replace('\\"','"') if m else r.stdout[:200]

# 上传图片（phone 或 tablet）
def upload_image(img_path, prefix):
    with open(img_path,"rb") as f:
        b64 = base64.b64encode(f.read()).decode()
    CHUNK = 40000
    chunks = [b64[i:i+CHUNK] for i in range(0, len(b64), CHUNK)]
    print(f"{prefix}: {len(b64)} chars, {len(chunks)} chunks")
    for i, chunk in enumerate(chunks):
        call_script(
            f"relay.root.setPluginData('{prefix}_chunk_{i}', {json.dumps(chunk)}); return 'ok';",
            f"store {prefix} chunk {i+1}/{len(chunks)}"
        )
    # 组装 + 写入节点
    node_ids_js = json.dumps(["6:177"])  # 替换为实际节点 ID 列表
    assemble = f"""
const TOTAL = {len(chunks)};
let b64 = '';
for (let i = 0; i < TOTAL; i++) {{
    const c = relay.root.getPluginData('{prefix}_chunk_' + i);
    if (!c) return 'ERROR chunk ' + i;
    b64 += c;
}}
const bytes = relay.base64Decode(b64);
const image = relay.createImage(bytes);
const nodeIds = {node_ids_js};
const results = [];
for (const id of nodeIds) {{
    const node = await relay.getNodeByIdAsync(id);
    if (!node) {{ results.push({{id, error:'not found'}}); continue; }}
    node.fills = [{{ type:'IMAGE', imageHash: image.hash, scaleMode:'FILL' }}];
    results.push({{id, ok:true, hash:image.hash}});
}}
for (let i = 0; i < TOTAL; i++) relay.root.setPluginData('{prefix}_chunk_' + i, '');
return JSON.stringify({{hash: image.hash, results}});
"""
    result = call_script(assemble, f"assemble {prefix} image and apply")
    print(result)
    return result
```

### 1.4 复用已上传图片到其余同类节点

第一次上传后得到 `imageHash`，后续同类节点直接复用，无需重传：

```javascript
const NEW_HASH = 'xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx';  // 上一步拿到的 hash
const existingImg = relay.getImageByHash(NEW_HASH);
if (!existingImg) return JSON.stringify({error: 'hash not found'});
const TARGET_NODES = ['6:1302', '6:1955', /* ... */];  // 其余同类节点 ID
const results = [];
for (const id of TARGET_NODES) {
    const node = await relay.getNodeByIdAsync(id);
    if (!node) { results.push({id, error:'not found'}); continue; }
    node.fills = [{ type:'IMAGE', imageHash: NEW_HASH, scaleMode:'FILL' }];
    results.push({id, name:node.name, ok:true});
}
return JSON.stringify({total: results.filter(r=>r.ok).length, results});
```

---

## Phase 2 · 替换标题文案

在主容器内一次性替换所有匹配文字：

```javascript
const container = relay.root.children[0].children.find(n => n.type==='FRAME' && n.width>10000);
const OLD_TEXT = '秒送全新改版';   // 精确匹配
const NEW_TEXT = '秒送体验升级';
const textNodes = container.findAll(n => n.type === 'TEXT' && n.characters === OLD_TEXT);
const results = [];
for (const n of textNodes) {
    n.characters = NEW_TEXT;
    results.push({id:n.id, parent:n.parent?.name, ok:true});
}
return JSON.stringify({total:results.length, results});
```

> ⚠️ `characters` 赋值会保留原始字体/字号/字重。若修改后字数差异大导致溢出，需额外调整 `fontSize` 或 `textAutoResize`。

---

## Phase 2.5 · 导出前校验

在正式导出之前运行此校验，发现问题立即中止，避免批量导出后才发现替换失败。

### 检查清单

| 编号 | 检查项 | 通过条件 |
|---|---|---|
| ① | 目标画板数量 | 与上方 Phase 1 找到的画板数一致，不为 0 |
| ② | 图片替换完整性 | 所有 IMAGE fill 节点的 `imageHash` 非空，无断图 |
| ③ | 文案替换完整性 | 旧文案残留 = 0；新文案出现次数 > 0 |
| ④ | 底层背景（可选） | 若执行了"最后一层"操作，`children[0]` 应为 IMAGE RECTANGLE |
| ⑤ | 导出预览 | 输出将生成的文件夹数 × 文件数，确认与预期一致 |

### 校验脚本

```javascript
// ——— 按实际操作填写 ———
const CONTAINER_MIN_WIDTH = 10000;   // 主容器最小宽度（大陆版通常 >10000）
const OLD_TEXT  = '京东酒店';        // 旧文案（替换后不应存在）
const NEW_TEXT  = '京东旅行';        // 新文案（替换后应存在）
const EXPECT_ARTBOARD_COUNT = 10;    // 预期画板数（Phase 1 找到的数量）
const CHECK_BOTTOM_LAYER = true;     // 是否校验"最后一层"图片背景

const page = relay.root.children[0];
const container = page.children.find(n => n.type==='FRAME' && n.width > CONTAINER_MIN_WIDTH);
if (!container) return JSON.stringify({error:'未找到主容器'});

const checks = [];

// ① 画板数量
const artboards = container.findAll(n =>
  n.type==='FRAME' && n.parent?.type==='FRAME' && n.width > 400 && n.height > 400
);
checks.push({
  id:'①', name:'画板数量',
  ok: artboards.length === EXPECT_ARTBOARD_COUNT,
  detail: `找到 ${artboards.length} 个，预期 ${EXPECT_ARTBOARD_COUNT} 个`
});

// ② 图片替换完整性
const imageNodes = container.findAll(n =>
  (n.type==='RECTANGLE' || n.type==='FRAME') &&
  n.fills.some(f => f.type==='IMAGE')
);
const broken = imageNodes.filter(n => n.fills.some(f => f.type==='IMAGE' && !f.imageHash));
checks.push({
  id:'②', name:'图片填充',
  ok: imageNodes.length > 0 && broken.length === 0,
  detail: `${imageNodes.length} 个 IMAGE 节点，${broken.length} 个 hash 缺失`
            + (broken.length ? `  缺失：${broken.map(n=>n.id).join(', ')}` : '')
});

// ③ 文案替换
const oldLeft = container.findAll(n => n.type==='TEXT' && n.characters.includes(OLD_TEXT));
const newFound = container.findAll(n => n.type==='TEXT' && n.characters.includes(NEW_TEXT));
checks.push({
  id:'③', name:'文案替换',
  ok: OLD_TEXT === '' || (oldLeft.length === 0 && newFound.length > 0),
  detail: `旧文案残留 ${oldLeft.length} 处，新文案出现 ${newFound.length} 处`
            + (oldLeft.length ? `  残留于：${oldLeft.slice(0,3).map(n=>n.parent?.name||n.id).join('/')}` : '')
});

// ④ 底层背景（可选）
if (CHECK_BOTTOM_LAYER) {
  const artboardList = container.findAll(n =>
    n.type==='FRAME' && n.parent?.type==='FRAME' && n.width > 400 && n.height > 400
  );
  const noBottom = artboardList.filter(n => {
    const c0 = n.children[0];
    return !c0 || c0.type !== 'RECTANGLE' || !c0.fills.some(f => f.type==='IMAGE');
  });
  checks.push({
    id:'④', name:'底层背景',
    ok: noBottom.length === 0,
    detail: `${artboardList.length} 个画板，${noBottom.length} 个底层非图片矩形`
              + (noBottom.length ? `  问题：${noBottom.map(n=>n.id).join(', ')}` : '')
  });
}

// ⑤ 导出预览：自动分组并预计文件数（与 Phase 3 逻辑一致）
const rawGroups2 = [], rawFrames2 = [];
for (const n of container.children) {
  if (n.type === 'GROUP') {
    const texts = n.findAll(c=>c.type==='TEXT').map(t=>t.characters.trim()).filter(Boolean);
    const label = (texts.join(' ')||n.name).replace(/\s+/g,' ').trim();
    rawGroups2.push({label, y:n.y, yBottom:n.y+n.height});
  } else if (n.type==='FRAME' && n.width>400 && n.height>400 && n.visible!==false) {
    rawFrames2.push({y:n.y});
  }
}
rawGroups2.sort((a,b)=>a.y-b.y);
const groupSizes = {};
const TOLE = 50;
for (const f of rawFrames2) {
  const above = rawGroups2.filter(g=>g.yBottom<=f.y+TOLE);
  const g = above.length ? above.reduce((b,c)=>c.y>b.y?c:b) : rawGroups2[0];
  if (g) groupSizes[g.label] = (groupSizes[g.label]||0) + 1;
}
const groupCount  = Object.keys(groupSizes).length || 1;
const frameCount  = rawFrames2.length;
const groupDetail = Object.entries(groupSizes).slice(0,4)
                     .map(([l,n])=>`${l}(${n})`).join(' / ');
checks.push({
  id:'⑤', name:'导出预览',
  ok: frameCount > 0,
  detail: `${groupCount} 个设备分组，${frameCount} 个画板 → 预计生成 ${frameCount} 个文件  ${groupDetail}${groupCount>4?'…':''}`
});

const allOk = checks.every(c => c.ok);
return JSON.stringify({allOk, checks});
```

### 输出解读

```
allOk: true  → 全部通过，可执行 Phase 3 导出
allOk: false → 中止，根据 detail 定位问题后重跑对应 Phase
```

> ⚠️ 若 ③ 旧文案残留 > 0，说明 Phase 2 的 `findAll` 匹配条件未能覆盖全部节点（可能存在嵌套文本或文案拼写不同），需在 Phase 2 中修正再重跑校验。

---

## Phase 3 · 导出全部画板

> **导出目录规则**：
> - 未指定打包文件夹名 → 直接在桌面建各设备文件夹（`~/Desktop/设备名/`）。
> - 指定了打包文件夹名（如"16.0.0"）→ 所有设备文件夹建在 `~/Desktop/16.0.0/设备名/` 内，桌面根目录不单独建文件夹。

下方脚本自动完成：① 查询分组 → ② 建目录 → ③ 并发导出，无需手动整理中间结果。

```python
import subprocess, json, re, os
from concurrent.futures import ThreadPoolExecutor, as_completed

DESKTOP = os.path.expanduser("~/Desktop")
BUNDLE  = "16.0.0"   # 指定打包文件夹名；无需打包时设为 None
ROOT    = os.path.join(DESKTOP, BUNDLE) if BUNDLE else DESKTOP

# ── 公共 helpers ──────────────────────────────────────────────
def call_script(code, desc=""):
    payload = json.dumps({
        "jsonrpc":"2.0","id":1,"method":"tools/call",
        "params":{"name":"use_design_script","arguments":{"description":desc,"code":code}}
    })
    r = subprocess.run(
        ["curl","-s","-X","POST","http://127.0.0.1:27618/mcp",
         "-H","Content-Type: application/json",
         "-H","Accept: application/json, text/event-stream","-d",payload],
        capture_output=True, text=True, timeout=60
    )
    m = re.search(r'"text":"(.*?)"(?=\s*,\s*"type")', r.stdout, re.DOTALL)
    return m.group(1).replace('\\"','"').replace('\\n','\n') if m else ''

def export_node(node_id):
    payload = json.dumps({
        "jsonrpc":"2.0","id":1,"method":"tools/call",
        "params":{"name":"export_image","arguments":{"nodeId":node_id,"format":"png"}}
    })
    r = subprocess.run(
        ["curl","-s","-X","POST","http://127.0.0.1:27618/mcp",
         "-H","Content-Type: application/json",
         "-H","Accept: application/json, text/event-stream","-d",payload],
        capture_output=True, text=True
    )
    m = re.search(r'"image_url":"([^"]+)"', r.stdout)
    return m.group(1) if m else None

def download(url, out_path):
    subprocess.run(
        ["curl","-s","-A","Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
         url,"-o",out_path],
        capture_output=True
    )
    return os.path.exists(out_path) and os.path.getsize(out_path) > 0

# ── Step 1：自动查询并分组 ────────────────────────────────────
# 算法：每个画板归到 y 坐标最近且在其上方的设备标签（GROUP）
AUTO_GROUP_JS = """
const container = relay.root.children[0].children.find(
  n => n.type==='FRAME' && n.width > 10000
);
if (!container) return JSON.stringify({error:'主容器未找到'});

const rawGroups = [], rawFrames = [];
for (const n of container.children) {
  if (n.type === 'GROUP') {
    const texts = n.findAll(c => c.type==='TEXT')
                   .map(t => t.characters.trim()).filter(Boolean);
    const label = (texts.join(' ') || n.name).replace(/\\s+/g,' ').trim();
    rawGroups.push({label, y: n.y, yBottom: n.y + n.height});
  } else if (n.type === 'FRAME' && n.width > 400 && n.height > 400 && n.visible !== false) {
    rawFrames.push({id: n.id, name: n.name, y: n.y, x: n.x});
  }
}

rawGroups.sort((a, b) => a.y - b.y);
rawFrames.sort((a, b) => a.y !== b.y ? a.y - b.y : a.x - b.x);

// 若文件内没有 GROUP 节点，全部画板归到一个以容器命名的组
if (!rawGroups.length) {
  return JSON.stringify([{
    label: container.name,
    frames: rawFrames.map(f => ({id: f.id, name: f.name}))
  }]);
}

// 为每个画板找"y 最大且 yBottom ≤ 画板 y + 容差"的 GROUP（即距离最近的上方标签）
const TOLERANCE = 50;
const grouped = {};
for (const f of rawFrames) {
  const above = rawGroups.filter(g => g.yBottom <= f.y + TOLERANCE);
  const g = above.length
    ? above.reduce((best, cur) => cur.y > best.y ? cur : best)
    : rawGroups[0];   // 兜底：使用第一个分组
  if (!grouped[g.label]) grouped[g.label] = [];
  grouped[g.label].push({id: f.id, name: f.name});
}

// 按 GROUP 原始 y 顺序输出，保持从上到下排列
return JSON.stringify(
  rawGroups
    .filter(g => grouped[g.label])
    .map(g => ({label: g.label, frames: grouped[g.label]}))
);
"""

raw = call_script(AUTO_GROUP_JS, "auto-group artboards by device label")
groups = json.loads(raw)   # [{label, frames:[{id,name}]}]

print(f"自动分组结果（共 {len(groups)} 组）：")
total = sum(len(g['frames']) for g in groups)
for g in groups:
    names = ' / '.join(f['name'] for f in g['frames'])
    print(f"  [{g['label']}]  {len(g['frames'])} 个画板  →  {names}")
print(f"合计导出 {total} 个文件至 {ROOT}/")

# ── Step 2：建目录 ────────────────────────────────────────────
for g in groups:
    os.makedirs(os.path.join(ROOT, g['label']), exist_ok=True)

# ── Step 3：并发导出 ──────────────────────────────────────────
tasks = [(f['id'], f['name'], g['label']) for g in groups for f in g['frames']]

def do_one(task):
    node_id, frame_name, folder = task
    url = export_node(node_id)
    if not url: return False, f"{folder}/{frame_name} URL失败"
    out = os.path.join(ROOT, folder, f"{frame_name}.png")
    ok  = download(url, out)
    return ok, f"{folder}/{frame_name}"

ok_count = 0
with ThreadPoolExecutor(max_workers=6) as ex:
    for ok, info in [f.result() for f in as_completed({ex.submit(do_one,t):t for t in tasks})]:
        print("✓" if ok else "✗", info)
        if ok: ok_count += 1

print(f"\n完成 {ok_count}/{len(tasks)}，文件已保存至：{ROOT}")
```

> ⚠️ `export_image` CDN 链接有防盗链，curl 必须带浏览器 UA，否则 403。脚本已内置。

---

## 常见问题

| 现象 | 原因 | 处理 |
|---|---|---|
| `use_design_script` 操作了错误文件 | MCP 始终操作当前聚焦的 Zero 窗口 | 在 Zero 桌面端切换到目标文件后再执行 |
| `createImage` 返回 null | 图片数据不完整或格式不支持 | 确认 base64 分块重组完整，使用 JPEG 而非 PNG |
| `relay.getImageByHash` 返回 null | 该 hash 不在当前文档的图片存储中 | 需要重新上传而非复用；或确认操作的是同一个文件 |
| `node.characters = X` 后字体变形 | 字符数变多导致文本框溢出 | 调小 `fontSize` 或设置 `node.textAutoResize = 'WIDTH_AND_HEIGHT'` |
| `export_image` CDN URL 403 | 未带浏览器 UA | curl 加 `-A "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"` |
| 平板截图裁切比例不对 | 不同文件平板节点比例不同 | 先查节点实际 `width/height`，用 `TAB_RATIO = w/h` 重新裁切 |
| `PIL` 未安装 | 首次使用 | `pip3 install Pillow -q` |
| 分块上传后组装报 chunk missing | 中间某块上传失败 | 单独重传缺失块：`relay.root.getPluginData('prefix_chunk_N')` 验证 |

---

## 完整触发指令模板

```
用 zero-banner-update skill，打开 Zero 文件 [relay.jd.com 链接]：
1. 把所有标题为「[原标题]」的画板，手机屏幕截图替换为 [本地图片路径]，平板等比适配
2. 把所有「[原标题]」文案改为「[新标题]」
3. 按设备分组导出全部画板（可选：打包至桌面/【版本名】文件夹，不在桌面根目录重复建文件夹）
```
