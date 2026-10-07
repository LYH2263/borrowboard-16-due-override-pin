<template>
  <div style="padding:16px;max-width:520px">
    <router-link to="/loans">← 借还记录</router-link>
    <h1>借阅详情</h1>
    <div v-if="loan" class="item" :class="{ overdue: loan.overdue }">
      <strong>{{ loan.title }}</strong> → {{ loan.borrower }}
      <!-- 顶细条：日期之外必须能看见时分 -->
      <div class="muted">
        应还 {{ loan.due_date }}<template v-if="loan.due_time"> {{ loan.due_time }}</template>
        （全板宽限 {{ loan.grace_days }} 个自然日，钟点不被宽限清掉）
      </div>
      <div v-if="loan.status === 'active'">
        <strong v-if="loan.overdue">已过点 · 逾期</strong>
        <strong v-else>尚未过点</strong>
      </div>
      <div v-else class="muted">已还 {{ loan.returned_at }}</div>

      <template v-if="loan.status === 'active'">
        <hr />
        <h3>顺延</h3>
        <input v-model.number="days" type="number" min="0" placeholder="顺延自然日" />
        <div class="policies">
          <label><input type="radio" value="follow_day" v-model="time_policy" /> 时分跟着新日走（原无钟点仍整日）</label>
          <label><input type="radio" value="keep_time" v-model="time_policy" /> 钉在原时刻（原无钟点钉 23:59）</label>
        </div>
        <button @click="extend">顺延</button>
        <hr />
        <button @click="ret">归还（逾期结论与分栏一致）</button>
      </template>
    </div>
  </div>
</template>
<script setup>
import { ref, onMounted } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { api } from '../api'
const route = useRoute()
const router = useRouter()
const loan = ref(null)
const days = ref(1)
const time_policy = ref('follow_day')
async function load() { loan.value = await api('/loans/' + route.params.id) }
async function extend() {
  await api('/loans/' + route.params.id + '/extend', {
    method: 'POST', body: JSON.stringify({ days: Number(days.value) || 0, time_policy: time_policy.value }),
  })
  await load()
}
async function ret() {
  const r = await api('/loans/' + route.params.id + '/return', { method: 'POST', body: '{}' })
  await load()
  alert(r.overdue ? '该笔按逾期归还' : '该笔未逾期')
}
onMounted(load)
</script>
