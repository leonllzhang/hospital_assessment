<template>
  <div class="dean-dashboard-container">
    
    <!-- 优化点 1：增加顶部工具栏，让标题和生成按钮左右对齐 -->
    <div class="dashboard-top-bar">
      <h3 class="dashboard-title">全院指标监控看板</h3>
      <!-- 优化点 2：增加防抖状态和动态文案 -->
      <button class="ai-report-btn" @click="fetchAiReport" :disabled="isGenerating">
        {{ isGenerating ? '⏳ 正在深度生成...' : '✨ AI 智能月报生成' }}
      </button>
    </div>

    <div class="summary-grid">
      <div 
        v-for="(list, dimName) in data" 
        :key="dimName"
        :class="['dim-card', { active: activeTab === dimName }]"
        @click="activeTab = dimName"
      >
        <div class="chart-box">
          <svg viewBox="0 0 100 100" class="ring-svg">
            <circle class="rail" cx="50" cy="50" r="40" />
            <circle 
              class="progress" 
              cx="50" 
              cy="50" 
              r="40" 
              :style="{ strokeDashoffset: calculateOffset(getDimStats(list).percent) }"
            />
          </svg>
          <div class="percent-text">{{ getDimStats(list).percent }}%</div>
        </div>
        
        <div class="dim-info">
          <div class="dim-name">{{ dimName }}</div>
          <div class="dim-sub">{{ getDimStats(list).ok }}/{{ list.length }} 项达标</div>
        </div>
        <!-- 预警角标 -->
        <div v-if="alertsByDim[dimName]?.red" class="alert-badge alert-badge-red">
          {{ alertsByDim[dimName].red }}
        </div>
        <div v-else-if="alertsByDim[dimName]?.yellow" class="alert-badge alert-badge-yellow">
          {{ alertsByDim[dimName].yellow }}
        </div>
      </div>
    </div>

    <!-- 预警摘要条 -->
    <div v-if="alertSummary && alertSummary.total > 0" class="alert-summary-bar" @click="activeAlertTab = activeAlertTab === 'alerts' ? null : 'alerts'">
      <span class="alert-summary-icon">⚠️</span>
      <span>本月共 <strong>{{ alertSummary.total }}</strong> 项指标预警</span>
      <span class="alert-summary-red">🔴 {{ alertSummary.red }} 项红灯</span>
      <span class="alert-summary-yellow">🟡 {{ alertSummary.yellow }} 项黄灯</span>
      <span class="alert-summary-toggle">{{ activeAlertTab === 'alerts' ? '▲' : '▼' }}</span>
    </div>

    <div class="detail-section">
      <div class="detail-header">
        <h4>{{ activeTab }} 指标详情</h4>
        <span class="count-tag">{{ data[activeTab]?.length }} 个监控项</span>
      </div>

      <div class="metric-grid">
        <div class="metric-card" v-for="item in data[activeTab]" :key="item.code">
          <div class="metric-top">
            <span class="m-name">{{ item.name }}</span>
            <span :class="['m-status', item.is_ok ? 'status-ok' : 'status-warn']">
              {{ item.is_ok ? '达标' : '待改进' }}
            </span>
          </div>

          <div class="m-values">
            <div class="val-group">
              <span class="v-label">当前值</span>
              <span class="v-num" :class="{ 'warn': !item.is_ok }">{{ item.value }} <small>{{ item.unit }}</small></span>
            </div>
            <div class="val-group">
              <span class="v-label">目标值</span>
              <span class="v-num target">{{ item.is_negative ? '≤' : '≥' }}{{ item.target }} <small>{{ item.unit }}</small></span>
            </div>
          </div>

          <div class="m-progress-bar">
            <div class="bar-bg">
              <div
                class="bar-fill"
                :class="item.is_ok ? 'fill-ok' : 'fill-warn'"
                :style="{ width: Math.min((item.value / (item.target || 1)) * 50, 100) + '%' }"
              ></div>
            </div>
          </div>
        </div>
      </div>

      <!-- 预警列表 -->
      <div v-if="activeAlertTab === 'alerts' && currentAlerts.length" class="alert-section">
        <div class="detail-header">
          <h4>🚨 当前维度预警详情</h4>
          <span class="count-tag">{{ currentAlerts.length }} 项预警</span>
        </div>
        <div class="alert-list">
          <div v-for="alert in currentAlerts" :key="alert.id" :class="['alert-item', `alert-${alert.alert_level}`]">
            <div class="alert-item-header">
              <span :class="['alert-level-badge', `level-${alert.alert_level}`]">
                {{ alert.alert_level === 'red' ? '🔴 红灯' : '🟡 黄灯' }}
              </span>
              <span class="alert-metric-name">{{ alert.metric_name }}</span>
              <span class="alert-deviation">偏离 {{ alert.deviation_pct }}%</span>
            </div>
            <div class="alert-item-values">
              当前值: <strong>{{ alert.metric_value }}</strong> &nbsp;|&nbsp; 目标值: {{ alert.target_value }}
              &nbsp;|&nbsp; 上报: {{ alert.escalation_target === 'dean' ? '院长' : alert.escalation_target === 'medical_office+dept_head' ? '医务处+科主任' : '科主任' }}
            </div>
            <div class="alert-actions">
              <button
                v-if="!alert.root_cause"
                class="ai-analyze-btn"
                @click="analyzeAlert(alert)"
                :disabled="analyzingId === alert.id"
              >
                {{ analyzingId === alert.id ? '⏳ 分析中...' : '🧠 AI 归因分析' }}
              </button>
              <button v-else class="view-analysis-btn" @click="showAlertAnalysis(alert)">
                📋 查看分析
              </button>
            </div>
          </div>
        </div>
      </div>
    </div>

    <!-- 报告弹窗 -->
    <div v-if="isReportVisible" class="report-modal-overlay" @click.self="isReportVisible = false">
      <div class="report-modal-content">
        <div class="modal-header">
          <h2>📊 医院运营深度分析报告</h2>
          <div class="modal-header-actions">
            <button v-if="!isGenerating && reportRawText" class="download-btn" @click="downloadReport('md')">📥 Markdown</button>
            <button v-if="!isGenerating && reportHtmlContent" class="download-btn html" @click="downloadReport('html')">🌐 HTML</button>
            <button class="close-btn" @click="isReportVisible = false">✖</button>
          </div>
        </div>
        <div class="modal-body">
          <div v-if="isGenerating" class="loading-state">
            <div class="spinner"></div>
            <p>AI 正在深度查阅 {{ Object.values(data).flat().length }} 项底层指标，生成归因分析，请稍候约 10-15 秒...</p>
          </div>
          <div v-else class="markdown-body" v-html="reportHtml"></div>
        </div>
      </div>
    </div>

    <!-- AI 归因分析弹窗 -->
    <div v-if="isAlertModalVisible" class="report-modal-overlay" @click.self="isAlertModalVisible = false">
      <div class="report-modal-content">
        <div class="modal-header">
          <h2>🔍 AI 归因分析: {{ selectedAlert?.metric_name }}</h2>
          <button class="close-btn" @click="isAlertModalVisible = false">✖</button>
        </div>
        <div class="modal-body">
          <div v-if="isAnalyzing" class="loading-state">
            <div class="spinner"></div>
            <p>AI 正在查询手术明细数据，追溯异常根因并生成改进建议...</p>
          </div>
          <div v-else class="analysis-content">
            <div class="analysis-section">
              <h3>📋 预警概览</h3>
              <div class="alert-overview-grid">
                <div class="overview-item">
                  <span class="overview-label">指标</span>
                  <span class="overview-value">{{ selectedAlert?.metric_name }}</span>
                </div>
                <div class="overview-item">
                  <span class="overview-label">等级</span>
                  <span :class="['overview-value', selectedAlert?.alert_level === 'red' ? 'text-red' : 'text-yellow']">
                    {{ selectedAlert?.alert_level === 'red' ? '🔴 红灯' : '🟡 黄灯' }}
                  </span>
                </div>
                <div class="overview-item">
                  <span class="overview-label">当前值</span>
                  <span class="overview-value">{{ selectedAlert?.metric_value }}</span>
                </div>
                <div class="overview-item">
                  <span class="overview-label">目标值</span>
                  <span class="overview-value">{{ selectedAlert?.target_value }}</span>
                </div>
                <div class="overview-item">
                  <span class="overview-label">偏离度</span>
                  <span class="overview-value text-red">{{ selectedAlert?.deviation_pct }}%</span>
                </div>
              </div>
            </div>
            <div class="analysis-section">
              <h3>🔬 根因诊断</h3>
              <p>{{ alertAnalysis?.root_cause || '暂无分析结果' }}</p>
            </div>
            <div class="analysis-section">
              <h3>💡 行动建议</h3>
              <div v-html="marked.parse(alertAnalysis?.action_recommendation || '')"></div>
            </div>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { computed, ref } from 'vue';
import { marked } from 'marked';

const props = defineProps({
  data: {
    type: Object,
    required: true
  },
  alerts: {
    type: Array,
    default: () => []
  }
});

// ---------- 预警计算 ----------
const alertSummary = computed(() => {
  if (!props.alerts || props.alerts.length === 0) return null;
  return {
    total: props.alerts.length,
    red: props.alerts.filter(a => a.alert_level === 'red').length,
    yellow: props.alerts.filter(a => a.alert_level === 'yellow').length
  };
});

const alertsByDim = computed(() => {
  const grouped = {};
  for (const a of (props.alerts || [])) {
    if (!grouped[a.dimension]) grouped[a.dimension] = { red: 0, yellow: 0 };
    grouped[a.dimension][a.alert_level]++;
  }
  return grouped;
});

const currentAlerts = computed(() => {
  return (props.alerts || []).filter(a => a.dimension === activeTab.value);
});

const activeAlertTab = ref(null);

// ---------- AI 归因分析状态 ----------
const isAlertModalVisible = ref(false);
const isAnalyzing = ref(false);
const analyzingId = ref(null);
const selectedAlert = ref(null);
const alertAnalysis = ref(null);

const analyzeAlert = async (alert) => {
  if (analyzingId.value) return;
  analyzingId.value = alert.id;
  try {
    const resp = await fetch(`/api/alert/${alert.id}/analyze`, { method: 'POST' });
    const data = await resp.json();
    if (data.status === 'success') {
      alert.root_cause = data.root_cause;
      alert.action_recommendation = data.action_recommendation;
    }
  } catch (e) {
    console.error('AI 分析失败', e);
  } finally {
    analyzingId.value = null;
  }
};

const showAlertAnalysis = (alert) => {
  selectedAlert.value = alert;
  alertAnalysis.value = {
    root_cause: alert.root_cause,
    action_recommendation: alert.action_recommendation
  };
  isAlertModalVisible.value = true;
};

// AI 报告状态
const isReportVisible = ref(false);
const isGenerating = ref(false);
const reportHtml = ref('');
const reportRawText = ref('');
const reportHtmlContent = ref('');

// 触发 AI 生成
const fetchAiReport = async () => {
  if (isGenerating.value) return; // 双重防抖

  isReportVisible.value = true;
  isGenerating.value = true;
  reportHtml.value = '';
  reportRawText.value = '';
  reportHtmlContent.value = '';

  try {
    const response = await fetch('/api/report/generate?month=2026-03&format=html');
    const resData = await response.json();

    if (resData.status === 'success') {
      reportRawText.value = resData.report_content;
      reportHtmlContent.value = resData.html_content || '';
      reportHtml.value = marked.parse(resData.report_content);
    } else {
      reportHtml.value = `<p style="color:#ef4444;">生成失败：${resData.message}</p>`;
    }
  } catch (error) {
    reportHtml.value = `<p style="color:#ef4444;">网络异常，请检查后端：${error.message}</p>`;
  } finally {
    isGenerating.value = false;
  }
};

// 下载报告
const downloadReport = (format) => {
  if (format === 'html') {
    if (!reportHtmlContent.value) return;
    const blob = new Blob([reportHtmlContent.value], { type: 'text/html;charset=utf-8' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `医院运营分析报告_2026年3月.html`;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    URL.revokeObjectURL(url);
  } else {
    if (!reportRawText.value) return;
    const blob = new Blob([reportRawText.value], { type: 'text/markdown;charset=utf-8' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `医院运营分析报告_2026年3月.md`;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    URL.revokeObjectURL(url);
  }
};

const activeTab = ref('医疗质量');

// 计算维度统计数据
const getDimStats = (list) => {
  if (!list || list.length === 0) return { ok: 0, percent: 0 };
  const ok = list.filter(i => i.is_ok).length;
  const percent = Math.round((ok / list.length) * 100);
  return { ok, percent };
};

// SVG 环状图偏移量计算 (周长约为 251.2)
const calculateOffset = (percent) => {
  const circumference = 2 * Math.PI * 40;
  return circumference - (percent / 100) * circumference;
};
</script>

<style scoped>
/* 整体背景与容器 */
.dean-dashboard-container {
  background: #0f1114;
  color: #ffffff;
  padding: 24px;
  border-radius: 12px;
  margin-top: 20px;
  font-family: 'Inter', -apple-system, sans-serif;
  width: 100%;
  box-sizing: border-box;
}

/* 顶部工具栏 */
.dashboard-top-bar {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 24px;
  padding-bottom: 16px;
  border-bottom: 1px solid #2d333b;
}

.dashboard-title {
  margin: 0;
  font-size: 22px;
  color: #e0e0e0;
}

/* AI 报告按钮 */
.ai-report-btn {
  background: linear-gradient(135deg, #3b82f6, #8b5cf6);
  color: #fff;
  border: none;
  padding: 10px 20px;
  border-radius: 8px;
  cursor: pointer;
  font-weight: bold;
  font-size: 14px;
  box-shadow: 0 4px 6px rgba(0,0,0,0.3);
  transition: all 0.3s;
}

.ai-report-btn:hover:not(:disabled) {
  transform: translateY(-2px);
  box-shadow: 0 6px 12px rgba(139, 92, 246, 0.4);
}

.ai-report-btn:disabled {
  opacity: 0.7;
  cursor: not-allowed;
}

/* 顶部网格布局 */
.summary-grid {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: 24px;
  margin-bottom: 32px;
}

/* 维度卡片样式 */
.dim-card {
  background: #1c1f24;
  border-radius: 16px;
  padding: 24px;
  display: flex;
  flex-direction: column;
  align-items: center;
  cursor: pointer;
  transition: all 0.3s cubic-bezier(0.4, 0, 0.2, 1);
  border: 2px solid transparent;
  position: relative; /* 预警角标定位锚点 */
}

.dim-card:hover {
  background: #252a30;
  transform: translateY(-4px);
}

.dim-card.active {
  border-color: #6fb2ff;
  box-shadow: 0 0 20px rgba(111, 178, 255, 0.2);
  background: #1c1f24;
}

/* 环状图盒子 */
.chart-box {
  position: relative;
  width: 100px;
  height: 100px;
  margin-bottom: 20px;
}

.ring-svg {
  transform: rotate(-90deg);
  width: 100%;
  height: 100%;
}

.rail {
  fill: none;
  stroke: #2d333b;
  stroke-width: 8;
}

.progress {
  fill: none;
  stroke: #f3af2b;
  stroke-width: 8;
  stroke-linecap: round;
  stroke-dasharray: 251.2;
  transition: stroke-dashoffset 1s ease;
}

.active .progress {
  stroke: #6fb2ff;
}

.percent-text {
  position: absolute;
  top: 50%;
  left: 50%;
  transform: translate(-50%, -50%);
  font-size: 22px;
  font-weight: 800;
  color: #ffffff;
}

/* 卡片文字信息 */
.dim-info { text-align: center; }
.dim-name { font-size: 18px; font-weight: 600; margin-bottom: 6px; color: #e0e0e0; }
.dim-sub { font-size: 14px; color: #8a8f98; }

/* 下方详情列表区 */
.detail-section {
  background: #1c1f24;
  border-radius: 16px;
  padding: 24px;
}

.detail-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 24px;
}

.detail-header h4 { margin: 0; font-size: 20px; color: #6fb2ff; }
.count-tag { background: #2d333b; padding: 6px 14px; border-radius: 20px; font-size: 14px; color: #8a8f98; }

/* 指标卡片网格 */
.metric-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(320px, 1fr));
  gap: 20px;
}

.metric-card {
  background: #252a30;
  border-radius: 12px;
  padding: 20px;
  border: 1px solid #2d333b;
  display: flex;
  flex-direction: column;
  justify-content: space-between;
}

.metric-top {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  margin-bottom: 20px;
}

.m-name {
  font-size: 15px;
  font-weight: 500;
  color: #e0e0e0;
  max-width: 75%;
  line-height: 1.4;
}

.m-status { font-size: 12px; padding: 4px 10px; border-radius: 4px; white-space: nowrap; }
.status-ok { background: rgba(103, 194, 58, 0.1); color: #67c23a; }
.status-warn { background: rgba(245, 108, 108, 0.1); color: #f56c6c; }

.m-values { display: flex; justify-content: space-between; margin-bottom: 16px; }
.val-group { display: flex; flex-direction: column; }
.v-label { font-size: 12px; color: #8a8f98; margin-bottom: 6px; }
.v-num { font-size: 18px; font-weight: 700; color: #67c23a; }
.v-num.warn { color: #f56c6c; }
.v-num.target { color: #ffffff; }

/* 指标进度条 */
.bar-bg { height: 6px; background: #2d333b; border-radius: 3px; }
.bar-fill { height: 100%; border-radius: 3px; transition: width 0.8s cubic-bezier(0.4, 0, 0.2, 1); }
.fill-ok { background: #67c23a; }
.fill-warn { background: #f56c6c; }

/* ================= 报告弹窗样式（移回 Scoped 保证作用域安全） ================= */
.report-modal-overlay {
  position: fixed;
  top: 0; left: 0; width: 100vw; height: 100vh;
  background: rgba(0, 0, 0, 0.75);
  backdrop-filter: blur(5px);
  display: flex;
  justify-content: center;
  align-items: center;
  z-index: 10000;
}

.report-modal-content {
  background: #1e1e2d;
  color: #e2e8f0;
  width: 65%;
  max-width: 900px;
  max-height: 85vh;
  border-radius: 12px;
  display: flex;
  flex-direction: column;
  box-shadow: 0 25px 50px -12px rgba(0, 0, 0, 0.7);
}

.modal-header {
  padding: 20px 24px;
  border-bottom: 1px solid #334155;
  display: flex;
  justify-content: space-between;
  align-items: center;
}

.modal-header h2 { margin: 0; font-size: 20px; }

.close-btn {
  background: transparent; border: none; color: #94a3b8;
  font-size: 24px; cursor: pointer; transition: color 0.2s;
}

.close-btn:hover { color: #ef4444; }

.modal-header-actions {
  display: flex;
  align-items: center;
  gap: 12px;
}

.download-btn {
  background: linear-gradient(135deg, #3b82f6, #2563eb);
  color: #fff;
  border: none;
  padding: 8px 18px;
  border-radius: 8px;
  cursor: pointer;
  font-weight: 600;
  font-size: 14px;
  transition: all 0.2s;
}

.download-btn:hover {
  background: linear-gradient(135deg, #2563eb, #1d4ed8);
  transform: translateY(-1px);
  box-shadow: 0 4px 12px rgba(59, 130, 246, 0.3);
}

.download-btn.html {
  background: linear-gradient(135deg, #059669, #047857);
}

.download-btn.html:hover {
  background: linear-gradient(135deg, #047857, #065f46);
  box-shadow: 0 4px 12px rgba(5, 150, 105, 0.3);
}

.modal-body {
  flex: 1; /* 修复滚动条的核心代码 */
  padding: 30px 40px;
  overflow-y: auto;
  line-height: 1.7;
}

.loading-state {
  text-align: center; padding: 60px 0; color: #a78bfa;
  font-size: 1.1rem; animation: pulse 2s cubic-bezier(0.4, 0, 0.6, 1) infinite;
}

.spinner {
  width: 40px; height: 40px; border: 4px solid rgba(167, 139, 250, 0.3);
  border-top-color: #a78bfa; border-radius: 50%;
  animation: spin 1s linear infinite; margin: 0 auto 15px auto;
}

@keyframes spin { 100% { transform: rotate(360deg); } }
@keyframes pulse { 0%, 100% { opacity: 1; } 50% { opacity: .5; } }

/* 优化渲染后的 Markdown 样式 */
.markdown-body :deep(h2) { border-bottom: 1px solid #334155; padding-bottom: 8px; margin-top: 24px; color: #fff;}
.markdown-body :deep(h3) { color: #818cf8; margin-top: 20px; }
.markdown-body :deep(strong) { color: #f87171; }
.markdown-body :deep(li) { margin-bottom: 8px; }
/* ================= 预警相关样式 ================= */
.alert-summary-bar {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 12px 20px;
  margin-bottom: 20px;
  background: #1e2228;
  border-radius: 10px;
  border: 1px solid #333a42;
  cursor: pointer;
  transition: background 0.2s;
  font-size: 14px;
  color: #c0c4cc;
  user-select: none;
}
.alert-summary-bar:hover {
  background: #252a32;
}
.alert-summary-icon {
  font-size: 18px;
}
.alert-summary-red {
  color: #f56c6c;
  font-weight: 600;
}
.alert-summary-yellow {
  color: #e6a23c;
  font-weight: 600;
}
.alert-summary-toggle {
  margin-left: auto;
  color: #6b7280;
  font-size: 12px;
}

/* 维度卡片预警角标 */
.alert-badge {
  position: absolute;
  top: 12px;
  right: 12px;
  min-width: 22px;
  height: 22px;
  border-radius: 11px;
  font-size: 12px;
  font-weight: 700;
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 0 6px;
}
.alert-badge-red {
  background: #f56c6c;
  color: #fff;
}
.alert-badge-yellow {
  background: #e6a23c;
  color: #fff;
}

/* 预警列表 */
.alert-section {
  margin-top: 28px;
  padding-top: 20px;
  border-top: 1px solid #2d333b;
}
.alert-list {
  display: flex;
  flex-direction: column;
  gap: 12px;
  margin-top: 16px;
}
.alert-item {
  background: #1c1f24;
  border-radius: 10px;
  padding: 16px 20px;
  border-left: 4px solid transparent;
  transition: background 0.2s;
}
.alert-item:hover {
  background: #252a30;
}
.alert-red {
  border-left-color: #f56c6c;
}
.alert-yellow {
  border-left-color: #e6a23c;
}
.alert-item-header {
  display: flex;
  align-items: center;
  gap: 12px;
  margin-bottom: 8px;
}
.alert-level-badge {
  font-size: 12px;
  padding: 3px 10px;
  border-radius: 4px;
  font-weight: 600;
  white-space: nowrap;
}
.level-red {
  background: rgba(245, 108, 108, 0.15);
  color: #f56c6c;
}
.level-yellow {
  background: rgba(230, 162, 60, 0.15);
  color: #e6a23c;
}
.alert-metric-name {
  font-size: 15px;
  font-weight: 600;
  color: #e0e0e0;
  flex: 1;
}
.alert-deviation {
  font-size: 13px;
  color: #8a8f98;
  white-space: nowrap;
}
.alert-item-values {
  font-size: 13px;
  color: #8a8f98;
  margin-bottom: 10px;
}
.alert-actions {
  display: flex;
  gap: 10px;
}
.ai-analyze-btn,
.view-analysis-btn {
  font-size: 12px;
  padding: 6px 14px;
  border-radius: 6px;
  border: none;
  cursor: pointer;
  font-weight: 500;
  transition: all 0.2s;
}
.ai-analyze-btn {
  background: linear-gradient(135deg, #3b82f6, #8b5cf6);
  color: #fff;
}
.ai-analyze-btn:hover:not(:disabled) {
  transform: translateY(-1px);
  box-shadow: 0 4px 12px rgba(139, 92, 246, 0.3);
}
.ai-analyze-btn:disabled {
  opacity: 0.6;
  cursor: not-allowed;
}
.view-analysis-btn {
  background: #2d333b;
  color: #8a8f98;
}
.view-analysis-btn:hover {
  background: #3a4149;
  color: #e0e0e0;
}

/* AI 归因分析弹窗内容 */
.analysis-content {
  color: #e2e8f0;
}
.analysis-section {
  margin-bottom: 28px;
}
.analysis-section h3 {
  color: #818cf8;
  margin: 0 0 12px 0;
  font-size: 17px;
  border-bottom: 1px solid #334155;
  padding-bottom: 8px;
}
.analysis-section p {
  line-height: 1.7;
  color: #c8ced6;
}
.analysis-section ul {
  padding-left: 20px;
}
.analysis-section li {
  margin-bottom: 8px;
  line-height: 1.6;
}
.alert-overview-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(180px, 1fr));
  gap: 12px;
}
.overview-item {
  background: #252a30;
  border-radius: 8px;
  padding: 12px 16px;
  display: flex;
  flex-direction: column;
  gap: 4px;
}
.overview-label {
  font-size: 12px;
  color: #6b7280;
  text-transform: uppercase;
  letter-spacing: 0.5px;
}
.overview-value {
  font-size: 16px;
  font-weight: 600;
  color: #e0e0e0;
}
.text-red {
  color: #f56c6c;
}
.text-yellow {
  color: #e6a23c;
}
</style>

<!-- 全局放宽聊天对话框的限制 -->
<style>
.message-row-ai:has(.dean-dashboard-container),
.message-row:has(.dean-dashboard-container) {
  max-width: 1400px !important;
  width: 95% !important;
}

.message-card-ai:has(.dean-dashboard-container),
.message-card:has(.dean-dashboard-container) {
  max-width: 100% !important;
  width: 100% !important;
}

@supports not selector(:has(*)) {
  .message-row-ai, .message-row {
    max-width: 1200px !important;
  }
}
</style>