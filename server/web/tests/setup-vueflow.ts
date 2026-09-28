// Vue Flow 需要 ResizeObserver——jsdom 不提供，测试环境 polyfill
globalThis.ResizeObserver = class ResizeObserver {
  observe() {}
  unobserve() {}
  disconnect() {}
};
