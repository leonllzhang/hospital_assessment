<template>
  <article :class="['message-row', isUser ? 'message-row-user' : 'message-row-ai']">
    <div :class="['message-card', isUser ? 'message-card-user' : 'message-card-ai']">
      <div v-if="isUser" class="message-text">{{ message.text }}</div>
      <div v-else class="message-markdown" v-html="message.htmlText"></div>
      <ChartCard v-if="message.chartOption" :option="message.chartOption" />
    </div>
  </article>
</template>

<script setup>
import { computed } from "vue";

import ChartCard from "./ChartCard.vue";

const props = defineProps({
  message: {
    type: Object,
    required: true,
  },
});

const isUser = computed(() => props.message.sender === "user");
</script>
