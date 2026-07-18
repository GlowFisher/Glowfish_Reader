# FAQ 强调色标题条 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将 FAQ 三条常显问答改为带蓝色题签和史料式细分隔线的阅读卡片。

**Architecture:** 保持 `index.html` 中的三张静态 `article.faq-item` 结构不变，仅在 `sections.css` 中重构 FAQ 卡片的题签、正文和移动端间距。测试文件断言结构、字体和新 CSS 标记；首页更新样式查询版本以避开缓存。

**Tech Stack:** 静态 HTML、CSS、Python `unittest`。

## Global Constraints

- FAQ 必须保留三条常显答案，不得新增 `details`、`summary`、折叠按钮或 JavaScript 交互。
- 标题继续使用加粗新细明体字体栈。
- 修改 `sections.css` 时必须更新 `index.html` 的样式查询版本。
- 通过 `tests/test_website_landing_static.py` 的全部测试后方可部署。

---

### Task 1: 为强调色题签建立回归测试

**Files:**
- Modify: `tests/test_website_landing_static.py`
- Test: `tests/test_website_landing_static.py`

- [ ] **Step 1: 写入失败断言**

```python
self.assertIn("border-left: 3px solid #3867ff;", css)
self.assertIn("background: #e9f1ff;", css)
self.assertIn("border-top: 1px solid rgba(19, 42, 82, .12);", css)
self.assertIn('assets/css/sections.css?v=20260718c', html)
```

- [ ] **Step 2: 验证测试失败**

运行：

```powershell
& 'C:\\Users\\18267\\.cache\\codex-runtimes\\codex-primary-runtime\\dependencies\\python\\python.exe' -m unittest tests/test_website_landing_static.py -q
```

预期：因 CSS 尚未含题签标记且首页版本仍为 `20260718b` 而失败。

### Task 2: 实现题签与正文阅读层级

**Files:**
- Modify: `glowfish_reader/website/assets/css/sections.css`
- Modify: `glowfish_reader/website/index.html`
- Test: `tests/test_website_landing_static.py`

- [ ] **Step 1: 在 `.faq-q` 中实现强调色题签**

```css
.faq-q {
  border-left: 3px solid #3867ff;
  background: #e9f1ff;
  border-radius: 10px 10px 0 0;
}
```

- [ ] **Step 2: 在 `.faq-answer` 中分隔正文区域**

```css
.faq-answer {
  border-top: 1px solid rgba(19, 42, 82, .12);
  background: #fff;
}
```

- [ ] **Step 3: 更新样式缓存版本**

```html
<link rel="stylesheet" href="assets/css/sections.css?v=20260718c">
```

- [ ] **Step 4: 验证测试通过**

运行：

```powershell
& 'C:\\Users\\18267\\.cache\\codex-runtimes\\codex-primary-runtime\\dependencies\\python\\python.exe' -m unittest tests/test_website_landing_static.py -q
```

预期：全部测试通过。

### Task 3: 部署与线上验证

**Files:**
- Deploy: `glowfish_reader/website/index.html`
- Deploy: `glowfish_reader/website/assets/css/sections.css`

- [ ] **Step 1: 提交源代码与设计文档**

```powershell
git add -- docs/superpowers glowfish_reader/website/index.html glowfish_reader/website/assets/css/sections.css tests/test_website_landing_static.py
git commit -m "feat(website): refine FAQ accent headers"
```

- [ ] **Step 2: 上传 CSS 后原子替换首页**

```powershell
scp -i 'C:\\Users\\18267\\.ssh\\glowfish_license_deploy' glowfish_reader/website/assets/css/sections.css root@47.83.12.17:/var/www/glowfish/site/assets/css/sections.css
scp -i 'C:\\Users\\18267\\.ssh\\glowfish_license_deploy' glowfish_reader/website/index.html root@47.83.12.17:/var/www/glowfish/site/index.html.next
ssh -i 'C:\\Users\\18267\\.ssh\\glowfish_license_deploy' root@47.83.12.17 "mv /var/www/glowfish/site/index.html.next /var/www/glowfish/site/index.html"
```

- [ ] **Step 3: 验证线上内容**

```powershell
curl.exe -L --silent https://glowfishreader.com/ | Select-String 'sections.css?v=20260718c'
curl.exe -L --silent 'https://glowfishreader.com/assets/css/sections.css?v=20260718c' | Select-String 'border-left: 3px solid #3867ff;'
```

预期：首页引用新版本样式，样式表包含强调色标题条。
