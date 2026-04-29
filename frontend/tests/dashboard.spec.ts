// tests/dashboard.spec.ts
import { test, expect } from '@playwright/test';

test.describe('院长驾驶舱 Agentic Workflow 端到端测试', () => {
  
  test('模拟院长唤醒并渲染全院大屏', async ({ page }) => {
    // 1. 访问本地前端页面 (请确保您的 Vue 项目运行在对应的端口，通常 Vite 默认是 5173 或 3000)
    await page.goto('http://localhost:5173');

    // 2. 定位输入框并输入指令
    // 如果您的输入框不是 textarea，请将其替换为对应的 class 或 id，例如 '.chat-input' 或 page.getByPlaceholder('请输入...')
    const chatInput = page.locator('textarea'); 
    await chatInput.click();
    await chatInput.fill('帮我打开院长驾驶舱，查看全院核心指标。');

    // 3. 模拟按下回车发送 (或者定位发送按钮进行 click)
    await chatInput.press('Enter');

    // 4. 等待 AI 响应并断言【引导话术】是否出现
    // Agentic Workflow 需要一点时间思考和请求后端，我们给它 10 秒钟的超时时间
    await expect(page.getByText('已为您自动汇总全院56项国考核心指标数据')).toBeVisible({ timeout: 10000 });

    // 5. 断言核心：【大屏 DOM 容器】是否成功挂载
    const dashboardContainer = page.locator('.dean-dashboard-container');
    await expect(dashboardContainer).toBeVisible();

    // 6. 深入断言：验证 Vue 组件是否成功解析了后端的 56 项数据

    
    // 验证四大维度卡片是否成功渲染
    await expect(dashboardContainer.getByText('医疗质量', { exact: true })).toBeVisible();
    await expect(dashboardContainer.getByText('运营效率', { exact: true })).toBeVisible();
    await expect(dashboardContainer.getByText('持续发展', { exact: true })).toBeVisible();
    await expect(dashboardContainer.getByText('满意度评价', { exact: true })).toBeVisible();

    // 验证卡片下方是否出现了类似 "14/14 项达标" 的动态统计文案
    // 使用正则表达式模糊匹配，因为具体数字是后端随机生成的
    const okText = dashboardContainer.getByText(/项达标/);
    await expect(okText.first()).toBeVisible();

    // 验证下方的详情列表区 Header 是否渲染
    await expect(dashboardContainer.getByText(/指标详情/)).toBeVisible();
    await expect(dashboardContainer.getByText(/个监控项/)).toBeVisible();

    // 验证环状图（SVG）是否被渲染
    const svgRings = dashboardContainer.locator('svg.ring-svg');
    await expect(svgRings).toHaveCount(4); // 应该有 4 个维度的环状图

    // 7. 最终步骤：视觉留存（自动截图）
    // 这会在根目录下生成一张截图，您可以直接拿去给领导汇报，证明系统自动化运行完美！
    await dashboardContainer.screenshot({ path: 'e2e-dashboard-success.png' });
  });

});