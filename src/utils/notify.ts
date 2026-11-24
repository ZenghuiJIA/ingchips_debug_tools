import { ref } from 'vue';

export type NotifyType = 'info' | 'success' | 'warn' | 'error';

export interface ToastItem {
  id: number;
  message: string;
  type: NotifyType;
}

export interface ConfirmState {
  open: boolean;
  title: string;
  message: string;
}

export const toasts = ref<ToastItem[]>([]);
export const confirmState = ref<ConfirmState>({
  open: false,
  title: '确认操作',
  message: '',
});

let nextToastId = 1;
let pendingConfirmResolve: ((accepted: boolean) => void) | null = null;

export function dismissToast(id: number): void {
  toasts.value = toasts.value.filter((item) => item.id !== id);
}

export function notify(message: string, type: NotifyType = 'info', durationMs = 4200): void {
  const id = nextToastId++;
  toasts.value = [...toasts.value.slice(-4), { id, message: String(message), type }];
  if (durationMs > 0 && typeof setTimeout === 'function') {
    setTimeout(() => dismissToast(id), durationMs);
  }
}

export function notifyInfo(message: string): void {
  notify(message, 'info');
}

export function notifySuccess(message: string): void {
  notify(message, 'success');
}

export function notifyWarn(message: string): void {
  notify(message, 'warn', 5000);
}

export function notifyError(message: string): void {
  notify(message, 'error', 6000);
}

export function confirmAction(message: string, title = '确认操作'): Promise<boolean> {
  if (pendingConfirmResolve) {
    pendingConfirmResolve(false);
    pendingConfirmResolve = null;
  }
  confirmState.value = { open: true, title, message };
  return new Promise<boolean>((resolve) => {
    pendingConfirmResolve = resolve;
  });
}

export function resolveConfirm(accepted: boolean): void {
  confirmState.value = { ...confirmState.value, open: false };
  const resolve = pendingConfirmResolve;
  pendingConfirmResolve = null;
  if (resolve) resolve(accepted);
}
