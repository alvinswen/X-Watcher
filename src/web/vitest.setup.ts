const storage = new Map<string, string>()

const memoryStorage: Storage = {
  get length() {
    return storage.size
  },
  clear() {
    storage.clear()
  },
  getItem(key) {
    return storage.get(String(key)) ?? null
  },
  key(index) {
    return Array.from(storage.keys())[index] ?? null
  },
  removeItem(key) {
    storage.delete(String(key))
  },
  setItem(key, value) {
    storage.set(String(key), String(value))
  },
}

if (!globalThis.localStorage) {
  Object.defineProperty(globalThis, "localStorage", {
    configurable: true,
    value: memoryStorage,
  })
}
