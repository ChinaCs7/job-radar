import { useEffect, useState } from "react";

export type Theme = "light" | "dark" | "system";

// 主题只存在本地（每台电脑、每个浏览器各自记住），桌面界面和结果页共用同一个 key
const KEY = "jr-theme";

function apply(t: Theme) {
  if (t === "system") delete document.documentElement.dataset.theme;
  else document.documentElement.dataset.theme = t;
}

export function useTheme(): [Theme, (t: Theme) => void] {
  const [theme, setTheme] = useState<Theme>(() => {
    try { return (localStorage.getItem(KEY) as Theme) || "system"; } catch { return "system"; }
  });
  useEffect(() => {
    apply(theme);
    try { localStorage.setItem(KEY, theme); } catch { /* 无痕模式等 */ }
  }, [theme]);
  return [theme, setTheme];
}
