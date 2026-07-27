import { defineConfig } from 'vitepress'

export default defineConfig({
  title: 'huavd-map-build',
  description: 'HUAVD offline PMTiles build pipeline documentation',
  cleanUrls: true,
  lastUpdated: true,
  themeConfig: {
    nav: [
      { text: '首页', link: '/' },
      { text: '手册', link: '/manual/' },
      { text: '开发', link: '/development/' },
      { text: '管线', link: '/pipeline/' },
      { text: '配置', link: '/configuration/' },
      { text: '运行', link: '/operations/' },
      { text: '参考', link: '/references/' },
    ],
    sidebar: [
      {
        text: 'huavd-map-build',
        items: [
          { text: '项目概览', link: '/' },
          { text: '安装与使用', link: '/manual/' },
          { text: '开发入口', link: '/development/' },
          { text: '构建管线', link: '/pipeline/' },
        ],
      },
      {
        text: '工程说明',
        items: [
          { text: '配置索引', link: '/configuration/' },
          { text: '运行与故障处理', link: '/operations/' },
          { text: '契约与外部工具', link: '/references/' },
        ],
      },
    ],
    search: {
      provider: 'local',
    },
    footer: {
      message: '本项目文档以当前代码实现为准，地图产品契约以 huavd-doc 为真值源。',
    },
  },
})
