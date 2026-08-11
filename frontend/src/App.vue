<template>
  <el-container class="layout">
    <el-header class="layout-header">
      <router-link to="/" class="brand">
        <el-icon :size="22"><Tools /></el-icon>
        <span>Lab Tools</span>
      </router-link>
      <div class="header-right">办公文件处理工具箱</div>
    </el-header>
    <el-main class="layout-main">
      <router-view />
    </el-main>
  </el-container>
</template>

<script setup>
import { Tools } from '@element-plus/icons-vue'
</script>

<style>
html,
body,
#app {
  height: 100%;
  margin: 0;
  background: #f5f7fa;
}

.layout {
  min-height: 100vh;
}

.layout-header {
  display: flex;
  align-items: center;
  background: #fff;
  border-bottom: 1px solid #e4e7ed;
  padding: 0 24px;
}

.brand {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 18px;
  font-weight: 600;
  color: #409eff;
  text-decoration: none;
}

.header-right {
  margin-left: auto;
  color: #909399;
  font-size: 13px;
}

.layout-main {
  padding: 20px;
  max-width: 1200px;
  margin: 0 auto;
  width: 100%;
  box-sizing: border-box;
}

.card {
  background: #fff;
  border-radius: 8px;
  box-shadow: 0 1px 3px rgba(0, 0, 0, 0.08);
  padding: 20px;
}

.card + .card {
  margin-top: 16px;
}

.card-title {
  font-size: 16px;
  font-weight: 600;
  margin: 0 0 16px;
  display: flex;
  align-items: center;
  gap: 8px;
}

.muted {
  color: #909399;
  font-size: 13px;
}
</style>