/* Zstock 前端入口（esbuild 打包：vue + ant-design-vue + echarts + 页面逻辑） */
import { createApp, ref, reactive, computed, onMounted, watch, h, onBeforeUnmount, nextTick } from 'vue';
import * as Vue from 'vue';
import Antd from 'ant-design-vue';
import 'ant-design-vue/dist/reset.css';
import * as echarts from 'echarts/core';
import { CandlestickChart, BarChart, LineChart } from 'echarts/charts';
import { GridComponent, TooltipComponent, DataZoomComponent, VisualMapComponent, MarkLineComponent, LegendComponent } from 'echarts/components';
import { CanvasRenderer } from 'echarts/renderers';
echarts.use([CandlestickChart, BarChart, LineChart, GridComponent, TooltipComponent, DataZoomComponent, VisualMapComponent, MarkLineComponent, LegendComponent, CanvasRenderer]);

// API 基址：跟随页面挂载点（子路径部署如 /forecast/ 时自动适配）
const API_BASE = new URL('./api/', document.baseURI).href;
const apiUrl = (p) => API_BASE + p.replace(/^\//, '');

// ---------- API 客户端 ----------
  const api = {
    async req(url, opts = {}) {
      const csrf = sessionStorage.getItem('csrf') || '';
      const res = await fetch(url, {
        credentials: 'same-origin',
        headers: {
          'Content-Type': 'application/json',
          'X-CSRF-Token': csrf,
          ...(opts.headers || {}),
        },
        ...opts,
      });
      if (res.status === 401) {
        // 解析服务端具体错误（如"账号或密码错误"），而非一律显示"未登录"
        let msg = '请先登录';
        try { msg = (await res.json()).message || msg; } catch (e) {}
        // 登录接口自身的 401 不跳转（已在登录页），其余 401 跳回登录
        if (!url.includes('/login')) {
          window.location.hash = '#/login';
        }
        throw new Error(msg);
      }
      if (!res.ok) {
        let msg = '请求失败';
        try { msg = (await res.json()).message || msg; } catch (e) {}
        throw new Error(msg);
      }
      return res.json();
    },
    get(url) { return this.req(url); },
    post(url, body) { return this.req(url, { method: 'POST', body: JSON.stringify(body || {}) }); },
  };

  // ---------- 工具 ----------
  const fmt = (v, digits = 2) => (v === null || v === undefined || v === '') ? '—'
    : (typeof v === 'number' ? v.toFixed(digits) : v);
  const fmtPct = (v) => v === null || v === undefined ? '—' : (v >= 0 ? '+' : '') + Number(v).toFixed(2) + '%';
  const dirColor = (d) => d === '看涨' ? '#cf1322' : d === '看跌' ? '#389e0d' : 'rgba(0,0,0,.65)';
  const confTag = (c) => c === '高' ? 'blue' : c === '中' ? 'orange' : 'default';
  const dirTag = (d) => d === '看涨' ? 'red' : d === '看跌' ? 'green' : 'default';

  // ---------- 登录页 ----------
  const LoginPage = {
    template: `
      <div class="login-wrap">
        <div class="login-card">
          <div class="login-title">Zstock 预测分析平台</div>
          <div class="login-sub">热点股票池 · 三层分析 · 回测对账</div>
          <a-alert v-if="error" type="error" :message="error" show-icon style="margin-bottom:16px" />
          <a-form layout="vertical" @submit.prevent="doLogin">
            <a-form-item label="账号">
              <a-input v-model:value="username" placeholder="请输入账号" size="large" autofocus />
            </a-form-item>
            <a-form-item label="密码">
              <a-input-password v-model:value="password" placeholder="请输入密码" size="large" @pressEnter="doLogin" />
            </a-form-item>
            <a-button type="primary" block size="large" :loading="loading" html-type="submit">登 录</a-button>
          </a-form>
          <div class="login-foot">仅供内部参考，不构成投资建议 · 市场有风险</div>
        </div>
      </div>`,
    setup() {
      const username = ref(''); const password = ref('');
      const loading = ref(false); const error = ref('');
      const doLogin = async () => {
        loading.value = true; error.value = '';
        try {
          const r = await api.post(apiUrl('login'), { username: username.value, password: password.value });
          sessionStorage.setItem('csrf', r.csrf_token);
          window.location.hash = '#/dashboard';
        } catch (e) { error.value = e.message; }
        finally { loading.value = false; }
      };
      return { username, password, loading, error, doLogin };
    },
  };

  // ---------- 布局 ----------
  const menuItems = [
    { key: '#/dashboard', label: '仪表盘' },
    { key: '#/runs', label: '报告中心' },
    { key: '#/backtest', label: '回测与准确率' },
    { key: '#/settings', label: '规则与研判' },
  ];

  const AppLayout = {
    template: `
      <a-layout class="layout">
        <a-layout-sider class="sider" :width="208" theme="dark" v-model:collapsed="collapsed">
          <div class="logo"><span class="mark">Z</span><span v-if="!collapsed">Zstock</span></div>
          <a-menu theme="dark" mode="inline" :selectedKeys="selectedKeys" @click="onMenu">
            <a-menu-item v-for="m in menu" :key="m.key">{{ m.label }}</a-menu-item>
          </a-menu>
        </a-layout-sider>
        <a-layout>
          <a-layout-header class="header">
            <a-breadcrumb>
              <a-breadcrumb-item>Zstock</a-breadcrumb-item>
              <a-breadcrumb-item>{{ pageTitle }}</a-breadcrumb-item>
            </a-breadcrumb>
            <a-dropdown>
              <span style="cursor:pointer">{{ user }} <span style="color:rgba(0,0,0,.35)">▾</span></span>
              <template #overlay>
                <a-menu @click="onUserMenu">
                  <a-menu-item key="logout">退出登录</a-menu-item>
                </a-menu>
              </template>
            </a-dropdown>
          </a-layout-header>
          <a-layout-content class="content">
            <component :is="page" :params="pageParams"></component>
          </a-layout-content>
        </a-layout>
      </a-layout>`,
    props: ['page', 'pageParams', 'routeName'],
    setup(props) {
      const collapsed = ref(false);
      const user = ref(sessionStorage.getItem('user') || 'admin');
      const menu = menuItems;
      // 用响应式 prop routeName，而非 window.location.hash（非响应式，路由变了不重算）
      const selectedKeys = computed(() => {
        const name = props.routeName || 'dashboard';
        return [menuItems.find(m => m.key === '#/' + name)?.key || '#/dashboard'];
      });
      const pageTitle = computed(() => {
        const item = menuItems.find(m => selectedKeys.value[0] === m.key);
        return item ? item.label : '详情';
      });
      const onMenu = ({ key }) => { window.location.hash = key; };
      const onUserMenu = async ({ key }) => {
        if (key === 'logout') {
          await api.post(apiUrl('logout')); sessionStorage.clear();
          window.location.hash = '#/login';
        }
      };
      return { collapsed, user, menu, selectedKeys, pageTitle, onMenu, onUserMenu };
    },
  };

  // ---------- 仪表盘 ----------
  const Dashboard = {
    template: `
      <div>
        <h2 class="page-title">仪表盘</h2>
        <p class="page-desc">每日 22:00 自动运行，预测次一交易日 · 研判引擎：{{ data.engine?.label || '—' }}</p>

        <!-- 市场概览：A股 / 港股 / 全球 -->
        <a-card size="small" style="margin-bottom:16px">
          <template #title>
            <span style="font-size:15px;font-weight:600">市场概览</span>
            <span style="margin-left:12px;font-size:12px;color:rgba(0,0,0,.45);font-weight:400">
              {{ market.fetched_at ? '数据时间 ' + market.fetched_at : '' }}
            </span>
          </template>
          <a-spin :spinning="mktLoading">
            <!-- A股 -->
            <div class="market-section" v-if="(market.a_shares?.indices || []).length || market.a_shares?.breadth?.up">
              <div class="market-hd">
                <div class="market-label">A股</div>
                <div class="market-turnover" v-if="market.a_shares?.turnover?.total_yi">
                  两市成交 <b>{{ fmt(market.a_shares.turnover.total_yi, 0) }}</b> 亿
                  <span class="turnover-split">（沪 {{ fmt(market.a_shares.turnover.sh_yi, 0) }} 亿 · 深 {{ fmt(market.a_shares.turnover.sz_yi, 0) }} 亿）</span>
                </div>
              </div>
              <div class="index-grid">
                <div class="index-item" v-for="idx in (market.a_shares?.indices || [])" :key="idx.name">
                  <div class="index-name">{{ idx.name }}</div>
                  <div class="index-price" :class="pctCls(idx.change_pct)">{{ fmt(idx.price, 2) }}</div>
                  <div class="index-row">
                    <span class="index-chg" :class="pctCls(idx.change_pct)">{{ chgStr(idx.change) }}</span>
                    <span class="index-pct" :class="pctCls(idx.change_pct)">{{ pctStr(idx.change_pct) }}</span>
                  </div>
                  <div class="index-amt" v-if="idx.amount_yi != null">{{ amtStr(idx.amount_yi) }}</div>
                </div>
              </div>
              <div class="breadth-wrap" v-if="market.a_shares?.breadth?.up != null">
                <div class="breadth-track">
                  <div class="breadth-up" :style="{width: upPct + '%'}"></div>
                  <div class="breadth-flat" :style="{width: flatPct + '%'}"></div>
                  <div class="breadth-down" :style="{width: downPct + '%'}"></div>
                </div>
                <div class="breadth-text">
                  <span class="c-up">涨 {{ market.a_shares.breadth.up }}</span>
                  · <span class="c-flat">平 {{ market.a_shares.breadth.flat }}</span>
                  · <span class="c-down">跌 {{ market.a_shares.breadth.down }}</span>
                </div>
              </div>
            </div>

            <!-- 港股 -->
            <div class="market-section" v-if="(market.hk?.indices || []).length">
              <div class="market-hd">
                <div class="market-label">港股</div>
              </div>
              <div class="index-grid">
                <div class="index-item" v-for="idx in (market.hk?.indices || [])" :key="idx.name">
                  <div class="index-name">{{ idx.name }}</div>
                  <div class="index-price" :class="pctCls(idx.change_pct)">{{ fmt(idx.price, 2) }}</div>
                  <div class="index-row">
                    <span class="index-chg" :class="pctCls(idx.change_pct)">{{ chgStr(idx.change) }}</span>
                    <span class="index-pct" :class="pctCls(idx.change_pct)">{{ pctStr(idx.change_pct) }}</span>
                  </div>
                </div>
              </div>
            </div>

            <!-- 全球：美股 / 亚太 / 欧洲 -->
            <div class="market-section" v-if="hasGlobal">
              <div class="market-hd">
                <div class="market-label">全球</div>
              </div>
              <div class="global-block" v-if="(market.global?.us || []).length">
                <div class="global-tag">🇺🇸 美股</div>
                <div class="index-grid">
                  <div class="index-item" v-for="idx in (market.global.us || [])" :key="idx.name">
                    <div class="index-name">{{ idx.name }}</div>
                    <div class="index-price" :class="pctCls(idx.change_pct)">{{ fmt(idx.price, 2) }}</div>
                    <div class="index-row">
                      <span class="index-pct" :class="pctCls(idx.change_pct)">{{ pctStr(idx.change_pct) }}</span>
                    </div>
                  </div>
                </div>
              </div>
              <div class="global-block" v-if="(market.global?.asia || []).length">
                <div class="global-tag">🌏 亚太</div>
                <div class="index-grid">
                  <div class="index-item" v-for="idx in (market.global.asia || [])" :key="idx.name">
                    <div class="index-name">{{ idx.name }}</div>
                    <div class="index-price" :class="pctCls(idx.change_pct)">{{ fmt(idx.price, 2) }}</div>
                    <div class="index-row">
                      <span class="index-pct" :class="pctCls(idx.change_pct)">{{ pctStr(idx.change_pct) }}</span>
                    </div>
                  </div>
                </div>
              </div>
              <div class="global-block" v-if="(market.global?.europe || []).length">
                <div class="global-tag">🌍 欧洲</div>
                <div class="index-grid">
                  <div class="index-item" v-for="idx in (market.global.europe || [])" :key="idx.name">
                    <div class="index-name">{{ idx.name }}</div>
                    <div class="index-price" :class="pctCls(idx.change_pct)">{{ fmt(idx.price, 2) }}</div>
                    <div class="index-row">
                      <span class="index-pct" :class="pctCls(idx.change_pct)">{{ pctStr(idx.change_pct) }}</span>
                    </div>
                  </div>
                </div>
              </div>
            </div>

            <div v-if="!mktLoading && !hasAnyMarket" style="padding:24px 0;text-align:center;color:rgba(0,0,0,.35)">
              行情数据暂不可用，请稍后刷新
            </div>
          </a-spin>
        </a-card>

        <a-spin :spinning="loading">
          <div class="stat-row" v-if="data.latest">
            <div class="stat-item">
              <div class="label">最新期号</div>
              <div class="value" style="font-size:16px">{{ data.latest.run_id }}</div>
              <div class="sub">{{ data.latest.generated_at }}</div>
            </div>
            <div class="stat-item">
              <div class="label">大盘判断</div>
              <div class="value" :class="trendClass">{{ data.latest.market_trend || '—' }}</div>
              <div class="sub">综合分 {{ fmt(data.latest.market_score, 1) }}</div>
            </div>
            <div class="stat-item">
              <div class="label">样本股</div>
              <div class="value">{{ data.latest.stock_count ?? '—' }}</div>
              <div class="sub">消息 {{ data.latest.news_count ?? 0 }} 条</div>
            </div>
            <div class="stat-item">
              <div class="label">回测命中率</div>
              <div class="value">{{ bt.rate != null ? bt.rate + '%' : '—' }}</div>
              <div class="sub">{{ bt.n }} 条已对账</div>
            </div>
            <div class="stat-item">
              <div class="label">消息面情绪</div>
              <div class="value">{{ data.latest.sentiment_label || '—' }}</div>
              <div class="sub">情绪分 {{ fmt(data.latest.sentiment_score, 0) }}</div>
            </div>
          </div>

          <a-row :gutter="16" v-if="data.latest">
            <a-col :span="12">
              <a-card title="预测方向分布" size="small">
                <div style="display:flex;gap:8px;flex-wrap:wrap">
                  <a-tag v-for="(v,k) in data.distribution" :key="k" :color="dirTag(k)" style="font-size:13px;padding:2px 12px">
                    {{ k }} {{ v }}
                  </a-tag>
                </div>
                <div style="margin-top:12px">
                  <span style="color:rgba(0,0,0,.45);font-size:12px">置信度：</span>
                  <a-tag v-for="(v,k) in data.confidence_dist" :key="k" :color="confTag(k)">{{ k }} {{ v }}</a-tag>
                </div>
              </a-card>
            </a-col>
            <a-col :span="12">
              <a-card title="大盘影响因素" size="small">
                <ul style="margin:0;padding-left:18px;color:rgba(0,0,0,.65);font-size:13px;line-height:1.9">
                  <li v-for="f in factors" :key="f">{{ f }}</li>
                </ul>
                <div v-if="!factors.length" style="color:rgba(0,0,0,.35)">暂无</div>
              </a-card>
            </a-col>
          </a-row>

          <a-card title="最近运行" size="small" style="margin-top:16px">
            <a-table :dataSource="data.runs || []" :columns="runCols" rowKey="run_id" size="middle" :pagination="false">
              <template #bodyCell="{ column, record }">
                <template v-if="column.key === 'trend'">
                  <a-tag :color="dirTag(record.market_trend)">{{ record.market_trend || '—' }}</a-tag>
                </template>
                <template v-if="column.key === 'action'">
                  <a @click="go('#/report/' + record.run_id)">查看</a>
                </template>
              </template>
            </a-table>
          </a-card>
        </a-spin>
      </div>`,
    setup() {
      const data = ref({}); const loading = ref(true);
      const factors = ref([]);
      // 市场指数从 dashboard API 合并返回，消除单独调用的时序问题
      const market = computed(() => data.value.market || {});
      const mktLoading = computed(() => loading.value);
      const bt = computed(() => data.value.backtest?.total || {});
      const trendClass = computed(() => {
        const t = data.value.latest?.market_trend;
        return t === '偏多' ? 'pos' : t === '偏空' ? 'neg' : '';
      });
      const pctCls = (v) => v > 0 ? 'c-up' : v < 0 ? 'c-down' : 'c-flat';
      const pctStr = (v) => v == null ? '—' : (v > 0 ? '+' : '') + Number(v).toFixed(2) + '%';
      const chgStr = (v) => v == null ? '' : (v > 0 ? '+' : '') + Number(v).toFixed(2);
      const amtStr = (v) => {
        if (v == null) return '';
        const yi = Number(v) / 1e8;
        return yi >= 10000 ? (yi / 10000).toFixed(2) + '万亿' : yi.toFixed(0) + '亿';
      };
      const upPct = computed(() => {
        const b = market.value.a_shares?.breadth;
        if (!b || b.up == null) return 50;
        const total = (b.up || 0) + (b.down || 0) + (b.flat || 0);
        return total ? (b.up / total) * 100 : 50;
      });
      const downPct = computed(() => {
        const b = market.value.a_shares?.breadth;
        if (!b || b.down == null) return 50;
        const total = (b.up || 0) + (b.down || 0) + (b.flat || 0);
        return total ? (b.down / total) * 100 : 50;
      });
      const flatPct = computed(() => Math.max(0, 100 - upPct.value - downPct.value));
      const hasGlobal = computed(() => {
        const g = market.value.global || {};
        return ((g.us || []).length + (g.asia || []).length + (g.europe || []).length) > 0;
      });
      const hasAnyMarket = computed(() => {
        return ((market.value.a_shares?.indices || []).length
          + (market.value.hk?.indices || []).length
          + (hasGlobal.value ? 1 : 0)) > 0;
      });
      const runCols = [
        { title: '期号', dataIndex: 'run_id', key: 'run_id' },
        { title: '生成时间', dataIndex: 'generated_at', key: 'time' },
        { title: '大盘', key: 'trend' },
        { title: '样本', dataIndex: 'stock_count', key: 'n' },
        { title: '消息', dataIndex: 'news_count', key: 'news' },
        { title: '消息窗口', dataIndex: 'news_window', key: 'window', ellipsis: true },
        { title: '操作', key: 'action' },
      ];
      onMounted(async () => {
        try {
          const d = await api.get(apiUrl('dashboard'));
          data.value = d;
          factors.value = (d.latest?.market_factors && typeof d.latest.market_factors === 'string')
            ? JSON.parse(d.latest.market_factors || '[]') : (d.latest?.market_factors || []);
        } catch (e) { console.error(e); }
        loading.value = false;
      });
      return {
        data, loading, market, mktLoading, factors, bt, trendClass,
        pctCls, pctStr, chgStr, amtStr, upPct, downPct, flatPct, hasGlobal, hasAnyMarket,
        runCols, fmt, dirTag, confTag, go: (h) => window.location.hash = h,
      };
    },
  };

  // ---------- 报告中心 ----------
  const RunsList = {
    template: `
      <div>
        <h2 class="page-title">报告中心</h2>
        <p class="page-desc">历史报告列表，点击行内链接查看明细</p>
        <a-table :dataSource="rows" :columns="cols" rowKey="run_id" :loading="loading" :pagination="{ pageSize: 10 }">
          <template #bodyCell="{ column, record }">
            <template v-if="column.key === 'trend'">
              <a-tag :color="dirTag(record.market_trend)">{{ record.market_trend || '—' }}</a-tag>
            </template>
            <template v-if="column.key === 'score'">{{ fmt(record.market_score, 1) }}</template>
            <template v-if="column.key === 'action'">
              <a @click="go('#/report/' + record.run_id)">查看</a>
            </template>
          </template>
        </a-table>
      </div>`,
    setup() {
      const rows = ref([]); const loading = ref(true);
      const cols = [
        { title: '期号', dataIndex: 'run_id', key: 'id', sorter: (a, b) => a.run_id.localeCompare(b.run_id) },
        { title: '生成时间', dataIndex: 'generated_at', key: 'time' },
        { title: '执行日', dataIndex: 'weekday', key: 'wd' },
        { title: '消息窗口', dataIndex: 'news_window', key: 'window', ellipsis: true },
        { title: '大盘', key: 'trend' },
        { title: '综合分', key: 'score' },
        { title: '样本股', dataIndex: 'stock_count', key: 'n' },
        { title: '消息', dataIndex: 'news_count', key: 'news' },
        { title: '操作', key: 'action' },
      ];
      onMounted(async () => {
        try { rows.value = (await api.get(apiUrl('runs'))).runs; } catch (e) { console.error(e); }
        loading.value = false;
      });
      return { rows, loading, cols, fmt, dirTag, go: (h) => window.location.hash = h };
    },
  };

  // ---------- 报告详情 ----------
  const ReportDetail = {
    props: ['params'],
    template: `
      <div>
        <h2 class="page-title">报告详情 <span class="mono" style="color:rgba(0,0,0,.45);font-size:13px">{{ run.run_id }}</span></h2>
        <p class="page-desc">{{ run.generated_at }} · {{ run.news_window }}</p>

        <a-descriptions bordered size="small" :column="3" v-if="run.run_id">
          <a-descriptions-item label="大盘判断">
            <a-tag :color="dirTag(run.market_trend)">{{ run.market_trend || '—' }}</a-tag>
          </a-descriptions-item>
          <a-descriptions-item label="综合分">{{ fmt(run.market_score, 1) }}</a-descriptions-item>
          <a-descriptions-item label="消息面情绪">{{ run.sentiment_label }}（{{ fmt(run.sentiment_score, 0) }}）</a-descriptions-item>
          <a-descriptions-item label="样本股">{{ run.stock_count }}</a-descriptions-item>
          <a-descriptions-item label="消息样本">{{ run.news_count }}</a-descriptions-item>
          <a-descriptions-item label="执行日">{{ run.weekday }}</a-descriptions-item>
        </a-descriptions>

        <a-card title="大盘影响因素" size="small" style="margin-top:16px" v-if="factors.length">
          <ul style="margin:0;padding-left:18px;line-height:1.9;font-size:13px">
            <li v-for="f in factors" :key="f">{{ f }}</li>
          </ul>
        </a-card>

        <a-card title="风险提示" size="small" style="margin-top:12px" v-if="risks.length">
          <ul style="margin:0;padding-left:18px;line-height:1.9;font-size:13px;color:#cf1322">
            <li v-for="r in risks" :key="r">{{ r }}</li>
          </ul>
        </a-card>

        <a-card size="small" style="margin-top:16px">
          <template #title>个股预测（{{ stocks.length }}）</template>
          <template #extra>
            <a @click="openFull">查看完整报告 →</a>
          </template>
          <a-table :dataSource="stocks" :columns="stockCols" rowKey="id" size="small" :pagination="{ pageSize: 20 }">
            <template #bodyCell="{ column, record }">
              <template v-if="column.key === 'code'">
                <a class="link" @click="goStock(record)">{{ record.code }}.{{ record.market }}</a>
              </template>
              <template v-if="column.key === 'dir'">
                <a-tag :color="dirTag(record.direction)">{{ record.direction }}</a-tag>
              </template>
              <template v-if="column.key === 'conf'">
                <a-tag :color="confTag(record.confidence)">{{ record.confidence }}</a-tag>
              </template>
              <template v-if="column.key === 'price'">{{ fmt(record.price, 2) }}</template>
              <template v-if="column.key === 'chg'">
                <span :style="{color: (record.change_pct||0) >= 0 ? '#cf1322' : '#389e0d'}">{{ fmtPct(record.change_pct) }}</span>
              </template>
              <template v-if="column.key === 'pe'">{{ fmt(record.pe_ttm, 1) }}</template>
              <template v-if="column.key === 'pb'">{{ fmt(record.pb, 2) }}</template>
              <template v-if="column.key === 'comp'">{{ fmt(record.composite_score, 1) }}</template>
            </template>
          </a-table>
        </a-card>

        <a-card title="完整报告" size="small" style="margin-top:16px">
          <iframe v-if="reportUrl" :src="reportUrl" class="report-frame"></iframe>
        </a-card>
      </div>`,
    setup(props) {
      const run = ref({}); const stocks = ref([]);
      const factors = ref([]); const risks = ref([]);
      const reportUrl = computed(() => run.value.run_id ? apiUrl('report/' + run.value.run_id + '/html') : '');
      const stockCols = [
        { title: '代码', key: 'code' },
        { title: '名称', dataIndex: 'name', key: 'name', ellipsis: true },
        { title: '方向', key: 'dir' },
        { title: '置信度', key: 'conf' },
        { title: '综合分', key: 'comp' },
        { title: '现价', key: 'price' },
        { title: '涨跌%', key: 'chg' },
        { title: 'PE(TTM)', key: 'pe' },
        { title: 'PB', key: 'pb' },
        { title: '依据', dataIndex: 'brief', key: 'brief', ellipsis: true },
      ];
      onMounted(async () => {
        try {
          const r = await api.get(apiUrl('report/') + props.params.id);
          run.value = r.run; stocks.value = r.stocks;
          factors.value = r.market_factors || [];
          risks.value = r.market_risks || [];
        } catch (e) { console.error(e); }
      });
      return {
        run, stocks, factors, risks, stockCols, reportUrl, fmt, fmtPct, dirTag, confTag,
        goStock: (rec) => window.location.hash = `#/stock/${rec.market}/${rec.code}`,
        openFull: () => window.open(reportUrl.value, '_blank'),
      };
    },
  };

  // ---------- 个股详情 ----------
  const StockDetail = {
    props: ['params'],
    template: `
      <div>
        <h2 class="page-title">{{ stock.name || '—' }}
          <span class="mono" style="color:rgba(0,0,0,.45);font-size:13px">{{ stock.code }}.{{ stock.market }}</span>
        </h2>
        <p class="page-desc">三层评分与历史预测对账</p>

        <!-- K 线图 -->
        <a-card size="small" style="margin-bottom:16px">
          <template #title>
            <span style="font-size:15px;font-weight:600">K 线图</span>
            <span style="margin-left:12px;font-size:12px;color:rgba(0,0,0,.45);font-weight:400">
              {{ klineFqLabel || '前复权' }} · {{ klineDays }} 日
            </span>
            <a-radio-group v-model:value="klineDays" size="small" style="float:right">
              <a-radio-button :value="60">60日</a-radio-button>
              <a-radio-button :value="120">120日</a-radio-button>
              <a-radio-button :value="250">250日</a-radio-button>
            </a-radio-group>
          </template>
          <a-spin :spinning="klineLoading">
            <div ref="klineRef" style="width:100%;height:580px"></div>
            <div v-if="!klineLoading && !klineRows.length" style="text-align:center;padding:24px;color:rgba(0,0,0,.35)">
              K 线数据暂不可用
            </div>
          </a-spin>
        </a-card>

        <a-descriptions bordered size="small" :column="4" v-if="latest.run_id">
          <a-descriptions-item label="最近预测">
            <a-tag :color="dirTag(latest.direction)">{{ latest.direction }}</a-tag>
          </a-descriptions-item>
          <a-descriptions-item label="置信度">
            <a-tag :color="confTag(latest.confidence)">{{ latest.confidence }}</a-tag>
          </a-descriptions-item>
          <a-descriptions-item label="综合分">{{ fmt(latest.composite_score, 1) }}</a-descriptions-item>
          <a-descriptions-item label="期号">{{ latest.run_id }}</a-descriptions-item>
          <a-descriptions-item label="基本面">{{ fmt(latest.fund_score, 1) }}（{{ latest.fund_verdict || '—' }}）</a-descriptions-item>
          <a-descriptions-item label="估值">{{ fmt(latest.val_score, 1) }}（{{ latest.val_verdict || '—' }}）</a-descriptions-item>
          <a-descriptions-item label="技术面">{{ fmt(latest.tech_score, 1) }}（{{ latest.tech_verdict || '—' }}）</a-descriptions-item>
          <a-descriptions-item label="预测价 / 实际">{{ fmt(latest.price_at_pred, 2) }} / {{ latest.result_pct != null ? fmtPct(latest.result_pct) : '待验证' }}</a-descriptions-item>
        </a-descriptions>

        <a-card title="历史预测与对账" size="small" style="margin-top:16px">
          <a-table :dataSource="stock.history" :columns="histCols" rowKey="id" size="small" :pagination="false">
            <template #bodyCell="{ column, record }">
              <template v-if="column.key === 'dir'">
                <a-tag :color="dirTag(record.direction)">{{ record.direction }}</a-tag>
              </template>
              <template v-if="column.key === 'conf'">
                <a-tag :color="confTag(record.confidence)">{{ record.confidence }}</a-tag>
              </template>
              <template v-if="column.key === 'run'">
                <a class="link" @click="go('#/report/' + record.run_id)">{{ record.run_id }}</a>
              </template>
              <template v-if="column.key === 'result'">
                <span v-if="record.result_pct != null" :style="{color: record.result_pct >= 0 ? '#cf1322' : '#389e0d'}">{{ fmtPct(record.result_pct) }}</span>
                <span v-else style="color:rgba(0,0,0,.35)">待验证</span>
              </template>
              <template v-if="column.key === 'hit'">
                <span v-if="record.hit === 1" style="color:#389e0d">命中</span>
                <span v-else-if="record.hit === 0" style="color:#cf1322">未中</span>
                <span v-else style="color:rgba(0,0,0,.35)">—</span>
              </template>
            </template>
          </a-table>
        </a-card>
      </div>`,
    setup(props) {
      const stock = ref({}); const latest = ref({});
      const klineRef = ref(null);
      const klineDays = ref(120);
      const klineLoading = ref(true);
      const klineRows = ref([]);
      const klineFqLabel = ref('');
      let klineChart = null;

      const histCols = [
        { title: '期号', key: 'run' },
        { title: '生成时间', dataIndex: 'generated_at', key: 'time' },
        { title: '大盘', dataIndex: 'market_trend', key: 'mt' },
        { title: '方向', key: 'dir' },
        { title: '置信度', key: 'conf' },
        { title: '综合分', dataIndex: 'composite_score', key: 'comp', render: (v) => fmt(v, 1) },
        { title: '预测价', dataIndex: 'price_at_pred', key: 'pp', render: (v) => fmt(v, 2) },
        { title: '实际涨跌', key: 'result' },
        { title: '命中', key: 'hit' },
      ];

      // K 线渲染（K线 + 成交量 + MACD + RSI 四面板）
      function renderKline(rows) {
        if (!klineRef.value || !rows.length) return;
        if (klineChart) klineChart.dispose();
        klineChart = echarts.init(klineRef.value);

        const dates = rows.map(r => r.date);
        const ohlc = rows.map(r => [r.open, r.close, r.low, r.high]); // ECharts: [open, close, low, high]
        const volumes = rows.map(r => r.volume || 0);
        const closes = rows.map(r => r.close);
        const hasInd = 'rsi14' in rows[0];
        const rsis = hasInd ? rows.map(r => r.rsi14) : [];
        const difs = hasInd ? rows.map(r => r.macd_dif) : [];
        const deas = hasInd ? rows.map(r => r.macd_dea) : [];
        const hists = hasInd ? rows.map(r => r.macd_hist) : [];

        // MA 计算
        const ma = (n) => {
          const out = [];
          for (let i = 0; i < closes.length; i++) {
            if (i < n - 1) { out.push(null); continue; }
            let s = 0;
            for (let j = i - n + 1; j <= i; j++) s += closes[j];
            out.push(+(s / n).toFixed(2));
          }
          return out;
        };

        // 成交量颜色跟蜡烛涨跌一致
        const volColors = rows.map(r => r.close >= r.open ? '#ef232a' : '#14b143');

        const upColor = '#ef232a';   // 涨红
        const downColor = '#14b143'; // 跌绿

        const series = [
          {
            name: 'K线', type: 'candlestick', data: ohlc, xAxisIndex: 0, yAxisIndex: 0,
            itemStyle: { color: upColor, color0: downColor, borderColor: upColor, borderColor0: downColor },
          },
          { name: 'MA5', type: 'line', data: ma(5), xAxisIndex: 0, yAxisIndex: 0, smooth: true, showSymbol: false, lineStyle: { width: 1, color: '#1677ff' } },
          { name: 'MA10', type: 'line', data: ma(10), xAxisIndex: 0, yAxisIndex: 0, smooth: true, showSymbol: false, lineStyle: { width: 1, color: '#faad14' } },
          { name: 'MA20', type: 'line', data: ma(20), xAxisIndex: 0, yAxisIndex: 0, smooth: true, showSymbol: false, lineStyle: { width: 1, color: '#722ed1' } },
          {
            name: '成交量', type: 'bar', data: volumes, xAxisIndex: 1, yAxisIndex: 1,
            itemStyle: { color: (p) => volColors[p.dataIndex] },
          },
        ];
        if (hasInd) {
          series.push(
            {
              name: 'MACD柱', type: 'bar', data: hists, xAxisIndex: 2, yAxisIndex: 2,
              itemStyle: { color: (p) => (p.data ?? 0) >= 0 ? upColor : downColor },
            },
            { name: 'DIF', type: 'line', data: difs, xAxisIndex: 2, yAxisIndex: 2, showSymbol: false, lineStyle: { width: 1, color: '#1677ff' } },
            { name: 'DEA', type: 'line', data: deas, xAxisIndex: 2, yAxisIndex: 2, showSymbol: false, lineStyle: { width: 1, color: '#faad14' } },
            {
              name: 'RSI', type: 'line', data: rsis, xAxisIndex: 3, yAxisIndex: 3, showSymbol: false,
              lineStyle: { width: 1.2, color: '#fa8c16' },
              markLine: {
                silent: true, symbol: 'none', lineStyle: { type: 'dashed', color: '#bfbfbf' },
                label: { show: false }, data: [{ yAxis: 70 }, { yAxis: 30 }],
              },
            },
          );
        }

        klineChart.setOption({
          animation: false,
          tooltip: {
            trigger: 'axis',
            axisPointer: { type: 'cross' },
            backgroundColor: 'rgba(255,255,255,0.96)',
            borderColor: '#e8e8e8',
            textStyle: { color: 'rgba(0,0,0,.85)', fontSize: 12 },
            formatter: (params) => {
              const k = params.find(p => p.seriesName === 'K线');
              if (!k) return '';
              const d = k.data;
              const find = (n) => params.find(p => p.seriesName === n)?.data;
              const indLine = hasInd
                ? `<br/>RSI ${find('RSI') ?? '—'}　DIF ${find('DIF') ?? '—'}　DEA ${find('DEA') ?? '—'}`
                : '';
              return `<b>${k.axisValue}</b><br/>
                开 <span style="color:${d[1] >= d[0] ? upColor : downColor}">${d[0]}</span>
                收 <span style="color:${d[1] >= d[0] ? upColor : downColor}">${d[1]}</span><br/>
                低 ${d[2]}　高 ${d[3]}<br/>
                成交量 ${find('成交量') ?? '—'}${indLine}`;
            },
          },
          axisPointer: { link: [{ xAxisIndex: 'all' }] },
          grid: [
            { left: 60, right: 20, top: 10, height: '42%' },
            { left: 60, right: 20, top: '50%', height: '11%' },
            { left: 60, right: 20, top: '64%', height: '13%' },
            { left: 60, right: 20, top: '80%', height: '13%' },
          ],
          xAxis: [
            { type: 'category', data: dates, gridIndex: 0, axisLabel: { show: false }, axisTick: { show: false }, axisLine: { lineStyle: { color: '#e0e0e0' } }, splitLine: { show: false } },
            { type: 'category', data: dates, gridIndex: 1, axisLabel: { show: false }, axisTick: { show: false }, axisLine: { lineStyle: { color: '#e0e0e0' } } },
            { type: 'category', data: dates, gridIndex: 2, axisLabel: { show: false }, axisTick: { show: false }, axisLine: { lineStyle: { color: '#e0e0e0' } } },
            { type: 'category', data: dates, gridIndex: 3, axisLine: { lineStyle: { color: '#e0e0e0' } }, axisLabel: { color: 'rgba(0,0,0,.45)', fontSize: 11 }, splitLine: { show: false } },
          ],
          yAxis: [
            { scale: true, gridIndex: 0, splitLine: { lineStyle: { color: '#f5f5f5' } }, axisLabel: { color: 'rgba(0,0,0,.45)', fontSize: 11 } },
            { scale: true, gridIndex: 1, splitNumber: 2, axisLabel: { color: 'rgba(0,0,0,.35)', fontSize: 10, formatter: (v) => v >= 1e8 ? (v/1e8).toFixed(1)+'亿' : v >= 1e4 ? (v/1e4).toFixed(0)+'万' : v }, splitLine: { show: false } },
            { scale: true, gridIndex: 2, splitNumber: 2, axisLabel: { color: 'rgba(0,0,0,.35)', fontSize: 10 }, splitLine: { show: false } },
            { min: 0, max: 100, gridIndex: 3, splitNumber: 2, axisLabel: { color: 'rgba(0,0,0,.35)', fontSize: 10 }, splitLine: { show: false } },
          ],
          dataZoom: [
            { type: 'inside', xAxisIndex: [0, 1, 2, 3], start: 40, end: 100 },
            { type: 'slider', xAxisIndex: [0, 1, 2, 3], bottom: 4, height: 16, borderColor: '#e0e0e0', fillerColor: 'rgba(22,119,255,.08)' },
          ],
          series,
        });

        const onResize = () => klineChart && klineChart.resize();
        window.addEventListener('resize', onResize);
        klineRef.value._onResize = onResize;
      }

      async function loadKline() {
        klineLoading.value = true;
        try {
          const d = await api.get(apiUrl(`stock/${props.params.market}/${props.params.code}/klines?days=${klineDays.value}&indicators=1`));
          klineRows.value = d.rows || [];
          klineFqLabel.value = d.fq_label || '';
          await nextTick();
          renderKline(klineRows.value);
        } catch (e) {
          console.error('K线加载失败:', e);
          klineRows.value = [];
          klineFqLabel.value = '';
        }
        klineLoading.value = false;
      }

      watch(klineDays, () => loadKline());

      onMounted(async () => {
        try {
          stock.value = await api.get(apiUrl(`stock/${props.params.market}/${props.params.code}`));
          latest.value = stock.value.latest || {};
        } catch (e) { console.error(e); }
        loadKline();
      });

      onBeforeUnmount(() => {
        if (klineChart) klineChart.dispose();
        if (klineRef.value?._onResize) window.removeEventListener('resize', klineRef.value._onResize);
      });

      return {
        stock, latest, histCols, fmt, fmtPct, dirTag, confTag,
        klineRef, klineDays, klineLoading, klineRows, klineFqLabel,
        go: (h) => window.location.hash = h,
      };
    },
  };

  // ---------- 回测 ----------
  const Backtest = {
    template: `
      <div>
        <h2 class="page-title">回测与准确率</h2>
        <p class="page-desc">对账口径：预测时点价格 vs 当前价格实际涨跌。看涨=实际上涨；看跌=实际下跌；震荡=|涨跌|&lt;阈值。</p>
        <a-spin :spinning="loading">
          <div class="stat-row">
            <div class="stat-item"><div class="label">已对账样本</div><div class="value">{{ s.total.n }}</div></div>
            <div class="stat-item"><div class="label">命中数</div><div class="value">{{ s.total.hit }}</div></div>
            <div class="stat-item"><div class="label">总命中率</div><div class="value">{{ s.total.rate != null ? s.total.rate + '%' : '—' }}</div></div>
            <div class="stat-item"><div class="label">平均实际涨跌</div>
              <div class="value" :class="(s.total.avg_pct||0) >= 0 ? 'pos' : 'neg'">{{ s.total.avg_pct != null ? fmtPct(s.total.avg_pct) : '—' }}</div>
            </div>
          </div>

          <a-card title="按方向统计" size="small">
            <a-table :dataSource="dirRows" :columns="statCols" rowKey="key" size="small" :pagination="false">
              <template #bodyCell="{ column, record }">
                <template v-if="column.key === 'rate'">{{ record.rate != null ? record.rate + '%' : '—' }}</template>
                <template v-else-if="column.key === 'pct'">
                  <span v-if="record.avg_pct != null" :style="{ color: record.avg_pct >= 0 ? '#cf1322' : '#389e0d' }">{{ fmtPct(record.avg_pct) }}</span>
                  <span v-else>—</span>
                </template>
              </template>
            </a-table>
          </a-card>

          <a-card title="按置信度统计" size="small" style="margin-top:12px">
            <a-table :dataSource="confRows" :columns="statCols" rowKey="key" size="small" :pagination="false">
              <template #bodyCell="{ column, record }">
                <template v-if="column.key === 'rate'">{{ record.rate != null ? record.rate + '%' : '—' }}</template>
                <template v-else-if="column.key === 'pct'">
                  <span v-if="record.avg_pct != null" :style="{ color: record.avg_pct >= 0 ? '#cf1322' : '#389e0d' }">{{ fmtPct(record.avg_pct) }}</span>
                  <span v-else>—</span>
                </template>
              </template>
            </a-table>
          </a-card>

          <a-card title="按市场统计" size="small" style="margin-top:12px">
            <a-table :dataSource="mktRows" :columns="statCols" rowKey="key" size="small" :pagination="false">
              <template #bodyCell="{ column, record }">
                <template v-if="column.key === 'rate'">{{ record.rate != null ? record.rate + '%' : '—' }}</template>
                <template v-else-if="column.key === 'pct'">
                  <span v-if="record.avg_pct != null" :style="{ color: record.avg_pct >= 0 ? '#cf1322' : '#389e0d' }">{{ fmtPct(record.avg_pct) }}</span>
                  <span v-else>—</span>
                </template>
              </template>
            </a-table>
          </a-card>
        </a-spin>

        <h2 class="page-title" style="margin-top:28px">策略绩效（量化回测）</h2>
        <p class="page-desc">口径：t 日信号 → t+1 开盘成交，佣金万三 / 卖出印花税万五；全池为等权组合，基准=同池等权买入持有。历史绩效不代表未来表现。</p>
        <a-alert v-if="btMsg.text" :type="btMsg.type" :message="btMsg.text" show-icon closable style="margin-bottom:12px" @close="btMsg.text=''" />

        <a-card size="small">
          <template #title>
            <span style="font-size:15px;font-weight:600">全池预测跟随</span>
            <span style="margin-left:12px;font-size:12px;color:rgba(0,0,0,.45);font-weight:400">等权组合 vs 买入持有</span>
          </template>
          <template #extra>
            <a-input v-model:value="poolSince" placeholder="起始日 如 2023-01-01" size="small" style="width:150px" />
            <a-input-number v-model:value="poolStop" :min="0" :max="50" size="small" style="width:82px;margin-left:8px" placeholder="止损%" />
            <a-button type="primary" size="small" :loading="poolLoading" style="margin-left:8px" @click="runPool">生成全池回测</a-button>
          </template>
          <div v-if="pool">
            <div class="stat-row">
              <div class="stat-item"><div class="label">标的 / 预测</div><div class="value">{{ pool.meta.n_stocks }} / {{ pool.meta.n_preds }}</div></div>
              <div class="stat-item"><div class="label">组合累计</div>
                <div class="value" :class="pool.portfolio.stats.total_return_pct >= 0 ? 'pos' : 'neg'">{{ fmtPct(pool.portfolio.stats.total_return_pct) }}</div></div>
              <div class="stat-item"><div class="label">买入持有基准</div>
                <div class="value" :class="pool.portfolio.stats.buy_hold_pct >= 0 ? 'pos' : 'neg'">{{ fmtPct(pool.portfolio.stats.buy_hold_pct) }}</div></div>
              <div class="stat-item"><div class="label">超额</div>
                <div class="value" :class="pool.portfolio.stats.excess_pct >= 0 ? 'pos' : 'neg'">{{ fmtPct(pool.portfolio.stats.excess_pct) }}</div></div>
              <div class="stat-item" v-if="pool.weighted"><div class="label">置信度加权</div>
                <div class="value" :class="pool.weighted.stats.total_return_pct >= 0 ? 'pos' : 'neg'">{{ fmtPct(pool.weighted.stats.total_return_pct) }}</div></div>
              <div class="stat-item"><div class="label">最大回撤</div><div class="value neg">{{ pool.portfolio.stats.max_drawdown_pct }}%</div></div>
              <div class="stat-item"><div class="label">夏普</div><div class="value">{{ pool.portfolio.stats.sharpe != null ? pool.portfolio.stats.sharpe : '—' }}</div></div>
            </div>
            <div ref="poolChartRef" style="width:100%;height:280px"></div>

            <a-card title="分方向前瞻收益（预测生效 → 次日/5日实际）" size="small" style="margin-top:8px">
              <a-table :dataSource="dirFwdRows" :columns="dirFwdCols" rowKey="key" size="small" :pagination="false">
                <template #bodyCell="{ column, record }">
                  <template v-if="column.key === 'n1'">
                    <span v-if="record.next1_avg_pct != null" :style="{ color: record.next1_avg_pct >= 0 ? '#cf1322' : '#389e0d' }">{{ fmtPct(record.next1_avg_pct) }}</span>
                    <span v-else>—</span>
                  </template>
                  <template v-else-if="column.key === 'nw'">{{ record.next1_win_pct != null ? record.next1_win_pct + '%' : '—' }}</template>
                  <template v-else-if="column.key === 'n5'">
                    <span v-if="record.next5_avg_pct != null" :style="{ color: record.next5_avg_pct >= 0 ? '#cf1322' : '#389e0d' }">{{ fmtPct(record.next5_avg_pct) }}</span>
                    <span v-else>—</span>
                  </template>
                </template>
              </a-table>
            </a-card>

            <a-card title="分标的（按超额降序）" size="small" style="margin-top:8px">
              <a-table :dataSource="poolRows" :columns="poolCols" rowKey="rowKey" size="small"
                       :pagination="{ pageSize: 10 }" :scroll="{ x: 760 }">
                <template #bodyCell="{ column, record }">
                  <template v-if="column.key === 'pr'">
                    <span :style="{ color: record.pred_return_pct >= 0 ? '#cf1322' : '#389e0d' }">{{ fmtPct(record.pred_return_pct) }}</span>
                  </template>
                  <template v-else-if="column.key === 'bh'">
                    <span :style="{ color: record.buy_hold_pct >= 0 ? '#cf1322' : '#389e0d' }">{{ fmtPct(record.buy_hold_pct) }}</span>
                  </template>
                  <template v-else-if="column.key === 'ex'">
                    <span :style="{ color: record.excess_pct >= 0 ? '#cf1322' : '#389e0d' }">{{ fmtPct(record.excess_pct) }}</span>
                  </template>
                  <template v-else-if="column.key === 'wr'">{{ record.win_rate != null ? record.win_rate + '%' : '—' }}</template>
                </template>
              </a-table>
            </a-card>
          </div>
          <a-empty v-else-if="!poolLoading" description="点击「生成全池回测」（需 predictions 与 klines 数据积累）" />
        </a-card>

        <a-card title="单标的策略回测" size="small" style="margin-top:12px">
          <a-form layout="inline" style="flex-wrap:wrap;gap:8px 0">
            <a-form-item label="标的"><a-input v-model:value="sf.code" placeholder="600519.SH" style="width:130px" /></a-form-item>
            <a-form-item label="策略">
              <a-select v-model:value="sf.strategy" style="width:160px">
                <a-select-option value="ma">双均线</a-select-option>
                <a-select-option value="rsi">RSI 均值回归</a-select-option>
                <a-select-option value="pred">三层预测跟随</a-select-option>
              </a-select>
            </a-form-item>
            <a-form-item v-if="sf.strategy==='ma'" label="快/慢线">
              <a-input-number v-model:value="sf.fast" :min="2" :max="250" style="width:72px" />
              <span style="margin:0 4px">/</span>
              <a-input-number v-model:value="sf.slow" :min="3" :max="250" style="width:72px" />
            </a-form-item>
            <a-form-item v-if="sf.strategy==='rsi'" label="周期/低/高">
              <a-input-number v-model:value="sf.rsiPeriod" :min="2" :max="100" style="width:66px" />
              <a-input-number v-model:value="sf.rsiLow" :min="1" :max="49" style="width:66px" />
              <a-input-number v-model:value="sf.rsiHigh" :min="51" :max="99" style="width:66px" />
            </a-form-item>
            <a-form-item label="止损%"><a-input-number v-model:value="sf.stopLoss" :min="0" :max="50" style="width:72px" /></a-form-item>
            <a-form-item label="起始日"><a-input v-model:value="sf.since" placeholder="可空" style="width:110px" /></a-form-item>
            <a-form-item><a-button type="primary" :loading="singleLoading" @click="runSingle">运行回测</a-button></a-form-item>
          </a-form>
          <div v-if="single" style="margin-top:12px">
            <div class="stat-row">
              <div class="stat-item"><div class="label">策略</div><div class="value" style="font-size:14px">{{ single.label }}</div></div>
              <div class="stat-item"><div class="label">累计收益</div>
                <div class="value" :class="single.stats.total_return_pct >= 0 ? 'pos' : 'neg'">{{ fmtPct(single.stats.total_return_pct) }}</div></div>
              <div class="stat-item"><div class="label">买入持有</div>
                <div class="value" :class="single.stats.buy_hold_pct >= 0 ? 'pos' : 'neg'">{{ fmtPct(single.stats.buy_hold_pct) }}</div></div>
              <div class="stat-item"><div class="label">超额</div>
                <div class="value" :class="single.stats.excess_pct >= 0 ? 'pos' : 'neg'">{{ fmtPct(single.stats.excess_pct) }}</div></div>
              <div class="stat-item"><div class="label">最大回撤</div><div class="value neg">{{ single.stats.max_drawdown_pct }}%</div></div>
              <div class="stat-item"><div class="label">夏普</div><div class="value">{{ single.stats.sharpe != null ? single.stats.sharpe : '—' }}</div></div>
              <div class="stat-item"><div class="label">交易 / 胜率</div>
                <div class="value">{{ single.stats.n_trades }} / {{ single.stats.win_rate_pct != null ? single.stats.win_rate_pct + '%' : '—' }}</div></div>
            </div>
            <div ref="singleChartRef" style="width:100%;height:240px"></div>
            <a-table :dataSource="single.trades" :columns="tradeCols" rowKey="entry_date" size="small"
                     :pagination="{ pageSize: 10 }" style="margin-top:8px">
              <template #bodyCell="{ column, record }">
                <template v-if="column.key === 'ep'">{{ fmt(record.entry_price) }}</template>
                <template v-else-if="column.key === 'xp'">{{ record.exit_price != null ? fmt(record.exit_price) : '—' }}</template>
                <template v-else-if="column.key === 'xd'">{{ record.exit_date || '（持仓中）' }}</template>
                <template v-else-if="column.key === 'rt'">
                  <span :style="{ color: record.ret_pct >= 0 ? '#cf1322' : '#389e0d' }">{{ fmtPct(record.ret_pct) }}</span>
                </template>
                <template v-else-if="column.key === 'rs'">{{ ({ stop: '止损', signal: '信号', open: '持仓' })[record.reason] || '—' }}</template>
              </template>
            </a-table>
          </div>
          <a-empty v-else-if="!singleLoading" description="输入标的代码并运行（如 600519.SH）" />
        </a-card>
      </div>`,
    setup() {
      const s = ref({ total: {}, by_direction: {}, by_confidence: {}, by_market: {} });
      const loading = ref(true);
      const statCols = [
        { title: '分类', dataIndex: 'key', key: 'key' },
        { title: '样本', dataIndex: 'n', key: 'n' },
        { title: '命中', dataIndex: 'hit', key: 'hit' },
        { title: '命中率', dataIndex: 'rate', key: 'rate' },
        { title: '平均实际涨跌', dataIndex: 'avg_pct', key: 'pct' },
      ];
      const toRows = (obj) => Object.entries(obj || {}).map(([k, v]) => ({ key: k, ...v }));
      const dirRows = computed(() => toRows(s.value.by_direction));
      const confRows = computed(() => toRows(s.value.by_confidence));
      const mktRows = computed(() => toRows(s.value.by_market));

      // ---------- 策略绩效：全池 ----------
      const btMsg = reactive({ text: '', type: 'info' });
      const pool = ref(null);
      const poolLoading = ref(false);
      const poolSince = ref('');
      const poolStop = ref(0);
      const poolChartRef = ref(null);
      let poolChart = null;

      const renderPoolChart = () => {
        if (!poolChartRef.value || !pool.value?.portfolio) return;
        if (poolChart) poolChart.dispose();
        poolChart = echarts.init(poolChartRef.value);
        const pc = pool.value.portfolio;
        const init0 = pool.value.meta.init_cash;
        const dates = pc.equity_curve.map(x => x[0]);
        const strat = pc.equity_curve.map(x => +((x[1] / init0 - 1) * 100).toFixed(2));
        const bench = pc.bench_curve.map(x => +((x[1] / init0 - 1) * 100).toFixed(2));
        const legend = ['预测跟随(等权)', '等权买入持有'];
        const series = [
          { name: '预测跟随(等权)', type: 'line', data: strat, showSymbol: false, lineStyle: { width: 2, color: '#cf1322' } },
          { name: '等权买入持有', type: 'line', data: bench, showSymbol: false, lineStyle: { width: 1.5, color: '#8c8c8c', type: 'dashed' } },
        ];
        const w = pool.value.weighted;
        if (w?.equity_curve?.length) {
          legend.push('置信度加权');
          series.push({
            name: '置信度加权', type: 'line', showSymbol: false,
            data: w.equity_curve.map(x => +((x[1] / init0 - 1) * 100).toFixed(2)),
            lineStyle: { width: 1.5, color: '#fa8c16' },
          });
        }
        poolChart.setOption({
          animation: false,
          tooltip: {
            trigger: 'axis', backgroundColor: 'rgba(255,255,255,0.96)', borderColor: '#e8e8e8',
            textStyle: { color: 'rgba(0,0,0,.85)', fontSize: 12 },
            valueFormatter: (v) => (v >= 0 ? '+' : '') + v + '%',
          },
          legend: { data: legend, top: 0 },
          grid: { left: 60, right: 20, top: 32, bottom: 44 },
          xAxis: {
            type: 'category', data: dates,
            axisLabel: { color: 'rgba(0,0,0,.45)', fontSize: 11 },
            axisLine: { lineStyle: { color: '#e0e0e0' } }, splitLine: { show: false },
          },
          yAxis: {
            type: 'value',
            axisLabel: { color: 'rgba(0,0,0,.45)', fontSize: 11, formatter: '{value}%' },
            splitLine: { lineStyle: { color: '#f5f5f5' } },
          },
          dataZoom: [
            { type: 'inside' },
            { type: 'slider', bottom: 4, height: 16, borderColor: '#e0e0e0', fillerColor: 'rgba(22,119,255,.08)' },
          ],
          series,
        });
        const onResize = () => poolChart && poolChart.resize();
        window.addEventListener('resize', onResize);
        poolChartRef.value._onResize = onResize;
      };

      async function runPool() {
        poolLoading.value = true;
        btMsg.text = '';
        try {
          const qs = new URLSearchParams({ weighted: '1', stop_loss: poolStop.value || 0 });
          // 默认起始日 2023-01-01，防止全量回测 OOM（2G 机器扛不住 2020 至今全部数据）
          qs.set('since', poolSince.value.trim() || '2023-01-01');
          pool.value = await api.get(apiUrl('backtest/pool?' + qs));
          await nextTick();
          renderPoolChart();
        } catch (e) {
          pool.value = null;
          btMsg.text = e.message || '全池回测失败';
          btMsg.type = 'error';
        }
        poolLoading.value = false;
      }

      const dirFwdCols = [
        { title: '方向', dataIndex: 'key', key: 'key' },
        { title: '样本', dataIndex: 'n', key: 'n' },
        { title: '次日均', dataIndex: 'next1_avg_pct', key: 'n1' },
        { title: '次日胜率', dataIndex: 'next1_win_pct', key: 'nw' },
        { title: '5日均', dataIndex: 'next5_avg_pct', key: 'n5' },
      ];
      const dirFwdRows = computed(() => Object.entries(pool.value?.direction_stats || {}).map(([k, v]) => ({ key: k, ...v })));

      const poolCols = [
        { title: '代码', dataIndex: 'code', key: 'code', fixed: 'left', width: 90 },
        { title: '市场', dataIndex: 'market', key: 'market', width: 70 },
        { title: '预测', dataIndex: 'n_preds', key: 'np', width: 70 },
        { title: '看涨', dataIndex: 'n_bull', key: 'nb', width: 70 },
        { title: '策略', dataIndex: 'pred_return_pct', key: 'pr', width: 92 },
        { title: '买入持有', dataIndex: 'buy_hold_pct', key: 'bh', width: 92 },
        { title: '超额', dataIndex: 'excess_pct', key: 'ex', width: 92 },
        { title: '交易', dataIndex: 'n_trades', key: 'nt', width: 70 },
        { title: '胜率', dataIndex: 'win_rate', key: 'wr', width: 80 },
      ];
      const poolRows = computed(() => (pool.value?.per_stock || [])
        .map(r => ({ ...r, rowKey: r.code + '.' + r.market })));

      // ---------- 策略绩效：单标的 ----------
      const sf = reactive({ code: '', strategy: 'ma', fast: 5, slow: 20, rsiPeriod: 14, rsiLow: 30, rsiHigh: 70, since: '', stopLoss: 0 });
      const single = ref(null);
      const singleLoading = ref(false);
      const singleChartRef = ref(null);
      let singleChart = null;

      const renderSingleChart = () => {
        if (!singleChartRef.value || !single.value?.equity_curve?.length) return;
        if (singleChart) singleChart.dispose();
        singleChart = echarts.init(singleChartRef.value);
        const eq = single.value.equity_curve;
        singleChart.setOption({
          animation: false,
          tooltip: {
            trigger: 'axis', backgroundColor: 'rgba(255,255,255,0.96)', borderColor: '#e8e8e8',
            textStyle: { color: 'rgba(0,0,0,.85)', fontSize: 12 },
            valueFormatter: (v) => Number(v).toLocaleString(),
          },
          grid: { left: 84, right: 20, top: 20, bottom: 42 },
          xAxis: {
            type: 'category', data: eq.map(x => x[0]),
            axisLabel: { color: 'rgba(0,0,0,.45)', fontSize: 11 }, splitLine: { show: false },
          },
          yAxis: {
            type: 'value', scale: true,
            axisLabel: { color: 'rgba(0,0,0,.45)', fontSize: 11 },
            splitLine: { lineStyle: { color: '#f5f5f5' } },
          },
          dataZoom: [
            { type: 'inside' },
            { type: 'slider', bottom: 4, height: 16, borderColor: '#e0e0e0' },
          ],
          series: [
            { name: '资金曲线', type: 'line', data: eq.map(x => +x[1].toFixed(2)), showSymbol: false, lineStyle: { width: 2, color: '#cf1322' } },
          ],
        });
        const onResize = () => singleChart && singleChart.resize();
        window.addEventListener('resize', onResize);
        singleChartRef.value._onResize = onResize;
      };

      async function runSingle() {
        const raw = (sf.code || '').trim().toUpperCase();
        const dot = raw.indexOf('.');
        if (dot < 1) { btMsg.text = '标的格式：600519.SH / 00700.HK'; btMsg.type = 'error'; return; }
        const code = raw.slice(0, dot), market = raw.slice(dot + 1);
        if (!['SH', 'SZ', 'HK'].includes(market)) { btMsg.text = '市场需为 SH/SZ/HK'; btMsg.type = 'error'; return; }
        singleLoading.value = true;
        btMsg.text = '';
        try {
          const qs = new URLSearchParams({
            strategy: sf.strategy, fast: sf.fast, slow: sf.slow,
            rsi_period: sf.rsiPeriod, rsi_low: sf.rsiLow, rsi_high: sf.rsiHigh,
            since: sf.since.trim(), stop_loss: sf.stopLoss || 0,
          });
          single.value = await api.get(apiUrl('backtest/stock/' + market + '/' + code + '?' + qs));
          await nextTick();
          renderSingleChart();
        } catch (e) {
          single.value = null;
          btMsg.text = e.message || '回测失败';
          btMsg.type = 'error';
        }
        singleLoading.value = false;
      }

      const tradeCols = [
        { title: '开仓日', dataIndex: 'entry_date', key: 'ed' },
        { title: '平仓日', dataIndex: 'exit_date', key: 'xd' },
        { title: '开仓价', dataIndex: 'entry_price', key: 'ep' },
        { title: '平仓价', dataIndex: 'exit_price', key: 'xp' },
        { title: '收益', dataIndex: 'ret_pct', key: 'rt' },
        { title: '原因', dataIndex: 'reason', key: 'rs' },
      ];

      onMounted(async () => {
        try { s.value = await api.get(apiUrl('backtest')); } catch (e) { console.error(e); }
        loading.value = false;
      });

      onBeforeUnmount(() => {
        if (poolChart) poolChart.dispose();
        if (singleChart) singleChart.dispose();
        if (poolChartRef.value?._onResize) window.removeEventListener('resize', poolChartRef.value._onResize);
        if (singleChartRef.value?._onResize) window.removeEventListener('resize', singleChartRef.value._onResize);
      });

      return {
        s, loading, statCols, dirRows, confRows, mktRows, fmtPct, fmt,
        btMsg, pool, poolLoading, poolSince, poolStop, poolChartRef, runPool,
        dirFwdCols, dirFwdRows, poolCols, poolRows,
        sf, single, singleLoading, singleChartRef, runSingle, tradeCols,
      };
    },
  };

  // ---------- 设置 ----------
  const Settings = {
    template: `
      <div>
        <h2 class="page-title">规则与研判</h2>
        <p class="page-desc">参数修改后下次运行生效，历史报告不变。</p>
        <a-spin :spinning="loading">
          <a-alert v-if="msg.text" :type="msg.type" :message="msg.text" show-icon closable style="margin-bottom:16px" @close="msg.text=''" />

          <a-card title="三层权重与方向阈值" size="small">
            <a-form layout="inline" style="flex-wrap:wrap;gap:8px 0">
              <a-form-item label="基本面权重 W1"><a-input-number v-model:value="rules.w_fund" :step="0.05" style="width:110px" /></a-form-item>
              <a-form-item label="估值权重 W2"><a-input-number v-model:value="rules.w_val" :step="0.05" style="width:110px" /></a-form-item>
              <a-form-item label="技术面权重 W3"><a-input-number v-model:value="rules.w_tech" :step="0.05" style="width:110px" /></a-form-item>
              <a-form-item label="看涨阈值"><a-input-number v-model:value="rules.dir_bull" :step="1" style="width:110px" /></a-form-item>
              <a-form-item label="看跌阈值"><a-input-number v-model:value="rules.dir_bear" :step="1" style="width:110px" /></a-form-item>
            </a-form>
          </a-card>

          <a-card title="基本面规则" size="small" style="margin-top:12px">
            <a-form layout="inline" style="flex-wrap:wrap;gap:8px 0">
              <a-form-item label="负债率低杠杆线 %"><a-input-number v-model:value="rules.fund_debt_ok" style="width:100px" /></a-form-item>
              <a-form-item label="负债率中等线 %"><a-input-number v-model:value="rules.fund_debt_mid" style="width:100px" /></a-form-item>
              <a-form-item label="现金流健康线"><a-input-number v-model:value="rules.fund_cf_pos" :step="0.01" style="width:100px" /></a-form-item>
              <a-form-item label="好公司阈值"><a-input-number v-model:value="rules.fund_verdict_good" style="width:100px" /></a-form-item>
              <a-form-item label="一般分界"><a-input-number v-model:value="rules.fund_verdict_mid" style="width:100px" /></a-form-item>
            </a-form>
          </a-card>

          <a-card title="估值规则" size="small" style="margin-top:12px">
            <a-form layout="inline" style="flex-wrap:wrap;gap:8px 0">
              <a-form-item label="PE 低估线"><a-input-number v-model:value="rules.val_pe_cheap" style="width:100px" /></a-form-item>
              <a-form-item label="PE 合理上限"><a-input-number v-model:value="rules.val_pe_fair" style="width:100px" /></a-form-item>
              <a-form-item label="PE 偏贵上限"><a-input-number v-model:value="rules.val_pe_expensive" style="width:100px" /></a-form-item>
              <a-form-item label="PB 破净线"><a-input-number v-model:value="rules.val_pb_cheap" :step="0.1" style="width:100px" /></a-form-item>
              <a-form-item label="PB 合理上限"><a-input-number v-model:value="rules.val_pb_fair" :step="0.5" style="width:100px" /></a-form-item>
              <a-form-item label="52周低位 %"><a-input-number v-model:value="rules.val_pos_low" style="width:100px" /></a-form-item>
              <a-form-item label="52周高位 %"><a-input-number v-model:value="rules.val_pos_high" style="width:100px" /></a-form-item>
              <a-form-item label="PEG 合理"><a-input-number v-model:value="rules.val_peg_good" :step="0.1" style="width:100px" /></a-form-item>
              <a-form-item label="PEG 偏贵"><a-input-number v-model:value="rules.val_peg_fair" :step="0.1" style="width:100px" /></a-form-item>
            </a-form>
          </a-card>

          <a-card title="技术面规则" size="small" style="margin-top:12px">
            <a-form layout="inline" style="flex-wrap:wrap;gap:8px 0">
              <a-form-item label="MA20 权重"><a-input-number v-model:value="rules.tech_ma20_w" style="width:90px" /></a-form-item>
              <a-form-item label="MA60 权重"><a-input-number v-model:value="rules.tech_ma60_w" style="width:90px" /></a-form-item>
              <a-form-item label="MA120 权重"><a-input-number v-model:value="rules.tech_ma120_w" style="width:90px" /></a-form-item>
              <a-form-item label="MACD 权重"><a-input-number v-model:value="rules.tech_macd_w" style="width:90px" /></a-form-item>
              <a-form-item label="RSI 超买"><a-input-number v-model:value="rules.tech_rsi_overbought" style="width:90px" /></a-form-item>
              <a-form-item label="RSI 超卖"><a-input-number v-model:value="rules.tech_rsi_oversold" style="width:90px" /></a-form-item>
              <a-form-item label="放量比"><a-input-number v-model:value="rules.tech_vol_confirm" :step="0.1" style="width:90px" /></a-form-item>
              <a-form-item label="偏多阈值"><a-input-number v-model:value="rules.tech_verdict_bull" style="width:90px" /></a-form-item>
            </a-form>
          </a-card>

          <a-card title="大盘与回测" size="small" style="margin-top:12px">
            <a-form layout="inline" style="flex-wrap:wrap;gap:8px 0">
              <a-form-item label="广度健康 %"><a-input-number v-model:value="rules.breadth_healthy" style="width:100px" /></a-form-item>
              <a-form-item label="广度弱势 %"><a-input-number v-model:value="rules.breadth_weak" style="width:100px" /></a-form-item>
              <a-form-item label="广度偏软 %"><a-input-number v-model:value="rules.breadth_soft" style="width:100px" /></a-form-item>
              <a-form-item label="回测震荡阈值 %"><a-input-number v-model:value="rules.backtest_flat_pct" :step="0.1" style="width:100px" /></a-form-item>
            </a-form>
          </a-card>

          <a-card title="LLM 研判配置" size="small" style="margin-top:12px">
            <a-form layout="vertical">
              <a-form-item label="启用 LLM 研判">
                <a-switch v-model:checked="llm.enabled" />
                <span style="margin-left:12px;color:rgba(0,0,0,.45);font-size:12px">关闭时全部走确定性规则</span>
              </a-form-item>
              <a-form-item label="API Base">
                <a-input v-model:value="llm.api_base" placeholder="https://api.deepseek.com/v1" />
              </a-form-item>
              <a-form-item label="API Key">
                <a-input-password v-model:value="llm.api_key" :placeholder="llm.api_key_set ? '已配置（留空保持不变）' : 'sk-...'" />
              </a-form-item>
              <a-form-item label="模型">
                <a-input v-model:value="llm.model" placeholder="deepseek-chat" style="width:240px" />
              </a-form-item>
            </a-form>
            <a-space>
              <a-button type="primary" :loading="saving" @click="save">保存配置</a-button>
              <a-button :loading="testing" @click="testLlm">测试 LLM 连接</a-button>
              <a-popconfirm title="确认恢复默认规则？LLM 配置不受影响。" @confirm="reset">
                <a-button danger>恢复默认规则</a-button>
              </a-popconfirm>
            </a-space>
          </a-card>

          <a-card title="说明" size="small" style="margin-top:12px">
            <p style="margin:0;color:rgba(0,0,0,.65);font-size:13px;line-height:1.8">
              修改只影响之后的运行，已生成的历史报告与回测记录不变。规则调整后建议观察 3-5 期命中率变化再决定是否回调。
              分档类参数（营收/净利/ROE）为 JSON 数组格式 <code class="mono">[[阈值,加分],...]</code>，如需调整请用 API 或直接编辑服务器
              <code class="mono">data/rules_config.json</code>。
            </p>
          </a-card>
        </a-spin>
      </div>`,
    setup() {
      const rules = ref({}); const llm = ref({}); const loading = ref(true);
      const saving = ref(false); const testing = ref(false);
      const msg = ref({ text: '', type: 'success' });
      onMounted(async () => {
        try {
          const r = await api.get(apiUrl('settings'));
          rules.value = r.rules; llm.value = r.llm;
        } catch (e) { console.error(e); }
        loading.value = false;
      });
      const save = async () => {
        saving.value = true;
        try {
          await api.post(apiUrl('settings'), { rules: rules.value, llm: llm.value });
          msg.value = { text: '配置已保存，下次运行生效', type: 'success' };
        } catch (e) { msg.value = { text: e.message, type: 'error' }; }
        saving.value = false;
      };
      const reset = async () => {
        try {
          const r = await api.post(apiUrl('settings'), { action: 'reset_rules' });
          rules.value = r.rules;
          msg.value = { text: '已恢复默认规则', type: 'info' };
        } catch (e) { msg.value = { text: e.message, type: 'error' }; }
      };
      const testLlm = async () => {
        testing.value = true;
        try {
          const r = await api.post(apiUrl('settings'), {
            action: 'test_llm', llm_api_base: llm.value.api_base,
            llm_api_key: llm.value.api_key, llm_model: llm.value.model,
          });
          msg.value = { text: r.message, type: r.ok ? 'success' : 'error' };
        } catch (e) { msg.value = { text: e.message, type: 'error' }; }
        testing.value = false;
      };
      return { rules, llm, loading, saving, testing, msg, save, reset, testLlm };
    },
  };

  // ---------- 根应用 + hash 路由 ----------
  const App = {
    components: { LoginPage, AppLayout, Dashboard, RunsList, ReportDetail, StockDetail, Backtest, Settings },
    template: `
      <component v-if="isLogin" :is="'LoginPage'"></component>
      <AppLayout v-else :page="currentPage" :pageParams="pageParams" :routeName="routeName" />
    `,
    setup() {
      const parseRoute = () => {
        const h = (window.location.hash || '#/dashboard').slice(1);
        const seg = h.split('/').filter(Boolean);
        return { name: seg[0] || 'dashboard', params: { id: seg[1], market: seg[1], code: seg[2] } };
      };
      const r = ref(parseRoute());
      window.addEventListener('hashchange', () => {
        r.value = parseRoute();
        window.scrollTo(0, 0);
      });
      const isLogin = computed(() => r.value.name === 'login');
      // 传组件对象（而非字符串），AppLayout 内 <component :is> 才能解析
      const pageMap = {
        dashboard: Dashboard, runs: RunsList, report: ReportDetail,
        stock: StockDetail, backtest: Backtest, settings: Settings,
      };
      const currentPage = computed(() => pageMap[r.value.name] || Dashboard);
      const pageParams = computed(() => r.value.params);
      const routeName = computed(() => r.value.name);
      onMounted(async () => {
        if (r.value.name !== 'login') {
          try {
            const m = await api.get(apiUrl('me'));
            sessionStorage.setItem('user', m.username);
            sessionStorage.setItem('csrf', m.csrf_token);
          } catch (e) { /* 已跳转登录 */ }
        }
      });
      return { isLogin, currentPage, pageParams, routeName };
    },
  };

const app = createApp(App);
app.use(Antd);
// 全局注册页面组件，确保 <component :is="字符串"> 在任意层级可解析
app.component('LoginPage', LoginPage);
app.component('AppLayout', AppLayout);
app.component('Dashboard', Dashboard);
app.component('RunsList', RunsList);
app.component('ReportDetail', ReportDetail);
app.component('StockDetail', StockDetail);
app.component('Backtest', Backtest);
app.component('Settings', Settings);
app.mount('#app');
