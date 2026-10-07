<template>
  <div class="split">
    <section class="pane">
      <h2>可借物</h2>
      <div v-for="i in board.available" :key="i.id" class="item">
        <strong>{{ i.title }}</strong>
        <div class="muted">物主 {{ i.owner || '—' }}</div>
        <input v-model="forms[i.id].borrower" placeholder="借用人" />
        <input v-model="forms[i.id].due_date" type="date" />
        <input v-model="forms[i.id].due_time" type="time" title="截止钟点（可空）" />
        <div class="muted">截止钟点可空；留空按应还日 00:00 计。钟点非法整单失败。</div>
        <button @click="lend(i.id)">借出通过</button>
        <div v-if="errors[i.id]" class="err">{{ errors[i.id] }}</div>
      </div>
    </section>
    <section class="pane">
      <h2>在借 / 逾期</h2>
      <div v-for="l in [...board.overdue, ...board.active]" :key="l.id"
           class="item" :class="{ overdue: l.overdue }">
        <strong>{{ l.title }}</strong> → {{ l.borrower }}
        <!-- 主行只到日期；截止钟点作为详情另起一行，逾期结论来自后端同一标记 -->
        <div class="muted">
          应还 {{ l.due_date }}<template v-if="l.due_time"> · 截止 {{ l.due_time }}</template>
          · {{ l.overdue ? '已过点 · 逾期' : '未到点' }}
        </div>
        <button @click="ret(l.id)">归还</button>
        <button @click="grace(l.id, 3)">宽限3天</button>
        <select v-model="policies[l.id]" class="policy" title="顺延时分策略">
          <option value="follow">时分跟新日走</option>
          <option value="keep">钉在原时刻</option>
        </select>
        <button @click="extend(l.id, 3)">顺延3天</button>
      </div>
    </section>
  </div>
</template>
<script setup>
import { inject, reactive, watch } from 'vue'
import { api } from '../api'
const board = inject('board')
const reload = inject('reloadBoard')
const forms = reactive({})
const policies = reactive({})
const errors = reactive({})
watch(board, (b) => {
  for (const i of (b.available || [])) {
    if (!forms[i.id]) forms[i.id] = { borrower: '邻居', due_date: '2026-12-31', due_time: '' }
  }
  for (const l of [...(b.active || []), ...(b.overdue || [])]) {
    if (!policies[l.id]) policies[l.id] = 'follow'
  }
}, { immediate: true, deep: true })
async function lend(id) {
  errors[id] = ''
  try {
    await api('/items/' + id + '/lend', { method: 'POST', body: JSON.stringify(forms[id]) })
    await reload()
  } catch (e) { errors[id] = e.message }
}
async function ret(id) {
  await api('/loans/' + id + '/return', { method: 'POST', body: '{}' })
  await reload()
}
async function grace(id, days) {
  await api('/loans/' + id + '/grace', { method: 'POST', body: JSON.stringify({ days }) })
  await reload()
}
async function extend(id, days) {
  await api('/loans/' + id + '/extend', {
    method: 'POST',
    body: JSON.stringify({ days, time_policy: policies[id] || 'follow' }),
  })
  await reload()
}
</script>
