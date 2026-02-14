/** 用户管理 API 客户端。 */

import { client } from "./client"
import type {
  UserInfo,
  CreateUserRequest,
  CreateUserResponse,
  ResetPasswordResponse,
} from "@/types"

/** 用户管理 API 路径前缀 */
const USERS_PREFIX = "/admin/users"

/** 用户管理 API 客户端 */
export const usersApi = {
  /** 获取用户列表 */
  async list(): Promise<UserInfo[]> {
    const response = await client.get<UserInfo[]>(USERS_PREFIX)
    return response.data
  },

  /** 创建用户 */
  async create(data: CreateUserRequest): Promise<CreateUserResponse> {
    const response = await client.post<CreateUserResponse>(
      USERS_PREFIX,
      data,
    )
    return response.data
  },

  /** 重置用户密码 */
  async resetPassword(userId: number): Promise<ResetPasswordResponse> {
    const response = await client.post<ResetPasswordResponse>(
      `${USERS_PREFIX}/${userId}/reset-password`,
    )
    return response.data
  },
}
