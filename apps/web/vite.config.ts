import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);

export default defineConfig({
  plugins: [react()],
  resolve: {
    alias: {
      '@reroute/ui': path.resolve(__dirname, '../../packages/ui/src'),
      '@reroute/utils': path.resolve(__dirname, '../../packages/utils/src')
    }
  },
  server: {
    port: 5173
  }
});
