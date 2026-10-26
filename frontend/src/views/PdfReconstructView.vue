<template>
  <div>
    <div class="page-head">
      <el-button link @click="$router.push('/')" :icon="ArrowLeft">返回</el-button>
      <h2 class="page-title">PDF 高保真转 Word</h2>
    </div>

    <el-alert
      v-if="kernelDown"
      title="转换内核未就绪"
      :description="health.detail || '后端未安装 kame-officetools-core，本工具暂时不可用'"
      type="error"
      show-icon
      :closable="false"
      style="margin-bottom: 16px"
    />

    <!-- 步骤 1：上传 -->
    <div class="card">
      <div class="card-title"><el-icon><Upload /></el-icon>1. 上传 PDF</div>
      <el-upload
        drag
        :auto-upload="true"
        :http-request="doUpload"
        :show-file-list="false"
        :disabled="uploading || converting"
        accept=".pdf"
      >
        <el-icon class="el-icon--upload"><UploadFilled /></el-icon>
        <div class="el-upload__text">将 PDF 拖到此处，或 <em>点击选择</em></div>
        <template #tip>
          <div class="el-upload__tip muted">
            单个 PDF 不超过 {{ maxMb }}MB。数字版直取文字层（秒级）；扫描件自动走 OCR，耗时较长。
          </div>
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
        <el-tag type="success" size="large">{{ fileInfo.name }}</el-tag>
        <el-tag size="large" type="info">{{ formatSize(fileInfo.size) }}</el-tag>
      </div>
    </div>

    <!-- 步骤 2：转换 -->
    <div v-if="fileInfo" class="card">
      <div class="card-title"><el-icon><Setting /></el-icon>2. 开始转换</div>

      <div class="muted">
        输出为 .docx。版面还原由内核按行距与标点规则恢复段落，表格与图片不保证保留。
      </div>

      <div class="action-row">
        <el-button
          type="primary"
          size="large"
          :loading="converting"
          :disabled="kernelDown"
          @click="doConvert"
        >
          <el-icon style="margin-right: 6px"><MagicStick /></el-icon>
          开始转换
        </el-button>
        <el-button size="large" :disabled="converting" @click="reset">重新上传</el-button>
      </div>
    </div>

    <!-- 步骤 3：结果 -->
    <div v-if="result" class="card">
      <div class="card-title"><el-icon><Document /></el-icon>3. 转换结果</div>

      <div class="result-meta">
        <el-tag v-for="chip in resultChips" :key="chip.text" size="small" effect="plain">
          {{ chip.text }}
        </el-tag>
      </div>

      <el-result
        icon="success"
        title="已生成 Word 文档"
        :sub-title="`${result.download_name}，点击下方按钮下载`"
      />

      <div class="action-row">
        <el-button type="primary" size="large" @click="download">
          <el-icon style="margin-right: 6px"><Download /></el-icon>
          下载文件（{{ result.download_name }}）
        </el-button>
        <el-button size="large" @click="reset">转换下一个</el-button>
      </div>
    </div>
  </div>
</template>

<script setup>
import { computed, onMounted, ref } from 'vue'
import {
  ArrowLeft, Document, Download, MagicStick, Setting, Upload, UploadFilled,
} from '@element-plus/icons-vue'
import { ElMessage } from 'element-plus'
import {
  convertPdfToDocx, getPdfReconstructHealth, pdfReconstructDownloadUrl,
} from '../api'

const uploading = ref(false)
const uploadError = ref('')
const fileInfo = ref(null)
const converting = ref(false)
const result = ref(null)
const kernelDown = ref(false)
const health = ref({})

const maxMb = computed(() => health.value.max_file_size_mb || 50)

const PDF_TYPE_LABELS = {
  digital: '数字版（直接取文字层）',
  scanned: '扫描件（已走 OCR）',
}

const pdfTypeLabel = computed(() => PDF_TYPE_LABELS[result.value?.pdf_type] || '')

const resultChips = computed(() => {
  if (!result.value) return []
  const r = result.value
  const chips = [{ text: pdfTypeLabel.value || '类型未知' }]
  chips.push({ text: `字符数：${r.chars}` })
  chips.push({ text: `耗时：${r.elapsed_ms}ms` })
  if (r.engine) chips.push({ text: `引擎：${r.engine}` })
  if (r.kernel_version) chips.push({ text: `内核：${r.kernel_version}` })
  return chips
})

onMounted(async () => {
  try {
    const data = await getPdfReconstructHealth()
    health.value = data || {}
    kernelDown.value = data?.status !== 'UP'
  } catch {
    // 探活失败不阻断上传，真正转换时会给出后端错误
    kernelDown.value = false
  }
})

function formatSize(bytes) {
  if (!bytes && bytes !== 0) return ''
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`
  return `${(bytes / 1024 / 1024).toFixed(1)} MB`
}

async function doUpload({ file }) {
  uploading.value = true
  uploadError.value = ''
  result.value = null
  try {
    const ext = (file.name.match(/\.[^.]+$/) || [''])[0].toLowerCase()
    if (ext !== '.pdf') throw new Error('仅支持 PDF 文件')
    if (file.size > maxMb.value * 1024 * 1024) {
      throw new Error(`文件超过 ${maxMb.value}MB 大小限制`)
    }
    fileInfo.value = { name: file.name, raw: file, size: file.size }
    ElMessage.success(`已选择：${file.name}`)
  } catch (e) {
    fileInfo.value = null
    uploadError.value = e.message
  } finally {
    uploading.value = false
  }
}

async function doConvert() {
  if (!fileInfo.value) return
  converting.value = true
  uploadError.value = ''
  try {
    result.value = await convertPdfToDocx(fileInfo.value.raw)
    ElMessage.success('转换完成')
  } catch (e) {
    uploadError.value = e.message
    ElMessage.error(e.message)
  } finally {
    converting.value = false
  }
}

function download() {
  if (!result.value?.job_id) return
  window.open(pdfReconstructDownloadUrl(result.value.job_id), '_blank')
}

function reset() {
  fileInfo.value = null
  result.value = null
  uploadError.value = ''
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
  font-size: 20px;
}

.file-info {
  margin-top: 12px;
  display: flex;
  gap: 8px;
  flex-wrap: wrap;
}

.action-row {
  display: flex;
  gap: 12px;
  margin-top: 16px;
  flex-wrap: wrap;
}

.result-meta {
  display: flex;
  gap: 8px;
  flex-wrap: wrap;
  margin-bottom: 8px;
}
</style>
