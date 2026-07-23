const REVIEW_PENDING_KEY_PREFIX = "subject-review-pending:"

export interface ReviewPendingStorage {
  getItem(key: string): string | null
  setItem(key: string, value: string): void
  removeItem(key: string): void
}

function browserStorage(): ReviewPendingStorage | null {
  try {
    return window.localStorage
  } catch {
    return null
  }
}

export function reviewPendingKey(subjectId: string): string {
  return `${REVIEW_PENDING_KEY_PREFIX}${subjectId}`
}

export function readReviewPending(
  subjectId: string,
  currentVersion: number,
  sessionPendingReviews: Record<string, number>,
  storage: ReviewPendingStorage | null = browserStorage(),
): boolean {
  const sessionVersion = sessionPendingReviews[subjectId]
  let pending = sessionVersion === currentVersion
  if (sessionVersion !== undefined && sessionVersion !== currentVersion) {
    delete sessionPendingReviews[subjectId]
  }

  if (!storage) {
    return pending
  }

  try {
    const raw = storage.getItem(reviewPendingKey(subjectId))
    if (!raw) {
      return pending
    }
    const parsed = JSON.parse(raw) as { pending?: unknown; version?: unknown }
    const storedVersion = Number(parsed.version)
    if (parsed.pending === true && Number.isFinite(storedVersion) && storedVersion === currentVersion) {
      pending = true
    } else {
      storage.removeItem(reviewPendingKey(subjectId))
    }
  } catch {
    try {
      storage.removeItem(reviewPendingKey(subjectId))
    } catch {
      // Ignore storage cleanup failures.
    }
  }

  return pending
}

export function markReviewPending(
  subjectId: string,
  version: number,
  sessionPendingReviews: Record<string, number>,
  storage: ReviewPendingStorage | null = browserStorage(),
): true {
  sessionPendingReviews[subjectId] = version
  try {
    storage?.setItem(
      reviewPendingKey(subjectId),
      JSON.stringify({ pending: true, version }),
    )
  } catch {
    // localStorage can be unavailable in private mode; session state remains usable.
  }
  return true
}
