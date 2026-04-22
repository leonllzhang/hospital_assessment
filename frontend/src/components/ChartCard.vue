<template>
  <div ref="chartRef" class="chart-card"></div>
</template>

<script setup>
import * as echarts from "echarts";
import { nextTick, onBeforeUnmount, onMounted, ref, watch } from "vue";

const props = defineProps({
  option: {
    type: Object,
    required: true,
  },
});

const chartRef = ref(null);
let chartInstance = null;

function resizeChart() {
  if (chartInstance) {
    chartInstance.resize();
  }
}

async function renderChart() {
  await nextTick();
  if (!chartRef.value || !props.option) {
    return;
  }

  if (!chartInstance) {
    chartInstance = echarts.init(chartRef.value);
  }

  chartInstance.setOption(props.option, true);
}

watch(
  () => props.option,
  () => {
    renderChart();
  },
  { deep: true }
);

onMounted(() => {
  renderChart();
  window.addEventListener("resize", resizeChart);
});

onBeforeUnmount(() => {
  window.removeEventListener("resize", resizeChart);
  if (chartInstance) {
    chartInstance.dispose();
    chartInstance = null;
  }
});
</script>
