/**
 * 通讯录「字段对应关系自动匹配」回归测试。
 *
 * 直接测试 ContactManagerView.vue 里的真实脚本逻辑：
 * 从 .vue 中提取 <script setup>，用最小桩替换 vue / axios / element-plus，
 * 然后在 Node 中以 vm 求值，从而验证真实代码路径（而非复制一份逻辑来测）。
 *
 * 用法：
 *   node tests/contact-manager-mapping.test.cjs
 *   node tests/contact-manager-mapping.test.cjs <任意 .vue 路径>   # 便于对比历史版本
 *
 * 覆盖的历史缺陷：
 *   1) fetchPreviewData 中 applyAutoMapping 先于 updateHeaderColumns 执行，
 *      导致映射恒为空 —— 自动匹配完全不生效；
 *   2) 未匹配到已有字段的列应默认「新建字段」，而不是留空/被忽略。
 */
const fs = require('fs')
const path = require('path')
const vm = require('vm')

const FILE = process.argv[2] || path.join(__dirname, '..', 'src', 'views', 'ContactManagerView.vue')
const src = fs.readFileSync(FILE, 'utf8')

const m = src.match(/<script setup>([\s\S]*?)<\/script>/)
if (!m) throw new Error('未找到 <script setup> 块')
let code = m[1]

// 去掉 import 语句（后面用桩替代）
code = code.replace(/^\s*import[\s\S]*?from\s+['"][^'"]+['"]\s*$/gm, '')
code = code.replace(/^\s*import\s+['"][^'"]+['"]\s*$/gm, '')

// 暴露内部符号供测试使用（不同版本可能缺少部分函数）
code += `
;globalThis.__t = {
  applyAutoMapping, updateHeaderColumns, fetchPreviewData, handleImport,
  rematchFields: (typeof rematchFields !== 'undefined') ? rematchFields : undefined,
  onHeaderRowChange: (typeof onHeaderRowChange !== 'undefined') ? onHeaderRowChange : undefined,
  goToImportConfirm,
  saveThreshold: (typeof saveThreshold !== 'undefined') ? saveThreshold : undefined,
  pendingNewFields,
  fieldMapping, headerColumns, dbFields, previewRows, headerRow,
  idMatchFields, importPrecheck,
  activeStep, tempPath, selectedSheet, versionDate, uploadResult,
  currentProject, projectPassword, versions, contacts, currentVersionId,
  setAxios: (a) => { axios = a },
  setElMessage: (e) => { ElMessage = e },
  setElMessageBox: (e) => { ElMessageBox = e },
}
`

// ---- 桩实现 ----
function ref(v) { return { value: v } }
function computed(fn) {
  return { get value() { return fn() } }
}
const onMounted = () => {}
const ElMessageStub = { error: () => {}, success: () => {}, warning: () => {} }
const ElMessageBoxStub = { prompt: () => Promise.resolve({ value: '' }), confirm: () => Promise.resolve() }
// axios 默认桩：记录调用并返回空数据
let axiosStub = {
  calls: [],
  get(url, cfg) { this.calls.push({ m: 'get', url, cfg }); return Promise.resolve({ data: {} }) },
  post(url, body, cfg) { this.calls.push({ m: 'post', url, body, cfg }); return Promise.resolve({ data: {} }) },
  delete(url, cfg) { this.calls.push({ m: 'delete', url, cfg }); return Promise.resolve({ data: {} }) },
}

const sandbox = {
  ref, computed, onMounted,
  ElMessage: ElMessageStub,
  ElMessageBox: ElMessageBoxStub,
  axios: axiosStub,
  console,
  Math, Object, Array, JSON, Promise, String, Number, Boolean, Set, Map, Error,
  document: { title: '' },
  window: {},
  globalThis: undefined,
  ArrowLeft: {}, Upload: {}, UploadFilled: {}, Setting: {}, Check: {}, Search: {},
  Folder: {}, Plus: {}, Download: {}, Lock: {},
}
sandbox.globalThis = sandbox
sandbox.__t = null

vm.createContext(sandbox)
try {
  vm.runInContext(code, sandbox, { filename: 'ContactManagerView.vue<script setup>' })
} catch (e) {
  console.error('脚本求值失败:', e.message)
  process.exit(2)
}

const T = sandbox.__t
module.exports = { T, sandbox }

// ==================== 测试 ====================

let pass = 0, fail = 0
function check(name, cond, extra) {
  if (cond) { console.log('  ✓ ' + name); pass++ }
  else { console.log('  ✗ ' + name + (extra ? '  ' + extra : '')); fail++ }
}

// 模拟后端 /inspect 返回：表头在第 2 行
const FIELDS = [
  { id: 1, name: 'name', label: '姓名', is_default: 1 },
  { id: 2, name: 'title', label: '职务', is_default: 1 },
  { id: 3, name: 'unit', label: '单位', is_default: 1 },
  { id: 4, name: 'mobile', label: '手机号码', is_default: 1 },
]
// 第 1 行是标题、第 2 行是表头（含一个项目里没有的「履职平台用户名」列）
const PREVIEW = [
  { row_index: 1, values: ['五届市政协委员名单', '', '', '', ''] },
  { row_index: 2, values: ['姓名', '职务', '单位', '手机号码', '履职平台用户名'] },
  { row_index: 3, values: ['张三', '科长', '甲单位', '13800000001', 'zhangsan'] },
]
const DETECTED = { detected_header_row: 2, mapping: { 0: 'name', 1: 'title', 2: 'unit', 3: 'mobile' } }

function makeAxios(inspectResp) {
  return {
    calls: [],
    get(url, cfg) {
      this.calls.push({ m: 'get', url, cfg })
      if (url === '/api/contact-manager/inspect') return Promise.resolve({ data: inspectResp })
      if (url === '/api/contact-manager/match-fields') {
        const hr = cfg && cfg.params ? cfg.params.header_row : 2
        const row = inspectResp.preview_rows.find(r => r.row_index === hr)
        const mapping = {}
        if (row) {
          const kw = { '姓名': 'name', '职务': 'title', '单位': 'unit', '手机号码': 'mobile' }
          row.values.forEach((v, i) => { if (kw[v]) mapping[i] = kw[v] })
        }
        return Promise.resolve({ data: { header_row: hr, mapping } })
      }
      if (url === '/api/contact-manager/fields') return Promise.resolve({ data: FIELDS })
      return Promise.resolve({ data: {} })
    },
    post(url, body, cfg) {
      this.calls.push({ m: 'post', url, body, cfg })
      if (url === '/api/contact-manager/import') {
        return Promise.resolve({ data: { success: true, version_id: 9, imported_count: 1 } })
      }
      if (url === '/api/contact-manager/fields') {
        FIELDS.push({ id: 100 + FIELDS.length, name: body.name, label: body.label, is_default: 0 })
        return Promise.resolve({ data: { id: 100, ...body } })
      }
      return Promise.resolve({ data: {} })
    },
    delete(url, cfg) { this.calls.push({ m: 'delete', url, cfg }); return Promise.resolve({ data: {} }) },
  }
}

;(async () => {
  console.log('=== 场景：上传后进入映射步骤（自动匹配）===')
  const ax = makeAxios({
    preview_rows: PREVIEW, fields: FIELDS,
    detected_header_row: DETECTED.detected_header_row, mapping: DETECTED.mapping,
  })
  T.setAxios(ax)
  T.tempPath.value = '/tmp/x.xlsx'
  T.selectedSheet.value = 'Sheet1'

  // 关键：走真实的 fetchPreviewData(true) —— 这正是「下一步」按钮触发的路径
  await T.fetchPreviewData(true)

  const fm = T.fieldMapping.value
  console.log('    实际 fieldMapping =', JSON.stringify(fm))

  check('自动匹配生效：列0 -> name', fm[0] === 'name', `实际 ${fm[0]}`)
  check('自动匹配生效：列1 -> title', fm[1] === 'title', `实际 ${fm[1]}`)
  check('自动匹配生效：列2 -> unit', fm[2] === 'unit', `实际 ${fm[2]}`)
  check('自动匹配生效：列3 -> mobile', fm[3] === 'mobile', `实际 ${fm[3]}`)
  check('未匹配列默认「新增字段」而非忽略', fm[4] === '__new__:履职平台用户名', `实际 ${fm[4]}`)
  check('映射覆盖全部 5 列', Object.keys(fm).length === 5, `实际 ${Object.keys(fm).length}`)
  check('待新建字段含未匹配列', T.pendingNewFields.value.includes('履职平台用户名'),
        JSON.stringify(T.pendingNewFields.value))

  console.log('\n=== 场景：手动切换表头行应重新匹配 ===')
  T.headerRow.value = 1
  if (T.onHeaderRowChange) await T.onHeaderRowChange()
  const fm2 = T.fieldMapping.value
  console.log('    表头行=1 时 fieldMapping =', JSON.stringify(fm2))
  check('表头行=1 时列0 为「五届市政协委员名单」→ 新增字段',
        fm2[0] === '__new__:五届市政协委员名单', `实际 ${fm2[0]}`)

  T.headerRow.value = 2
  if (T.onHeaderRowChange) await T.onHeaderRowChange()
  const fm3 = T.fieldMapping.value
  check('切回表头行=2 后重新匹配到 name', fm3[0] === 'name', `实际 ${fm3[0]}`)

  console.log('\n=== 场景：导入时新建字段并映射 ===')
  T.headerRow.value = 2
  T.updateHeaderColumns()
  T.applyAutoMapping(DETECTED.mapping)
  const before = FIELDS.length
  const ax2 = makeAxios({
    preview_rows: PREVIEW, fields: FIELDS,
    detected_header_row: 2, mapping: DETECTED.mapping,
  })
  T.setAxios(ax2)
  T.uploadResult.value = { filename: 'x.xlsx' }
  T.versionDate.value = '2026-09-01'
  await T.handleImport()

  const created = FIELDS.slice(before)
  console.log('    新建字段 =', JSON.stringify(created.map(f => f.label)))
  check('为未匹配列创建了新字段', created.some(f => f.label === '履职平台用户名'),
        JSON.stringify(created.map(f => f.label)))
  check('同名新字段只创建一次', created.filter(f => f.label === '履职平台用户名').length === 1)

  const importCall = ax2.calls.find(c => c.url === '/api/contact-manager/import')
  check('调用了 import 接口', !!importCall)
  if (importCall) {
    const m2 = importCall.body.mapping
    console.log('    提交的 mapping =', JSON.stringify(m2))
    check('提交映射包含已匹配字段', m2['0'] === 'name' && m2['1'] === 'title', JSON.stringify(m2))
    check('提交映射包含新字段（5 列全部提交）', Object.keys(m2).length === 5, JSON.stringify(m2))
    const newName = created.find(f => f.label === '履职平台用户名')
    check('未匹配列指向新建字段名', !!newName && m2['4'] === newName.name,
          `m2[4]=${m2['4']} newName=${newName && newName.name}`)
  }

  console.log('\n=== 场景：姓名列必须映射 ===')
  T.headerRow.value = 2
  T.updateHeaderColumns()
  // 直接把姓名列设为「忽略」，此时映射中不含 name，应阻止进入下一步
  T.fieldMapping.value = { 0: '__ignore__', 1: 'title', 2: 'unit', 3: 'mobile', 4: '__ignore__' }
  T.activeStep.value = 1
  await T.goToImportConfirm()
  check('identity: 未映射姓名列时阻止进入下一步', T.activeStep.value === 1,
        `activeStep=${T.activeStep.value}`)

  // 恢复正确映射后可继续
  T.applyAutoMapping(DETECTED.mapping)
  await T.goToImportConfirm()
  check('identity: 映射姓名列后可进入下一步', T.activeStep.value === 2,
        `activeStep=${T.activeStep.value}`)

  console.log('\n=== 场景：阈值设置可保存 ===')
  const axT = makeAxios({
    preview_rows: PREVIEW, fields: FIELDS,
    detected_header_row: 2, mapping: DETECTED.mapping,
  })
  T.setAxios(axT)
  T.idMatchFields.value = 7
  await T.saveThreshold()
  const setCall = axT.calls.find(c => c.url === '/api/contact-manager/settings')
  check('threshold: 保存阈值到设置接口', !!setCall && setCall.body.id_match_fields === 7,
        setCall ? JSON.stringify(setCall.body) : 'no call')

  console.log('\n=== 场景：重名时询问合并/各自保留 ===')
  const DUP_PREVIEW = [
    { row_index: 1, values: ['姓名', '职务', '单位'] },
    { row_index: 2, values: ['张三', '科长', '甲单位'] },
    { row_index: 3, values: ['张三', '处长', '乙单位'] },
  ]
  T.previewRows.value = DUP_PREVIEW
  T.headerRow.value = 1
  T.updateHeaderColumns()
  T.applyAutoMapping({ 0: 'name', 1: 'title', 2: 'unit' })

  // 预检返回重名
  const axD = makeAxios({ preview_rows: DUP_PREVIEW, fields: FIELDS,
                          detected_header_row: 1, mapping: { 0: 'name', 1: 'title', 2: 'unit' } })
  axD.post = function (url, body, cfg) {
    this.calls.push({ m: 'post', url, body, cfg })
    if (url === '/api/contact-manager/import/preview') {
      return Promise.resolve({ data: {
        duplicates: [{ name: '张三', count: 2 }], duplicate_count: 1,
        total_rows: 2, threshold: 5, matched_count: 0, new_count: 2, has_previous: false } })
    }
    if (url === '/api/contact-manager/import') {
      return Promise.resolve({ data: { success: true, version_id: 1, imported_count: 1,
        new_count: 1, merged_count: 0, removed_count: 0, duplicate_action: 'merge',
        merge_conflicts: {}, has_previous: false } })
    }
    return Promise.resolve({ data: {} })
  }
  T.setAxios(axD)
  T.activeStep.value = 1
  await T.goToImportConfirm()
  check('dup: 预检后进入确认步骤', T.activeStep.value === 2, `activeStep=${T.activeStep.value}`)
  check('dup: 预检结果被记录', T.importPrecheck.value.duplicate_count === 1,
        JSON.stringify(T.importPrecheck.value))

  // 用户选择「合并为一条」→ confirm 回 resolve
  let askedTitle = null
  T.setElMessageBox({
    confirm: (msg, title) => { askedTitle = title; return Promise.resolve() },
    prompt: () => Promise.resolve({ value: '' }),
  })
  await T.handleImport()
  const impCall = axD.calls.find(c => c.url === '/api/contact-manager/import')
  check('dup: 弹出重名询问', askedTitle === '发现重名', String(askedTitle))
  check('dup: 选择合并时提交 duplicate_action=merge',
        !!impCall && impCall.body.duplicate_action === 'merge',
        impCall ? JSON.stringify(impCall.body.duplicate_action) : 'no call')
  check('dup: 不再提交 id_field', !!impCall && !('id_field' in impCall.body),
        impCall ? JSON.stringify(Object.keys(impCall.body)) : 'no call')

  // 用户选择「各自保留」→ cancel 回 'cancel'
  const axS = makeAxios({ preview_rows: DUP_PREVIEW, fields: FIELDS,
                          detected_header_row: 1, mapping: { 0: 'name', 1: 'title', 2: 'unit' } })
  axS.post = function (url, body, cfg) {
    this.calls.push({ m: 'post', url, body, cfg })
    if (url === '/api/contact-manager/import/preview') {
      return Promise.resolve({ data: { duplicates: [{ name: '张三', count: 2 }],
        duplicate_count: 1, total_rows: 2, threshold: 5, matched_count: 0,
        new_count: 2, has_previous: false } })
    }
    return Promise.resolve({ data: { success: true, version_id: 1, imported_count: 2,
      new_count: 2, merged_count: 0, removed_count: 0, merge_conflicts: {}, has_previous: false } })
  }
  T.setAxios(axS)
  T.setElMessageBox({
    confirm: () => Promise.reject('cancel'),
    prompt: () => Promise.resolve({ value: '' }),
  })
  T.activeStep.value = 1
  await T.goToImportConfirm()
  await T.handleImport()
  const sepCall = axS.calls.find(c => c.url === '/api/contact-manager/import')
  check('dup: 选择各自保留时提交 duplicate_action=separate',
        !!sepCall && sepCall.body.duplicate_action === 'separate',
        sepCall ? JSON.stringify(sepCall.body.duplicate_action) : 'no call')

  console.log(`\n结果: ${pass} 通过, ${fail} 失败`)
  process.exit(fail === 0 ? 0 : 1)
})()
