<template>
  <div>
    <h2 class="page-title">工具列表</h2>
    <p class="muted">选择一个工具开始使用</p>

    <el-row :gutter="16">
      <el-col v-for="tool in tools" :key="tool.id" :xs="24" :sm="12" :md="8">
        <el-card class="tool-card" shadow="hover" @click="$router.push(tool.route)">
          <div class="tool-icon">
            <el-icon :size="28"><component :is="tool.icon || 'Grid'" /></el-icon>
          </div>
          <div class="tool-name">{{ tool.name }}</div>
          <div class="tool-desc">{{ tool.description }}</div>
        </el-card>
      </el-col>
    </el-row>

    <el-empty v-if="!loading && tools.length === 0" description="暂无可用工具" />
  </div>
</template>

<script setup>
import { onMounted, ref } from 'vue'
import { getTools } from '../api'

const tools = ref([])
const loading = ref(true)

onMounted(async () => {
  try {
    tools.value = await getTools()
  } catch (e) {
    ElMessage.error(e.message)
  } finally {
    loading.value = false
  }
})
</script>

<style scoped>
.page-title {
  margin: 0 0 4px;
}

.tool-card {
  margin-bottom: 16px;
  cursor: pointer;
  transition: transform 0.15s ease, box-shadow 0.15s ease;
}

.tool-card:hover {
  transform: translateY(-2px);
  box-shadow: 0 6px 16px rgba(0, 0, 0, 0.12);
}

.tool-icon {
  width: 56px;
  height: 56px;
  border-radius: 12px;
  background: #ecf5ff;
  color: #409eff;
  display: flex;
  align-items: center;
  justify-content: center;
  margin-bottom: 12px;
}

.tool-name {
  font-size: 16px;
  font-weight: 600;
  margin-bottom: 6px;
}

.tool-desc {
  color: #909399;
  font-size: 13px;
  line-height: 1.5;
}
</style>