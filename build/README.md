# 前端构建

```bash
cd build
npm install        # 首次
npm run build      # → ../static/js/bundle.js + bundle.css
```

## 关键约束：CSP 不能加 unsafe-eval

站点 CSP 为 `script-src 'self'`（无 `unsafe-eval`）。
Vue 的运行时模板编译用 `new Function()`，会被 CSP 拦截 → **白屏**。

因此本构建用 `vue-template-plugin.js`（esbuild 插件）在**构建期**
把 `template: '...'` 预编译成 `render` 函数（`@vue/compiler-dom`），
运行时零 eval，CSP 可保持严格。

同时 vue 用 **runtime-only** 构建（`vue.runtime.esm-bundler.js`），
体积更小——模板已预编译，不需要编译器。

## 踩过的坑

1. `antd.min.js` UMD 不是独立包，依赖 vue + dayjs + 6 个 dayjs 插件
2. esbuild 默认解析到 `vue.runtime.esm-bundler.js`，`template:` 不编译 → 白屏
3. 即使换成完整构建，运行时编译仍需 `new Function`，被 CSP 拦 → 还是白屏
4. **验证白屏必须用 Playwright/jsdom 在真实 CSP 下测**，curl 只能验资源可达
