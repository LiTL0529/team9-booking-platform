import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

// In development the Vite server proxies API calls to the local gateway, so the browser
// talks to a single origin, exactly as it does behind CloudFront in AWS.
const gateway = process.env.GATEWAY_URL ?? 'http://127.0.0.1:8080';

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      '/v1': gateway,
      '/auth': gateway,
    },
  },
});
