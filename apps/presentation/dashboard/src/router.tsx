import {
  Outlet,
  createRootRoute,
  createRoute,
  createRouter,
  lazyRouteComponent,
} from "@tanstack/react-router";
import { z } from "zod";

import { DashboardPage } from "./views/dashboard-page";
import { FrontstageDeveloperPage } from "./views/frontstage-developer-page";
import { FrontstagePage } from "./views/frontstage-page";

const searchSchema = z.object({
  actionKind: z.enum(["all", "reward", "controller", "codex", "evidence", "health"]).optional().default("all"),
  goalId: z.string().optional().default(""),
  lane: z.enum(["all", "user", "codex", "watch"]).optional().default("all"),
  severity: z.enum(["all", "high", "action", "watch"]).optional().default("all"),
  statusUrl: z.string().optional().default(""),
  todoGoalId: z.string().optional().default("all"),
  todoQuery: z.string().optional().default(""),
  todoRole: z.enum(["all", "user", "agent"]).optional().default("all"),
  todoStatus: z.enum(["all", "open", "done", "blocked", "deferred"]).optional().default("all"),
  view: z.enum(["ops", "share"]).optional(),
});

const frontstageSearchSchema = z.object({
  goalId: z.string().optional().default(""),
  mode: z.enum(["showcase", "developer", "ops"]).optional().default("showcase"),
  statusUrl: z.string().optional().default(""),
  todoLane: z.enum(["all", "user", "agent"]).optional().default("all"),
  todoQuery: z.string().optional().default(""),
});

const operatorSearchSchema = z.object({
  goalId: z.string().optional().default(""),
});

export const rootRoute = createRootRoute({
  component: () => <Outlet />,
});

export const dashboardRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/",
  validateSearch: (search) => searchSchema.parse(search),
  component: DashboardPage,
});

export const frontstageRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/frontstage",
  validateSearch: (search) => frontstageSearchSchema.parse(search),
  component: FrontstagePage,
});

export const frontstageDeveloperRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/frontstage/developer",
  component: FrontstageDeveloperPage,
});

export const operatorRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/operator",
  validateSearch: (search) => operatorSearchSchema.parse(search),
  component: lazyRouteComponent(
    () => import("./views/operator-console-page"),
    "OperatorConsolePage",
  ),
});

const routeTree = rootRoute.addChildren([
  dashboardRoute,
  frontstageRoute,
  frontstageDeveloperRoute,
  operatorRoute,
]);

function routerBasepathFromViteBase(baseUrl: string) {
  if (!baseUrl || baseUrl === "/" || baseUrl === "./") {
    return "/";
  }
  const withLeadingSlash = baseUrl.startsWith("/") ? baseUrl : `/${baseUrl}`;
  return withLeadingSlash.replace(/\/+$/, "") || "/";
}

export const router = createRouter({
  routeTree,
  basepath: routerBasepathFromViteBase(import.meta.env.BASE_URL),
});

declare module "@tanstack/react-router" {
  interface Register {
    router: typeof router;
  }
}
