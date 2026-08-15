import { createApp } from 'vue'
import { createPinia } from 'pinia'
import { Quasar, Notify } from 'quasar'
import '@quasar/extras/material-icons/material-icons.css'
import 'quasar/src/css/index.sass'
import '@/styles/app.scss'
import App from './App.vue'
import router from './router'
import { i18n } from '@/i18n'

const app = createApp(App)
app.use(createPinia()).use(router).use(i18n).use(Quasar, { plugins: { Notify } }).mount('#app')
