<script setup lang="ts">
import { computed } from "vue"
import type { FormInstance, FormRules } from "element-plus"
import type { SubjectStatus } from "@/types"

interface SubjectForm {
  name: string
  nl_description: string
  keywords: string[]
  status: SubjectStatus
}

const props = defineProps<{
  visible: boolean
  title: string
  form: SubjectForm
  rules: FormRules<SubjectForm>
  formRef?: FormInstance
  keywordInput: string
  error: string
  submitting: boolean
}>()

const emit = defineEmits<{
  "update:visible": [value: boolean]
  "update:formRef": [value: FormInstance | undefined]
  "update:keywordInput": [value: string]
  addKeyword: []
  removeKeyword: [keyword: string]
  submit: []
}>()

const visibleModel = computed({
  get: () => props.visible,
  set: (value: boolean) => emit("update:visible", value),
})
</script>

<template>
  <el-drawer
    v-model="visibleModel"
    :title="title"
    direction="rtl"
    size="480px"
    class="subject-drawer"
  >
    <el-form
      :ref="(value: unknown) => $emit('update:formRef', value as FormInstance | undefined)"
      :model="form"
      :rules="rules"
      label-position="top"
    >
      <el-form-item label="议题名" prop="name">
        <el-input v-model="form.name" maxlength="120" show-word-limit />
      </el-form-item>
      <el-form-item label="语义描述" prop="nl_description">
        <el-input v-model="form.nl_description" type="textarea" :rows="6" />
      </el-form-item>
      <el-form-item label="关键词">
        <div class="keyword-editor">
          <el-tag
            v-for="keyword in form.keywords"
            :key="keyword"
            closable
            type="info"
            @close="$emit('removeKeyword', keyword)"
          >
            {{ keyword }}
          </el-tag>
          <el-input
            :model-value="keywordInput"
            class="keyword-input"
            placeholder="输入后回车"
            @update:model-value="$emit('update:keywordInput', $event)"
            @keydown.enter.prevent="$emit('addKeyword')"
            @blur="$emit('addKeyword')"
          />
        </div>
      </el-form-item>
      <el-form-item label="状态">
        <el-radio-group v-model="form.status">
          <el-radio-button label="active">活跃</el-radio-button>
          <el-radio-button label="paused">暂停</el-radio-button>
        </el-radio-group>
      </el-form-item>
      <el-alert v-if="error" type="error" :closable="false" show-icon>
        {{ error }}
      </el-alert>
    </el-form>

    <template #footer>
      <el-button @click="visibleModel = false">取消</el-button>
      <el-button type="primary" :loading="submitting" @click="$emit('submit')">
        保存
      </el-button>
    </template>
  </el-drawer>
</template>
