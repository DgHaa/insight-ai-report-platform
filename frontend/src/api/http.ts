import axios, { AxiosInstance, AxiosResponse } from 'axios';
import { message } from 'antd';
import { useAuthStore } from '../store/auth';

export class BizError extends Error {
  code: number;
  constructor(code: number, msg: string) {
    super(msg);
    this.code = code;
  }
}

const baseURL = import.meta.env.VITE_API_BASE || '/api/v1';

export const http: AxiosInstance = axios.create({
  baseURL,
  timeout: 60000,
});

// 请求拦截：自动注入 JWT token
http.interceptors.request.use((config) => {
  const token = useAuthStore.getState().token;
  if (token) {
    config.headers.Authorization = `Bearer ${token}`;
  }
  return config;
});

// 响应拦截：统一处理认证失效 / 网络错误
http.interceptors.response.use(
  (resp) => resp,
  (error) => {
    const status = error.response?.status;
    if (status === 401) {
      const url = error.config?.url || '';
      const isLoginRequest = url.includes('/auth/login');
      if (isLoginRequest) {
        // 登录失败：展示后端细分提示（用户名/部门不匹配、账号禁用），不清空登录态
        const msg = error.response?.data?.message;
        message.error(typeof msg === 'string' && msg ? msg : '登录失败，请检查用户名与部门');
      } else {
        useAuthStore.getState().clearAuth();
        message.error('登录已过期，请重新登录');
        if (!window.location.pathname.startsWith('/login')) {
          window.location.href = '/login';
        }
      }
    } else if (status === 403) {
      message.error('无权限执行该操作');
    } else if (error.response) {
      const msg = error.response.data?.message;
      if (msg && typeof msg === 'string') message.error(msg);
      else message.error('请求失败');
    } else {
      message.error('网络连接失败，请检查服务是否启动');
    }
    return Promise.reject(error);
  },
);

async function unwrap<T>(promise: Promise<AxiosResponse>): Promise<T> {
  const resp = await promise;
  const body = resp.data;
  if (body && typeof body.code === 'number') {
    if (body.code !== 0) {
      const msg = body.message || '请求失败';
      if (msg !== 'success') message.error(msg);
      throw new BizError(body.code, msg);
    }
    return body.data as T;
  }
  return body as T;
}

export const request = {
  get: <T>(url: string, params?: Record<string, unknown>) =>
    unwrap<T>(http.get(url, { params })),
  post: <T>(url: string, data?: unknown) => unwrap<T>(http.post(url, data)),
  put: <T>(url: string, data?: unknown) => unwrap<T>(http.put(url, data)),
  del: <T>(url: string) => unwrap<T>(http.delete(url)),
};

/** 文件下载（导出功能），支持从 Content-Disposition 解析文件名 */
export async function downloadFile(
  url: string,
  params?: Record<string, unknown>,
): Promise<void> {
  const resp = await http.get(url, { params, responseType: 'blob' });

  // 后端异常时可能以 JSON 错误体返回，此时不能当作文件下载，
  // 否则用户会拿到一个“错误 JSON blob”且被提示“导出成功”。
  const blob = resp.data as Blob | undefined;
  if (blob && blob.type && /json/i.test(blob.type)) {
    let msg = '导出失败';
    let code = -1;
    try {
      const body = JSON.parse(await blob.text());
      if (body && typeof body.message === 'string' && body.message) {
        msg = body.message;
      }
      if (body && typeof body.code === 'number') {
        code = body.code;
      }
    } catch {
      /* 解析失败则沿用默认文案与通用错误码 */
    }
    throw new BizError(code, msg);
  }

  const cd = resp.headers['content-disposition'] as string | undefined;
  let filename = 'download';
  if (cd) {
    // 优先解析 RFC5987 文件名（支持中文）：filename*=UTF-8''xxx
    const star = /filename\*=UTF-8''([^;]+)/i.exec(cd);
    if (star) {
      filename = decodeURIComponent(star[1]);
    } else {
      const plain = /filename="?([^";]+)"?/.exec(cd);
      if (plain) filename = decodeURIComponent(plain[1]);
    }
  }
  const blobUrl = URL.createObjectURL(resp.data);
  const a = document.createElement('a');
  a.href = blobUrl;
  a.download = filename;
  // 挂载到 DOM 后再触发点击，兼容性更稳，点击后移除并释放 URL
  document.body.appendChild(a);
  a.click();
  a.remove();
  URL.revokeObjectURL(blobUrl);
}
