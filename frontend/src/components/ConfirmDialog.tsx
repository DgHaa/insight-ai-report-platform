import { Modal } from 'antd';
import { ExclamationCircleOutlined } from '@ant-design/icons';

/**
 * 通用确认对话框
 *
 * 注意：调用方常传入 async 回调（内部 await 接口）。antd 的 Modal.confirm 不会
 * 捕获 onOk 返回的 promise 拒绝，若直接抛出会产生 unhandled rejection 且弹窗不关闭。
 * 这里统一 try/catch 兜底：错误提示已由 http 响应拦截器统一展示，此处仅吞掉拒绝，
 * 使弹窗正常关闭且不产生未处理拒绝。
 */
export function confirmAction(
  title: string,
  content: string,
  onOk: () => void | Promise<void>,
  danger = true,
) {
  Modal.confirm({
    title,
    icon: <ExclamationCircleOutlined />,
    content,
    okText: '确定',
    cancelText: '取消',
    okButtonProps: { danger },
    onOk: async () => {
      try {
        await onOk();
      } catch {
        // 已由 http 拦截器提示错误信息，无需重复 toast
      }
    },
  });
}
