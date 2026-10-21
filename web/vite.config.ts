import { resolve } from 'node:path';
import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

// In development the Vite server proxies API calls to the local gateway, so the browser
// talks to a single origin, exactly as it does behind CloudFront in AWS.
const gateway = process.env.GATEWAY_URL ?? 'http://127.0.0.1:8080';

export default defineConfig({
  plugins: [react()],
  build: {
    rollupOptions: {
      // Two apps share the build: CourtHub itself, and FitPal, a demo partner app at /partner/.
      input: {
        main: resolve(__dirname, 'index.html'),
        partner: resolve(__dirname, 'partner/index.html'),
      },
    },
  },
  server: {
    port: 5173,
    proxy: {
      '/v1': gateway,
      '/auth': gateway,
    },
  },
});
