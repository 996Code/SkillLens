// AG0 spike：验证 chrome.debugger 四件事——attach / 可信点击 / 网络体捕获 / detach
// 结果经 console.log 打点，由驱动脚本经 CDP 读 SW console 断言。
const RESULTS = [];

function log(step, ok, detail = "") {
  RESULTS.push({ step, ok, detail });
  console.log(`[AG0] ${step}: ${ok ? "PASS" : "FAIL"} ${detail}`);
}

chrome.runtime.onMessage.addListener((msg, _sender, sendResponse) => {
  if (msg?.type === "AG0_RUN") {
    run(msg.testUrl).then(sendResponse);
    return true; // async
  }
  if (msg?.type === "AG0_CONFLICT") {
    conflict().then(sendResponse);
    return true;
  }
  if (msg?.type === "AG0_RESULTS") {
    sendResponse(RESULTS);
    return false;
  }
});

async function findTargetTab(testUrl) {
  const tabs = await chrome.tabs.query({ url: "http://mock.local/*" });
  return tabs.find((t) => t.url && t.url.includes("ag0-page")) || null;
}

async function conflict() {
  // 同 tab 连续两次 attach 不放开——第二次应报错（模拟外部调试器占用：
  // 真实场景是 DevTools 或另一扩展已 attach；同源二次 attach 报同语义错误）
  const tab = await findTargetTab("");
  if (!tab) return { step: "conflict-setup", ok: false, detail: "target tab not found" };
  const debuggee = { tabId: tab.id };
  try {
    await chrome.debugger.attach(debuggee, "1.3");
    try {
      await chrome.debugger.attach(debuggee, "1.3");
      await chrome.debugger.detach(debuggee);
      return { step: "conflict", ok: true, detail: "二次 attach 未报错（需人工 DevTools 复核）" };
    } catch (e) {
      await chrome.debugger.detach(debuggee);
      return { step: "conflict", ok: true, detail: `二次 attach 报错形态: ${e.message}` };
    }
  } catch (e) {
    return { step: "conflict", ok: false, detail: e.message };
  }
}

async function run(testUrl) {
  const tab = await findTargetTab(testUrl);
  if (!tab) {
    log("find-tab", false, "target tab not found");
    return RESULTS;
  }
  const tabId = tab.id;
  const debuggee = { tabId };
  try {
    // ① attach
    await chrome.debugger.attach(debuggee, "1.3");
    log("attach", true);
    await chrome.debugger.sendCommand(debuggee, "Page.enable");
    await chrome.debugger.sendCommand(debuggee, "Network.enable");
    await chrome.debugger.sendCommand(debuggee, "Runtime.enable");

    // ② 导航到测试页
    await chrome.debugger.sendCommand(debuggee, "Page.navigate", { url: testUrl });
    await sleep(2000);

    // ④ 网络体捕获：listener 必须在触发动作前注册（响应早于注册=竞态丢事件）
    const networkBody = new Promise((resolve) => {
      const listener = async (source, method, params) => {
        if (source.tabId !== tabId || method !== "Network.responseReceived") return;
        if (!params.response.url.includes("/api/spike")) return;
        chrome.debugger.onEvent.removeListener(listener);
        try {
          const b = await chrome.debugger.sendCommand(debuggee, "Network.getResponseBody", {
            requestId: params.requestId,
          });
          resolve(b?.body ?? null);
        } catch (e) { resolve(`ERR:${e.message}`); }
      };
      chrome.debugger.onEvent.addListener(listener);
      setTimeout(() => resolve(null), 8000);
    });

    // ③ 可信点击：Runtime.evaluate 取按钮坐标 → Input.dispatchMouseEvent
    const rect = await chrome.debugger.sendCommand(debuggee, "Runtime.evaluate", {
      expression: "JSON.stringify(document.querySelector('#btn').getBoundingClientRect())",
      returnByValue: true,
    });
    const r = JSON.parse(rect.result.value);
    const x = r.x + r.width / 2, y = r.y + r.height / 2;
    await chrome.debugger.sendCommand(debuggee, "Input.dispatchMouseEvent", {
      type: "mousePressed", x, y, button: "left", clickCount: 1,
    });
    await chrome.debugger.sendCommand(debuggee, "Input.dispatchMouseEvent", {
      type: "mouseReleased", x, y, button: "left", clickCount: 1,
    });
    await sleep(1000);

    // 验证点击真实生效（isTrusted=true 且框架状态更新）
    const clicked = await chrome.debugger.sendCommand(debuggee, "Runtime.evaluate", {
      expression: "JSON.stringify({trusted: window.__lastTrusted, label: document.querySelector('#state').textContent})",
      returnByValue: true,
    });
    const c = JSON.parse(clicked.result.value);
    log("trusted-click", c.trusted === true, `isTrusted=${c.trusted} state=${c.label}`);

    const body = await networkBody;
    log("network-body", body !== null && !String(body).startsWith("ERR"), `body=${String(body).slice(0, 60)}`);

    // AG2 追验：fill 原语（click 聚焦→insertText→值确认——水合语义）
    const fillRes = await chrome.debugger.sendCommand(debuggee, "Runtime.evaluate", {
      expression: "JSON.stringify(document.querySelector('#fillme') ? 1 : 0)",
      returnByValue: true,
    });
    if (JSON.parse(fillRes.result.value) === 1) {
      const fr = await chrome.debugger.sendCommand(debuggee, "Runtime.evaluate", {
        expression: "JSON.stringify(document.querySelector('#fillme').getBoundingClientRect())",
        returnByValue: true,
      });
      const fr2 = JSON.parse(fr.result.value);
      const fx = fr2.x + fr2.width / 2, fy = fr2.y + fr2.height / 2;
      await chrome.debugger.sendCommand(debuggee, "Input.dispatchMouseEvent", {
        type: "mousePressed", x: fx, y: fy, button: "left", clickCount: 1 });
      await chrome.debugger.sendCommand(debuggee, "Input.dispatchMouseEvent", {
        type: "mouseReleased", x: fx, y: fy, button: "left", clickCount: 1 });
      await chrome.debugger.sendCommand(debuggee, "Input.insertText", { text: "ag2-fill-ok" });
      await sleep(500);
      const val = await chrome.debugger.sendCommand(debuggee, "Runtime.evaluate", {
        expression: "document.querySelector('#fillme').value",
        returnByValue: true,
      });
      log("ag2-fill", val.result.value === "ag2-fill-ok", `value=${val.result.value}`);
      // 截图原语
      try {
        const shot = await chrome.debugger.sendCommand(debuggee, "Page.captureScreenshot", { format: "png" });
        log("ag2-screenshot", !!shot && shot.data.length > 1000, `len=${shot.data ? shot.data.length : 0}`);
      } catch (e) {
        log("ag2-screenshot", false, e.message);
      }
    }

    // ⑤ detach
    await chrome.debugger.detach(debuggee);
    log("detach", true);
    return RESULTS;
  } catch (e) {
    log("exception", false, e.message);
    try { await chrome.debugger.detach(debuggee); } catch {}
    return RESULTS;
  }
}

function sleep(ms) { return new Promise((r) => setTimeout(r, ms)); }

// SW 保活探针：外部每 10s 发 AG0_KEEPALIVE，回显计数——驱动脚本用
// 连续递增计数验证 SW 未被杀（若被杀重建，计数归零）
let keepaliveCount = 0;
chrome.runtime.onMessage.addListener((msg, _s, sendResponse) => {
  if (msg?.type === "AG0_KEEPALIVE") {
    keepaliveCount += 1;
    sendResponse({ keepaliveCount });
    return false;
  }
});
