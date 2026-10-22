import { defineConfig } from "vite";
// Development-only proxy. The private capability stays in Node, never in the UI.
const target = process.env.ADAM_DESKTOP_QA_ORIGIN;
export default defineConfig({
  clearScreen: false,
  server: {
    host: "127.0.0.1",
    port: 1420,
    strictPort: true,
    cors: false,
    proxy: target
      ? {
          "/api": {
            target,
            rewrite: (path) => path.replace(/^\/api/, ""),
            headers: {
              "x-adam-desktop": process.env.ADAM_DESKTOP_QA_NONCE ?? "",
            },
            configure: (proxy) =>
              proxy.on("proxyReq", (request) => request.removeHeader("origin")),
          },
        }
      : undefined,
  },
  plugins: [
    {
      name: "local-qa-origin",
      configureServer(server) {
        server.middlewares.use((request, response, next) => {
          if (
            request.headers.origin &&
            request.headers.origin !== "http://127.0.0.1:1420"
          ) {
            response.statusCode = 403;
            response.end("Origin denied");
            return;
          }
          next();
        });
      },
    },
  ],
  build: { target: "es2022", chunkSizeWarningLimit: 800 },
});
