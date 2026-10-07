<template>
  <div style="padding:16px">
    <h1>借还记录</h1>
    <h3>逾期</h3>
    <div v-for="l in data.overdue" :key="'o'+l.id" class="item overdue">
      <div>{{ l.title }} · {{ l.borrower }} · 应还 {{ l.due_date }}</div>
      <div class="muted">截止 {{ l.due_time || '—' }} · 已过点</div>
    </div>
    <h3>在借</h3>
    <div v-for="l in data.active" :key="'a'+l.id" class="item">
      <div>{{ l.title }} · {{ l.borrower }} · 应还 {{ l.due_date }}</div>
      <div class="muted">截止 {{ l.due_time || '—' }} · {{ l.overdue ? '已过点' : '未到点' }}</div>
    </div>
    <h3>已还</h3>
    <div v-for="l in data.returned" :key="'r'+l.id" class="item" :class="{ overdue: l.overdue }">
      <div>{{ l.title }} · {{ l.borrower }} · 应还 {{ l.due_date }}</div>
      <div class="muted">
        截止 {{ l.due_time || '—' }} · 归还时刻{{ l.overdue ? '已过点（逾期笔）' : '未到点' }}
      </div>
    </div>
  </div>
</template>
<script setup>
import { ref, onMounted } from 'vue'
import { api } from '../api'
const data = ref({ active: [], overdue: [], returned: [] })
onMounted(async () => { data.value = await api('/loans') })
</script>
