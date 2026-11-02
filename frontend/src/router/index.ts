import { createRouter, createWebHistory } from 'vue-router'
import RemoteView from '../views/RemoteView.vue'

const router = createRouter({
  history: createWebHistory(import.meta.env.BASE_URL),
  routes: [
    {
      path: '/',
      name: 'remote',
      component: RemoteView
    },
    {
      path: '/catalog',
      name: 'catalog',
      component: () => import('../views/CatalogView.vue')
    },
    {
      path: '/appearance',
      name: 'appearance',
      component: () => import('../views/AppearanceView.vue')
    },
    {
      path: '/settings',
      name: 'settings',
      component: () => import('../views/SettingsView.vue')
    },
    {
      path: '/optimizer',
      name: 'optimizer',
      component: () => import('../views/OptimizerView.vue')
    },
    {
      path: '/agendador',
      name: 'agendador',
      component: () => import('../views/AgendadorView.vue')
    },
    {
      path: '/sistema',
      name: 'sistema',
      component: () => import('../views/SistemaView.vue')
    }
  ]
})

export default router
