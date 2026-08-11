<template>
  <div>
    <div class="page-head">
      <el-button link @click="$router.push('/')" :icon="ArrowLeft">返回</el-button>
      <h2 class="page-title">Excel 表格拆分</h2>
    </div>

    <!-- 步骤 1：上传 -->
    <div class="card">
      <div class="card-title"><el-icon><Upload /></el-icon>1. 上传 Excel 文件</div>
      <el-upload
        drag
        :auto-upload="true"
        :http-request="doUpload"
        :show-file-list="false"
        :disabled="uploading"
        accept=".xlsx,.xls"
      >
        <el-icon class="el-icon--upload"><UploadFilled /></el-icon>
        <div class="el-upload__text">将文件拖到此处，或 <em>点击上传</em></div>
        <template #tip>
          <div class="el-upload__tip muted">支持 .xlsx / .xls，单个文件不超过 100MB</div>
        </template>
      </el-upload>

      <el-alert
        v-if="uploadError"
        :title="uploadError"
        type="error"
        show-icon
        :closable="false"
        style="margin-top: 12px"
      />

      <div v-if="fileInfo" class="file-info">
        <el-tag type="success" size="large">{{ fileInfo.file_name }}</el-tag>
        <span class="muted">
          共 {{ fileInfo.sheets.length }} 个 sheet：{{ fileInfo.sheets.map((s) => `${s.name}(${s.rows} 行)`).join('、') }}
        </span>
      </div>
    </div>

    <!-- 步骤 2：预览 -->
    <div v-if="fileId" class="card">
      <div class="card-title"><el-icon><View /></el-icon>2. 预览数据</div>
      <el-tabs v-model="activeSheet" @tab-change="changeSheet">
        <el-tab-pane v-for="s in fileInfo.sheets" :key="s.name" :label="`${s.name}（${s.rows} 行）`" :name="s.name" />
      </el-tabs>

      <el-table v-if="preview.rows.length" :data="preview.rows" border size="small" max-height="420" stripe>
        <el-table-column v-for="(h, i) in preview.headers" :key="i" :prop="String(i)" :label="h" min-width="120" show-overflow-tooltip />
      </el-table>
      <el-empty v-else description="没有可预览的内容" :image-size="80" />

      <div class="preview-foot">
        <span class="muted">
          已显示 {{ preview.rows.length }} / {{ preview.total }} 行
          <template v-if="preview.rows.length < preview.total">（当前 sheet 仅预览前 100 行，拆分时使用全部数据）</template>
        </span>
      </div>
    </div>

    <!-- 步骤 3：拆分配置 -->
    <div v-if="fileId" class="card">
      <div class="card-title"><el-icon><Setting /></el-icon>3. 拆分配置</div>
      <el-form label-width="130px" label-position="left">
        <el-form-item label="拆分 sheet" required>
          <el-select v-model="config.sheet" placeholder="选择要拆分的 sheet" style="width: 320px" @change="onSplitSheetChange">
            <el-option v-for="s in fileInfo.sheets" :key="s.name" :label="`${s.name}（${s.rows} 行）`" :value="s.name" />
          </el-select>
          <div class="muted" style="margin-left: 12px">仅拆分所选 sheet 的数据</div>
        </el-form-item>

        <el-form-item label="拆分列" required>
          <el-select v-model="config.split_column" placeholder="选择用于拆分的表头" style="width: 320px">
            <el-option v-for="c in allColumns" :key="c" :label="c" :value="c" />
          </el-select>
          <div class="muted" style="margin-left: 12px">每个唯一值生成一个输出分组</div>
        </el-form-item>

        <el-form-item label="保留列">
          <el-checkbox v-model="keepAll" style="margin-right: 16px">全部保留</el-checkbox>
          <el-checkbox-group v-model="config.keep_columns" :disabled="keepAll">
            <el-checkbox v-for="c in allColumns" :key="c" :label="c" :value="c">{{ c }}</el-checkbox>
          </el-checkbox-group>
        </el-form-item>

        <el-form-item label="输出方式">
          <el-radio-group v-model="config.output_mode">
            <el-radio value="separate">多个文件（打包 zip）</el-radio>
            <el-radio value="workbook">单个工作簿（每个分组一个 sheet）</el-radio>
          </el-radio-group>
        </el-form-item>

        <el-form-item v-if="config.output_mode === 'separate'" label="文件名模板">
          <el-input v-model="config.filename_template" style="width: 320px" />
          <div class="template-tips">
            <template v-for="ph in placeholders" :key="ph.key">
              <el-tag size="small" class="ph-tag" @click="insertPlaceholder(ph.key)">{{ ph.key }}</el-tag>
            </template>
            <div class="muted">点击插入占位符；非法字符（如 / \ : * ?）会被自动替换</div>
          </div>
        </el-form-item>

        <el-form-item v-else label="sheet 标题模板">
          <el-input v-model="config.sheet_title_template" style="width: 320px" placeholder="默认 {value}" />
          <div class="template-tips">
            <el-tag size="small" class="ph-tag" @click="config.sheet_title_template = (config.sheet_title_template || '') + '{value}'">{value}</el-tag>
            <el-tag size="small" class="ph-tag" @click="config.sheet_title_template = (config.sheet_title_template || '') + '{index}'">{index}</el-tag>
            <div class="muted">sheet 标题最长 31 个字符，重复时自动加序号</div>
          </div>
        </el-form-item>
      </el-form>

      <div style="display: flex; gap: 12px; margin-top: 8px">
        <el-button type="primary" size="large" :loading="splitting" @click="doSplit">开始拆分</el-button>
        <el-button size="large" @click="reset">重新上传</el-button>
      </div>
    </div>

    <!-- 步骤 4：结果 -->
    <div v-if="result" class="card">
      <div class="card-title"><el-icon><Download /></el-icon>4. 拆分结果</div>
      <el-result icon="success" :title="`拆分完成，共 ${result.groups.length} 个分组`">
        <template #sub-title>
          <div class="muted">共 {{ result.total_rows }} 行数据</div>
        </template>
        <template #extra>
          <el-button type="primary" size="large" @click="download">
            <el-icon style="margin-right: 6px"><Download /></el-icon>
            {{ result.is_zip ? '下载 zip 压缩包' : '下载文件' }}（{{ result.download_name }}）
          </el-button>
        </template>
      </el-result>
      <el-table :data="result.groups" border size="small" max-height="380">
        <el-table-column type="index" label="#" width="50" />
        <el-table-column prop="key" label="分组值" min-width="140" show-overflow-tooltip />
        <el-table-column prop="sheet_name" label="来源 sheet" min-width="120" />
        <el-table-column prop="file_name" label="输出文件" min-width="200" show-overflow-tooltip />
        <el-table-column prop="rows" label="行数" width="80" />
      </el-table>
    </div>
  </div>
</template>

<script setup>
import { computed, reactive, ref } from 'vue'
import { ArrowLeft, Download, Setting, Upload, UploadFilled, View } from '@element-plus/icons-vue'
import { ElMessage } from 'element-plus'
import { previewSheet, splitDownloadUrl, splitFile, uploadExcel } from '../api'

const uploading = ref(false)
const uploadError = ref('')
const fileInfo = ref(null)
const fileId = ref('')
const activeSheet = ref('')
const preview = reactive({ headers: [], rows: [], total: 0 })

const config = reactive({
  sheet: '',
  split_column: '',
  keep_columns: [],
  output_mode: 'separate',
  filename_template: '{value}',
  sheet_title_template: '',
})
const keepAll = ref(true)
const splitting = ref(false)
const result = ref(null)

const placeholders = [
  { key: '{value}', label: '分组值' },
  { key: '{sheet}', label: '来源 sheet' },
  { key: '{index}', label: '序号(001)' },
  { key: '{date}', label: '日期' },
  { key: '{time}', label: '时间' },
]

const allColumns = computed(() => {
  if (!fileInfo.value) return []
  const s = fileInfo.value.sheets.find((x) => x.name === config.sheet)
  return s ? [...(s.headers || [])] : []
})

function insertPlaceholder(key) {
  config.filename_template = (config.filename_template || '') + key
}

async function doUpload({ file }) {
  uploading.value = true
  uploadError.value = ''
  try {
    const data = await uploadExcel(file)
    fileInfo.value = data
    fileId.value = data.file_id
    activeSheet.value = data.sheets[0]?.name || ''
    config.sheet = data.sheets[0]?.name || ''
    await loadPreview(0)
    ElMessage.success(`上传成功：${data.file_name}`)
  } catch (e) {
    uploadError.value = e.message
  } finally {
    uploading.value = false
  }
}

async function loadPreview(skip = 0) {
  if (!fileId.value || !activeSheet.value) return
  const data = await previewSheet(fileId.value, activeSheet.value, skip, 100)
  preview.headers = data.headers
  preview.rows = data.rows
  preview.total = data.total
}

async function changeSheet() {
  await loadPreview(0)
}

function onSplitSheetChange() {
  config.split_column = ''
  config.keep_columns = []
  keepAll.value = true
}

async function doSplit() {
  if (!config.sheet) {
    ElMessage.warning('请选择要拆分的 sheet')
    return
  }
  if (!config.split_column) {
    ElMessage.warning('请选择拆分列')
    return
  }
  if (!keepAll.value && !config.keep_columns.length) {
    ElMessage.warning('请至少保留一列，或勾选“全部保留”')
    return
  }
  splitting.value = true
  try {
    const payload = { ...config }
    payload.keep_columns = keepAll.value ? null : payload.keep_columns
    payload.sheet_title_template = payload.sheet_title_template || null
    result.value = await splitFile(fileId.value, payload)
  } catch (e) {
    ElMessage.error(e.message)
  } finally {
    splitting.value = false
  }
}

function download() {
  if (!result.value) return
  window.open(splitDownloadUrl(result.value.job_id), '_blank')
}

function reset() {
  fileInfo.value = null
  fileId.value = ''
  result.value = null
  config.sheet = ''
  config.split_column = ''
  config.keep_columns = []
  keepAll.value = true
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

.file-info {
  margin-top: 14px;
  display: flex;
  align-items: center;
  gap: 12px;
}

.preview-foot {
  margin-top: 10px;
}

.template-tips {
  display: flex;
  align-items: center;
  gap: 6px;
  flex-wrap: wrap;
  margin-left: 12px;
}

.ph-tag {
  cursor: pointer;
}
</style>