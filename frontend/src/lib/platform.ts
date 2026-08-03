export const isMac =
  typeof navigator !== "undefined" && /Mac|iPod|iPhone|iPad/.test(navigator.userAgent);

export function formatShortcut(key: string): string {
  if (isMac) {
    return key
      .replace("Mod", "\u2318")
      .replace("Alt", "\u2325")
      .replace("Shift", "\u21E7")
      .replace("Ctrl", "\u2303");
  }
  return key.replace("Mod", "Ctrl");
}

export const MOD_KEY = isMac ? "\u2318" : "Ctrl";
