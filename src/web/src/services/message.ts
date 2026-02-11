/** 消息提示服务。 */

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
export function showError(message: string): void {
  ElMessage.error(message)
}

/** 消息服务对象。 */
export const messageService = {
  success: showSuccess,
  warning: showWarning,
  info: showInfo,
  error: showError,
}
