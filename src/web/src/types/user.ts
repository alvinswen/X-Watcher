/** 用户相关类型定义。 */

/** 用户信息。 */
export interface UserInfo {
  /** 用户 ID */
  id: number
  /** 用户名称 */
  name: string
  /** 用户邮箱 */
  email: string
  /** 是否为管理员 */
  is_admin: boolean
  /** 创建时间 */
  created_at: string
}

/** 创建用户请求。 */
export interface CreateUserRequest {
  /** 用户名称 */
  name: string
  /** 用户邮箱 */
  email: string
}

/** 创建用户响应。 */
export interface CreateUserResponse {
  /** 用户信息 */
  user: UserInfo
  /** 临时密码 */
  temp_password: string
  /** API Key */
  api_key: string
}

/** 重置密码响应。 */
export interface ResetPasswordResponse {
  /** 新临时密码 */
  temp_password: string
}

/** 更新用户请求。 */
export interface UpdateUserRequest {
  /** 用户名称 */
  name?: string
  /** 用户邮箱 */
  email?: string
  /** 是否为管理员 */
  is_admin?: boolean
}

/** 用户关注记录。 */
export interface UserFollow {
  /** 关注记录 ID */
  id: number
  /** 用户 ID */
  user_id: number
  /** Twitter 用户名 */
  username: string
  /** 创建时间 */
  created_at: string
}

/** 批量关注失败项。 */
export interface BatchFollowError {
  username: string
  reason: string
}

/** 批量关注响应。 */
export interface BatchFollowResponse {
  succeeded: string[]
  failed: BatchFollowError[]
  total: number
  succeeded_count: number
  failed_count: number
}
