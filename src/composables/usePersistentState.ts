import { ref, watch, type Ref } from 'vue';

/**
 * 响应式持久化状态管理器 (Persistent State Composable)
 * 包装标准 Vue ref，当值变更时自动写回 localStorage；
 * 软件重启或页面刷新时自动读取上一次保存的状态。
 *
 * @param key 存储键名，建议前缀 'hil_cfg_'
 * @param defaultValue 首次使用时的默认兜底值
 */
export function usePersistentState<T>(key: string, defaultValue: T): Ref<T> {
  const readInitial = (): T => {
    try {
      const stored = localStorage.getItem(key);
      if (stored !== null) {
        return JSON.parse(stored) as T;
      }
    } catch (e) {
      console.warn(`[usePersistentState] Error parsing key ${key}:`, e);
    }
    return defaultValue;
  };

  const state = ref<T>(readInitial()) as Ref<T>;

  watch(
    state,
    (newVal) => {
      try {
        if (newVal === undefined) {
          localStorage.removeItem(key);
        } else {
          localStorage.setItem(key, JSON.stringify(newVal));
        }
      } catch (e) {
        console.warn(`[usePersistentState] Error persisting key ${key}:`, e);
      }
    },
    { deep: true }
  );

  return state;
}
