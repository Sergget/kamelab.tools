<template>
  <div>
    <!-- 头部与项目切换 -->
    <div class="page-head">
      <el-button link @click="$router.push('/')" :icon="ArrowLeft">返回首页</el-button>
      <h2 class="page-title">通讯录智能处理与归档管理</h2>

      <div v-if="currentProject" class="project-indicator">
        <el-tag type="success" size="large" effect="dark">
          当前项目: {{ currentProject.name }}
        </el-tag>
        <el-button link type="primary" @click="exitProject" style="margin-left: 8px;">切换/退出项目</el-button>
        <el-button link type="danger" @click="openDeleteProjectDialog" style="margin-left: 4px;">删除项目</el-button>
      </div>

      <div v-if="currentProject && activeStep === -1" style="margin-left: auto;">
        <el-button type="primary" :icon="Upload" @click="startImport">导入新版本通讯录</el-button>
      </div>
      <div v-else-if="currentProject && activeStep >= 0" style="margin-left: auto;">
        <el-button @click="exitImport">取消导入并返回列表</el-button>
      </div>
    </div>

    <!-- ================= 0. 项目管理与选择视图 (未进入项目时展示) ================= -->
    <div v-if="!currentProject" class="project-selection-container">
      <div class="card">
        <div class="card-title" style="display: flex; justify-content: space-between; align-items: center;">
          <span><el-icon><Folder /></el-icon> 通讯录项目管理</span>
          <div>
            <el-button type="primary" :icon="Plus" @click="openCreateProjectDialog">新建项目</el-button>
            <el-button type="warning" :icon="Download" @click="openImportDbDialog">导入项目数据库</el-button>
          </div>
        </div>
        <p class="muted" style="margin-bottom: 20px;">
          不同项目之间的通讯录完全隔离互不影响。进入特定项目需输入设定的密码。删除项目前必须先验证密码，再导出完整数据库备份，且删除后服务器不保留任何数据。
        </p>

        <!-- 项目卡片列表 -->
        <el-row :gutter="20">
          <el-col v-for="proj in projects" :key="proj.id" :xs="24" :sm="12" :md="8" style="margin-bottom: 20px;">
            <el-card shadow="hover" class="project-card">
              <template #header>
                <div style="display: flex; justify-content: space-between; align-items: center;">
                  <span style="font-weight: 600; font-size: 16px;">{{ proj.name }}</span>
                  <el-tag size="small" type="info">{{ proj.version_count }} 个版本</el-tag>
                </div>
              </template>
              <div class="project-desc">{{ proj.description || '暂无项目描述' }}</div>
              <div class="project-meta muted">
                <div>联系人总数: {{ proj.entity_count }} 人</div>
                <div>创建时间: {{ proj.created_at?.split(' ')[0] }}</div>
              </div>
              <div class="project-actions" style="margin-top: 16px; display: flex; justify-content: space-between;">
                <el-button type="primary" :icon="Lock" @click="promptEnterProject(proj)">输入密码进入</el-button>
                <el-dropdown trigger="click">
                  <el-button link type="info">更多操作</el-button>
                  <template #dropdown>
                    <el-dropdown-menu>
                      <el-dropdown-item @click="promptExportDb(proj)">导出项目数据库</el-dropdown-item>
                      <el-dropdown-item divided style="color: #f56c6c;" @click="promptDeleteProject(proj)">
                        删除项目 (需导出备份)
                      </el-dropdown-item>
                    </el-dropdown-menu>
                  </template>
                </el-dropdown>
              </div>
            </el-card>
          </el-col>
        </el-row>

        <el-empty v-if="projects.length === 0" description="暂无项目，请先新建项目或导入数据库" />
      </div>
    </div>

    <!-- ================= 1. 项目内工作区 (已解锁进入项目后展示) ================= -->
    <div v-else>
      <!-- 导入步骤导航条 (仅在导入模式显示) -->
      <el-steps v-if="activeStep >= 0" :active="activeStep" finish-status="success" align-center class="step-bar">
        <el-step title="上传通讯录" description="上传Excel并解析文件名日期" />
        <el-step title="表头确认与字段映射" description="检查预览、设定表头行并映射字段" />
        <el-step title="导入与归档确认" description="确认解析数据并入库" />
      </el-steps>

      <!-- 步骤 0：上传与 Sheet 选择 -->
      <div v-if="activeStep === 0" class="card">
        <div class="card-title"><el-icon><Upload /></el-icon>1. 上传通讯录 Excel 文件</div>
        <el-upload
          drag
          :auto-upload="true"
          :http-request="doUpload"
          :show-file-list="false"
          accept=".xlsx,.xls"
        >
          <el-icon class="el-icon--upload"><UploadFilled /></el-icon>
          <div class="el-upload__text">将 Excel 文件拖到此处，或 <em>点击上传</em></div>
          <template #tip>
            <div class="el-upload__tip muted">文件名中包含日期（如 2026-09-09_通讯录.xlsx）将自动识别为版本日期</div>
          </template>
        </el-upload>

        <div v-if="uploadResult" class="upload-result-box">
          <el-descriptions title="文件解析成功" border :column="2" style="margin-top: 20px;">
            <el-descriptions-item label="文件名">{{ uploadResult.filename }}</el-descriptions-item>
            <el-descriptions-item label="建议版本日期">
              <el-date-picker v-model="versionDate" type="date" value-format="YYYY-MM-DD" placeholder="选择版本日期" />
            </el-descriptions-item>
            <el-descriptions-item label="选择工作表 (Sheet)" :span="2">
              <el-select v-model="selectedSheet" placeholder="请选择要处理的 Sheet" style="width: 320px">
                <el-option v-for="sh in uploadResult.sheets" :key="sh" :label="sh" :value="sh" />
              </el-select>
            </el-descriptions-item>
          </el-descriptions>

          <div style="margin-top: 20px; text-align: right;">
            <el-button type="primary" :disabled="!selectedSheet" @click="goToInspect">下一步：配置表头与字段映射</el-button>
          </div>
        </div>
      </div>

      <!-- 步骤 1：表头确认与字段映射 -->
      <div v-if="activeStep === 1" class="card">
        <div class="card-title"><el-icon><Setting /></el-icon>2. 自动特征识别与字段映射</div>
        <div class="muted" style="margin-bottom: 12px;">
          您可以调整表头行索引，系统会实时更新预览。您可以手动调整每一列对应的字段，未匹配的字段可选择“设为新增”。
        </div>

        <el-form inline style="margin-bottom: 16px;">
          <el-form-item label="表头所在行号">
            <el-input-number v-model="headerRow" :min="1" :max="15" @change="onHeaderRowChange" />
          </el-form-item>
          <el-form-item>
            <el-button type="info" plain @click="autoDetectMapping">重新自动匹配字段</el-button>
          </el-form-item>
        </el-form>

        <!-- 预览表格 -->
        <div class="preview-table-container" style="max-height: 300px; overflow-y: auto; margin-bottom: 20px; border: 1px solid #ebeef5;">
          <el-table :data="previewRows" border size="small" stripe>
            <el-table-column prop="row_index" label="行号" width="70" align="center" fixed />
            <el-table-column v-for="(val, colIdx) in maxCols" :key="colIdx" :label="`列 ${colIdx + 1}`" min-width="120">
              <template #default="{ row }">
                <span :class="{ 'highlight-header': row.row_index === headerRow }">
                  {{ row.values[colIdx] || '' }}
                </span>
              </template>
            </el-table-column>
          </el-table>
        </div>

        <!-- 字段映射配置 -->
        <h3 style="margin-bottom: 12px;">字段对应关系设置</h3>

        <el-alert type="info" show-icon :closable="false" style="margin-bottom: 12px;">
          <template #title>身份标识由后端自动计算</template>
          <div class="muted">
            系统以<strong>姓名</strong>为主键识别联系人。若同一份表中出现重名，导入时会询问您
            「合并为一条」还是「各自保留」；与历史版本比对时，只要同名且
            <strong>{{ idMatchFields }}</strong> 个字段取值相同，即判定为同一个人
            （可在下方调整该数量）。
          </div>
        </el-alert>
        <el-form inline style="margin-bottom: 16px;">
          <el-form-item label="同一人判定所需相同字段数">
            <el-input-number v-model="idMatchFields" :min="1" :max="30" @change="saveThreshold" />
            <span class="muted" style="margin-left: 8px;">
              （不含姓名；调高更严格，调低更容易认作同一人）
            </span>
          </el-form-item>
        </el-form>

        <div class="mapping-grid">
          <div v-for="(colName, colIdx) in headerColumns" :key="colIdx" class="mapping-item">
            <el-card shadow="hover" size="small" :class="{ 'mapping-card-active': fieldMapping[colIdx] && fieldMapping[colIdx] !== '__ignore__' }">
              <template #header>
                <div class="card-header">
                  <span class="col-title">列 {{ colIdx + 1 }}: <strong>{{ colName || '(空)' }}</strong></span>
                </div>
              </template>
              <el-form-item label-width="0" style="margin-bottom: 0;">
                <el-select v-model="fieldMapping[colIdx]" placeholder="不导入 / 忽略" clearable filterable style="width: 100%;">
                  <el-option-group label="当前项目已有字段">
                    <el-option v-for="f in dbFields" :key="f.name" :label="f.label" :value="f.name" />
                  </el-option-group>
                  <el-option-group label="操作">
                    <el-option label="[新增字段] 以列名为准创建" :value="`__new__:${colName}`" :disabled="!colName" />
                    <el-option label="[忽略] 不导入此列" value="__ignore__" />
                  </el-option-group>
                </el-select>
              </el-form-item>
            </el-card>
          </div>
        </div>

        <div style="margin-top: 20px; display: flex; justify-content: space-between;">
          <el-button @click="activeStep = 0">上一步</el-button>
          <el-button type="primary" @click="goToImportConfirm">下一步：确认导入</el-button>
        </div>
      </div>

      <!-- 步骤 2：导入与归档确认 -->
      <div v-if="activeStep === 2" class="card">
        <div class="card-title"><el-icon><Check /></el-icon>3. 导入数据预览与归档确认</div>
        <el-descriptions border :column="2" style="margin-bottom: 20px;">
          <el-descriptions-item label="归属项目">{{ currentProject.name }}</el-descriptions-item>
          <el-descriptions-item label="文件名">{{ uploadResult?.filename }}</el-descriptions-item>
          <el-descriptions-item label="工作表 (Sheet)">{{ selectedSheet }}</el-descriptions-item>
          <el-descriptions-item label="归档版本日期">{{ versionDate }}</el-descriptions-item>
          <el-descriptions-item label="表头行">{{ headerRow }}</el-descriptions-item>
          <el-descriptions-item label="同一人判定">
            <span class="muted">同名且 {{ idMatchFields }} 个字段相同</span>
          </el-descriptions-item>
          <el-descriptions-item label="重名情况" :span="2">
            <template v-if="importPrecheck.duplicate_count > 0">
              <el-tag type="warning" effect="plain" style="margin-right: 6px;">
                {{ importPrecheck.duplicate_count }} 个姓名重复
              </el-tag>
              <span class="muted">
                {{ importPrecheck.duplicates.slice(0, 6).map(d => `${d.name}(${d.count})`).join('、') }}
                <template v-if="importPrecheck.duplicates.length > 6"> …</template>
                （导入时可选择合并或各自保留）
              </span>
            </template>
            <span v-else class="muted">无重名</span>
          </el-descriptions-item>
          <el-descriptions-item label="跨版本预估" :span="2">
            <template v-if="importPrecheck.has_previous">
              <el-tag type="success" effect="plain" style="margin-right: 6px;">
                匹配已有 {{ importPrecheck.matched_count }} 条
              </el-tag>
              <el-tag type="info" effect="plain">新增 {{ importPrecheck.new_count }} 条</el-tag>
            </template>
            <span v-else class="muted">首个版本，全部为新增</span>
          </el-descriptions-item>
          <el-descriptions-item label="待创建新字段" :span="2">
            <el-tag v-for="nf in pendingNewFields" :key="nf" type="warning" style="margin-right: 8px;">{{ nf }}</el-tag>
            <span v-if="pendingNewFields.length === 0" class="muted">无</span>
          </el-descriptions-item>
        </el-descriptions>

        <div style="margin-top: 20px; display: flex; justify-content: space-between;">
          <el-button @click="activeStep = 1">上一步</el-button>
          <el-button type="success" :loading="importing" @click="handleImport">确认并创建字段导入</el-button>
        </div>
      </div>

      <!-- ================= 管理模式界面 (浏览、检索、编辑) ================= -->
      <div v-if="activeStep === -1" class="card">
        <div class="card-title"><el-icon><Search /></el-icon>【{{ currentProject.name }}】通讯录综合查询与可视化编辑</div>

        <!-- 查询与版本控制面板 -->
        <div class="toolbar" style="display: flex; gap: 16px; margin-bottom: 20px; flex-wrap: wrap; align-items: center;">
          <el-form inline style="margin-bottom: 0;">
            <el-form-item label="版本归档">
              <el-select v-model="currentVersionId" placeholder="所有版本 (跨版本搜索)" clearable style="width: 240px" @change="onVersionFilterChange">
                <el-option v-for="v in versions" :key="v.id" :label="`${v.version_date} - ${v.filename}`" :value="v.id" />
              </el-select>
            </el-form-item>
            <el-form-item label="时点查询">
              <el-tooltip content="选择了版本归档时不可用；不选版本时按此日期过滤（含当日）" placement="top">
                <span>
                  <el-date-picker v-model="queryDate" type="date" value-format="YYYY-MM-DD"
                                  placeholder="截止日期" :disabled="!!currentVersionId"
                                  @change="loadContacts" style="width: 150px" />
                </span>
              </el-tooltip>
            </el-form-item>
            <el-form-item label="关键词">
              <el-input v-model="keyword" placeholder="支持 * 通配，如 张* / *委员*" clearable
                        @clear="loadContacts" @keyup.enter="loadContacts" style="width: 200px" />
            </el-form-item>
          </el-form>
          <div style="display: flex; gap: 8px;">
            <el-button type="primary" @click="loadContacts">查询</el-button>
            <el-button @click="clearFilters">重置</el-button>
            <el-button type="success" @click="exportExcel">导出 Excel</el-button>
            <el-button type="warning" @click="openAddContactDialog">新增联系人</el-button>
            <el-button plain @click="openFieldCleanDialog">
              清理空字段<template v-if="emptyFieldCount > 0"> ({{ emptyFieldCount }})</template>
            </el-button>
            <el-button type="danger" plain @click="saveOnlineChanges" :disabled="!hasPendingChanges">
              保存修改到新版本 ({{ pendingChangesCount }})
            </el-button>
          </div>
        </div>

        <!-- 联系人数据表格 -->
        <el-table :data="contacts" border stripe size="small" max-height="600">
          <el-table-column type="index" label="序号" width="60" align="center" fixed />
          <el-table-column v-if="isHistorical" label="归档日期" width="110" align="center" fixed sortable prop="_version_date">
            <template #default="{ row }">
              <el-tag size="small" effect="plain">{{ row._version_date }}</el-tag>
            </template>
          </el-table-column>
          <el-table-column v-for="f in dbFields" :key="f.name" :prop="f.name" :label="f.label" min-width="140" show-overflow-tooltip>
            <template #default="{ row }">
              <span>{{ row[f.name] || '' }}</span>
            </template>
          </el-table-column>
          <el-table-column label="操作" width="120" align="center" fixed="right">
            <template #default="{ row }">
              <el-button size="small" type="primary" link @click="openEditDialog(row)">编辑</el-button>
              <el-button size="small" type="danger" link @click="deleteContactItem(row.id)">删除</el-button>
            </template>
          </el-table-column>
        </el-table>
        <el-empty v-if="!contacts.length && !versions.length" description="当前项目暂无通讯录版本，请点击右上角导入新版本" />
      </div>

      <!-- 编辑/新增弹窗 -->
      <el-dialog v-model="editDialogVisible" :title="editingContact.id ? '修改联系人' : '手动新增联系人'" width="550px">
        <el-form :model="editingContact" label-width="100px" style="max-height: 400px; overflow-y: auto;">
          <el-form-item v-for="f in dbFields" :key="f.name" :label="f.label">
            <el-input v-model="editingContact[f.name]" />
          </el-form-item>
        </el-form>
        <template #footer>
          <el-button @click="editDialogVisible = false">取消</el-button>
          <el-button type="primary" @click="saveContact">确定</el-button>
        </template>
      </el-dialog>

      <!-- 清理空字段弹窗 -->
      <el-dialog v-model="fieldCleanDialogVisible" title="清理无内容字段" width="620px">
        <div class="muted" style="margin-bottom: 12px;">
          以下字段在本项目已归档的数据中<strong>没有任何内容</strong>。删除字段只会从表单与导出中移除该列，
          <strong>不会删除任何联系人数据</strong>。
        </div>
        <el-table :data="emptyFields" border size="small" max-height="340">
          <el-table-column prop="label" label="字段名称" min-width="140" />
          <el-table-column label="类型" width="110" align="center">
            <template #default="{ row }">
              <el-tag size="small" :type="row.is_default ? 'info' : 'warning'" effect="plain">
                {{ row.is_default ? '默认字段' : '自定义' }}
              </el-tag>
            </template>
          </el-table-column>
          <el-table-column prop="non_empty" label="非空值" width="90" align="center" />
        </el-table>
        <el-empty v-if="!emptyFields.length" description="没有无内容的字段，无需清理" :image-size="60" />

        <el-checkbox v-if="emptyDefaultCount > 0" v-model="cleanIncludeDefault" style="margin-top: 12px;">
          同时删除 {{ emptyDefaultCount }} 个空的默认字段（职务 / 单位 / 电话 等）
        </el-checkbox>
        <template #footer>
          <el-button @click="fieldCleanDialogVisible = false">取消</el-button>
          <el-button type="danger" :loading="cleaningFields" :disabled="!emptyFields.length"
                     @click="confirmCleanFields">
            确认删除 {{ emptyFields.length }} 个字段
          </el-button>
        </template>
      </el-dialog>
    </div>

    <!-- ================= 弹窗管理 ================= -->

    <!-- 1. 新建项目弹窗 -->
    <el-dialog v-model="createProjectDialogVisible" title="新建通讯录项目" width="480px">
      <el-form :model="newProjectForm" label-width="90px">
        <el-form-item label="项目名称" required>
          <el-input v-model="newProjectForm.name" placeholder="如：2026机关单位通讯录" />
        </el-form-item>
        <el-form-item label="访问密码" required>
          <el-input v-model="newProjectForm.password" type="password" show-password placeholder="进入该项目所需的密码" />
        </el-form-item>
        <el-form-item label="项目描述">
          <el-input v-model="newProjectForm.description" type="textarea" :rows="2" placeholder="可选备注信息" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="createProjectDialogVisible = false">取消</el-button>
        <el-button type="primary" @click="handleCreateProject">创建项目</el-button>
      </template>
    </el-dialog>

    <!-- 2. 进入项目密码弹窗 -->
    <el-dialog v-model="enterPasswordDialogVisible" title="安全验证：进入项目" width="400px">
      <p style="margin-bottom: 16px;">请输入项目 <strong>{{ targetProject?.name }}</strong> 的访问密码：</p>
      <el-input v-model="inputPassword" type="password" show-password placeholder="项目密码" @keyup.enter="handleEnterProject" />
      <template #footer>
        <el-button @click="enterPasswordDialogVisible = false">取消</el-button>
        <el-button type="primary" @click="handleEnterProject">验证并进入</el-button>
      </template>
    </el-dialog>

    <!-- 3. 导入项目数据库弹窗 -->
    <el-dialog v-model="importDbDialogVisible" title="导入项目数据库 (.cmdb)" width="480px">
      <el-form :model="importDbForm" label-width="100px">
        <el-form-item label="选择备份文件" required>
          <input type="file" ref="dbFileInput" accept=".cmdb,.json" @change="onDbFileChange" />
        </el-form-item>
        <el-form-item label="重命名项目">
          <el-input v-model="importDbForm.name" placeholder="留空使用备份文件内置的项目名" />
        </el-form-item>
        <el-form-item label="重设访问密码" required>
          <el-input v-model="importDbForm.password" type="password" show-password placeholder="为恢复的项目设定访问密码" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="importDbDialogVisible = false">取消</el-button>
        <el-button type="primary" :loading="importingDb" @click="handleImportDb">导入并恢复</el-button>
      </template>
    </el-dialog>

    <!-- 4. 删除项目强制导出确认弹窗 -->
    <el-dialog v-model="deleteProjectDialogVisible" title="⚠️ 删除项目风险确认" width="520px">
      <el-alert
        title="重要警告：删除操作彻底且不可逆！"
        type="error"
        description="删除项目将永久抹除该项目及其名下的所有版本、联系人和修改痕迹，服务器不保留任何数据。为了保障数据安全，系统强制要求必须先验证密码，再导出完整数据库备份。"
        show-icon
        :closable="false"
        style="margin-bottom: 20px;"
      />

      <el-form label-width="110px">
        <el-form-item label="步骤 1：密码验证" required>
          <el-input v-model="deletePassword" type="password" show-password placeholder="输入当前项目密码确认身份" />
        </el-form-item>
        <el-form-item label="步骤 2：导出备份" required>
          <el-button type="warning" :icon="Download" @click="downloadDbBeforeDelete" :disabled="!deletePassword">
            {{ hasExportedBackup ? '✓ 已导出数据库备份 (可再次导出)' : '立即导出项目数据库备份' }}
          </el-button>
        </el-form-item>
      </el-form>

      <template #footer>
        <el-button @click="deleteProjectDialogVisible = false">取消</el-button>
        <el-button
          type="danger"
          :disabled="!hasExportedBackup || !deletePassword"
          :loading="deletingProject"
          @click="confirmDeleteProject"
        >
          我已保存备份，确认彻底删除
        </el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { ref, computed, onMounted } from 'vue'
import {
  ArrowLeft, Upload, UploadFilled, Setting, Check, Search,
  Folder, Plus, Download, Lock
} from '@element-plus/icons-vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import axios from 'axios'

// ================= 项目管理状态 =================
const projects = ref([])
const currentProject = ref(null)
const projectPassword = ref('')

const createProjectDialogVisible = ref(false)
const newProjectForm = ref({ name: '', password: '', description: '' })

const enterPasswordDialogVisible = ref(false)
const targetProject = ref(null)
const inputPassword = ref('')

const importDbDialogVisible = ref(false)
const importDbForm = ref({ name: '', password: '' })
const dbFile = ref(null)
const dbFileInput = ref(null)
const importingDb = ref(false)

const deleteProjectDialogVisible = ref(false)
const hasExportedBackup = ref(false)
const deletePassword = ref('')
const deletingProject = ref(false)

// Axios 请求拦截器或封装 Header
const getAuthHeaders = () => {
  if (!currentProject.value) return {}
  return {
    'X-Project-Id': currentProject.value.id,
    'X-Project-Password': projectPassword.value
  }
}

// 模式切换: -1 为管理模式, 0+ 为导入模式步骤
const activeStep = ref(-1)

const uploadResult = ref(null)
const selectedSheet = ref('')
const versionDate = ref('')
const tempPath = ref('')

const previewRows = ref([])
const dbFields = ref([])
const headerRow = ref(1)
const fieldMapping = ref({})
const headerColumns = ref([])
const maxCols = ref(0)

// 跨版本「同一人」判定所需的相同字段数（不含姓名，默认 5，由后端持久化）
const idMatchFields = ref(5)

const importing = ref(false)
const versions = ref([])
const currentVersionId = ref(null)
const queryDate = ref('')
const keyword = ref('')
const contacts = ref([])
const isHistorical = ref(false)

// 空字段清理
const fieldUsage = ref([])
const fieldCleanDialogVisible = ref(false)
const cleaningFields = ref(false)
const cleanIncludeDefault = ref(true)
const emptyFieldCount = computed(() => fieldUsage.value.filter(f => f.empty).length)
const emptyFields = computed(() => fieldUsage.value.filter(
  f => f.empty && (cleanIncludeDefault.value || !f.is_default)))
const emptyDefaultCount = computed(() => fieldUsage.value.filter(
  f => f.empty && f.is_default).length)

// 暂存尚未提交到新版本的在线修改操作列表
const pendingOperations = ref([])
const hasPendingChanges = computed(() => pendingOperations.value.length > 0)
const pendingChangesCount = computed(() => pendingOperations.value.length)

const editDialogVisible = ref(false)
const editingContact = ref({})

const pendingNewFields = computed(() => {
  // 去重：多列可能对应同一个待新建字段名
  const labels = Object.values(fieldMapping.value)
    .filter(v => v && v.startsWith('__new__:'))
    .map(v => v.replace('__new__:', '').trim())
    .filter(Boolean)
  return [...new Set(labels)]
})

// ================= 项目生命周期与逻辑 =================

const loadProjects = async () => {
  try {
    const res = await axios.get('/api/contact-manager/projects')
    projects.value = res.data
  } catch (err) {
    ElMessage.error('加载项目列表失败')
  }
}

const openCreateProjectDialog = () => {
  newProjectForm.value = { name: '', password: '', description: '' }
  createProjectDialogVisible.value = true
}

const handleCreateProject = async () => {
  if (!newProjectForm.value.name.trim() || !newProjectForm.value.password.trim()) {
    return ElMessage.warning('请填写项目名称和访问密码')
  }
  try {
    const res = await axios.post('/api/contact-manager/projects', newProjectForm.value)
    ElMessage.success('项目创建成功')
    createProjectDialogVisible.value = false
    await loadProjects()
    // 自动以设定密码进入
    currentProject.value = res.data.project
    projectPassword.value = newProjectForm.value.password
    await enterProjectWorkspace()
  } catch (err) {
    ElMessage.error(err.response?.data?.detail || '创建项目失败')
  }
}

const promptEnterProject = (proj) => {
  targetProject.value = proj
  inputPassword.value = ''
  enterPasswordDialogVisible.value = true
}

const handleEnterProject = async () => {
  if (!inputPassword.value) return ElMessage.warning('请输入项目访问密码')
  try {
    const res = await axios.post('/api/contact-manager/projects/auth', {
      project_id: targetProject.value.id,
      password: inputPassword.value
    })
    currentProject.value = res.data.project
    projectPassword.value = inputPassword.value
    enterPasswordDialogVisible.value = false
    ElMessage.success(`已进入项目: ${currentProject.value.name}`)
    await enterProjectWorkspace()
  } catch (err) {
    ElMessage.error(err.response?.data?.detail || '密码错误或无权访问')
  }
}

const exitProject = () => {
  currentProject.value = null
  projectPassword.value = ''
  activeStep.value = -1
  contacts.value = []
  versions.value = []
  fieldUsage.value = []
  loadProjects()
}

// ================= 空字段清理 =================

const loadFieldUsage = async () => {
  try {
    const res = await axios.get('/api/contact-manager/fields/usage', { headers: getAuthHeaders() })
    fieldUsage.value = res.data.fields || []
  } catch (err) {
    fieldUsage.value = []
  }
}

const openFieldCleanDialog = async () => {
  await loadFieldUsage()
  cleanIncludeDefault.value = true
  fieldCleanDialogVisible.value = true
}

const confirmCleanFields = async () => {
  const targets = emptyFields.value
  if (!targets.length) return
  try {
    await ElMessageBox.confirm(
      `将删除 ${targets.length} 个无内容的字段：${targets.map(f => f.label).join('、')}。` +
      '此操作不会删除任何联系人数据，是否继续？',
      '确认清理空字段',
      { type: 'warning', confirmButtonText: '确认删除', cancelButtonText: '取消' }
    )
  } catch {
    return
  }
  cleaningFields.value = true
  try {
    const res = await axios.post('/api/contact-manager/fields/clean',
      { field_ids: targets.map(f => f.id) },
      { headers: getAuthHeaders() })
    ElMessage.success(res.data.message || `已删除 ${res.data.deleted} 个字段`)
    fieldCleanDialogVisible.value = false
    // 刷新字段与数据
    const fieldRes = await axios.get('/api/contact-manager/fields', { headers: getAuthHeaders() })
    dbFields.value = fieldRes.data
    await loadFieldUsage()
    await loadContacts()
  } catch (err) {
    ElMessage.error(err.response?.data?.detail || err.message || '清理失败')
  } finally {
    cleaningFields.value = false
  }
}

const enterProjectWorkspace = async () => {
  activeStep.value = -1
  pendingOperations.value = []
  try {
    const fieldRes = await axios.get('/api/contact-manager/fields', { headers: getAuthHeaders() })
    dbFields.value = fieldRes.data
    loadFieldUsage()
    await loadVersions()
    if (versions.value.length > 0) {
      currentVersionId.value = versions.value[0].id
      await loadContacts()
    } else {
      contacts.value = []
      currentVersionId.value = null
    }
  } catch (err) {
    ElMessage.error('加载项目工作区失败')
  }
}

// 导出项目数据库
const promptExportDb = (proj) => {
  ElMessageBox.prompt(`请输入项目【${proj.name}】的访问密码以导出完整数据库:`, '导出数据库', {
    inputType: 'password',
    confirmButtonText: '验证并导出',
    cancelButtonText: '取消'
  }).then(({ value: pwd }) => {
    if (!pwd) return
    const url = `/api/contact-manager/projects/${proj.id}/export-db?password=${encodeURIComponent(pwd)}`
    window.open(url, '_blank')
  }).catch(() => {})
}

// 导入数据库
const openImportDbDialog = () => {
  importDbForm.value = { name: '', password: '' }
  dbFile.value = null
  if (dbFileInput.value) dbFileInput.value.value = ''
  importDbDialogVisible.value = true
}

const onDbFileChange = (e) => {
  dbFile.value = e.target.files[0] || null
}

const handleImportDb = async () => {
  if (!dbFile.value) return ElMessage.warning('请选择数据库备份文件 (.cmdb/.json)')
  if (!importDbForm.value.password.trim()) return ElMessage.warning('请为恢复的项目设定访问密码')

  const formData = new FormData()
  formData.append('file', dbFile.value)
  if (importDbForm.value.name.trim()) formData.append('name', importDbForm.value.name.trim())
  formData.append('password', importDbForm.value.password.trim())

  importingDb.value = true
  try {
    const res = await axios.post('/api/contact-manager/projects/import-db', formData)
    ElMessage.success(res.data.message || '项目数据库导入成功')
    importDbDialogVisible.value = false
    await loadProjects()
  } catch (err) {
    ElMessage.error(err.response?.data?.detail || '导入数据库失败')
  } finally {
    importingDb.value = false
  }
}

// 删除项目 (强制导出)
const promptDeleteProject = (proj) => {
  targetProject.value = proj
  hasExportedBackup.value = false
  deletePassword.value = ''
  deleteProjectDialogVisible.value = true
}

const openDeleteProjectDialog = () => {
  if (!currentProject.value) return
  promptDeleteProject(currentProject.value)
}

const downloadDbBeforeDelete = () => {
  const proj = targetProject.value || currentProject.value
  const pwd = deletePassword.value || projectPassword.value
  if (!deletePassword.value) {
    return ElMessage.warning('请先在上方输入项目密码')
  }
  if (!pwd) {
    return ElMessage.warning('请先输入项目密码以验证身份')
  }
  const url = `/api/contact-manager/projects/${proj.id}/export-db?password=${encodeURIComponent(pwd)}`
  window.open(url, '_blank')
  hasExportedBackup.value = true
  ElMessage.success('已触发数据库导出，请确认下载完成')
}

const confirmDeleteProject = async () => {
  const proj = targetProject.value || currentProject.value
  if (!deletePassword.value) return ElMessage.warning('请输入密码确认删除')
  if (!hasExportedBackup.value) return ElMessage.warning('请先完成数据库备份导出')

  deletingProject.value = true
  try {
    await axios.delete(`/api/contact-manager/projects/${proj.id}?password=${encodeURIComponent(deletePassword.value)}`)
    ElMessage.success('项目已彻底从服务器清除')
    hasExportedBackup.value = false
    deleteProjectDialogVisible.value = false
    if (currentProject.value?.id === proj.id) {
      exitProject()
    } else {
      await loadProjects()
    }
  } catch (err) {
    ElMessage.error(err.response?.data?.detail || '删除失败，请检查密码')
  } finally {
    deletingProject.value = false
  }
}

// ================= 通讯录导入与管理业务 =================

const startImport = () => {
  activeStep.value = 0
  uploadResult.value = null
  selectedSheet.value = ''
}

const exitImport = () => {
  activeStep.value = -1
}

const doUpload = async (options) => {
  const formData = new FormData()
  formData.append('file', options.file)
  try {
    const res = await axios.post('/api/contact-manager/upload', formData, {
      headers: getAuthHeaders()
    })
    uploadResult.value = res.data
    tempPath.value = res.data.temp_path
    versionDate.value = res.data.suggested_date
    selectedSheet.value = res.data.sheets[0] || ''
    ElMessage.success('上传成功')
  } catch (err) {
    ElMessage.error(err.response?.data?.detail || '上传失败')
  }
}

const goToInspect = async () => {
  activeStep.value = 1
  await fetchPreviewData(true)
}

const fetchPreviewData = async (shouldAutoDetect = false) => {
  try {
    const res = await axios.get('/api/contact-manager/inspect', {
      params: { temp_path: tempPath.value, sheet_name: selectedSheet.value },
      headers: getAuthHeaders()
    })
    previewRows.value = res.data.preview_rows
    dbFields.value = res.data.fields
    maxCols.value = Math.max(...(previewRows.value.map(r => r.values.length) || [0]))

    if (shouldAutoDetect) {
      headerRow.value = res.data.detected_header_row
    }
    // 必须先根据表头行刷新列名，applyAutoMapping 依赖 headerColumns 逐列生成映射
    updateHeaderColumns()
    if (shouldAutoDetect) {
      applyAutoMapping(res.data.mapping)
    }
    // 跨版本同一人判定阈值：沿用项目设置
    if (res.data.id_match_fields) idMatchFields.value = res.data.id_match_fields
  } catch (err) {
    ElMessage.error('加载预览失败')
  }
}

// 把界面上的阈值保存到项目设置
const saveThreshold = async () => {
  try {
    await axios.post('/api/contact-manager/settings',
      { id_match_fields: idMatchFields.value }, { headers: getAuthHeaders() })
  } catch (err) {
    ElMessage.error(err.response?.data?.detail || '保存判定阈值失败')
  }
}

const onHeaderRowChange = async () => {
  updateHeaderColumns()
  // 表头行变了，重新做一次字段匹配，避免沿用旧行的映射
  await rematchFields()
}

const updateHeaderColumns = () => {
  const targetRow = previewRows.value.find(r => r.row_index === headerRow.value)
  headerColumns.value = targetRow ? targetRow.values : []
}

const rematchFields = async () => {
  try {
    const res = await axios.get('/api/contact-manager/match-fields', {
      params: {
        temp_path: tempPath.value,
        sheet_name: selectedSheet.value,
        header_row: headerRow.value
      },
      headers: getAuthHeaders()
    })
    applyAutoMapping(res.data.mapping)
  } catch (err) {
    // 重新匹配失败时，至少按列名给出「新增字段」默认值，不阻断用户手工调整
    applyAutoMapping({})
  }
}

const applyAutoMapping = (autoMap) => {
  const safeMap = autoMap || {}
  // 后端匹配结果可能用字符串或数字做键，统一按字符串取用
  const pick = (idx) => safeMap[idx] ?? safeMap[String(idx)]
  // 已有字段的显示名 -> 字段名，用于兜底匹配（避免重复创建同名字段）
  const labelToName = new Map(dbFields.value.map(f => [String(f.label).trim(), f.name]))

  const newMapping = {}
  headerColumns.value.forEach((colName, idx) => {
    const matched = pick(idx)
    if (matched) {
      // 已匹配到当前项目的现有字段
      newMapping[idx] = matched
      return
    }
    const label = (colName || '').trim()
    if (!label) {
      newMapping[idx] = '__ignore__'
      return
    }
    // 未能匹配到已有字段：若显示名已存在则复用，否则默认按列名新建字段
    newMapping[idx] = labelToName.has(label) ? labelToName.get(label) : `__new__:${label}`
  })
  fieldMapping.value = newMapping
}

const autoDetectMapping = async () => {
  await fetchPreviewData(true)
  ElMessage.success('自动匹配已完成')
}

// 导入前预检：重名情况与跨版本匹配预估
const importPrecheck = ref({ duplicates: [], matched_count: 0, new_count: 0, has_previous: false })

const goToImportConfirm = async () => {
  // 姓名列必须映射：后端以姓名作为联系人主键
  if (!Object.values(fieldMapping.value || {}).includes('name')) {
    ElMessage.warning('请把表格中的姓名列映射到「姓名」字段（用于识别联系人）')
    return
  }
  try {
    const res = await axios.post('/api/contact-manager/import/preview', {
      temp_path: tempPath.value,
      sheet_name: selectedSheet.value,
      header_row: headerRow.value,
      mapping: fieldMapping.value,
    }, { headers: getAuthHeaders() })
    importPrecheck.value = res.data
    if (res.data.duplicate_count > 0) {
      const names = res.data.duplicates.slice(0, 6).map(d => `${d.name}(${d.count}条)`).join('、')
      const more = res.data.duplicates.length > 6 ? ` 等 ${res.data.duplicates.length} 个姓名` : ''
      ElMessage.warning(`检测到重名：${names}${more}；导入时需选择合并或各自保留`)
    }
  } catch (err) {
    // 预检失败不阻断流程，最终以后端导入时的校验为准
    importPrecheck.value = { duplicates: [], matched_count: 0, new_count: 0, has_previous: false }
    ElMessage.warning(err.response?.data?.detail || '预检未完成，可继续导入')
  }
  activeStep.value = 2
}

const handleImport = async () => {
  importing.value = true
  try {
    // 待新建字段去重（多列同名时只建一次）
    const labelsToCreate = [...new Set(pendingNewFields.value)]
    const existingLabels = new Set(dbFields.value.map(f => String(f.label).trim()))
    for (const label of labelsToCreate) {
      if (!label || existingLabels.has(label)) continue
      const name = 'ext_' + Math.random().toString(36).slice(2, 7)
      await axios.post('/api/contact-manager/fields', { name, label }, { headers: getAuthHeaders() })
    }
    const fieldRes = await axios.get('/api/contact-manager/fields', { headers: getAuthHeaders() })
    dbFields.value = fieldRes.data
    const labelToName = new Map(dbFields.value.map(f => [String(f.label).trim(), f.name]))

    const finalMapping = {}
    const unmapped = []
    Object.entries(fieldMapping.value).forEach(([idx, val]) => {
      if (val === '__ignore__' || !val) return
      if (val.startsWith('__new__:')) {
        const label = val.replace('__new__:', '').trim()
        const field = labelToName.get(label)
        if (field) {
          finalMapping[idx] = field
        } else {
          unmapped.push(label)
        }
      } else {
        finalMapping[idx] = val
      }
    })

    if (unmapped.length > 0) {
      throw new Error(`以下列未能创建/匹配字段，请重新选择对应字段：${[...new Set(unmapped)].join('、')}`)
    }

    // 重名处理：由用户选择「合并为一条」或「各自保留」
    let duplicateAction = 'none'
    if (importPrecheck.value.duplicate_count > 0) {
      const names = importPrecheck.value.duplicates
        .slice(0, 8).map(d => `${d.name}（${d.count} 条）`).join('、')
      const more = importPrecheck.value.duplicates.length > 8
        ? ` 等 ${importPrecheck.value.duplicates.length} 个姓名` : ''
      duplicateAction = await ElMessageBox.confirm(
        `检测到重名：${names}${more}。请选择处理方式：`,
        '发现重名',
        {
          distinguishCancelAndClose: true,
          confirmButtonText: '各自保留',
          cancelButtonText: '合并为一条',
          type: 'warning',
        }
      ).then(() => 'separate').catch((action) => {
        if (action === 'cancel') return 'merge'
        throw new Error('已取消导入')
      })
    }

    const res = await axios.post('/api/contact-manager/import', {
      temp_path: tempPath.value,
      sheet_name: selectedSheet.value,
      header_row: headerRow.value,
      mapping: finalMapping,
      duplicate_action: duplicateAction,
      version_date: versionDate.value,
      filename: uploadResult.value.filename
    }, { headers: getAuthHeaders() })

    const skipped = res.data.skipped_count || 0
    const removed = res.data.removed_count || 0
    const isNew = res.data.new_count || 0
    const isMerged = res.data.merged_count || 0
    let msg = `导入成功，本次归档 ${res.data.imported_count} 条记录`
    if (res.data.has_previous !== false) msg += `（匹配到已有 ${isMerged} 条，新增 ${isNew} 条）`
    if (removed > 0) msg += `，标记删除 ${removed} 条`
    if (skipped > 0) msg += `；已跳过 ${skipped} 行（姓名为空）`
    ElMessage.success({ message: msg, duration: 6000 })

    const conflicts = res.data.merge_conflicts || {}
    const conflictKeys = Object.keys(conflicts)
    if (conflictKeys.length) {
      ElMessage.warning({
        message: `合并时以下字段存在多个取值，已用「、」拼接：${conflictKeys.join('、')}`,
        duration: 8000,
      })
    }
    activeStep.value = -1
    currentVersionId.value = res.data.version_id
    await loadVersions()
    await loadContacts()
  } catch (err) {
    ElMessage.error(err.response?.data?.detail || err.message || '导入过程中出错')
  } finally {
    importing.value = false
  }
}

const loadVersions = async () => {
  const res = await axios.get('/api/contact-manager/versions', { headers: getAuthHeaders() })
  versions.value = res.data
  if (!currentVersionId.value && versions.value.length > 0) currentVersionId.value = versions.value[0].id
}

const loadContacts = async () => {
  const params = { keyword: keyword.value }
  if (currentVersionId.value) {
    // 选择了版本 → 只查该版本，日期条件不生效
    params.version_id = currentVersionId.value
  } else if (queryDate.value) {
    // 未选版本 + 选了日期 → 查该日期之前（含当日）所有版本中匹配到的结果
    params.query_date = queryDate.value
  }

  const res = await axios.get('/api/contact-manager/contacts', {
    params,
    headers: getAuthHeaders()
  })
  contacts.value = res.data.contacts
  isHistorical.value = !!res.data.is_historical
  if (res.data.version) {
    currentVersionId.value = res.data.version.id
  } else if (res.data.is_historical) {
    currentVersionId.value = null
  }
}

// 选择了版本归档 → 日期条件不生效，清空日期
const onVersionFilterChange = async () => {
  if (currentVersionId.value) {
    queryDate.value = ''
  }
  await loadContacts()
}

const clearFilters = async () => {
  currentVersionId.value = versions.value[0]?.id || null
  queryDate.value = ''
  keyword.value = ''
  await loadContacts()
}

const exportExcel = () => {
  // 包含密码认证参数通过 Axios 或新窗口
  const url = `/api/contact-manager/export?version_id=${currentVersionId.value || ''}&query_date=${queryDate.value || ''}`
  // 由于普通 a 链接无法带 header，我们通过 axios blob 下载
  axios.get(url, {
    headers: getAuthHeaders(),
    responseType: 'blob'
  }).then(response => {
    const blob = new Blob([response.data], { type: 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet' })
    const link = document.createElement('a')
    link.href = URL.createObjectURL(blob)
    link.download = `${currentProject.value.name}_通讯录导出.xlsx`
    link.click()
    URL.revokeObjectURL(link.href)
  }).catch(() => {
    ElMessage.error('导出失败')
  })
}

const openEditDialog = (row) => {
  editingContact.value = { ...row }
  editDialogVisible.value = true
}

const openAddContactDialog = () => {
  editingContact.value = {}
  editDialogVisible.value = true
}

const saveContact = async () => {
  if (editingContact.value.id) {
    const idx = contacts.value.findIndex(c => c.id === editingContact.value.id)
    if (idx !== -1) {
      contacts.value[idx] = { ...editingContact.value }
    }
    pendingOperations.value.push({
      type: 'upsert',
      id: editingContact.value.id,
      data: { ...editingContact.value }
    })
    ElMessage.success('已暂存修改，点击【保存修改到新版本】正式生效')
  } else {
    const tempId = 'temp_' + Date.now()
    const newRow = { id: tempId, ...editingContact.value }
    contacts.value.unshift(newRow)

    pendingOperations.value.push({
      type: 'upsert',
      data: { ...editingContact.value }
    })
    ElMessage.success('已暂存新增，点击【保存修改到新版本】正式生效')
  }
  editDialogVisible.value = false
}

const deleteContactItem = async (id) => {
  await ElMessageBox.confirm('确定要从当前列表中删除该记录吗？保存后将作为新版本入库。', '提示', { type: 'warning' })

  const target = contacts.value.find(c => c.id === id)
  contacts.value = contacts.value.filter(c => c.id !== id)

  pendingOperations.value.push({
    type: 'delete',
    id: id,
    name: target?.name
  })
  ElMessage.success('已暂存删除，点击【保存修改到新版本】正式生效')
}

const saveOnlineChanges = async () => {
  if (!pendingOperations.value.length) return

  try {
    const { value: newVersionDate } = await ElMessageBox.prompt(
      '请输入本次修改生成的新版本日期 (格式: YYYY-MM-DD):',
      '提交为新版本',
      {
        confirmButtonText: '确定提交',
        cancelButtonText: '取消',
        inputValue: new Date().toISOString().split('T')[0],
        inputPattern: /^\d{4}-\d{2}-\d{2}$/,
        inputErrorMessage: '日期格式不正确 (如 2026-09-10)'
      }
    )

    const res = await axios.post('/api/contact-manager/versions/create-from-latest', {
      version_date: newVersionDate,
      filename: `${newVersionDate.replace(/-/g, '')}_在线修改版本.xlsx`,
      operations: pendingOperations.value
    }, { headers: getAuthHeaders() })

    ElMessage.success(res.data.message || '已成功创建新版本！')
    pendingOperations.value = []
    await loadVersions()
    currentVersionId.value = res.data.new_version_id
    await loadContacts()
  } catch (err) {
    if (err !== 'cancel') {
      ElMessage.error(err.response?.data?.detail || '创建新版本失败')
    }
  }
}

onMounted(() => {
  loadProjects()
})
</script>

<style scoped>
.page-head { display: flex; align-items: center; margin-bottom: 20px; gap: 12px; }
.page-title { margin: 0; font-size: 20px; font-weight: 600; }
.project-indicator { display: flex; align-items: center; }
.step-bar { margin-bottom: 24px; }
.card { background: #fff; padding: 24px; border-radius: 8px; box-shadow: 0 1px 3px rgba(0,0,0,0.1); margin-bottom: 20px; }
.card-title { font-size: 16px; font-weight: 600; margin-bottom: 16px; display: flex; align-items: center; gap: 8px; }
.muted { color: #8c8c8c; font-size: 13px; }
.highlight-header { color: #409EFF; font-weight: bold; background-color: #f0f7ff; }
.mapping-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(240px, 1fr)); gap: 12px; }
.mapping-card-active { border: 1px solid #409eff; background: #f0f9ff; }
.toolbar { background: #fdfdfd; padding: 12px; border-radius: 4px; border: 1px solid #f0f0f0; }

.project-card { height: 100%; display: flex; flex-direction: column; justify-content: space-between; }
.project-desc { font-size: 14px; color: #606266; margin-bottom: 12px; min-height: 40px; }
.project-meta { font-size: 12px; line-height: 1.6; }
</style>
