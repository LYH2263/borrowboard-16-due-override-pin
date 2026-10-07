<template>
  <div class="split">
    <section class="pane">
      <h2>可借物</h2>
      <div v-for="i in board.available" :key="i.id" class="item">
        <strong>{{ i.title }}</strong>
        <div class="muted">物主 {{ i.owner || '—' }}</div>
        <input v-model="forms[i.id].borrower" placeholder="借用人" />
        <input v-model="forms[i.id].due_date" placeholder="应还日 YYYY-MM-DD" />
        <input v-model="forms[i.id].due_time" placeholder="截止钟点 HH:MM（可空）" />
        <button @click="lend(i.id)">借出通过</button>
      </div>
    </section>
    <section class="pane">
      <h2>在借 / 逾期</h2>
      <div v-for="l in [...board.overdue, ...board.active]" :key="l.id"
           class="item loan-row" :class="{ overdue: l.overdue }"
           @click="open(l.id)">
        <strong>{{ l.title }}</strong> → {{ l.borrower }}
        <!-- 主行只显示借出那天的日期；时分点进顶细条看 -->
        <div class="muted">应还 {{ l.due_date }} {{ l.overdue ? '· 逾期' : '' }}</div>
        <button @click.stop="ret(l.id)">归还</button>
      </div>
    </section>
  </div>
</template>
<script setup>
import { inject, reactive, watch } from 'vue'
import { useRouter } from 'vue-router'
import { api } from '../api'
const board = inject('board')
const reload = inject('reloadBoard')
const router = useRouter()
const forms = reactive({})
watch(board, (b) => {
  for (const i of (b.available || [])) {
    if (!forms[i.id]) forms[i.id] = { borrower: '邻居', due_date: '2026-12-31', due_time: '' }
  }
}, { immediate: true, deep: true })
async function lend(id) {
  try {
    // 钟点非法（如 25 点或缺分钟）后端会整单拒绝，不产生任何借阅
    await api('/items/' + id + '/lend', { method: 'POST', body: JSON.stringify(forms[id]) })
    await reload()
  } catch (e) { alert('借出失败：' + e.message) }
}
async function ret(id) {
  await api('/loans/' + id + '/return', { method: 'POST', body: '{}' })
  await reload()
}
function open(id) { router.push('/loans/' + id) }
</script>
