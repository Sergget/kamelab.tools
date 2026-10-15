<template>
  <div>
    <div class="page-head">
      <el-button link @click="$router.push('/')" :icon="ArrowLeft">返回</el-button>
      <h2 class="page-title">文档汇编</h2>
    </div>

    <!-- 1. 批量上传 -->
    <div class="card">
      <div class="card-title"><el-icon><Upload /></el-icon>1. 批量上传</div>
      <el-upload
        ref="uploadRef"
        v-model:file-list="pendingFiles"
        drag
        multiple
        :auto-upload="false"
        :disabled="uploading"
        accept=".doc,.docx,.docm,.wps,.rtf,.txt"
      >
        <el-icon class="el-icon--upload"><UploadFilled /></el-icon>
        <div class="el-upload__text">将文件拖到此处，或 <em>点击选择多个文件</em></div>
        <template #tip>
          <div class="el-upload__tip muted">
            支持 Word（.doc/.docx/.docm）、WPS（.wps）、RTF、纯文本（.txt），可多选；
            {{ maxFileSizeHint }} 选择的文件先进入待上传列表，点「上传到队列」后统一提交
          </div>
        </template>
      </el-upload>

      <div class="upload-actions">
        <el-button type="primary" :loading="uploading" :disabled="!pendingFiles.length" @click="submitUpload">
          <el-icon style="margin-right: 6px"><Upload /></el-icon>
          上传到队列{{ pendingFiles.length ? `（${pendingFiles.length} 个）` : '' }}
        </el-button>
        <el-button v-if="pendingFiles.length" size="default" @click="clearPending">清空待上传列表</el-button>
      </div>

      <div v-if="pendingFiles.length" class="pending-list muted">
        已选择：{{ pendingFiles.map(f => f.name).join('、') }}
      </div>

      <!-- 被丢弃的文件列表 -->
      <el-alert
        v-if="droppedItems.length"
        type="warning"
        show-icon
        :closable="false"
        :title="`${droppedItems.length} 个文件无法处理被丢弃：`"
        style="margin-top: 12px"
      >
        <ul class="dropped-list">
          <li v-for="(d, i) in droppedItems" :key="i">
            <span class="dropped-name">{{ d.original_name }}</span>
            <span class="muted">—— {{ d.reason }}</span>
          </li>
        </ul>
      </el-alert>
    </div>

    <!-- 2. 待汇编队列 -->
    <div class="card">
      <div class="card-title">
        <el-icon><Files /></el-icon>2. 待汇编队列
        <el-tag v-if="items.length" size="small" round>{{ items.length }} 篇</el-tag>
      </div>

      <div class="queue-toolbar">
        <el-button size="small" @click="sortByFileName">按文件名排序</el-button>
        <el-button size="small" @click="sortByTitle">按识别标题排序</el-button>
        <el-button size="small" @click="reverseQueue">一键倒序</el-button>
        <el-button size="small" type="danger" plain :disabled="!items.length" @click="removeAll">批量移除</el-button>
        <div class="toolbar-right">
          <span class="muted">全部写回源文档</span>
          <el-switch
            v-model="allWriteBack"
            :disabled="!applyToSourceCap"
            @change="onAllWriteBackChange"
          />
          <el-tooltip v-if="!applyToSourceCap" content="服务器不支持写回源文档" placement="top">
            <el-icon class="hint-icon"><WarningFilled /></el-icon>
          </el-tooltip>
        </div>
      </div>

      <div v-if="!items.length" class="muted empty-hint">
        队列为空，请先在上方上传文档。
      </div>

      <div v-else class="queue-list">
        <div
          v-for="(item, index) in items"
          :key="item.file_id"
          class="queue-row"
          draggable="true"
          :class="{ 'row-selected': selectedId === item.file_id, 'row-dragging': dragIndex === index }"
          @dragstart="onRowDragStart(index)"
          @dragover.prevent="onRowDragOver(index)"
          @drop.prevent="onRowDrop"
          @dragend="onRowDragEnd"
        >
          <span class="row-sort-handle"><el-icon><Rank /></el-icon></span>
          <span class="row-seq muted">{{ index + 1 }}</span>
          <el-tag size="small" :type="classTagType(item.classified_as)">{{ classLabel(item.classified_as) }}</el-tag>
          <span class="row-name" :title="item.original_name">{{ item.original_name }}</span>

          <el-input
            v-model="item.title"
            size="small"
            class="row-title"
            placeholder="标题"
            @blur="scheduleSave(item)"
            @keyup.enter="scheduleSave(item)"
          />
          <el-input
            v-model="item.author"
            size="small"
            class="row-author"
            placeholder="作者"
            @blur="scheduleSave(item)"
            @keyup.enter="scheduleSave(item)"
          />

          <el-tag v-if="item.auto_detected" size="small" type="success" effect="plain" class="row-tag">自动识别</el-tag>
          <el-tag v-if="item.source_updated" size="small" type="info" effect="plain" class="row-tag">已写回源文档</el-tag>
          <el-tooltip v-if="item.warnings && item.warnings.length" :content="item.warnings.join('；')" placement="top">
            <el-icon class="warn-icon"><WarningFilled /></el-icon>
          </el-tooltip>
          <el-tag v-if="item.saving" size="small" type="warning" effect="plain">保存中…</el-tag>

          <div class="row-actions">
            <el-button size="small" text type="primary" @click.stop="selectItem(item)">预览</el-button>
            <el-button size="small" text :disabled="index === 0" @click.stop="moveItem(index, -1)">上移</el-button>
            <el-button size="small" text :disabled="index === items.length - 1" @click.stop="moveItem(index, 1)">下移</el-button>
            <el-button size="small" text type="danger" @click.stop="removeItem(item)">删除</el-button>
            <el-checkbox
              v-model="item.applyToSource"
              :disabled="!applyToSourceCap"
              class="write-back"
              title="写回源文档"
              @change="scheduleSave(item)"
            >写回源文档</el-checkbox>
          </div>
        </div>
      </div>
    </div>

    <!-- 3. 预览 -->
    <div v-if="selected" class="card">
      <div class="card-title">
        <el-icon><View /></el-icon>3. 预览
        <el-tag size="small" :type="classTagType(selected.classified_as)">{{ classLabel(selected.classified_as) }}</el-tag>
        <span class="muted preview-file">{{ selected.original_name }}</span>
        <div class="card-actions">
          <el-button size="small" text type="primary" @click="downloadSource(selected)">
            <el-icon style="margin-right: 4px"><Download /></el-icon>下载源文件
          </el-button>
          <el-button size="small" text @click="closePreview">关闭预览</el-button>
        </div>
      </div>

      <!-- 页码导航 -->
      <div class="preview-nav">
        <el-button size="small" :disabled="previewPage <= 1 || !canNav" @click="gotoPage(previewPage - 1)">上一页</el-button>
        <span class="muted">
          第
          <el-input-number
            v-model="previewPageInput"
            :min="1"
            :max="selected.page_count || 1"
            size="small"
            style="width: 90px"
            :disabled="!canNav"
            @change="onPageInput"
          />
          / {{ selected.page_count ?? '页数未知' }} 页
        </span>
        <el-button size="small" :disabled="!canNav || previewPage >= (selected.page_count || 1)" @click="gotoPage(previewPage + 1)">下一页</el-button>
        <el-button v-if="previewState === 'image'" size="small" text @click="loadPreviewText">查看纯文本</el-button>
        <el-button v-else-if="previewState === 'text'" size="small" text @click="loadPreviewImage">查看图片</el-button>
      </div>

      <!-- 预览主体：图片 / 纯文本（降级）/ 错误 -->
      <div v-loading="previewState === 'loading'" class="preview-body">
        <img v-if="previewState === 'image' && previewBlobUrl" :src="previewBlobUrl" class="preview-img" alt="文档预览" />
        <template v-else-if="previewState === 'text'">
          <el-alert
            v-if="previewImageUnavailable"
            :title="previewImageUnavailable"
            type="warning"
            show-icon
            :closable="false"
            style="margin-bottom: 12px"
          />
          <pre class="preview-text">{{ previewText }}</pre>
        </template>
        <el-alert v-else-if="previewState === 'error'" :title="previewError" type="error" show-icon :closable="false" />
        <div v-else-if="previewState === 'none'" class="muted">未选择文件</div>
      </div>

      <!-- 预览面板内编辑（与行内编辑同步） -->
      <div class="preview-meta">
        <div class="set-row">
          <div class="set-label">标题</div>
          <el-input
            v-model="selected.title"
            size="small"
            placeholder="标题"
            @blur="scheduleSave(selected)"
            @keyup.enter="scheduleSave(selected)"
          />
        </div>
        <div class="set-row">
          <div class="set-label">作者</div>
          <el-input
            v-model="selected.author"
            size="small"
            placeholder="作者"
            @blur="scheduleSave(selected)"
            @keyup.enter="scheduleSave(selected)"
          />
        </div>
      </div>
    </div>

    <!-- 4. 汇编设置 -->
    <div class="card">
      <div class="card-title"><el-icon><Setting /></el-icon>4. 汇编设置</div>

      <div class="set-row">
        <div class="set-label">输出格式</div>
        <div>
          <el-radio-group v-model="outputFormat">
            <el-radio value="docx">Word (.docx)</el-radio>
            <el-radio value="doc" :disabled="!outputDocCap">Word 老格式 (.doc)</el-radio>
            <el-radio value="wps" :disabled="!outputWpsCap">WPS 兼容 (.wps)</el-radio>
          </el-radio-group>
          <div class="muted" style="margin-top: 6px">
            <template v-if="!outputDocCap">「.doc」老格式输出依赖服务器 LibreOffice，当前不可用； </template>
            <template v-if="!outputWpsCap">「.wps」为兼容格式输出，服务器当前不可用； </template>
            {{ envHint }}
          </div>
        </div>
      </div>

      <!-- 目录 -->
      <div class="set-row">
        <div class="set-label">目录</div>
        <div>
          <div class="inline-line">
            <el-switch v-model="tocEnabled" />
            <el-radio-group v-model="tocMode" :disabled="!tocEnabled" style="margin-left: 16px">
              <el-radio value="custom">静态目录（custom）</el-radio>
              <el-radio value="field">Word 目录域（field）</el-radio>
            </el-radio-group>
          </div>

          <template v-if="tocEnabled && tocMode === 'custom'">
            <div class="inline-line" style="margin-top: 10px">
              <el-select v-model="tocTemplate" size="small" style="width: 240px" placeholder="选择模板">
                <el-option v-for="t in (formats?.toc_templates || [])" :key="t.value" :label="t.label" :value="t.value" />
              </el-select>
              <el-input v-model="tocTemplate" size="small" style="width: 300px" placeholder="自定义模板，如 &lt;seq&gt;. &lt;title&gt;……&lt;author&gt;" />
            </div>
            <div class="inline-line" style="margin-top: 8px">
              <el-checkbox v-model="includePageNumbers">目录含页码</el-checkbox>
              <span v-if="!tocPageNumCap" class="muted">（服务器当前不支持目录页码）</span>
            </div>
            <div class="toc-example" v-if="tocExample">
              <span class="muted">示例：</span>
              <code>{{ tocExample }}</code>
            </div>
          </template>
          <div v-else-if="tocEnabled && tocMode === 'field'" class="muted" style="margin-top: 6px">
            由 Word 自动生成目录域（含页码），无需模板，打开文档后按 F9 刷新目录
          </div>
        </div>
      </div>

      <!-- 封面 -->
      <div class="set-row">
        <div class="set-label">封面</div>
        <div>
          <el-switch v-model="coverEnabled" />
          <template v-if="coverEnabled">
            <div class="grid-2">
              <el-input v-model="coverTitle" size="small" placeholder="封面标题（如汇编名）" />
              <el-input v-model="coverSubtitle" size="small" placeholder="副题（可空）" />
              <el-input v-model="coverDate" size="small" placeholder="日期（可空）" />
            </div>
          </template>
        </div>
      </div>

      <div class="set-row">
        <div class="set-label">篇间分页</div>
        <div>
          <el-switch v-model="pageBreakBetween" />
          <span class="muted" style="margin-left: 10px">每篇文档之间插入分页符</span>
        </div>
      </div>

      <div class="set-row">
        <div class="set-label">标题样式</div>
        <div class="inline-line">
          <el-select v-model="titleFont" size="small" style="width: 140px">
            <el-option v-for="f in FONTS" :key="f" :label="f" :value="f" />
          </el-select>
          <el-input-number v-model="titleSizePt" :min="8" :max="72" size="small" style="width: 110px" />
          <span class="muted">pt</span>
        </div>
      </div>
      <div class="set-row">
        <div class="set-label">作者样式</div>
        <div class="inline-line">
          <el-select v-model="authorFont" size="small" style="width: 140px">
            <el-option v-for="f in FONTS" :key="f" :label="f" :value="f" />
          </el-select>
          <el-input-number v-model="authorSizePt" :min="8" :max="72" size="small" style="width: 110px" />
          <span class="muted">pt</span>
        </div>
      </div>

      <div style="display: flex; gap: 12px; margin-top: 8px">
        <el-button type="primary" size="large" :loading="compiling" :disabled="!items.length" @click="doCompile">
          <el-icon style="margin-right: 6px"><MagicStick /></el-icon>
          开始汇编{{ items.length ? `（${items.length} 篇）` : '' }}
        </el-button>
        <el-button size="large" @click="loadFormats">刷新环境信息</el-button>
      </div>
    </div>

    <!-- 5. 结果 -->
    <div v-if="result" class="card">
      <div class="card-title"><el-icon><Document /></el-icon>5. 汇编结果</div>

      <div class="result-meta">
        <el-tag v-for="chip in resultChips" :key="chip.text" size="small" effect="plain">
          {{ chip.text }}
        </el-tag>
      </div>

      <el-alert
        v-if="result.stats?.warnings?.length"
        type="warning"
        show-icon
        :closable="false"
        :title="`${result.stats.warnings.length} 条警告：`"
        style="margin-bottom: 12px"
      >
        <ul class="msg-list">
          <li v-for="(w, i) in result.stats.warnings" :key="i">{{ w }}</li>
        </ul>
      </el-alert>

      <el-alert
        v-if="result.errors?.length"
        type="error"
        show-icon
        :closable="false"
        :title="`${result.errors.length} 条错误：`"
        style="margin-bottom: 12px"
      >
        <ul class="msg-list">
          <li v-for="(er, i) in result.errors" :key="i">{{ er }}</li>
        </ul>
      </el-alert>

      <div class="result-actions">
        <el-button type="primary" size="large" @click="downloadResult">
          <el-icon style="margin-right: 6px"><Download /></el-icon>
          下载汇编成果（{{ result.download_name }}）
        </el-button>
        <el-button size="large" @click="continueCompile">继续汇编</el-button>
      </div>
    </div>
  </div>
</template>

<script setup>
import { computed, onMounted, onUnmounted, ref } from 'vue'
import {
  ArrowLeft, Document, Download, Files, MagicStick, Rank, Setting, Upload, UploadFilled, View, WarningFilled,
} from '@element-plus/icons-vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import {
  compileDocs,
  docCompileDownloadUrl,
  docCompileSourceDownloadUrl,
  getDocCompileFileInfo,
  getDocCompileFormats,
  getDocCompilePreviewBlob,
  getDocCompilePreviewText,
  updateDocCompileMeta,
  uploadDocCompile,
} from '../api'

const FONTS = ['黑体', '宋体', '仿宋', '楷体', '微软雅黑', '隶书', '华文行楷', 'Arial', 'Times New Roman']

// ---- 分类 → 中文标签与 tag 颜色 ----
const CLASS_LABELS = { docx: 'DOCX', doc: 'DOC 老格式', wps: 'WPS', rtf: 'RTF', plain: '文本', unknown: '未知' }
const CLASS_TAG_TYPES = { docx: 'success', doc: 'warning', wps: 'warning', rtf: 'info', plain: 'info', unknown: 'danger' }
function classLabel(cls) {
  return CLASS_LABELS[cls] || cls || '未知'
}
function classTagType(cls) {
  return CLASS_TAG_TYPES[cls] || 'info'
}

// ---- 1. 上传 ----
const uploadRef = ref(null)
const pendingFiles = ref([])
const uploading = ref(false)
const droppedItems = ref([])
const items = ref([])
const formats = ref(null)

const maxFileSizeHint = computed(() => {
  const mb = formats.value?.max_file_size_mb
  return mb ? `单个文件不超过 ${mb}MB；` : ''
})

// 选择文件后先收集，点「上传到队列」统一提交（便于展示整体进度）
async function submitUpload() {
  const files = pendingFiles.value.map((f) => f.raw).filter(Boolean)
  if (!files.length) {
    ElMessage.warning('请先选择要上传的文件')
    return
  }
  uploading.value = true
  droppedItems.value = []
  try {
    const res = await uploadDocCompile(files)
    const added = res.items || []
    const dropped = res.dropped || []
    for (const it of added) {
      items.value.push({ ...it, applyToSource: false, saving: false })
    }
    droppedItems.value = dropped
    const m = added.length
    const k = dropped.length
    const text = `共 ${files.length} 个：${m} 个进入队列${k ? `，${k} 个被丢弃` : ''}`
    if (k > 0) ElMessage.warning(text)
    else ElMessage.success(text)

    pendingFiles.value = []
    uploadRef.value?.clearFiles()
    if (!formats.value) loadFormats()
  } catch (e) {
    ElMessage.error(e.message)
  } finally {
    uploading.value = false
  }
}

function clearPending() {
  pendingFiles.value = []
  uploadRef.value?.clearFiles()
}

// ---- 2. 队列 ----
const dragIndex = ref(null)
const allWriteBack = ref(false)

const applyToSourceCap = computed(() => formats.value?.capabilities?.apply_to_source !== false)

function onRowDragStart(index) {
  dragIndex.value = index
}
// 拖拽经过时交换，实现即时换序反馈
function onRowDragOver(index) {
  if (dragIndex.value === null || dragIndex.value === index) return
  const arr = items.value
  const from = dragIndex.value
  ;[arr[from], arr[index]] = [arr[index], arr[from]]
  dragIndex.value = index
}
function onRowDrop() {
  dragIndex.value = null
}
function onRowDragEnd() {
  dragIndex.value = null
}

function moveItem(index, delta) {
  const target = index + delta
  if (target < 0 || target >= items.value.length) return
  const arr = items.value
  ;[arr[index], arr[target]] = [arr[target], arr[index]]
}

function sortByFileName() {
  items.value.sort((a, b) => a.original_name.localeCompare(b.original_name, 'zh'))
}
function sortByTitle() {
  // 按（识别出的）标题排序，无标题时退回文件名
  items.value.sort((a, b) => (a.title || a.original_name).localeCompare(b.title || b.original_name, 'zh'))
}
function reverseQueue() {
  items.value.reverse()
}
async function removeAll() {
  if (!items.value.length) return
  try {
    await ElMessageBox.confirm('确定清空全部队列？', '批量移除', { type: 'warning', confirmButtonText: '清空', cancelButtonText: '取消' })
  } catch {
    return
  }
  items.value = []
  clearPreview()
  ElMessage.success('队列已清空')
}
async function removeItem(item) {
  const idx = items.value.indexOf(item)
  if (idx === -1) return
  items.value.splice(idx, 1)
  if (selectedId.value === item.file_id) clearPreview()
}

// 全部写回源文档：开关变化 → 应用到所有行并保存
async function onAllWriteBackChange(val) {
  for (const it of items.value) it.applyToSource = val
  const results = await Promise.allSettled(items.value.map((it) => saveMeta(it)))
  const failed = results.filter((r) => r.status === 'rejected').length
  if (failed) ElMessage.warning(`已更新，但有 ${failed} 篇保存失败`)
  else ElMessage.success(val ? '已全部标记并保存写回源文档' : '已取消全部写回源文档')
}

// 标题/作者失焦或回车 → 防抖保存；写回源文档勾选变化同样触发
function scheduleSave(item) {
  clearTimeout(item._saveTimer)
  item._saveTimer = setTimeout(() => saveMeta(item), 500)
}
async function saveMeta(item) {
  clearTimeout(item._saveTimer)
  item.saving = true
  try {
    const updated = await updateDocCompileMeta(item.file_id, {
      title: item.title || '',
      author: item.author || '',
      apply_to_source: !!item.applyToSource,
    })
    // 同步后端返回的最新状态（source_updated、惰性 page_count 等）
    item.source_updated = updated.source_updated
    item.warnings = updated.warnings ?? item.warnings
    if (updated.page_count != null) item.page_count = updated.page_count
  } catch (e) {
    ElMessage.error(`保存失败：${e.message}`)
  } finally {
    item.saving = false
  }
}

// ---- 3. 预览 ----
const selectedId = ref('')
const previewPage = ref(1)
const previewPageInput = ref(1)
const previewState = ref('none') // none | loading | image | text | error
const previewBlobUrl = ref('')
const previewText = ref('')
const previewImageUnavailable = ref('')
const previewError = ref('')
let previewToken = 0

const selected = computed(() => items.value.find((i) => i.file_id === selectedId.value) || null)
const canNav = computed(() => (selected.value?.page_count || 0) > 1)

async function selectItem(item) {
  if (selectedId.value === item.file_id && previewState.value !== 'none') return
  selectedId.value = item.file_id
  previewPage.value = 1
  previewPageInput.value = 1
  revokePreviewUrl()
  previewText.value = ''
  previewImageUnavailable.value = ''
  previewError.value = ''
  previewState.value = 'loading'
  // 页数惰性计算：首次选中时拉取 info 刷新 page_count
  if (!item.page_count) {
    try {
      const info = await getDocCompileFileInfo(item.file_id)
      item.page_count = info.page_count
      item.warnings = info.warnings ?? item.warnings
    } catch {
      /* info 拉取失败不影响预览主体 */
    }
  }
  await loadPreviewImage()
}

async function loadPreviewImage() {
  const item = selected.value
  if (!item) return
  const token = ++previewToken
  previewState.value = 'loading'
  try {
    const blob = await getDocCompilePreviewBlob(item.file_id, previewPage.value)
    if (token !== previewToken) return
    revokePreviewUrl()
    previewBlobUrl.value = URL.createObjectURL(blob)
    previewState.value = 'image'
  } catch (e) {
    if (token !== previewToken) return
    if (e.status === 503) {
      // 图片预览不可用（缺 LibreOffice/poppler）→ 降级纯文本
      previewImageUnavailable.value = e.message
      await loadPreviewText()
    } else {
      previewState.value = 'error'
      previewError.value = e.message
    }
  }
}

async function loadPreviewText() {
  const item = selected.value
  if (!item) return
  const token = ++previewToken
  previewState.value = 'loading'
  try {
    const data = await getDocCompilePreviewText(item.file_id)
    if (token !== previewToken) return
    previewText.value = data.text || ''
    previewState.value = 'text'
  } catch (e) {
    if (token !== previewToken) return
    previewState.value = 'error'
    previewError.value = e.message
  }
}

function gotoPage(p) {
  const item = selected.value
  if (!item) return
  const max = item.page_count || 1
  p = Math.min(Math.max(1, Number(p) || 1), max)
  if (p === previewPage.value) return
  previewPage.value = p
  previewPageInput.value = p
  previewToken++ // 取消尚未返回的旧页请求
  previewState.value = 'loading'
  loadPreviewImage()
}
function onPageInput(val) {
  gotoPage(val || 1)
}

function closePreview() {
  clearPreview()
}
function clearPreview() {
  previewToken++
  selectedId.value = ''
  previewState.value = 'none'
  revokePreviewUrl()
  previewText.value = ''
  previewImageUnavailable.value = ''
  previewError.value = ''
}
function revokePreviewUrl() {
  if (previewBlobUrl.value) {
    URL.revokeObjectURL(previewBlobUrl.value)
    previewBlobUrl.value = ''
  }
}
function downloadSource(item) {
  window.open(docCompileSourceDownloadUrl(item.file_id), '_blank')
}

// ---- 4. 汇编设置 ----
const outputFormat = ref('docx')
const tocEnabled = ref(false)
const tocMode = ref('custom')
const tocTemplate = ref('<seq>. <title>……<author>')
const includePageNumbers = ref(false)
const coverEnabled = ref(false)
const coverTitle = ref('')
const coverSubtitle = ref('')
const coverDate = ref('')
const pageBreakBetween = ref(true)
const titleFont = ref('黑体')
const titleSizePt = ref(16)
const authorFont = ref('楷体')
const authorSizePt = ref(12)

const outputDocCap = computed(() => formats.value?.capabilities?.doc_output !== false)
const outputWpsCap = computed(() => formats.value?.capabilities?.wps_output !== false)
const tocPageNumCap = computed(() => formats.value?.capabilities?.toc_page_numbers !== false)
const envHint = computed(() => {
  if (!formats.value) return '环境信息加载中…'
  const soffice = formats.value.soffice
  const poppler = formats.value.poppler
  return `LibreOffice：${soffice?.available ? `可用（${soffice.version}）` : '不可用'} ｜ poppler：${poppler?.available ? `可用（${poppler.version}）` : '不可用'}`
})

const tocExample = computed(() => {
  if (tocMode.value !== 'custom' || !tocTemplate.value) return ''
  const first = items.value[0]
  const title = first?.title || '示例标题'
  const author = first?.author || '示例作者'
  const line = tocTemplate.value
    .replaceAll('<seq>', '1')
    .replaceAll('<title>', title)
    .replaceAll('<author>', author)
    .replaceAll('<page>', '1')
  // 渲染第一行示例
  return line.split('\n').find((l) => l.trim()) ?? line
})

async function loadFormats() {
  try {
    formats.value = await getDocCompileFormats()
    const tpls = formats.value?.toc_templates || []
    if (tpls.length) tocTemplate.value = tpls[0].value
    else if (!tocTemplate.value) tocTemplate.value = '<seq>. <title>……<author>'
  } catch (e) {
    console.warn('supported-formats 拉取失败：', e.message)
  }
}

function buildPayload() {
  return {
    items: items.value.map((i) => ({
      file_id: i.file_id,
      title: i.title || '',
      author: i.author || '',
      apply_to_source: !!i.applyToSource,
    })),
    options: {
      output_format: outputFormat.value,
      toc: {
        enabled: tocEnabled.value,
        mode: tocMode.value,
        template: tocTemplate.value || '',
        include_page_numbers: includePageNumbers.value,
      },
      cover: {
        enabled: coverEnabled.value,
        title: coverTitle.value,
        subtitle: coverSubtitle.value,
        date: coverDate.value,
      },
      page_break_between: pageBreakBetween.value,
      stylesheet: {
        title_font: titleFont.value,
        title_size_pt: titleSizePt.value,
        author_font: authorFont.value,
        author_size_pt: authorSizePt.value,
      },
    },
  }
}

// ---- 5. 结果 ----
const compiling = ref(false)
const result = ref(null)

const resultChips = computed(() => {
  if (!result.value) return []
  const s = result.value.stats || {}
  const chips = [
    { text: `篇数：${s.doc_count ?? '-'}` },
    { text: `总页数：${s.total_pages ?? '-'}` },
    { text: `目录条目：${s.toc_entries ?? '-'}` },
  ]
  if (result.value.mime_type) chips.push({ text: `类型：${result.value.mime_type}` })
  return chips
})

async function doCompile() {
  if (!items.value.length) {
    ElMessage.warning('队列为空，请先上传文档')
    return
  }
  compiling.value = true
  try {
    result.value = await compileDocs(buildPayload())
    ElMessage.success('汇编完成')
  } catch (e) {
    ElMessage.error(e.message)
  } finally {
    compiling.value = false
  }
}

function downloadResult() {
  if (!result.value) return
  window.open(docCompileDownloadUrl(result.value.job_id), '_blank')
}

// 「继续汇编」：保留队列与设置，仅清空结果
function continueCompile() {
  result.value = null
}

onMounted(loadFormats)

onUnmounted(() => {
  for (const it of items.value) clearTimeout(it._saveTimer)
  revokePreviewUrl()
})
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

.upload-actions {
  display: flex;
  gap: 12px;
  margin-top: 12px;
  align-items: center;
}

.pending-list {
  margin-top: 10px;
  font-size: 13px;
  word-break: break-all;
}

.dropped-list {
  margin: 4px 0 0;
  padding-left: 18px;
  max-height: 160px;
  overflow: auto;
}

.dropped-name {
  font-weight: 600;
}

.queue-toolbar {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
  margin-bottom: 12px;
}

.toolbar-right {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-left: auto;
}

.hint-icon {
  color: #e6a23c;
}

.empty-hint {
  padding: 12px 0;
}

.queue-list {
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.queue-row {
  display: flex;
  align-items: center;
  gap: 8px;
  border: 1px solid #e4e7ed;
  border-radius: 6px;
  padding: 6px 10px;
  background: #fff;
  transition: box-shadow 0.15s, border-color 0.15s;
}

.queue-row.row-selected {
  border-color: #409eff;
  box-shadow: 0 0 0 1px #409eff inset;
}

.queue-row.row-dragging {
  opacity: 0.5;
}

.row-sort-handle {
  color: #c0c4cc;
  cursor: grab;
  display: flex;
}

.row-seq {
  width: 24px;
  text-align: center;
  flex-shrink: 0;
  font-size: 13px;
}

.row-name {
  width: 150px;
  flex-shrink: 0;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.row-title {
  width: 220px;
}

.row-author {
  width: 140px;
}

.row-tag {
  flex-shrink: 0;
}

.warn-icon {
  color: #e6a23c;
  flex-shrink: 0;
}

.row-actions {
  display: flex;
  align-items: center;
  gap: 2px;
  margin-left: auto;
  flex-shrink: 0;
}

.write-back {
  margin-left: 6px;
  white-space: nowrap;
}

.card-actions {
  margin-left: auto;
  display: flex;
  gap: 4px;
}

.preview-file {
  max-width: 320px;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.preview-nav {
  display: flex;
  align-items: center;
  gap: 10px;
  flex-wrap: wrap;
  margin-bottom: 12px;
}

.preview-body {
  border: 1px solid #e4e7ed;
  border-radius: 6px;
  padding: 12px;
  min-height: 200px;
  max-height: 70vh;
  overflow: auto;
  display: flex;
  flex-direction: column;
}

.preview-img {
  max-width: 100%;
  margin: 0 auto;
  display: block;
}

.preview-text {
  font-family: Consolas, 'Courier New', monospace;
  font-size: 13px;
  line-height: 1.7;
  white-space: pre-wrap;
  word-break: break-word;
  margin: 0;
}

.preview-meta {
  margin-top: 14px;
}

.preview-meta .set-row {
  margin-bottom: 8px;
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

.inline-line {
  display: flex;
  align-items: center;
  gap: 10px;
  flex-wrap: wrap;
}

.grid-2 {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(220px, 1fr));
  gap: 10px;
  margin-top: 10px;
}

.toc-example {
  margin-top: 10px;
  background: #f5f7fa;
  border: 1px dashed #e4e7ed;
  border-radius: 6px;
  padding: 8px 12px;
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 13px;
}

.toc-example code {
  color: #303133;
}

.result-meta {
  display: flex;
  gap: 8px;
  flex-wrap: wrap;
  margin-bottom: 14px;
}

.msg-list {
  margin: 4px 0 0;
  padding-left: 18px;
}

.result-actions {
  display: flex;
  gap: 12px;
  margin-top: 16px;
  flex-wrap: wrap;
}
</style>