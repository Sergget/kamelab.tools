<template>
  <div>
    <div class="page-head">
      <el-button link @click="$router.push('/')" :icon="ArrowLeft">返回</el-button>
      <h2 class="page-title">文档转换</h2>
    </div>

    <!-- 步骤 1：上传 -->
    <div class="card">
      <div class="card-title"><el-icon><Upload /></el-icon>1. 上传文件</div>
      <el-upload
        drag
        :auto-upload="true"
        :http-request="doUpload"
        :show-file-list="false"
        :disabled="uploading"
        :accept="acceptExt"
      >
        <el-icon class="el-icon--upload"><UploadFilled /></el-icon>
        <div class="el-upload__text">将文件拖到此处，或 <em>点击上传</em></div>
        <template #tip>
          <div class="el-upload__tip muted">
            支持 office 文档 / 图片 / PDF 等，单个文件不超过 50MB；图片与 PDF 支持预览后裁剪识别
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
        <el-tag size="large" :type="ocrStatusTag.type">{{ ocrStatusTag.text }}</el-tag>
      </div>
    </div>

    <!-- 步骤 2：转换设置 -->
    <div v-if="fileInfo" class="card">
      <div class="card-title"><el-icon><Setting /></el-icon>2. 转换设置</div>

      <div class="set-row">
        <div class="set-label">输出格式</div>
        <el-radio-group v-model="outputFormat">
          <el-radio value="md">Markdown (.md)</el-radio>
          <el-radio value="txt">纯文本 (.txt)</el-radio>
          <el-radio value="docx" :disabled="isDocxSource">Word (.docx)</el-radio>
        </el-radio-group>
        <div v-if="isDocxSource" class="muted">源文件本身是 .docx，再转 docx 没有意义，请使用原文件</div>
      </div>

      <!-- 区域裁剪：图片与 PDF 提供可视化预览-框选，其余格式提示不支持 -->
      <div class="set-row">
        <div class="set-label">区域裁剪</div>

        <div v-if="isImage || isPdf" class="crop-area">
          <div v-if="isPdf && pdfNumPages > 1" class="pdf-nav">
            <el-button
              size="small"
              :disabled="pdfCurrentPage <= 1"
              @click="goToPdfPage(pdfCurrentPage - 1)"
            >
              <el-icon><ArrowLeft /></el-icon>上一页
            </el-button>
            <span class="muted">
              第
              <el-input-number
                v-model="pdfPageInputVal"
                :min="1"
                :max="pdfNumPages"
                size="small"
                style="width: 90px"
                @change="onPdfPageInput"
              />
              / {{ pdfNumPages }} 页
            </span>
            <el-button
              size="small"
              :disabled="pdfCurrentPage >= pdfNumPages"
              @click="goToPdfPage(pdfCurrentPage + 1)"
            >
              下一页<el-icon><ArrowRight /></el-icon>
            </el-button>
          </div>
          <div v-if="isPdf && pdfNumPages > 1" class="muted pdf-note">
            裁剪框会按同一比例应用到所有页面。
          </div>

          <div ref="cropStage" class="crop-stage"></div>

          <div class="crop-tip">
            <el-checkbox v-model="cropEnabled" style="margin-right: 12px">启用裁剪</el-checkbox>
            <el-button size="small" @click="resetCropBox">重置裁剪框</el-button>
            <span class="muted crop-meta">
              裁剪比例 x={{ crop.x.toFixed(4) }} y={{ crop.y.toFixed(4) }} 宽={{ crop.width.toFixed(4) }} 高={{ crop.height.toFixed(4) }}
            </span>
          </div>
          <div v-if="isOcrNodeDown" class="crop-warn">
            OCR 节点离线，将降级为本地 OCR 识别（首次加载模型较慢，扫描件转换耗时较长）
          </div>
        </div>

        <div v-else class="muted">该格式不支持区域裁剪，将转换整份文件</div>
      </div>

      <div style="display: flex; gap: 12px; margin-top: 8px">
        <el-button type="primary" size="large" :loading="converting" @click="doConvert">
          <el-icon style="margin-right: 6px"><MagicStick /></el-icon>
          开始转换
        </el-button>
        <el-button size="large" @click="reset">重新上传</el-button>
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

      <pre v-if="result.content" class="result-pre">{{ result.content }}</pre>
      <el-result
        v-else
        icon="success"
        title="已生成 Word 文档"
        :sub-title="`引擎：${result.docx_engine || 'python-docx-fallback'}，点击下方按钮下载`"
      />

      <div class="result-actions">
        <el-button type="primary" size="large" @click="download">
          <el-icon style="margin-right: 6px"><Download /></el-icon>
          下载文件（{{ result.download_name }}）
        </el-button>
        <el-button v-if="result.content" size="large" @click="copyText">
          <el-icon style="margin-right: 6px"><CopyDocument /></el-icon>
          复制文本
        </el-button>
        <el-button size="large" @click="reset">转换下一个</el-button>
      </div>
    </div>
  </div>
</template>

<script setup>
import { computed, nextTick, onMounted, onUnmounted, reactive, ref } from 'vue'
import {
  ArrowLeft, ArrowRight, CopyDocument, Document, Download, MagicStick, Setting, Upload, UploadFilled,
} from '@element-plus/icons-vue'
import { ElMessage } from 'element-plus'
import Cropper from 'cropperjs'
import 'cropperjs/dist/cropper.min.css'
import * as pdfjsLib from 'pdfjs-dist'
import pdfWorkerUrl from 'pdfjs-dist/build/pdf.worker.min.js?url'
import { convertDocument, docConvertDownloadUrl, getDocConvertHealth } from '../api'

pdfjsLib.GlobalWorkerOptions.workerSrc = pdfWorkerUrl

const IMAGE_EXTS = ['.png', '.jpg', '.jpeg', '.bmp', '.tif', '.tiff', '.webp']
const acceptExt = '.png,.jpg,.jpeg,.bmp,.tif,.tiff,.webp,.pdf,.docx,.xlsx,.pptx,.txt,.csv,.md,.html,.htm,.epub,.odp,.ods,.odt,.rtf,.xml,.json,.zip'

const uploading = ref(false)
const uploadError = ref('')
const fileInfo = ref(null)
const objectUrl = ref('')
const outputFormat = ref('md')
const converting = ref(false)
const result = ref(null)
const ocrNodeDown = ref(false)
const cropStage = ref(null)

const crop = reactive({ enabled: false, x: 0, y: 0, width: 1, height: 1 })
const pdfNumPages = ref(1)
const pdfCurrentPage = ref(1)
const pdfPageInputVal = ref(1)

let cropper = null
let currentRatio = null
let pdfDoc = null
let pdfRenderToken = 0
let cropSessionToken = 0

const cropEnabled = computed({
  get: () => crop.enabled,
  set: (v) => {
    crop.enabled = v
  },
})

const isImage = computed(() => {
  const ext = fileInfo.value?.ext || ''
  return IMAGE_EXTS.includes(ext)
})
const isPdf = computed(() => fileInfo.value?.ext === '.pdf')
const isDocxSource = computed(() => fileInfo.value?.ext === '.docx')
const isOcrNodeDown = computed(() => ocrNodeDown.value)

const ocrStatusTag = computed(() => {
  if (isImage.value || isPdf.value) {
    return ocrNodeDown.value
      ? { type: 'warning', text: 'OCR 节点离线（将用本地 OCR 降级）' }
      : { type: 'success', text: 'OCR 节点在线' }
  }
  return { type: 'info', text: '本文件走本地转换' }
})

const ROUTE_LABELS = {
  local: '本地转换',
  local_ocr: '本地 OCR',
  ocr_node: 'OCR 节点',
}

const resultChips = computed(() => {
  if (!result.value) return []
  const r = result.value
  const chips = [
    { text: `格式：${r.output_format.toUpperCase()}` },
    { text: `引擎：${r.engine}` },
    { text: `路由：${ROUTE_LABELS[r.routed_to] || r.routed_to}` },
    { text: `耗时：${r.elapsed_ms}ms` },
  ]
  if (r.pages) chips.push({ text: `页数：${r.pages}` })
  if (r.crop_applied) chips.push({ text: '已按区域裁剪' })
  if (r.crop_ignored) chips.push({ text: r.crop_ignored })
  if (r.layout_reconstructed) chips.push({ text: '已做版面重建' })
  return chips
})

onMounted(async () => {
  try {
    const health = await getDocConvertHealth()
    ocrNodeDown.value = health.ocr_status !== 'UP'
  } catch {
    ocrNodeDown.value = true
  }
})

onUnmounted(() => {
  clearCropStage()
  if (objectUrl.value) {
    URL.revokeObjectURL(objectUrl.value)
    objectUrl.value = ''
  }
})

async function doUpload({ file }) {
  uploading.value = true
  uploadError.value = ''
  result.value = null
  try {
    const ext = (file.name.match(/\.[^.]+$/) || [''])[0].toLowerCase()
    if (!ext) throw new Error('文件缺少扩展名')
    if (file.size > 50 * 1024 * 1024) throw new Error('文件超过 50MB 大小限制')
    fileInfo.value = { name: file.name, ext, raw: file, size: file.size }
    if (objectUrl.value) URL.revokeObjectURL(objectUrl.value)
    objectUrl.value = URL.createObjectURL(file)
    outputFormat.value = 'md'
    resetCrop()
    await nextTick()
    await mountCropPreview()
    ElMessage.success(`上传成功：${file.name}`)
  } catch (e) {
    uploadError.value = e.message
  } finally {
    uploading.value = false
  }
}

// ---- 裁剪预览（移植自 puremark-converter：图片/PDF 均走预览 → 框选 → 识别）----
async function mountCropPreview() {
  clearCropStage()
  const myToken = cropSessionToken
  if (!cropStage.value) return
  try {
    if (isPdf.value) {
      await mountPdfCropper(fileInfo.value.raw, myToken)
    } else if (isImage.value) {
      mountImageCropper(objectUrl.value, myToken)
    }
  } catch (e) {
    console.warn('裁剪界面初始化失败:', e)
    crop.enabled = false
    ElMessage.warning('裁剪预览初始化失败，可取消启用裁剪直接转换全文')
  }
}

function mountImageCropper(src, myToken) {
  crop.enabled = true
  const img = document.createElement('img')
  img.src = src
  img.className = 'crop-img'
  cropStage.value.appendChild(img)
  img.addEventListener('load', () => {
    if (myToken !== cropSessionToken) return
    cropper = new Cropper(img, {
      viewMode: 1,
      autoCropArea: 0.8,
      background: false,
      movable: true,
      zoomable: true,
      crop: updateCropRatio,
    })
  })
}

async function mountPdfCropper(file, myToken) {
  crop.enabled = true
  const buf = await file.arrayBuffer()
  if (myToken !== cropSessionToken) return
  pdfDoc = await pdfjsLib.getDocument({ data: buf }).promise
  if (myToken !== cropSessionToken) {
    try {
      pdfDoc.destroy()
    } catch { /* ignore */ }
    return
  }
  pdfNumPages.value = pdfDoc.numPages
  pdfCurrentPage.value = 1
  pdfPageInputVal.value = 1
  await renderPdfPage(1, myToken)
}

async function renderPdfPage(pageNum, myToken) {
  pageNum = Math.min(Math.max(1, pageNum), pdfNumPages.value)
  pdfCurrentPage.value = pageNum
  pdfPageInputVal.value = pageNum
  const myRenderToken = ++pdfRenderToken

  const prevRatio = currentRatio

  const page = await pdfDoc.getPage(pageNum)
  if (myToken !== cropSessionToken || myRenderToken !== pdfRenderToken) return
  const viewport = page.getViewport({ scale: 1.8 })
  const canvas = document.createElement('canvas')
  canvas.width = viewport.width
  canvas.height = viewport.height
  await page.render({ canvasContext: canvas.getContext('2d'), viewport }).promise
  if (myToken !== cropSessionToken || myRenderToken !== pdfRenderToken) return

  if (cropper) {
    cropper.destroy()
    cropper = null
  }
  const stage = cropStage.value
  if (!stage) return
  stage.querySelectorAll('img').forEach((el) => el.remove())

  const img = document.createElement('img')
  img.src = canvas.toDataURL('image/png')
  img.className = 'crop-img'
  stage.appendChild(img)
  img.addEventListener('load', () => {
    if (myToken !== cropSessionToken || myRenderToken !== pdfRenderToken) return
    cropper = new Cropper(img, {
      viewMode: 1,
      autoCropArea: 0.8,
      background: false,
      movable: true,
      zoomable: true,
      crop: updateCropRatio,
      ready() {
        if (prevRatio) {
          const imgData = cropper.getImageData()
          cropper.setData({
            x: prevRatio.x * imgData.naturalWidth,
            y: prevRatio.y * imgData.naturalHeight,
            width: prevRatio.width * imgData.naturalWidth,
            height: prevRatio.height * imgData.naturalHeight,
          })
        }
        updateCropRatio()
      },
    })
  })
}

function goToPdfPage(pageNum) {
  if (!pdfDoc) return
  pageNum = Math.min(Math.max(1, pageNum), pdfNumPages.value)
  if (pageNum === pdfCurrentPage.value) return
  renderPdfPage(pageNum, cropSessionToken)
}

function onPdfPageInput(val) {
  goToPdfPage(val || 1)
}

function updateCropRatio() {
  if (!cropper) return
  const data = cropper.getData(true)
  const img = cropper.getImageData()
  const ratio = {
    x: +(data.x / img.naturalWidth).toFixed(4),
    y: +(data.y / img.naturalHeight).toFixed(4),
    width: +(data.width / img.naturalWidth).toFixed(4),
    height: +(data.height / img.naturalHeight).toFixed(4),
  }
  currentRatio = ratio
  crop.x = ratio.x
  crop.y = ratio.y
  crop.width = ratio.width
  crop.height = ratio.height
}

function resetCropBox() {
  if (cropper) {
    cropper.reset()
    updateCropRatio()
  }
}

function clearCropStage() {
  cropSessionToken++
  if (cropper) {
    cropper.destroy()
    cropper = null
  }
  if (pdfDoc) {
    try {
      pdfDoc.destroy()
    } catch { /* ignore */ }
    pdfDoc = null
  }
  pdfNumPages.value = 1
  pdfCurrentPage.value = 1
  pdfPageInputVal.value = 1
  pdfRenderToken++
  currentRatio = null
  if (cropStage.value) cropStage.value.innerHTML = ''
}

function resetCrop() {
  crop.enabled = false
  crop.x = 0
  crop.y = 0
  crop.width = 1
  crop.height = 1
}

async function doConvert() {
  if (!fileInfo.value) return
  converting.value = true
  try {
    const options = { output_format: outputFormat.value }
    if (crop.enabled && crop.width > 0 && crop.height > 0) {
      options.crop = JSON.stringify({
        unit: 'ratio',
        x: round(crop.x),
        y: round(crop.y),
        width: round(crop.width),
        height: round(crop.height),
      })
    }
    result.value = await convertDocument(fileInfo.value.raw, options)
    ElMessage.success('转换完成')
  } catch (e) {
    ElMessage.error(e.message)
  } finally {
    converting.value = false
  }
}

function round(v) {
  return Math.round(v * 10000) / 10000
}

function download() {
  if (!result.value) return
  window.open(docConvertDownloadUrl(result.value.job_id), '_blank')
}

async function copyText() {
  if (!result.value?.content) return
  try {
    await navigator.clipboard.writeText(result.value.content)
    ElMessage.success('已复制到剪贴板')
  } catch {
    ElMessage.warning('复制失败，请手动选择文本复制')
  }
}

function reset() {
  fileInfo.value = null
  result.value = null
  uploading.value = false
  uploadError.value = ''
  clearCropStage()
  if (objectUrl.value) {
    URL.revokeObjectURL(objectUrl.value)
    objectUrl.value = ''
  }
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

.set-row {
  display: flex;
  align-items: flex-start;
  gap: 16px;
  margin-bottom: 20px;
}

.set-label {
  width: 90px;
  flex-shrink: 0;
  color: #606266;
  font-weight: 600;
  padding-top: 8px;
}

.crop-stage {
  position: relative;
  display: inline-block;
  max-width: 100%;
}

.crop-stage :deep(.crop-img) {
  display: block;
  max-width: 100%;
  max-height: 60vh;
}

.pdf-nav {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-bottom: 12px;
  flex-wrap: wrap;
}

.pdf-note {
  margin-bottom: 10px;
}

.crop-tip {
  margin-top: 12px;
  display: flex;
  align-items: center;
  gap: 12px;
  flex-wrap: wrap;
}

.crop-meta {
  font-family: Consolas, 'Courier New', monospace;
  font-size: 12px;
}

.crop-warn {
  margin-top: 8px;
  color: #e6a23c;
  font-size: 13px;
}

.result-meta {
  display: flex;
  gap: 8px;
  flex-wrap: wrap;
  margin-bottom: 14px;
}

.result-pre {
  font-family: Consolas, 'Courier New', monospace;
  white-space: pre-wrap;
  word-break: break-word;
  background: #f5f7fa;
  border: 1px solid #e4e7ed;
  border-radius: 6px;
  padding: 16px;
  max-height: 55vh;
  overflow: auto;
  font-size: 13px;
  line-height: 1.6;
  margin: 0;
}

.result-actions {
  display: flex;
  gap: 12px;
  margin-top: 16px;
  flex-wrap: wrap;
}
</style>
