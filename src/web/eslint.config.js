// 前端体检门禁 · 正确性档（CHG-048 · Q1=A）
// 档位语义：只拦「真错误」（类型正确性 + Vue 契约正确性），不拦风格（454 条风格类留 prettier 专项）
import pluginVue from "eslint-plugin-vue"
import tseslint from "typescript-eslint"

export default tseslint.config(
  { ignores: ["dist/**", "node_modules/**", "coverage/**"] },
  ...tseslint.configs.recommended,
  ...pluginVue.configs["flat/essential"],
  {
    files: ["**/*.vue"],
    languageOptions: {
      parserOptions: { parser: tseslint.parser },
    },
  },
)
