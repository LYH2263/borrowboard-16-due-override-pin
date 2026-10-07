<template>
  <div style="padding:16px">
    <h1>借还记录</h1>
    <h3>逾期</h3>
    <router-link v-for="l in data.overdue" :key="'o'+l.id" :to="'/loans/'+l.id" custom v-slot="{ navigate }">
      <div class="item overdue loan-row" @click="navigate">{{ l.title }} · {{ l.borrower }} · 应还 {{ l.due_date }}</div>
    </router-link>
    <h3>在借</h3>
    <router-link v-for="l in data.active" :key="'a'+l.id" :to="'/loans/'+l.id" custom v-slot="{ navigate }">
      <div class="item loan-row" @click="navigate">{{ l.title }} · {{ l.borrower }} · 应还 {{ l.due_date }}</div>
    </router-link>
    <h3>已还</h3>
    <router-link v-for="l in data.returned" :key="'r'+l.id" :to="'/loans/'+l.id" custom v-slot="{ navigate }">
      <div class="item loan-row" @click="navigate">{{ l.title }} · {{ l.borrower }} · 应还 {{ l.due_date }}</div>
    </router-link>
  </div>
</template>
<script setup>
import { ref, onMounted } from 'vue'
import { api } from '../api'
const data = ref({ active: [], overdue: [], returned: [] })
onMounted(async () => { data.value = await api('/loans') })
</script>
