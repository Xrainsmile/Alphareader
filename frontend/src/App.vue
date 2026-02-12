<script>
export default {
  onLaunch() {
    console.log('AlphaReader launched')
  },
}
</script>

<style>
/* 全局样式 */
page {
  background-color: #f0f2f5;
  color: #1a1a2e;
  font-family: 'PingFang SC', 'SF Pro Text', -apple-system, BlinkMacSystemFont,
    'Helvetica Neue', 'Noto Sans SC', 'Microsoft YaHei', sans-serif;
  -webkit-font-smoothing: antialiased;
  -moz-osx-font-smoothing: grayscale;
}

/* PC 端滚动条美化 */
@media screen and (min-width: 768px) {
  ::-webkit-scrollbar {
    width: 6px;
  }
  ::-webkit-scrollbar-track {
    background: transparent;
  }
  ::-webkit-scrollbar-thumb {
    background: rgba(0, 0, 0, 0.15);
    border-radius: 3px;
  }
  ::-webkit-scrollbar-thumb:hover {
    background: rgba(0, 0, 0, 0.25);
  }
  /* 鼠标选中文本样式 */
  ::selection {
    background: rgba(66, 133, 244, 0.2);
    color: inherit;
  }
}
</style>
