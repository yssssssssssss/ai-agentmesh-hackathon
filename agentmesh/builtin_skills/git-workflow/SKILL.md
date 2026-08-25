---
name: git-workflow
harness-version: 0
description: "Git 分支工作流助手。封装常用的分支操作：开始新工作、保存进度、 确认合并、丢弃改动、查看历史。不需要记任何 git 命令，用自然语言描述要做什么即可。 调用示例：\n  /git-workflow start 更新knowledge-preview样式\n\
  \  /git-workflow save 调整了截图区块布局\n  /git-workflow done\n  /git-workflow discard\n  /git-workflow status\n  /git-workflow\
  \ log\n"
user-invocable: true
triggers:
- 分支操作
- 提交代码
- git 相关操作
allowed-tools:
- Bash
metadata:
  author: 2C-DesignWiki
  source: 2C-DesignWiki/jd-design-system-md-v16/product-architecture/huangliu-design/product-details/JD-ProductDetails-web/brain-frontend/public/design-kb/skills/git-workflow/SKILL.md
  agentmesh-wiki-import: 'true'
  agentmesh-stage: post_design
  agentmesh-activation: explicit_only
  short-description: Git 分支工作流助手。封装常用的分支操作：开始新工作、保存进度、 确认合并、丢弃改动、查看历史。不需要记任何 git 命令，用自然语言描述要做什么即可。 调用示例： /git-workflow s…
disable-model-invocation: true
---

# /git-workflow · Git 分支工作流助手

## 工作目录

执行本 skill 前，请先定位到仓库中的 `JD-ProductDetails-web/brain-frontend/` 目录，
所有路径均以此为根目录。

## 这个 Skill 做什么

把常用的 Git 分支操作封装成简单指令，不需要记具体命令：

- `start`：开始新工作，自动创建分支
- `save`：保存当前进度到分支
- `done`：确认没问题，合并回主线
- `discard`：改坏了，丢弃全部改动
- `status`：查看当前状态
- `log`：查看历史记录

## 调用方式

```
/git-workflow start <工作描述>     ← 开始新工作，创建分支
/git-workflow save <改动说明>      ← 保存当前进度
/git-workflow done                 ← 确认完成，合并回 main
/git-workflow discard              ← 丢弃当前分支所有改动，回到 main
/git-workflow status               ← 查看当前在哪个分支、有哪些未保存改动
/git-workflow log                  ← 查看最近 10 条历史记录
```

---

## 执行流程

### start：开始新工作

```
/git-workflow start 更新knowledge-preview样式
```

**执行：**

```bash
# 1. 确保在 main 分支且是最新状态
git checkout main
git pull origin main

# 2. 根据工作描述生成分支名（英文小写+连字符）
# 例："更新knowledge-preview样式" → "update/knowledge-preview-style"

# 3. 创建并切换到新分支
git checkout -b update/knowledge-preview-style
```

分支命名规则：
- 新功能：`feature/xxx`
- 修复问题：`fix/xxx`
- 更新优化：`update/xxx`
- 录入案例：`case/xxx`

**输出：**
```
✅ 已创建分支 update/knowledge-preview-style
现在可以开始工作了。完成后运行：
- /git-workflow save <说明>   保存进度
- /git-workflow done          完成并合并
- /git-workflow discard       放弃所有改动
```

---

### save：保存当前进度

```
/git-workflow save 调整了截图区块布局，增加了点击放大功能
```

**执行：**

```bash
# 检查当前分支（不能在 main 上直接 save）
git branch --show-current

# 保存所有改动
git add .
git commit -m "[说明]"
git push origin <当前分支名>
```

若当前在 main 分支，提示：
```
⚠️ 你现在在 main 分支上，直接保存会影响主线。
建议先运行 /git-workflow start <工作描述> 创建分支再保存。
是否仍然直接保存到 main？（请明确回复「确认」才会执行）
```

**输出：**
```
✅ 进度已保存

分支：update/knowledge-preview-style
说明：调整了截图区块布局，增加了点击放大功能
改动文件：[列出改动的文件列表]

继续工作后再次运行 /git-workflow save 保存，
完成后运行 /git-workflow done 合并回主线。
```

---

### done：完成工作，合并回 main

```
/git-workflow done
```

**执行前先确认：**

```bash
# 显示当前分支与 main 的差异摘要
git diff main --stat
```

输出差异摘要，询问确认：
```
准备将以下改动合并到 main：

分支：update/knowledge-preview-style
改动文件：
  - skills/knowledge-preview/SKILL.md（+45 -23行）

确认合并吗？（回复「确认」执行，回复「取消」退出）
```

用户回复「确认」后执行：

```bash
git checkout main
git merge <分支名> --no-ff -m "合并：[分支名]"
git push origin main
git branch -d <分支名>
```

**输出：**
```
✅ 已合并到 main 并推送到 GitHub

合并的分支：update/knowledge-preview-style（已删除）
main 现在是最新状态。
```

---

### discard：丢弃改动，回到 main

```
/git-workflow discard
```

**执行前先确认：**

```bash
git branch --show-current
git diff main --stat
```

输出当前未合并的改动，询问确认：
```
⚠️ 即将丢弃以下所有改动，此操作不可恢复：

分支：update/knowledge-preview-style
将丢弃的改动：
  - skills/knowledge-preview/SKILL.md（+45 -23行）

确认丢弃吗？（回复「确认丢弃」执行，其他回复取消）
```

用户回复「确认丢弃」后执行：

```bash
git checkout main
git branch -D <分支名>
```

**输出：**
```
✅ 已丢弃分支 update/knowledge-preview-style 的所有改动
现在回到 main 的最新状态。
```

若当前在 main 分支，提示：
```
⚠️ 你现在在 main 分支上，没有可丢弃的分支改动。
如果你想回退 main 的某次提交，运行 /git-workflow log 查看历史，
告诉我要回退到哪个版本。
```

---

### status：查看当前状态

```
/git-workflow status
```

**执行：**

```bash
git branch --show-current
git status --short
git log main..HEAD --oneline
```

**输出：**
```
📍 当前分支：update/knowledge-preview-style

未保存的改动：
  - skills/knowledge-preview/SKILL.md（已修改）

本分支已保存的记录：
  - 调整了截图区块布局，增加了点击放大功能

与 main 的差异：1 个文件，+45 -23 行
```

若在 main 分支且无改动：
```
📍 当前在 main 分支，无未保存改动。
最近一次保存：[最近 commit 的说明和时间]
```

---

### log：查看历史记录

```
/git-workflow log
```

**执行：**

```bash
git log --oneline -10 --all --decorate
```

**输出（翻译为可读格式）：**
```
📋 最近 10 条历史记录

  [今天 16:30] 合并：update/knowledge-preview-style
  [今天 15:45] 调整了截图区块布局，增加了点击放大功能
  [今天 11:15] 新增Case：国补叠加以旧换新利益点感知提升
  [昨天 10:30] 初始化：4个Skills + 2个Case + 知识库索引
  ...

如需回退到某个版本，告诉我「回退到第N条」。
```

---

### 回退到历史版本（在 log 后触发）

用户说「回退到第3条」或「回退到 abc1234」：

**执行前确认：**
```
⚠️ 即将回退到：「新增Case：国补叠加以旧换新利益点感知提升」

回退后，该版本之后的所有改动将从 main 消失（但 Git 历史保留）。
此操作会自动创建一个「回退」commit，可以再次回退。

确认回退吗？（回复「确认回退」执行）
```

**执行：**
```bash
git revert <commit-id>..HEAD --no-commit
git commit -m "回退到：[版本说明]"
git push origin main
```

**输出：**
```
✅ 已回退到「新增Case：国补叠加以旧换新利益点感知提升」的状态
main 已推送到 GitHub。
```

---

## 关键约束

1. **save 和 done 之前必须展示改动摘要。** 不能盲目执行，让用户知道改了什么。
2. **discard 必须二次确认。** 必须用户明确回复「确认丢弃」才执行，其他任何回复都取消。
3. **done 必须二次确认。** 用户回复「确认」才合并。
4. **不在 main 上直接 save。** 检测到在 main 分支时，save 操作要提示并询问确认。
5. **分支名自动生成。** 根据用户的工作描述自动生成英文分支名，不需要用户手动写。
6. **回退只用 revert，不用 reset。** revert 保留历史，reset 会删除历史，前者更安全。

---

## 版本历史

- **v1.0** (2026-05-22) 初版
