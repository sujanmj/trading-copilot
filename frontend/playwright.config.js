// @ts-check
const path = require('path');
process.env.NODE_PATH = path.join(__dirname, 'node_modules');
require('module').Module._initPaths();

const { defineConfig } = require('@playwright/test');

module.exports = defineConfig({
  testDir: '../tests/gui',
  timeout: 60000,
  retries: 0,
  use: {
    baseURL: process.env.ASTRA_GUI_BASE || 'http://127.0.0.1:5173',
    headless: true,
    trace: 'retain-on-failure',
    screenshot: 'only-on-failure',
    video: 'retain-on-failure',
  },
  reporter: [['list']],
});
