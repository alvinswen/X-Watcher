/** 用户管理 API 客户端。 */

import { client } from "./client"
import type {
  UserInfo,
  CreateUserRequest,
  CreateUserResponse,
  ResetPasswordResponse,
  UpdateUserRequest,
  UserFollow,
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

  /** 更新用户信息 */
  async update(userId: number, data: UpdateUserRequest): Promise<UserInfo> {
    const response = await client.put<UserInfo>(
      `${USERS_PREFIX}/${userId}`,
      data,
    )
    return response.data
  },

  /** 获取用户关注列表 */
  async getUserFollows(userId: number): Promise<UserFollow[]> {
    const response = await client.get<UserFollow[]>(
      `${USERS_PREFIX}/${userId}/follows`,
    )
    return response.data
  },

  /** 为用户添加关注 */
  async addUserFollow(
    userId: number,
    username: string,
  ): Promise<UserFollow> {
    const response = await client.post<UserFollow>(
      `${USERS_PREFIX}/${userId}/follows`,
      { username },
    )
    return response.data
  },

  /** 为用户移除关注 */
  async removeUserFollow(
    userId: number,
    username: string,
  ): Promise<void> {
    await client.delete(`${USERS_PREFIX}/${userId}/follows/${username}`)
  },
}
