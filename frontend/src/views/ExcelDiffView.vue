<template>
  <div>
    <div class="page-head">
      <el-button link @click="$router.push('/')" :icon="ArrowLeft">返回</el-button>
      <h2 class="page-title">Excel 表格比对</h2>
    </div>

    <!-- 步骤 1：上传两个表格 -->
    <div class="card">
      <div class="card-title"><el-icon><Upload /></el-icon>1. 上传两个 Excel 表格</div>
      <el-row :gutter="16">
        <el-col :xs="24" :sm="12">
          <div class="upload-label">基准表 <el-tag size="small" type="info">以它为准</el-tag></div>
          <el-upload
            drag
            :auto-upload="true"
            :http-request="doUploadBase"
            :show-file-list="false"
            :disabled="uploading"
            accept=".xlsx,.xls"
          >
            <el-icon class="el-icon--upload"><UploadFilled /></el-icon>
            <div class="el-upload__text">将文件拖到此处，或 <em>点击上传</em></div>
          </el-upload>
          <div v-if="baseInfo" class="file-info">
            <el-tag type="success" size="large">{{ baseInfo.file_name }}</el-tag>
            <span class="muted">{{ sheetsSummary(baseInfo) }}</span>
          </div>
        </el-col>
        <el-col :xs="24" :sm="12">
          <div class="upload-label">比对对象 <el-tag size="small" type="info">与之比对</el-tag></div>
          <el-upload
            drag
            :auto-upload="true"
            :http-request="doUploadCompare"
            :show-file-list="false"
            :disabled="uploading"
            accept=".xlsx,.xls"
          >
            <el-icon class="el-icon--upload"><UploadFilled /></el-icon>
            <div class="el-upload__text">将文件拖到此处，或 <em>点击上传</em></div>
          </el-upload>
          <div v-if="compareInfo" class="file-info">
            <el-tag type="success" size="large">{{ compareInfo.file_name }}</el-tag>
            <span class="muted">{{ sheetsSummary(compareInfo) }}</span>
          </div>
        </el-col>
      </el-row>
      <div class="el-upload__tip muted" style="margin-top: 8px">支持 .xlsx / .xls，单个文件不超过 100MB；两表先各自上传后再配置比对</div>
      <el-alert v-if="uploadError" :title="uploadError" type="error" show-icon :closable="false" style="margin-top: 12px" />
    </div>

    <!-- 步骤 2：比对配置 -->
    <div v-if="baseFileId && compareFileId" class="card">
      <div class="card-title"><el-icon><Setting /></el-icon>2. 比对配置</div>
      <el-form label-width="120px" label-position="left">
        <el-row :gutter="16">
          <el-col :xs="24" :sm="12">
            <el-form-item label="基准表 sheet" required>
              <el-select v-model="config.base_sheet" placeholder="选择 sheet" style="width: 100%" @change="onBaseSheetChange">
                <el-option v-for="s in baseInfo.sheets" :key="s.name" :label="`${s.name}（${s.rows} 行）`" :value="s.name" />
              </el-select>
            </el-form-item>
          </el-col>
          <el-col :xs="24" :sm="12">
            <el-form-item label="比对表 sheet" required>
              <el-select v-model="config.compare_sheet" placeholder="选择 sheet" style="width: 100%" @change="onCompareSheetChange">
                <el-option v-for="s in compareInfo.sheets" :key="s.name" :label="`${s.name}（${s.rows} 行）`" :value="s.name" />
              </el-select>
            </el-form-item>
          </el-col>
          <el-col :xs="24" :sm="12">
            <el-form-item label="基准表键列" required>
              <el-select v-model="config.base_key_column" placeholder="选择唯一标识列" style="width: 100%" clearable>
                <el-option v-for="c in baseColumns" :key="c" :label="c" :value="c" />
              </el-select>
              <div class="muted" style="line-height: 1.4">两表按该列的值匹配行，值需唯一</div>
            </el-form-item>
          </el-col>
          <el-col :xs="24" :sm="12">
            <el-form-item label="比对表键列" required>
              <el-select v-model="config.compare_key_column" placeholder="选择唯一标识列" style="width: 100%" clearable>
                <el-option v-for="c in compareColumns" :key="c" :label="c" :value="c" />
              </el-select>
              <div class="muted" style="line-height: 1.4">可与基准表键列同名或不同名</div>
            </el-form-item>
          </el-col>
        </el-row>

        <el-form-item label="值列">
          <el-checkbox v-model="keepAllValue" style="margin-right: 16px">全部共有列</el-checkbox>
          <el-checkbox-group v-model="config.value_columns" :disabled="keepAllValue">
            <el-checkbox v-for="c in commonColumns" :key="c" :label="c" :value="c">{{ c }}</el-checkbox>
          </el-checkbox-group>
          <div v-if="!keepAllValue && !config.value_columns.length" class="muted" style="margin-top: 4px">未选择任何列，比对将只统计行数差异（键匹配情况）</div>
        </el-form-item>

        <el-form-item label="输出方式">
          <el-radio-group v-model="config.output_mode">
            <el-radio value="diff">输出独立差异明细表</el-radio>
            <el-radio value="highlight">在表格中高亮差异</el-radio>
          </el-radio-group>
          <div class="muted" style="margin-left: 12px; line-height: 1.4">
            {{ config.output_mode === 'diff' ? '生成包含差异明细与统计的 xlsx 文件' : '在原表副本中高亮：黄色=值差异（带批注），橙/绿=仅一侧有，另一侧独有行追加在末尾' }}
          </div>
        </el-form-item>

        <el-form-item v-if="config.output_mode === 'highlight'" label="高亮底版">
          <el-radio-group v-model="config.highlight_target">
            <el-radio value="base">基准表</el-radio>
            <el-radio value="compare">比对表</el-radio>
          </el-radio-group>
        </el-form-item>
      </el-form>

      <div style="display: flex; gap: 12px; margin-top: 8px">
        <el-button type="primary" size="large" :loading="comparing" @click="doCompare">开始比对</el-button>
        <el-button size="large" @click="reset">重新上传</el-button>
      </div>
    </div>

    <!-- 步骤 3：结果 -->
    <div v-if="result" class="card">
      <div class="card-title"><el-icon><Download /></el-icon>3. 比对结果</div>
      <el-alert
        v-if="result.skipped_columns.length"
        :title="`以下列因比对表缺少同名表头而跳过：${result.skipped_columns.join('、')}`"
        type="warning"
        show-icon
        :closable="false"
        style="margin-bottom: 14px"
      />

      <el-descriptions :column="4" border size="small" class="stats-desc">
        <el-descriptions-item label="基准表行数">{{ result.stats.base_rows }}</el-descriptions-item>
        <el-descriptions-item label="比对表行数">{{ result.stats.compare_rows }}</el-descriptions-item>
        <el-descriptions-item label="键匹配数">{{ result.stats.matched }}</el-descriptions-item>
        <el-descriptions-item label="完全一致">{{ result.stats.identical }}</el-descriptions-item>
        <el-descriptions-item label="值差异行数">
          <el-tag :type="result.stats.changed_rows ? 'danger' : 'success'">{{ result.stats.changed_rows }}</el-tag>
        </el-descriptions-item>
        <el-descriptions-item label="仅基准有">
          <el-tag type="warning">{{ result.stats.only_base }}</el-tag>
        </el-descriptions-item>
        <el-descriptions-item label="仅比对有">
          <el-tag type="success">{{ result.stats.only_compare }}</el-tag>
        </el-descriptions-item>
        <el-descriptions-item label="差异总数">{{ result.preview_total }}</el-descriptions-item>
      </el-descriptions>

      <div style="margin: 16px 0 10px">
        <el-button type="primary" size="large" @click="download">
          <el-icon style="margin-right: 6px"><Download /></el-icon>
          下载{{ result.output_mode === 'diff' ? '差异明细表' : '高亮文件' }}（{{ result.download_name }}）
        </el-button>
      </div>

      <template v-if="result.preview.length">
        <div class="muted" style="margin-bottom: 8px">差异预览（前 {{ result.preview.length }} 条，完整结果见下载文件）</div>
        <el-table :data="result.preview" border size="small" max-height="420" stripe>
          <el-table-column label="差异类型" width="110">
            <template #default="{ row }">
              <el-tag :type="typeTag(row.diff_type)" size="small">{{ typeLabel(row.diff_type) }}</el-tag>
            </template>
          </el-table-column>
          <el-table-column prop="key_value" label="键值" min-width="120" show-overflow-tooltip />
          <el-table-column prop="column" label="涉及列" min-width="120" show-overflow-tooltip />
          <el-table-column prop="base_value" label="基准值" min-width="180" show-overflow-tooltip />
          <el-table-column prop="compare_value" label="比对值" min-width="180" show-overflow-tooltip />
        </el-table>
      </template>
      <el-result v-else icon="success" title="两个表格完全一致，未发现差异" />
    </div>
  </div>
</template>

<script setup>
import { computed, reactive, ref } from 'vue'
import { ArrowLeft, Download, Setting, Upload, UploadFilled } from '@element-plus/icons-vue'
import { ElMessage } from 'element-plus'
import { compareExcel, excelDiffDownloadUrl, uploadExcelDiff } from '../api'

const uploading = ref(false)
const uploadError = ref('')
const baseInfo = ref(null)
const compareInfo = ref(null)
const baseFileId = ref('')
const compareFileId = ref('')
const comparing = ref(false)
const result = ref(null)

const config = reactive({
  base_sheet: '',
  compare_sheet: '',
  base_key_column: '',
  compare_key_column: '',
  value_columns: [],
  output_mode: 'diff',
  highlight_target: 'base',
})
const keepAllValue = ref(true)

const sheetsSummary = (info) => `共 ${info.sheets.length} 个 sheet：${info.sheets.map((s) => `${s.name}(${s.rows} 行)`).join('、')}`

const baseColumns = computed(() => {
  const s = baseInfo.value?.sheets.find((x) => x.name === config.base_sheet)
  return s ? [...(s.headers || [])] : []
})

const compareColumns = computed(() => {
  const s = compareInfo.value?.sheets.find((x) => x.name === config.compare_sheet)
  return s ? [...(s.headers || [])] : []
})

// 两表共有的非键列表头，作为值列候选项
const commonColumns = computed(() => {
  const b = new Set(baseColumns.value)
  return compareColumns.value.filter((c) => b.has(c) && c !== config.base_key_column && c !== config.compare_key_column)
})

const typeLabel = (t) => ({ changed: '值差异', only_base: '基准独有', only_compare: '比对独有' }[t] || t)
const typeTag = (t) => ({ changed: 'danger', only_base: 'warning', only_compare: 'success' }[t] || 'info')

function doUploadBase({ file }) {
  return doUpload(file, 'base')
}

function doUploadCompare({ file }) {
  return doUpload(file, 'compare')
}

async function doUpload(file, side) {
  uploading.value = true
  uploadError.value = ''
  try {
    const data = await uploadExcelDiff(file)
    if (side === 'base') {
      baseInfo.value = data
      baseFileId.value = data.file_id
      config.base_sheet = data.sheets[0]?.name || ''
      config.base_key_column = ''
    } else {
      compareInfo.value = data
      compareFileId.value = data.file_id
      config.compare_sheet = data.sheets[0]?.name || ''
      config.compare_key_column = ''
    }
    result.value = null
    ElMessage.success(`上传成功：${data.file_name}`)
  } catch (e) {
    uploadError.value = e.message
  } finally {
    uploading.value = false
  }
}

function onBaseSheetChange() {
  config.base_key_column = ''
}
function onCompareSheetChange() {
  config.compare_key_column = ''
}

async function doCompare() {
  if (!config.base_sheet) return ElMessage.warning('请选择基准表 sheet')
  if (!config.compare_sheet) return ElMessage.warning('请选择比对表 sheet')
  if (!config.base_key_column) return ElMessage.warning('请选择基准表键列')
  if (!config.compare_key_column) return ElMessage.warning('请选择比对表键列')
  if (!keepAllValue.value && !config.value_columns.length) return ElMessage.warning('请至少选择一个值列，或勾选"全部共有列"')

  comparing.value = true
  try {
    const payload = {
      ...config,
      value_columns: keepAllValue.value ? null : [...config.value_columns],
    }
    result.value = await compareExcel(payload)
  } catch (e) {
    ElMessage.error(e.message)
  } finally {
    comparing.value = false
  }
}

function download() {
  if (!result.value) return
  window.open(excelDiffDownloadUrl(result.value.job_id), '_blank')
}

function reset() {
  baseInfo.value = null
  compareInfo.value = null
  baseFileId.value = ''
  compareFileId.value = ''
  result.value = null
  config.base_sheet = ''
  config.compare_sheet = ''
  config.base_key_column = ''
  config.compare_key_column = ''
  config.value_columns = []
  keepAllValue.value = true
}
</script>

<style scoped>
.page-head {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 16px;
}

.page-title {
  margin: 0;
}

.upload-label {
  margin-bottom: 8px;
  display: flex;
  align-items: center;
  gap: 8px;
}

.file-info {
  margin-top: 10px;
  display: flex;
  align-items: center;
  gap: 12px;
}

.stats-desc {
  margin-top: 4px;
}
</style>
