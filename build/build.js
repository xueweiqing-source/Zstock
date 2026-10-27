/* 构建脚本：打包 vue + ant-design-vue + 页面逻辑
 * 关键：用 vue-template-plugin 预编译模板，运行时无需 eval（CSP 友好）
 */
const esbuild = require('esbuild');
const vuePrecompile = require('./vue-template-plugin');

esbuild.build({
  entryPoints: ['src/main.js'],
  bundle: true,
  minify: true,
  format: 'iife',
  outfile: '../static/js/bundle.js',
  plugins: [vuePrecompile],
  // 模板已预编译，用 runtime-only 构建即可（体积更小）
  alias: { vue: './node_modules/vue/dist/vue.runtime.esm-bundler.js' },
  define: {
    'process.env.NODE_ENV': '"production"',
    '__VUE_OPTIONS_API__': 'true',
    '__VUE_PROD_DEVTOOLS__': 'false',
    '__VUE_PROD_HYDRATION_MISMATCH_DETAILS__': 'false',
  },
  loader: { '.js': 'jsx' },
}).then(() => console.log('打包完成')).catch((e) => {
  console.error(e);
  process.exit(1);
});
