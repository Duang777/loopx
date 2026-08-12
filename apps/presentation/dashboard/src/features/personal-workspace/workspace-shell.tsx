import type { ReactNode } from "react";

export function WorkspaceShell({
  drawer,
  drawerOpen,
  main,
  mobileSidebarOpen = false,
  onCloseMobileSidebar,
  sidebar,
}: {
  drawer?: ReactNode;
  drawerOpen: boolean;
  main: ReactNode;
  mobileSidebarOpen?: boolean;
  onCloseMobileSidebar?: () => void;
  sidebar: ReactNode;
}) {
  return (
    <section className={`personal-workspace-shell${drawerOpen ? " has-drawer" : ""}${mobileSidebarOpen ? " mobile-sidebar-open" : ""}`}>
      {mobileSidebarOpen ? <button aria-label="关闭 Goal 导航" className="personal-sidebar-backdrop" onClick={onCloseMobileSidebar} type="button" /> : null}
      <aside className="personal-workspace-sidebar" data-workspace-sidebar><div className="personal-workspace-sidebar-inner">{sidebar}</div></aside>
      <main className="personal-workspace-main">{main}</main>
      {drawerOpen ? <aside className="personal-workspace-drawer" data-context-drawer>{drawer}</aside> : null}
    </section>
  );
}
