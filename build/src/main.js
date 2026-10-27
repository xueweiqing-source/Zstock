/* Zstock 前端入口（esbuild 打包：vue + ant-design-vue + 页面逻辑） */
import { createApp, ref, reactive, computed, onMounted, watch, h } from 'vue';
import * as Vue from 'vue';
import Antd from 'ant-design-vue';
import 'ant-design-vue/dist/reset.css';

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
      if (res.status === 401) { window.location.hash = '#/login'; throw new Error('未登录'); }
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
    props: ['page', 'pageParams'],
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
    setup(props) {
      const collapsed = ref(false);
      const user = ref(sessionStorage.getItem('user') || 'admin');
      const menu = menuItems;
      const selectedKeys = computed(() => {
        const hash = window.location.hash || '#/dashboard';
        return [menuItems.find(m => hash.startsWith(m.key))?.key || '#/dashboard'];
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
      const bt = computed(() => data.value.backtest?.total || {});
      const trendClass = computed(() => {
        const t = data.value.latest?.market_trend;
        return t === '偏多' ? 'pos' : t === '偏空' ? 'neg' : '';
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
          data.value = await api.get(apiUrl('dashboard'));
          factors.value = (data.value.latest?.market_factors && typeof data.value.latest.market_factors === 'string')
            ? JSON.parse(data.value.latest.market_factors || '[]') : (data.value.latest?.market_factors || []);
        } catch (e) { console.error(e); }
        loading.value = false;
      });
      return { data, loading, factors, bt, trendClass, runCols, fmt, dirTag, confTag, go: (h) => window.location.hash = h };
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
      onMounted(async () => {
        try {
          stock.value = await api.get(apiUrl(`stock/${props.params.market}/${props.params.code}`));
          latest.value = stock.value.latest || {};
        } catch (e) { console.error(e); }
      });
      return { stock, latest, histCols, fmt, fmtPct, dirTag, confTag, go: (h) => window.location.hash = h };
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
            <a-table :dataSource="dirRows" :columns="statCols" rowKey="key" size="small" :pagination="false" />
          </a-card>

          <a-card title="按置信度统计" size="small" style="margin-top:12px">
            <a-table :dataSource="confRows" :columns="statCols" rowKey="key" size="small" :pagination="false" />
          </a-card>

          <a-card title="按市场统计" size="small" style="margin-top:12px">
            <a-table :dataSource="mktRows" :columns="statCols" rowKey="key" size="small" :pagination="false" />
          </a-card>
        </a-spin>
      </div>`,
    setup() {
      const s = ref({ total: {}, by_direction: {}, by_confidence: {}, by_market: {} });
      const loading = ref(true);
      const statCols = [
        { title: '分类', dataIndex: 'key', key: 'key' },
        { title: '样本', dataIndex: 'n', key: 'n' },
        { title: '命中', dataIndex: 'hit', key: 'hit' },
        { title: '命中率', dataIndex: 'rate', key: 'rate', render: (v) => v != null ? v + '%' : '—' },
        { title: '平均实际涨跌', dataIndex: 'avg_pct', key: 'pct',
          render: (v) => v != null ? `<span style="color:${v >= 0 ? '#cf1322' : '#389e0d'}">${fmtPct(v)}</span>` : '—' },
      ];
      const toRows = (obj) => Object.entries(obj || {}).map(([k, v]) => ({ key: k, ...v }));
      const dirRows = computed(() => toRows(s.value.by_direction));
      const confRows = computed(() => toRows(s.value.by_confidence));
      const mktRows = computed(() => toRows(s.value.by_market));
      onMounted(async () => {
        try { s.value = await api.get(apiUrl('backtest')); } catch (e) { console.error(e); }
        loading.value = false;
      });
      return { s, loading, statCols, dirRows, confRows, mktRows, fmtPct };
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
      <AppLayout v-else :page="currentPage" :pageParams="pageParams" />
    `,
    setup() {
      const route = ref(window.location.hash || '#/dashboard');
      const me = ref(null);
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
      const pageMap = {
        dashboard: 'Dashboard', runs: 'RunsList', report: 'ReportDetail',
        stock: 'StockDetail', backtest: 'Backtest', settings: 'Settings',
      };
      const currentPage = computed(() => pageMap[r.value.name] || 'Dashboard');
      const pageParams = computed(() => r.value.params);
      onMounted(async () => {
        // 未登录直接跳登录页
        if (r.value.name !== 'login') {
          try {
            const m = await api.get(apiUrl('me'));
            me.value = m; sessionStorage.setItem('user', m.username);
            sessionStorage.setItem('csrf', m.csrf_token);
          } catch (e) { /* api 已跳转 */ }
        }
      });
      return { isLogin, currentPage, pageParams };
    },
  };

const app = createApp(App);
app.use(Antd);
app.mount('#app');
