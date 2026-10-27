# 前端构建

改动 `build/src/main.js` 后重新打包：

```bash
cd build
npm install          # 首次
npm run build        # 产出到 ../static/js/bundle.js + bundle.css
```

**关键**：必须用 `--alias:vue=./node_modules/vue/dist/vue.esm-bundler.js`
指到含模板编译器的完整构建。默认解析到 `vue.runtime.esm-bundler.js`
（runtime-only），`template:` 字符串不编译 → 白屏。
