<template>
  <article :class="['message-row', isUser ? 'message-row-user' : 'message-row-ai']">
    <div :class="['message-card', isUser ? 'message-card-user' : 'message-card-ai']">
      <div v-if="isUser" class="message-text">{{ message.text }}</div>
      <div v-else class="message-markdown" v-html="message.htmlText"></div>
      
      <ChartCard v-if="message.chartOption" :option="message.chartOption" />

      <DeanDashboard v-if="message.dashboardData" :data="message.dashboardData" />

      <div v-if="!isUser && message.engine" class="engine-badge" style="margin-top: 12px; font-size: 12px; border-top: 1px solid #eee; padding-top: 8px;">
        <span v-if="message.engine === 'core_kpi'" style="color: #67C23A;">
          ✅ 数据源：国考指标标准语义库 (安全准确)
        </span>
        <span v-else-if="message.engine === 'sql_query'" style="color: #E6A23C;">
          ⚠️ 数据源：AI 动态 SQL 探索 (供参考)
        </span>
        <span v-else-if="message.engine === 'graph_query'" style="color: #409EFF;">
          📘 数据源：医院制度与知识图谱
        </span>
        <span v-else-if="message.engine === 'dashboard'" style="color: #9c27b0;">
          📊 数据源：全院绩效考核大屏引擎
        </span>
      </div>

    </div>
  </article>
</template>

<script setup>
import { computed } from "vue";
import ChartCard from "./ChartCard.vue";
import DeanDashboard from "./DeanDashboard.vue"; // [新增引入]

const props = defineProps({
  message: {
    type: Object,
    required: true,
  },
});

const isUser = computed(() => props.message.sender === "user");
</script>