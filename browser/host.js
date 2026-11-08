// Connects the game (../web) to the browser: the save lives in extension storage and the
// toolbar badge shows "!" while a crisis is active. Runs before the game's own scripts.
(function () {
  const api = globalThis.browser ?? globalThis.chrome;
  const KEY = "dc-tui-save";
  let badge = null;

  window.DC_HOST = {
    theme: null,
    storage: {
      load: async () => {
        try {
          const found = await api.storage.local.get(KEY);
          return (found && found[KEY]) || null;
        } catch {
          return null;
        }
      },
      save: (json) => {
        try {
          return api.storage.local.set({ [KEY]: json }).catch(() => {});
        } catch {
          return undefined;
        }
      },
    },
    onStatus: (status) => {
      const next = status && status.crisis ? "!" : "";
      if (next === badge) return;
      badge = next;
      try {
        api.action.setBadgeText({ text: next });
        if (next) api.action.setBadgeBackgroundColor({ color: "#cc241d" });
      } catch {
        /* the badge is a nicety, never break the game over it */
      }
    },
  };
})();
