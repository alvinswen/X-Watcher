import type { SubjectReview } from "@/types"

/** hasTrend 判定——必须以「所看版本」的 review 调用（CHG-050: 回看态显隐错位修正）。 */
export function reviewHasTrendOf(review: SubjectReview | null): boolean {
  return (review?.version ?? 0) >= 2
    && Boolean(review?.trend.emerging.length || review?.trend.fading.length)
}
