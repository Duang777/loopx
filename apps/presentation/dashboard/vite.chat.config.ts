import tailwindcss from "@tailwindcss/vite";
import react from "@vitejs/plugin-react";
import { resolve } from "node:path";
import { defineConfig, type Plugin } from "vite";

function trimChunkTrailingWhitespace(): Plugin {
  return {
    name: "loopx-chat-trim-chunk-trailing-whitespace",
    renderChunk(code) {
      return code.replace(/[\t ]+$/gm, "");
    },
  };
}

export default defineConfig({
  root: resolve(import.meta.dirname, "chat"),
  base: "/chat/",
  plugins: [react(), tailwindcss(), trimChunkTrailingWhitespace()],
  build: {
    outDir: resolve(import.meta.dirname, "../../../loopx/web/chat"),
    emptyOutDir: true,
  },
});
