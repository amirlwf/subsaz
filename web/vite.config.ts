import { defineConfig } from "vite";

// Built assets must load from pywebview's local http server, so keep paths
// relative and emit into ../web_dist which Python serves.
export default defineConfig({
  base: "./",
  build: {
    outDir: "../web_dist",
    emptyOutDir: true,
    target: "es2020",
  },
  server: { port: 5199, strictPort: true },
});
