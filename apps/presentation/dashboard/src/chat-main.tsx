import { createRoot } from "react-dom/client";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

import { ChatPage } from "./views/chat-page";
import "./styles.css";

const root = document.getElementById("root");

if (!root) {
  throw new Error("Root element not found");
}

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      refetchOnWindowFocus: false,
      retry: 1,
      staleTime: 10_000,
    },
  },
});
const initialGoalId = new URLSearchParams(window.location.search).get("goalId") || "";

createRoot(root).render(
  <QueryClientProvider client={queryClient}>
    <ChatPage initialGoalId={initialGoalId} />
  </QueryClientProvider>,
);
