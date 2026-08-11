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
      path: '/:pathMatch(.*)*',
      redirect: '/',
    },
  ],
})

router.afterEach((to) => {
  document.title = to.meta.title ? `${to.meta.title} - Lab Tools` : 'Lab Tools'
})

export default router