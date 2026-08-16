import { defineConfig } from 'vitest/config'
import react from '@vitejs/plugin-react'

// 5175: 5173 is the product client, 5174 the operator's console. No strictPort
// — .claude/launch.json's autoPort must be able to move this if it is taken
// (the lesson admin-web learned).
export default defineConfig({
  plugins: [react()],
  server: { port: 5175, host: true },
  test: { include: ['src/**/*.test.ts'] },
})
