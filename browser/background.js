// Clicking the toolbar icon opens the game in its own tab (or focuses it if already open).
const api = globalThis.browser ?? globalThis.chrome;

api.action.onClicked.addListener(async () => {
  const url = api.runtime.getURL("app/index.html");
  const [existing] = await api.tabs.query({ url });
  if (existing) {
    await api.tabs.update(existing.id, { active: true });
    await api.windows.update(existing.windowId, { focused: true });
  } else {
    await api.tabs.create({ url });
  }
});
