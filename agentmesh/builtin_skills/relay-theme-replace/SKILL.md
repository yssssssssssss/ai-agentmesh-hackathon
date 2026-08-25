---
name: relay-theme-replace
description: 把 Relay 推荐页模版克隆成新主题，自动搜索京东商品图、填充名称/价格/辅助文字/鱼眼文案，截图验收。用户说"换成 XX 主题"、"生成 XX 主题页面"时触发。
metadata:
  author: 2C-DesignWiki
  source: 2C-DesignWiki/jd-design-system-md-v16/product-architecture/search-recommend-foundation/skills&tools/relay-theme-replace/SKILL.md
  agentmesh-wiki-import: 'true'
  agentmesh-stage: during_design
  agentmesh-activation: explicit_only
  short-description: 把 Relay 推荐页模版克隆成新主题，自动搜索京东商品图、填充名称/价格/辅助文字/鱼眼文案，截图验收。用户说"换成 XX 主题"、"生成 XX 主题页面"时触发。
disable-model-invocation: true
---

# Relay 页面模版主题替换

把 Relay 推荐页模版克隆一份，替换为指定主题的商品内容（名称、价格、辅助文字、图片、鱼眼文案）。

## 触发方式

用户提供一个 Relay 模版，想克隆一份并替换为指定主题的商品内容（名称、价格、图片、辅助文字等）时触发。

## 图片来源路由（优先级）

1. **用户给了图**（CDN 直链 URL 或 Relay 文件 node_id）→ 走对应路径，**不搜京东**
2. **用户没给图** → 走京东搜索路径（metasearch）

---

## 完整流程

> **已记忆模版可跳过第 1 步**，直接从第 2 步开始，模版结构参见对应记忆文档。

### 第 1 步 — 探索模版结构（新模版首次使用）

1. 从 Relay URL 提取 `node_id`，调用 `get_design_metadata` 了解层级
2. 用调试脚本确认：商卡分布、哪些商卡有特殊容器（如战略标签）、各字段节点路径
3. 记录模版结构到记忆文档，之后直接走第 2 步

### 第 2 步 — 确定商品列表

根据主题列出商品，填表确认后再写脚本：

| 商卡 | 结构 | 名称宽度上限 | 目标区间 |
|------|------|------------|--------|
| 1、5 | 有战略标签（容器 10704） | **≤ 125px** | 8–9 汉字（104–117px） |
| 2、3、4、6、7 | 无标签 | **≤ 158px** | 11–12 汉字（143–156px） |

宽度估算：`汉字×13 + 大写字母×8 + 小写字母×7`（仅供初估，**实际字体可能差异较大**）

> ⚠️ **必须逐字点数，不能目测**：`瑜伽慵懒手办盲盒` 是 8 汉字不是 6 汉字——目测少数会导致超宽。写完名称后重新数一遍再算。

> ⚠️ **字体渲染宽度因模版而异**：有好货模版实测汉字≈16px（不是13px）、大写字母≈9.5px。每次用新模版，必须用 `textAutoResize='WIDTH_AND_HEIGHT'` 实测后再定名称：
> ```javascript
> nn.textAutoResize = 'WIDTH_AND_HEIGHT';
> nn.characters = '候选名称';
> console.log(nn.width); // 实际渲染宽度
> // 测完还原：
> nn.textAutoResize = 'HEIGHT'; nn.maxLines = 1;
> ```

**名称必须满足双侧约束：不超上限，也不能低于下限（≥上限的 75%）。**

| 上限 | 最低要求（75%） | 典型填充 |
|------|--------------|--------|
| ≤125px | ≥94px（≥7汉字） | 8–9汉字 |
| ≤158px | ≥119px（≥9汉字） | 11–12汉字 |
| ≤170px | ≥128px（≥9汉字） | 11–13汉字 |
| ≤200px | ≥150px（≥11汉字） | 12–14汉字 |

若从搜索结果直接截取的名称宽度不足，从原始产品全名中补充关键规格词（容量、功能系列名、型号等）直到满足最低要求。

> ⚠️ 商卡7 的促销标签（FRAME[name=标签]，如"满300减30"）**绝对不改**，辅助文字设为 null 跳过。

#### 名称宽度正确探测方法（新模版必做）

读 **`nameFrame.width`（父框架宽度）**，而非 `textNode.width`（文本节点会随内容自动缩放，不代表上限）：

```javascript
// 调试脚本：查各商卡名称上限（在原始模版节点上运行）
const cards = orig.findAll(n => n.name === '商品X').sort((a, b) => a.y - b.y); // 按实际卡片名
cards.forEach((card, i) => {
  const nameFrame = card.findAll(n => n.name === '商品名称')[0];
  const hasInst   = nameFrame?.children.some(n => n.type === 'INSTANCE');
  console.log(`商卡${i+1}: nameFrame.width=${nameFrame?.width}  hasInstance=${hasInst}`);
});
```

规则：
- **无 INSTANCE**：安全上限 = `nameFrame.width - 13`（留1汉字余量）
- **有 INSTANCE**：需先实测 INSTANCE 实际占宽，或直接用下表已验证值

#### 已验证模版宽度（实测）

| 模版 | 商卡 | nameFrame.width | 有 INSTANCE | 安全上限 |
|-----|-----|----------------|------------|---------|
| me model `6:6652` | 商卡1/5 | ~130px | 有战略标签 | **≤ 125px**（≤9汉字） |
| me model `6:6652` | 商卡2/3/4/6/7 | ~163px | 无 | **≤ 158px**（≤12汉字） |
| 搜索结果页 `7:1603` | 商卡1/3 | 213px | 有自营 | **≤ 170px**（≤13汉字） |
| 搜索结果页 `7:1603` | 商卡2/4 | 213px | 无 | **≤ 200px**（≤15汉字） |
| 有好货 `10:209` | 商卡1–6 | 160px | 无 | **≤ 160px**（实测必测，汉字≈16px非13px） |

### 第 3 步 — 获取图片

根据图片来源路由，选择对应路径：

- **用户没给图** → 京东搜索（见下方）
- **用户给了 CDN 直链** → 见「CDN 直链图片路径」章节
- **用户给了 Relay 文件 node_id** → 见「文件内图片路径」章节

**京东搜索（~5 秒）**

```bash
PATH="$HOME/.o2/bin:$PATH"
metasearch --json search "关键词1" --output json > /tmp/s1.json &
metasearch --json search "关键词2" --output json > /tmp/s2.json &
metasearch --json search "关键词3" --output json > /tmp/s3.json &
metasearch --json search "关键词4" --output json > /tmp/s4.json &
metasearch --json search "关键词5" --output json > /tmp/s5.json &
metasearch --json search "关键词6" --output json > /tmp/s6.json &
metasearch --json search "关键词7" --output json > /tmp/s7.json &
wait
```

```bash
python3 << 'PYEOF'
import json
for i in range(1, 8):
    with open(f'/tmp/s{i}.json') as f: d = json.load(f)
    p = d['data']['products'][0]
    price = p['price'].split('.')[0]
    print(f"// 商卡{i}: {p['name'][:35]}")
    print(f"{{ name:'', price:'{price}', aux:'', img:'{p['image']}' }},")
    print()
PYEOF
```

并行下载图片，用 Read 工具核查每张主体是否清晰：

```bash
python3 << 'PYEOF'
import json, subprocess
procs = []
for i in range(1, 8):
    with open(f'/tmp/s{i}.json') as f: d = json.load(f)
    url = d['data']['products'][0]['image']
    procs.append(subprocess.Popen(['curl', '-s', url, '-o', f'/tmp/check{i}.jpg']))
for p in procs: p.wait()
print("Downloaded check1.jpg … check7.jpg")
PYEOF
```

> 若 check{n}.jpg 不满足，直接换一件商品重新搜。token 存储在 `~/.config/metasearch/token.json`，失效时见文末"重新获取 token"。

### 第 4 步 — 克隆并填充

```javascript
// ========== 按主题填写 ==========
const THEME_NAME = '主题名称';
const YUYAN     = '鱼眼文案';   // 2-6 字，对应主题核心词
const products  = [
  { name:'',  price:'',  aux:'',    img:'' }, // 商卡1  有标签 8-9字
  { name:'',  price:'',  aux:'',    img:'' }, // 商卡2  无标签 11-12字
  { name:'',  price:'',  aux:'',    img:'' }, // 商卡3  无标签 11-12字
  { name:'',  price:'',  aux:'',    img:'' }, // 商卡4  无标签 11-12字
  { name:'',  price:'',  aux:'',    img:'' }, // 商卡5  有标签 8-9字
  { name:'',  price:'',  aux:'',    img:'' }, // 商卡6  无标签 11-12字
  { name:'',  price:'' , aux:null,  img:'' }, // 商卡7  无标签，aux=null不改标签
];
// =================================

const orig = await relay.getNodeByIdAsync('6:6652'); // me model 节点ID
const clone = orig.clone();
clone.name = THEME_NAME;
// 找页面最右边，把新克隆放在所有已有内容右侧（避免覆盖旧克隆）
const allFrames = orig.parent.findAll(n => n.type === 'FRAME' && n.x > orig.x);
const maxRight  = allFrames.reduce((m, n) => Math.max(m, n.x + n.width), orig.x + orig.width);
clone.x = maxRight + 40;
clone.y = orig.y;

// 字体
const fontSet = new Map();
clone.findAll(n => {
  if (n.type === 'TEXT') { const fn = n.fontName; if (fn !== relay.mixed) fontSet.set(`${fn.family}|${fn.style}`, fn); }
  return false;
});
await Promise.all([...fontSet.values()].map(f => relay.loadFontAsync(f)));

// 鱼眼文案（输入框文案不改）
clone.findAll(n => n.name === '鱼眼文案')[0].characters = YUYAN;

// 商卡导航
const shopkaFrame = clone.children.find(n => n.name === '商卡');
const left  = shopkaFrame.children.find(n => n.name === '左侧');
const right = shopkaFrame.children.find(n => n.name === '右侧');
const cardMap = {};
left.children.forEach(c  => { cardMap[c.name] = c; });
right.children.forEach(c => { cardMap[c.name] = c; });

const results = [];
for (let i = 0; i < 7; i++) {
  const card = cardMap[`商卡${i+1}`];
  const p    = products[i];
  const info = card.children.find(n => n.name === '商品信息');

  // 名称（区分结构A/B）
  const c10704   = info.children.find(n => n.name === '容器 10704');
  const nameNode = c10704
    ? c10704.children.find(n => n.type === 'TEXT')   // 结构B：商卡1、5
    : info.children.find(n => n.type === 'TEXT');     // 结构A：其他
  if (nameNode) { nameNode.characters = p.name; nameNode.maxLines = 1; nameNode.textAutoResize = 'TRUNCATE'; }

  // 价格（只改数字节点，不改¥符号）
  const priceFrame = info.children.find(n => n.name === '价格销量行')
    .children.find(n => n.type === 'FRAME')
    .children.find(n => n.name === '价格');
  priceFrame.children.find(n => n.name === '价格').characters = p.price;

  // 辅助文字（商卡7 aux=null 跳过）
  if (p.aux) {
    const auxFrame = info.children.find(n => n.name === '辅助信息行');
    if (auxFrame) {
      const auxText = auxFrame.children.find(n => n.type === 'TEXT');
      if (auxText) { auxText.textAutoResize = 'WIDTH_AND_HEIGHT'; auxText.characters = p.aux; }
    }
  }

  // 图片
  const img     = await relay.createImageAsync(p.img);
  const imgNode = card.children.find(n => n.name === '主图').children.find(n => n.name === '商品图');
  if (img && imgNode) {
    imgNode.fills = [{ type:'IMAGE', imageHash:img.hash, scaleMode:'FILL' }];
    results.push(`✓ 商卡${i+1}: ${p.name}`);
  } else {
    results.push(`✗ 商卡${i+1}: img=${!!img}`);
  }
}
return { cloneId: clone.id, results };
```

### 第 5 步 — 截图验收

脚本返回 `cloneId` 后，调用 `export_image(nodeId: cloneId, scale: 2)` 导出高清截图，逐一核查：
- 每张商品图主体清晰，能一眼看出是什么商品
- 所有商品名称单行（无换行）
- 战略标签文字正确（如"自营"），商卡7促销标签未被修改
- 原始模版节点未被修改

---

## 文件内图片路径（用户在 Relay 文件中预置图片）

用户说"商品图用这个节点"或提供 Relay URL + node_id 时，走此路径。**与 JD URL 路径互不影响。**

### 第 1 步 — 读取图片 hash 和尺寸

```javascript
const frame = await relay.getNodeByIdAsync('图片容器nodeId');
const imgData = frame.children.map((n, i) => ({
  index: i,
  nodeId: n.id,
  hash: n.fills?.[0]?.imageHash ?? null,
  w: n.width,
  h: n.height,
  ratio: n.height / n.width,   // ≥1.25 → 3:4 长图；< 1.25 → 1:1 方图
}));
return imgData;
```

### 第 2 步 — 视觉识别每张图（必做，不能跳过）

节点名通常是 `undefined_xxx`，**无语义**。必须用 `export_image` 逐一导出后用 Read 工具查看，确认每张图实际展示的是什么商品，再写对应的名称和辅助信息。

### 第 3 步 — 名称/辅助信息匹配原则

- **名称必须描述图片里实际看到的商品**，不能用主题关键词盲猜
- 辅助信息同理，取商品实际卖点（材质、风格、功能等）
- 若需要价格，按实际商品搜索 JD 获取；若用户未要求精确价格，可合理估填

### 第 4 步 — 图片比例处理

| 类型 | 来源图 ratio | 商卡图区处理 |
|------|------------|------------|
| 时尚类（连衣裙、上衣等） | `ratio ≥ 1.25`（3:4 长图） | 将 `主图` FRAME 和 `商品图` 矩形都 resize 为 3:4 |
| 时尚类 | `ratio < 1.25`（1:1 方图） | 保持原始尺寸不变 |
| 非时尚类（数码、食品等） | 任意 | **只支持 1:1**，保持原始尺寸，scaleMode='FILL' |

**3:4 resize 写法：**

```javascript
// imgFrame = card.children.find(n => n.name === '主图')
// imgNode  = imgFrame.children.find(n => n.name === '商品图')
if (is34 && isFashion) {
  const newH = Math.round(imgFrame.width * 4 / 3);
  imgFrame.resize(imgFrame.width, newH);
  imgNode.resize(imgNode.width, newH);
}
imgNode.fills = [{ type: 'IMAGE', imageHash: p.hash, scaleMode: 'FILL' }];
```

### 第 5 步 — 填充脚本 products 数组格式

```javascript
// 用 hash 替代 img URL，isFashion 控制比例
const products = [
  { name:'', price:'', aux:'', hash:'<imageHash>', is34: true },
  // ...
];
```

---

## CDN 直链图片路径（用户提供图片 URL）

用户提供 `i.pinimg.com`、京东 `img.*.360buyimg.com` 或其他可公开访问的图片直链时，走此路径。

### 第 1 步 — 批量下载，视觉核查（必做）

```bash
urls=(
  "https://i.pinimg.com/xxx/a.jpg"
  "https://i.pinimg.com/xxx/b.jpg"
)
for i in "${!urls[@]}"; do
  curl -sL "${urls[$i]}" -o "/tmp/pin_$((i+1)).jpg" &
done
wait
```

用 Read 工具逐一查看 `/tmp/pin_1.jpg` … 确认每张图的商品内容，再写名称和辅助信息。

### 第 2 步 — 比例检测

```bash
python3 -c "
from PIL import Image
for i in range(1, 8):
    img = Image.open(f'/tmp/pin_{i}.jpg')
    w, h = img.size
    print(f'图{i}: {w}x{h} ratio={h/w:.2f}')
"
```

ratio ≥ 1.25 → 3:4 长图；< 1.25 → 1:1 方图（比例处理规则与文件内图片路径第 4 步相同）。

### 第 3 步 — 名称/辅助信息匹配原则

与文件内图片路径第 3 步相同：名称和辅助信息必须描述图片里实际看到的商品，不能盲猜。

### 第 4 步 — 填充脚本 products 数组格式

```javascript
// 用 img URL，Relay 内部 createImageAsync 上传
const products = [
  { name:'', price:'', aux:'', img:'https://i.pinimg.com/xxx/a.jpg', is34: false },
  // ...
];

// 图片填充写法：
const imgObj = await relay.createImageAsync(p.img);
imgNode.fills = [{ type: 'IMAGE', imageHash: imgObj.hash, scaleMode: 'FILL' }];
```

---

## 搜索关键词更换（搜索结果页必做）

搜索框是 INSTANCE 组件，内部 TEXT 节点的 **name 会随 characters 内容自动同步**，不能用固定名称定位。

```javascript
// 正确做法：按内容特征查找，不依赖节点 name
const searchBox = clone.findAll(n => n.name === '搜索框')[0];
const allTexts  = searchBox ? searchBox.findAll(n => n.type === 'TEXT') : [];
// 找含原始关键词（如"手机"）的节点，替换为新主题词
const kwNode = allTexts.find(t => t.characters && t.characters.includes('手机'));
if (kwNode) kwNode.characters = '空调';  // 换成目标主题关键词
```

> ⚠️ 不能用 `clone.findAll(n => n.name === '文字 177')` 定位——节点 name 在文字改变后随之变化，下次执行时名称已不是 '文字 177'。

---

## 辅助信息（所有模版）

**只替换文字内容，不改结构、不改节点数量、不改格式。原来是什么类型，填什么类型。**

### 各模版结构与内容类型

| 模版 | 商卡 | 节点结构 | 字数上限 | 内容类型 |
|------|------|---------|---------|---------|
| me model | 商卡1–6 | `辅助信息行 > TEXT` | ~6字 | 短卖点文案（材质/风格/功能） |
| me model | 商卡7 | 无辅助信息行（有促销FRAME） | — | `aux=null` 跳过，绝对不改 |
| 有好货 | 商卡1–6 | `辅助信息行 > [星星FRAME, TEXT]` | ≤6字（66px） | 短卖点文案 |
| 搜索结果页 | 商品1（有自营） | `辅助信息行 > 3子FRAME，每FRAME含2TEXT` | — | 规格值 + 标签 |
| 搜索结果页 | 商品2（无自营） | `辅助信息行 > 3独立TEXT，竖线分隔` | — | 横排规格文字 |
| 搜索结果页 | 商品3/4 | 直接 `TEXT[name=辅助信息]`，无FRAME | — | 用户评价引用 |

| 内容类型 | 示例 | 文案策略 |
|---------|------|--------|
| 短卖点文案 | `"轻薄透气"` `"简约高雅"` | 取商品材质/风格/功能，≤6字 |
| 规格值 + 标签 | `"A15芯片" / "处理器"` | 换同主题规格：`"1.5L容量" / "容量"` |
| 横排规格文字 | `"A15芯片" \| "低光拍摄"` | 换同主题规格：`"方形杯" \| "0涂层"` |
| 用户评价引用 | `"宝贝质感很好，价格适中"` | 换同主题评价：`"低音效果好，破壁很细腻"` |
| 促销/活动标签（FRAME） | `"满300减30"` | **绝对不改** |

### 写法：me model / 有好货（单 TEXT）

```javascript
if (p.aux !== null) {
  const auxFrame = info.children.find(n => n.name === '辅助信息行');
  if (auxFrame) {
    const auxText = auxFrame.children.find(n => n.type === 'TEXT');
    if (auxText) { auxText.textAutoResize = 'WIDTH_AND_HEIGHT'; auxText.characters = p.aux; }
  }
}
```

### 写法：搜索结果页（4 种结构）

```javascript
const auxFrame = upper.children.find(n => n.name === '辅助信息行');
if (auxFrame) {
  const subFrames = auxFrame.children.filter(n => n.type === 'FRAME');
  if (subFrames.length > 0) {
    // 商品1（有自营）：3子FRAME，每FRAME [0]=值 [1]=标签
    subFrames.forEach((f, fi) => {
      const texts = f.children.filter(n => n.type === 'TEXT');
      if (texts[0] && auxPairs[fi]) texts[0].characters = auxPairs[fi][0];
      if (texts[1] && auxPairs[fi]) texts[1].characters = auxPairs[fi][1];
    });
  } else {
    // 商品2（无自营）：3独立TEXT，竖线分隔
    const texts = auxFrame.children.filter(n => n.type === 'TEXT');
    texts.forEach((t, ti) => { if (auxTexts[ti]) t.characters = auxTexts[ti]; });
  }
} else {
  // 商品3/4：直接 TEXT[name=辅助信息]
  const auxText = upper.children.find(n => n.name === '辅助信息');
  if (auxText) { auxText.textAutoResize = 'WIDTH_AND_HEIGHT'; auxText.characters = auxVal; }
}
```

### 新模版调试脚本

```javascript
cards.forEach((card, i) => {
  const auxFrame = card.findAll(n => n.name === '辅助信息行')[0];
  if (!auxFrame) { console.log(`商卡${i+1}: 无辅助信息行`); return; }
  console.log(`商卡${i+1}: ` + auxFrame.children.map(c =>
    `${c.type}[${c.name}]${c.type==='TEXT'?'="'+c.characters+'"':''}`
  ).join(' | '));
});
```

---

## 价格（所有模版）

### me model / 有好货 — 整数字符串直接写

```javascript
// 路径：商品信息 > 价格销量行 > FRAME > 价格 > TEXT[name="价格"]
priceFrame.children.find(n => n.name === '价格').characters = p.price; // 如 "199"
```

### 搜索结果页 — 拆分为三个节点

```
价格行 > 01 > 价格字段 > [TEXT[¥]（不改）, TEXT[主价格], TEXT[小数点后价格]]
```

```javascript
const [intPart, decPart] = price.split('.');
const formatDec = dec => (dec || '00').replace(/0+$/, ''); // "00"→"", "90"→"9"
mainPriceNode.characters = intPart + '.';
decPriceNode.characters  = formatDec(decPart);
```

| 原始价格 | 主价格节点 | 小数节点 |
|---------|---------|--------|
| 2498.00 | `2498.` | `""` |
| 1998.90 | `1998.` | `9` |
| 3299.15 | `3299.` | `15` |
| 4399.02 | `4399.` | `02` |

---

## 店铺名称（搜索结果页）

取自搜索结果 `shop_name` 字段，随主题更换。

```
商卡 > 商卡信息 > 下部分 > 店铺行 > 店铺名称 FRAME > TEXT（按 type 查找，不按 name）
```

> ⚠️ TEXT 节点的 `name` 与 `characters` 自动同步，不能用固定名称定位。

```javascript
const shopRow       = lower.children.find(n => n.name === '店铺行');
const shopNameFrame = shopRow.children.find(n => n.name === '店铺名称');
const shopText      = shopNameFrame.children.find(n => n.type === 'TEXT');
if (shopText) shopText.characters = d['data']['products'][0]['shop_name'];
```

---

## 常见错误

| 错误现象 | 原因 | 修复 |
|---------|------|------|
| 战略标签文字变成商品名 | 用 `findAll(TEXT)[0]` 递归进 INSTANCE | 改用 `children.find(TEXT)` |
| 战略标签恢复后尺寸仍错 | 改文字会撑大父节点，不自动缩回 | 还原文字后 `resize` 父节点 |
| 价格显示 `¥199199` | `findAll(含¥)` 改到了¥符号节点 | 只改 `children.find(n=>n.name==='价格')` 纯数字节点 |
| 商品名换行 | 名称超宽或未设 TRUNCATE | 逐字估算宽度；`maxLines=1` + `TRUNCATE` |
| `createImageAsync` 返回 null | URL 不可达 | 取 `products[1]` 换一张 |
| 鱼眼文案未变 | 旧内容残留，克隆不自动清除 | 显式覆写 `clone.findAll(n=>n.name==='鱼眼文案')[0].characters` |
| 修改了原始模版 | 直接操作了原始节点 | 始终在 `clone()` 副本上操作 |
