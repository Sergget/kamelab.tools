import axios from 'axios'

const http = axios.create({ baseURL: '/api', timeout: 300000 })

function messageError(error) {
  const detail = error?.response?.data?.detail
  if (detail) return Promise.reject(new Error(detail))
  return Promise.reject(new Error(error.message || '请求失败'))
}

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