<template>
  <div class="dean-dashboard-container">
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
      </div>
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
    </div>
  </div>
</template>

<script setup>
import { ref } from 'vue';

const props = defineProps({
  data: {
    type: Object,
    required: true
  }
});

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
  background: #0f1114; /* 极致深色背景 */
  color: #ffffff;
  padding: 24px;
  border-radius: 12px;
  margin-top: 20px;
  font-family: 'Inter', -apple-system, sans-serif;
  width: 100%;
}

/* 顶部网格布局 - 在宽屏下会更加舒展 */
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
  stroke: #f3af2b; /* 默认橙色进度 */
  stroke-width: 8;
  stroke-linecap: round;
  stroke-dasharray: 251.2;
  transition: stroke-dashoffset 1s ease;
}

.active .progress {
  stroke: #6fb2ff; /* 激活时变为蓝色 */
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
.dim-info {
  text-align: center;
}

.dim-name {
  font-size: 18px;
  font-weight: 600;
  margin-bottom: 6px;
  color: #e0e0e0;
}

.dim-sub {
  font-size: 14px;
  color: #8a8f98;
}

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

.detail-header h4 {
  margin: 0;
  font-size: 20px;
  color: #6fb2ff;
}

.count-tag {
  background: #2d333b;
  padding: 6px 14px;
  border-radius: 20px;
  font-size: 14px;
  color: #8a8f98;
}

/* 指标卡片网格 - 响应式自适应宽度 */
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

.m-status {
  font-size: 12px;
  padding: 4px 10px;
  border-radius: 4px;
  white-space: nowrap;
}

.status-ok { background: rgba(103, 194, 58, 0.1); color: #67c23a; }
.status-warn { background: rgba(245, 108, 108, 0.1); color: #f56c6c; }

.m-values {
  display: flex;
  justify-content: space-between;
  margin-bottom: 16px;
}

.val-group {
  display: flex;
  flex-direction: column;
}

.v-label { font-size: 12px; color: #8a8f98; margin-bottom: 6px; }
.v-num { font-size: 18px; font-weight: 700; color: #67c23a; }
.v-num.warn { color: #f56c6c; }
.v-num.target { color: #ffffff; }

/* 指标进度条 */
.bar-bg {
  height: 6px;
  background: #2d333b;
  border-radius: 3px;
}

.bar-fill {
  height: 100%;
  border-radius: 3px;
  transition: width 0.8s cubic-bezier(0.4, 0, 0.2, 1);
}

.fill-ok { background: #67c23a; }
.fill-warn { background: #f56c6c; }
</style>

<!-- 
  新增：无作用域 (Unscoped) 的全局样式。
  利用 :has() 伪类，当聊天气泡内部渲染了驾驶舱组件时，
  自动破除父级聊天气泡的最大宽度限制，使其占满更宽的屏幕空间。
-->
<style>
/* 扩大包含仪表盘的对话框整体宽度 */
.message-row-ai:has(.dean-dashboard-container),
.message-row:has(.dean-dashboard-container) {
  max-width: 1400px !important; /* 扩大最大宽度，利用两侧空白 */
  width: 95% !important;
}

.message-card-ai:has(.dean-dashboard-container),
.message-card:has(.dean-dashboard-container) {
  max-width: 100% !important;
  width: 100% !important;
}

/* 兼容不支持 :has 的老旧浏览器，直接放宽整个聊天流的最大限制 */
@supports not selector(:has(*)) {
  .message-row-ai, .message-row {
    max-width: 1200px !important;
  }
}
</style>