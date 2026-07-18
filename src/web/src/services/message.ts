/** 消息提示服务。 */

import { h } from "vue"
import { ElMessage } from "element-plus"

/** 消息类型。 */
export type MessageType = "success" | "warning" | "info" | "error"

/** 显示成功消息。 */
export function showSuccess(message: string): void {
  ElMessage.success(message)
}

/** 显示警告消息。 */
export function showWarning(message: string): void {
  ElMessage.warning(message)
}

/** 显示信息消息。 */
export function showInfo(message: string): void {
  ElMessage.info(message)
}

/** 显示错误消息。 */
let lastErrorMessage = ""
let lastErrorAt = 0

export function showError(message: string): void {
  const now = Date.now()
  if (message === lastErrorMessage && now - lastErrorAt < 2000) {
    return
  }
  lastErrorMessage = message
  lastErrorAt = now
  ElMessage.error(message)
}

/** 显示带恢复动作的错误消息。 */
export function showErrorWithAction(
  message: string,
  actionLabel: string,
  onAction: () => void,
): void {
  ElMessage({
    type: "error",
    message: h("span", { "data-testid": "global-error-toast" }, [
      message,
      " ",
      h(
        "button",
        {
          "data-testid": "global-error-toast-action",
          onClick: onAction,
          type: "button",
        },
        actionLabel,
      ),
    ]),
  })
}

/** 消息服务对象。 */
export const messageService = {
  success: showSuccess,
  warning: showWarning,
  info: showInfo,
  error: showError,
  errorWithAction: showErrorWithAction,
}
