import axios from 'axios'

const http = axios.create({ baseURL: '/api', timeout: 300000 })

function messageError(error) {
  const detail = error?.response?.data?.detail
  const err = detail ? new Error(detail) : new Error(error.message || '请求失败')
  // 透传 HTTP 状态码，便于调用方（如图片预览降级）判断具体失败原因
  if (error?.response?.status) err.status = error.response.status
  return err
}

// 兼容性：messageError 返回 Error 对象，所有调用方均通过 `throw messageError(e)` 抛出，
// 因此调用方的 try/catch 和 .catch() 能正确捕获。保持此模式不变。

export async function getTools() {
  try {
    const { data } = await http.get('/tools')
    return data
  } catch (e) {
    throw messageError(e)
  }
}

export async function uploadExcel(file) {
  const form = new FormData()
  form.append('file', file)
  try {
    const { data } = await http.post('/tools/excel-split/upload', form)
    return data
  } catch (e) {
    throw messageError(e)
  }
}

export async function previewSheet(fileId, sheet, skip = 0, limit = 100) {
  try {
    const { data } = await http.get(`/tools/excel-split/${fileId}/preview`, {
      params: { sheet, skip, limit },
    })
    return data
  } catch (e) {
    throw messageError(e)
  }
}

export async function splitFile(fileId, options) {
  try {
    const { data } = await http.post(`/tools/excel-split/${fileId}/split`, options)
    return data
  } catch (e) {
    throw messageError(e)
  }
}

export function splitDownloadUrl(jobId) {
  return `/api/tools/excel-split/download/${jobId}`
}

export async function convertDocument(file, { output_format = 'md', crop = '' } = {}) {
  const form = new FormData()
  form.append('file', file)
  form.append('output_format', output_format)
  if (crop) form.append('crop', crop)
  try {
    const { data } = await http.post('/tools/doc-convert/convert', form)
    return data
  } catch (e) {
    throw messageError(e)
  }
}

export function docConvertDownloadUrl(jobId) {
  return `/api/tools/doc-convert/download/${jobId}`
}

export async function getDocConvertHealth() {
  try {
    const { data } = await http.get('/tools/doc-convert/health')
    return data
  } catch (e) {
    throw messageError(e)
  }
}

export async function getDocConvertFormats() {
  try {
    const { data } = await http.get('/tools/doc-convert/supported-formats')
    return data
  } catch (e) {
    throw messageError(e)
  }
}

// ---- Excel 表格比对（excel-diff）----

export async function uploadExcelDiff(file) {
  const form = new FormData()
  form.append('file', file)
  try {
    const { data } = await http.post('/tools/excel-diff/upload', form)
    return data
  } catch (e) {
    throw messageError(e)
  }
}

export async function compareExcel(payload) {
  try {
    const { data } = await http.post('/tools/excel-diff/compare', payload)
    return data
  } catch (e) {
    throw messageError(e)
  }
}

export function excelDiffDownloadUrl(jobId) {
  return `/api/tools/excel-diff/download/${jobId}`
}

// ---- 文档汇编（doc-compile）----

// 批量上传（多选），返回 { items, dropped }
export async function uploadDocCompile(files) {
  const form = new FormData()
  for (const f of files) form.append('files', f)
  try {
    const { data } = await http.post('/tools/doc-compile/upload', form)
    return data
  } catch (e) {
    throw messageError(e)
  }
}

// ---- PDF 高保真转 Word（pdf-reconstruct）----

export async function convertPdfToDocx(file) {
  const form = new FormData()
  form.append('file', file)
  try {
    const { data } = await http.post('/tools/pdf-reconstruct/convert', form)
    return data
  } catch (e) {
    throw messageError(e)
  }
}

// 文件详情（含惰性计算的 page_count）
export async function getDocCompileFileInfo(fileId) {
  try {
    const { data } = await http.get(`/tools/doc-compile/files/${fileId}/info`)
    return data
  } catch (e) {
    throw messageError(e)
  }
}

// 纯文本预览（任何环境可用）
export async function getDocCompilePreviewText(fileId) {
  try {
    const { data } = await http.get(`/tools/doc-compile/files/${fileId}/preview-text`)
    return data
  } catch (e) {
    throw messageError(e)
  }
}

// 页面图片预览（需服务器 LibreOffice + poppler，503 时抛出带 status 的错误）
export async function getDocCompilePreviewBlob(fileId, page = 1) {
  try {
    const { data } = await http.get(`/tools/doc-compile/files/${fileId}/preview`, {
      params: { page },
      responseType: 'blob',
    })
    return data
  } catch (e) {
    // responseType=blob 时错误响应体也是 Blob，需解析其中的中文 detail
    if (e.response?.data instanceof Blob) {
      try {
        const text = await e.response.data.text()
        const parsed = JSON.parse(text)
        if (parsed?.detail) {
          const err = new Error(parsed.detail)
          err.status = e.response.status
          throw err
        }
      } catch {
        /* 解析失败则走默认错误处理 */
      }
    }
    throw messageError(e)
  }
}

// 更新标题/作者/写回源文档标记
export async function updateDocCompileMeta(fileId, meta) {
  try {
    const { data } = await http.put(`/tools/doc-compile/files/${fileId}/meta`, meta)
    return data
  } catch (e) {
    throw messageError(e)
  }
}

// 源文件下载（已写回则为更新版）
export function docCompileSourceDownloadUrl(fileId) {
  return `/api/tools/doc-compile/files/${fileId}/source-download`
}

// 发起汇编
export async function compileDocs(payload) {
  try {
    const { data } = await http.post('/tools/doc-compile/compile', payload)
    return data
  } catch (e) {
    throw messageError(e)
  }
}

// 汇编产物下载
export function docCompileDownloadUrl(jobId) {
  return `/api/tools/doc-compile/download/${jobId}`
}

// 支持的能力与目录模板
export async function getDocCompileFormats() {
  try {
    const { data } = await http.get('/tools/doc-compile/supported-formats')
    return data
  } catch (e) {
    throw messageError(e)
  }
}

// 健康检查
export async function getDocCompileHealth() {
  try {
    const { data } = await http.get('/tools/doc-compile/health')
    return data
  } catch (e) {
    throw messageError(e)
  }
}

// ---- PDF 高保真转 Word（pdf-reconstruct）----

export function pdfReconstructDownloadUrl(jobId) {
  return `/api/tools/pdf-reconstruct/download/${jobId}`
}

export async function getPdfReconstructHealth() {
  try {
    const { data } = await http.get('/tools/pdf-reconstruct/health')
    return data
  } catch (e) {
    throw messageError(e)
  }
}