import path from "node:path";
import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
export default defineConfig({
    plugins: [react()],
    resolve: {
        alias: {
            "@": path.resolve(__dirname, "./src"),
        },
    },
    build: {
        outDir: "../dist",
        emptyOutDir: true,
        sourcemap: false,
        chunkSizeWarningLimit: 2000,
    },
    server: {
        port: 5173,
        strictPort: false,
        proxy: {
            "/api": {
                target: "http://127.0.0.1:8787",
                changeOrigin: true,
            },
            "/open": {
                target: "http://127.0.0.1:8787",
                changeOrigin: true,
            },
        },
    },
});
