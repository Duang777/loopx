import { useEffect, useLayoutEffect, useState } from "react";

type Language = "en" | "zh";
const readLanguage = (): Language =>
  new URLSearchParams(window.location.search).get("lang") === "zh" ? "zh" : "en";

// Both public React pages share URL language and fragment navigation. The static
// shell has no section IDs, so the browser's first fragment lookup can miss them.
export function usePublicPageNavigation() {
  const [language, setLanguage] = useState<Language>(readLanguage);

  useEffect(() => {
    const restoreLanguage = () => setLanguage(readLanguage());
    window.addEventListener("popstate", restoreLanguage);
    return () => window.removeEventListener("popstate", restoreLanguage);
  }, []);

  useLayoutEffect(() => {
    const url = new URL(window.location.href);
    if (language === "zh") url.searchParams.set("lang", "zh");
    else url.searchParams.delete("lang");
    window.history.replaceState(window.history.state, "", url);
    document.documentElement.lang = language === "zh" ? "zh-CN" : "en";

    let id: string;
    try {
      id = decodeURIComponent(url.hash.slice(1));
    } catch {
      return; // Malformed fragments leave normal page entry intact.
    }
    const target = document.getElementById(id);
    if (!target) return;
    // :target can remain unresolved after parsing the empty shell. Reveal the
    // destination before scrolling, including when translated content reflows.
    target.closest(".reveal-block")?.setAttribute("data-anchor-entry", "");
    const align = () => target.scrollIntoView({ behavior: "instant" });
    align();

    // Web fonts can change all preceding section heights after the first layout.
    // Correct that one late reflow, but never pull a reader back after input or
    // another navigation. Cleanup also cancels stale locale/unmount callbacks.
    let cancelled = false;
    const cancel = () => { cancelled = true; };
    const interrupts = ["wheel", "touchstart", "pointerdown", "keydown", "hashchange", "popstate"] as const;
    for (const event of interrupts) window.addEventListener(event, cancel, { passive: true });
    void document.fonts.ready.then(() => {
      if (!cancelled && window.location.hash === url.hash) align();
    });
    return () => {
      cancel();
      for (const event of interrupts) window.removeEventListener(event, cancel);
    };
  }, [language]);

  return [language, setLanguage] as const;
}
