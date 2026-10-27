/* esbuild 插件：构建期把 Vue 组件的 template 字符串编译为 render 函数，
   使运行时不再需要 new Function / eval，CSP 可保持 script-src 'self' 无需 unsafe-eval
*/
const fs = require('fs');
const { compile } = require('@vue/compiler-dom');

module.exports = {
  name: 'vue-precompile-template',
  setup(build) {
    build.onLoad({ filter: /main\.js$/ }, async (args) => {
      let src = fs.readFileSync(args.path, 'utf8');

      // 匹配对象字面量里的 template 属性（反引号或单引号模板串）
      const re = /(\btemplate:\s*)(`(?:\\.|[^`\\])*`|'(?:\\.|[^'\\])*')/g;
      let count = 0;
      let failed = 0;

      src = src.replace(re, (match, prefix, literal) => {
        // 还原字符串字面量为模板源码
        let tpl;
        if (literal.startsWith('`')) {
          tpl = literal.slice(1, -1)
            .replace(/\\`/g, '`')
            .replace(/\\\\/g, '\\');
        } else {
          tpl = literal.slice(1, -1)
            .replace(/\\'/g, "'")
            .replace(/\\\\/g, '\\');
        }
        // 非 HTML 模板（保险）：原样保留
        if (!/^\s*</.test(tpl)) return match;

        let code;
        try {
          const r = compile(tpl, {
            mode: 'function',
            hoistStatic: true,
            prefixIdentifiers: true,
            onError(e) { throw e; },
          });
          code = r.code;
        } catch (e) {
          failed++;
          console.warn('[vue-precompile] 编译失败，保留 template:', e.message);
          return match;
        }
        count++;
        // compiler(mode:'function') 输出形如：
        //   const { createElementVNode: _x, ... } = Vue
        //   const _hoisted_1 = ...
        //   return function render(_ctx, _cache) {...}
        // 用 IIFE 把 Vue 命名空间注进去，返回 render 函数
        return 'render: ((Vue) => {\n' + code + '\n})(Vue)';
      });

      console.log(`[vue-precompile] 预编译模板 ${count} 处，失败 ${failed} 处`);
      return { contents: src, loader: 'js' };
    });
  },
};
