import { useCallback } from 'react';
import { useLocation, useNavigate } from 'react-router-dom';

/**
 * 返回导航 Hook（统一返回逻辑）。
 *
 * 判定优先级：
 * 1. `location.state.from`（如登录后由守卫/来源页跳转进入）→ 回到来源页；
 * 2. 浏览器存在可回退历史（React Router 中 `location.key !== 'default'`，
 *    即非直接通过 URL 首次进入）→ `navigate(-1)` 保留上一页的筛选/分页状态；
 * 3. 无历史（直接通过 URL 进入的深层链接）→ 跳转 `fallbackPath`（replace，
 *    避免在历史栈中堆积无效记录）。
 */
export function useBackNavigation(fallbackPath: string): () => void {
  const navigate = useNavigate();
  const location = useLocation();

  return useCallback(() => {
    const state = location.state as { from?: string } | null;
    if (state?.from) {
      navigate(state.from, { replace: true });
      return;
    }
    if (location.key !== 'default') {
      navigate(-1);
    } else {
      navigate(fallbackPath, { replace: true });
    }
  }, [fallbackPath, location.key, location.state, navigate]);
}
