<template>
  <main class="app-shell">
    <section class="hero-panel">
      <p class="hero-kicker">Hospital QA System</p>
      <h1>三级公立医院考核指标问答平台</h1>
      <p class="hero-description">
        前端已改为 Vue 3 工程化结构，后端继续使用 FastAPI，保留现有知识图谱与联动数据问答接口。
      </p>
      <div class="hero-tags">
        <span>制度逻辑问答</span>
        <span>联动业务数据</span>
        <span>ECharts 可视化</span>
      </div>
    </section>

    <section class="chat-panel">
      <header class="chat-header">
        <div>
          <p class="panel-label">对话工作台</p>
          <h2>院长指标分析助手</h2>
        </div>
        <span class="status-chip">{{ isLoading ? "分析中" : "待命" }}</span>
      </header>

      <div ref="chatBoxRef" class="chat-box">
        <ChatMessage
          v-for="message in messages"
          :key="message.id"
          :message="message"
        />
      </div>

      <form class="composer" @submit.prevent="handleSubmit">
        <textarea
          v-model="userInput"
          class="composer-input"
          rows="3"
          :disabled="isLoading"
          placeholder="请输入问题，例如：2026年3月骨科和普外科的微创手术占比对比"
          @keydown.enter.exact.prevent="handleSubmit"
        ></textarea>
        <div class="composer-actions">
          <p class="composer-hint">可查询制度定义、公式口径和具体业务数据。</p>
          <button class="send-button" type="submit" :disabled="isLoading || !trimmedInput">
            {{ isLoading ? "思考中..." : "发送问题" }}
          </button>
        </div>
      </form>
    </section>
  </main>
</template>

<script setup>
import { computed, nextTick, ref } from "vue";
import { marked } from "marked";

import { sendChatMessage } from "./api/chat";
import ChatMessage from "./components/ChatMessage.vue";

marked.setOptions({
  breaks: true,
});

const welcomeText =
  "院长您好。您可以询问 **制度逻辑**，例如“微创手术占比怎么算”；也可以直接查询 **业务数据**，例如“2026年3月骨科和普外科的手术对比”。";

const chatBoxRef = ref(null);
const userInput = ref("");
const isLoading = ref(false);
const messages = ref([
  {
    id: Date.now(),
    sender: "ai",
    text: welcomeText,
    htmlText: marked.parse(welcomeText),
    chartOption: null,
  },
]);

const trimmedInput = computed(() => userInput.value.trim());

async function scrollToBottom() {
  await nextTick();
  if (chatBoxRef.value) {
    chatBoxRef.value.scrollTop = chatBoxRef.value.scrollHeight;
  }
}

async function handleSubmit() {
  const query = trimmedInput.value;
  if (!query || isLoading.value) {
    return;
  }

  messages.value.push({
    id: Date.now(),
    sender: "user",
    text: query,
    htmlText: query,
    chartOption: null,
  });

  userInput.value = "";
  isLoading.value = true;

  const placeholderId = Date.now() + 1;
  messages.value.push({
    id: placeholderId,
    sender: "ai",
    text: "思考分析中...",
    htmlText: "<span class='loading-inline'>正在分析意图并生成结果...</span>",
    chartOption: null,
  });

  await scrollToBottom();

  try {
    const result = await sendChatMessage(query);
    const target = messages.value.find((item) => item.id === placeholderId);
    if (!target) {
      return;
    }

    if (result.status === "success") {
      target.text = result.text;
      target.htmlText = marked.parse(result.text || "");
      target.chartOption = result.chart_option;
    } else {
      target.text = result.text;
      target.htmlText = `<span class="error-inline">${result.text}</span>`;
    }
  } catch (error) {
    const target = messages.value.find((item) => item.id === placeholderId);
    if (target) {
      target.text = "网络请求失败";
      target.htmlText =
        "<span class='error-inline'>网络请求失败，请检查 FastAPI 服务和前端代理配置。</span>";
    }
  } finally {
    isLoading.value = false;
    await scrollToBottom();
  }
}
</script>
