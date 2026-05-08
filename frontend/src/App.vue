<template>
  <main class="full-screen-app">
    <!-- 删除了原有的 hero-panel，直接让对话框成为视觉中心 -->

    <section class="chat-container">
      <header class="chat-header">
        <div>
          <p class="panel-label">HOSPITAL QA SYSTEM</p>
          <h2>院长指标分析助手</h2>
        </div>
        <span class="status-chip">{{ isLoading ? "思考分析中..." : "系统待命" }}</span>
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
          placeholder="请输入问题，例如：打开院长驾驶舱，查看全院核心指标"
          @keydown.enter.exact.prevent="handleSubmit"
        ></textarea>
        <div class="composer-actions">
          <p class="composer-hint">💡 提示：可查询制度定义、公式口径和具体业务数据，支持唤醒大屏。</p>
          <button class="send-button" type="submit" :disabled="isLoading || !trimmedInput">
            {{ isLoading ? "发送中..." : "发送指令" }}
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
  "院长您好。您可以询问 **制度逻辑**，例如“微创手术占比怎么算”；也可以直接查询 **业务数据**，或者发送指令 **“打开院长驾驶舱”** 唤醒全院指标大屏。";

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
      target.engine = result.engine;
      target.dashboardData = result.dashboard_data;
      target.alertData = result.alert_data;
    } else {
      target.text = result.text;
      target.htmlText = `<span class="error-inline">${result.text}</span>`;
      target.engine = null;
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

<style scoped>
/* ========== 全局布局：居中沉浸式 ========== */
.full-screen-app {
  display: flex;
  justify-content: center; /* 让聊天窗口水平居中 */
  align-items: center; /* 垂直居中（带有一点阴影留白） */
  width: 100vw;
  height: 100vh;
  background-color: #f3f5f9; /* 浅色背景托底，凸显主聊天区 */
  overflow: hidden;
  box-sizing: border-box;
  padding: 20px; /* 屏幕边缘留白 */
}

/* ========== 核心聊天容器 ========== */
.chat-container {
  display: flex;
  flex-direction: column;
  width: 100%;
  max-width: 900px; /* 平时聊天的最佳阅读宽度 */
  height: 100%;
  background-color: #ffffff;
  border-radius: 16px; /* 圆角让视觉更柔和 */
  box-shadow: 0 10px 40px rgba(0, 0, 0, 0.08); /* 高级软阴影 */
  overflow: hidden;
  /* 核心动画：宽度变化时的丝滑过渡 */
  transition: max-width 0.6s cubic-bezier(0.16, 1, 0.3, 1);
}

/* 【黑科技】：如果聊天流里渲染了大屏组件，自动撑宽整个 App 容器 */
.chat-container:has(.dean-dashboard-container) {
  max-width: 1400px;
}

/* ========== 头部样式 ========== */
.chat-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 20px 30px;
  background-color: #ffffff;
  border-bottom: 1px solid #f1f5f9;
  z-index: 10;
}

.chat-header h2 {
  margin: 0;
  font-size: 18px;
  color: #1e293b;
  font-weight: 600;
}

.panel-label {
  margin: 0 0 4px 0;
  font-size: 12px;
  color: #94a3b8;
  letter-spacing: 1px;
  font-weight: bold;
}

.status-chip {
  font-size: 12px;
  padding: 6px 14px;
  background: #eff6ff;
  color: #3b82f6;
  border-radius: 20px;
  font-weight: 500;
}

/* ========== 消息对话区 ========== */
.chat-box {
  flex: 1;
  overflow-y: auto;
  padding: 30px;
  scroll-behavior: smooth;
  background-color: #fafbfc; /* 对话区稍微带点极浅灰，区分输入框 */
}

/* 隐藏原生滚动条使 UI 更极客 */
.chat-box::-webkit-scrollbar { width: 6px; }
.chat-box::-webkit-scrollbar-thumb { background: #cbd5e1; border-radius: 4px; }
.chat-box::-webkit-scrollbar-track { background: transparent; }

/* ========== 底部输入法区 ========== */
.composer {
  padding: 20px 30px;
  background: #ffffff;
  border-top: 1px solid #f1f5f9;
  flex-shrink: 0;
}

.composer-input {
  width: 100%;
  box-sizing: border-box;
  border: 1px solid #e2e8f0;
  border-radius: 12px;
  padding: 16px;
  font-family: inherit;
  font-size: 15px;
  line-height: 1.5;
  resize: none;
  outline: none;
  transition: all 0.3s;
  background-color: #f8fafc;
}

.composer-input:focus {
  border-color: #3b82f6;
  background-color: #ffffff;
  box-shadow: 0 0 0 3px rgba(59, 130, 246, 0.1);
}

.composer-actions {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-top: 16px;
}

.composer-hint {
  margin: 0;
  font-size: 13px;
  color: #94a3b8;
}

.send-button {
  background: #3b82f6;
  color: #fff;
  border: none;
  padding: 10px 24px;
  border-radius: 8px;
  cursor: pointer;
  font-weight: 600;
  font-size: 14px;
  transition: all 0.2s;
}

.send-button:disabled {
  background: #94a3b8;
  cursor: not-allowed;
  opacity: 0.7;
}

.send-button:hover:not(:disabled) {
  background: #2563eb;
  transform: translateY(-1px);
  box-shadow: 0 4px 12px rgba(59, 130, 246, 0.3);
}

/* 兼容内联样式 */
:deep(.loading-inline) { color: #8b5cf6; animation: pulse 1.5s infinite; }
:deep(.error-inline) { color: #ef4444; }
@keyframes pulse {
  0%, 100% { opacity: 1; }
  50% { opacity: 0.5; }
}
</style>