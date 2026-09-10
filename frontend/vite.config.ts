import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

// 前端开发服务器：/api 与 WebSocket 代理到后端 FastAPI
export default defineConfig({
  plugins: [react()],
  server: {
    host: '0.0.0.0', // 监听所有网卡：允许同局域网其他用户通过 http://<本机IP>:3000 访问
    port: 3000,
    // 放行内网穿透域名（cpolar / localhost.run），否则 Vite 会拦截非 localhost 的 Host 请求
    allowedHosts: ['.cpolar.cn', '.cpolar.top', '.lhr.life', '.localhost.run'],
    proxy: {
      '/api': {
        target: 'http://localhost:8000',
        changeOrigin: true,
        ws: true,
      },
    },
  },
  preview: {
    host: '0.0.0.0',
    port: 3000,
    allowedHosts: ['.cpolar.cn', '.cpolar.top', '.lhr.life', '.localhost.run'],
    proxy: {
      '/api': {
        target: 'http://localhost:8000',
        changeOrigin: true,
        ws: true,
      },
    },
  },
  build: {
    outDir: 'dist',
    chunkSizeWarningLimit: 1500,
  },
});
