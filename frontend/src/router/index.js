import { createRouter, createWebHistory } from 'vue-router'

const router = createRouter({
  history: createWebHistory(),
  routes: [
    {
      path: '/',
      name: 'home',
      component: () => import('../views/HomeView.vue'),
      meta: { title: '工具列表' },
    },
    {
      path: '/tools/excel-split',
      name: 'excel-split',
      component: () => import('../views/ExcelSplitView.vue'),
      meta: { title: 'Excel 表格拆分' },
    },
    {
      path: '/tools/doc-convert',
      name: 'doc-convert',
      component: () => import('../views/DocConvertView.vue'),
      meta: { title: '文档转换' },
    },
    {
      path: '/tools/excel-diff',
      name: 'excel-diff',
      component: () => import('../views/ExcelDiffView.vue'),
      meta: { title: 'Excel 表格比对' },
    },
    {
      path: '/:pathMatch(.*)*',
      redirect: '/',
    },
  ],
})

router.afterEach((to) => {
  document.title = to.meta.title ? `${to.meta.title} - Lab Tools` : 'Lab Tools'
})

export default router