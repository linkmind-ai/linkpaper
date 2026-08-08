import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// 백엔드(FastAPI)가 준비되면 아래 proxy target만 실제 주소로 바꾸면 됩니다.
// 개발 중에는 VITE_USE_MOCK=true 로 두면 네트워크 요청 없이 목업 데이터로 동작합니다.
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      "/api": {
        target: process.env.VITE_BACKEND_ORIGIN || "http://localhost:8000",
        changeOrigin: true,
      },
    },
  },
});
