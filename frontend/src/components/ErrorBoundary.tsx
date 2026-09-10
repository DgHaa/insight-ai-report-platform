import React from 'react';
import { Button, Result } from 'antd';

interface Props {
  children: React.ReactNode;
}

interface State {
  error: Error | null;
}

/**
 * 全局错误边界：捕获渲染期异常，避免任一组件抛错导致整页白屏。
 * 仅覆盖渲染/生命周期错误；事件回调中的异常仍需业务代码自行 try/catch。
 */
export class ErrorBoundary extends React.Component<Props, State> {
  state: State = { error: null };

  static getDerivedStateFromError(error: Error): State {
    return { error };
  }

  componentDidCatch(error: Error, info: React.ErrorInfo) {
    // 保留现场信息，便于定位
    console.error('[ErrorBoundary] 渲染异常:', error, info.componentStack);
  }

  private handleReload = () => {
    window.location.reload();
  };

  render() {
    const { error } = this.state;
    if (error) {
      return (
        <div style={{ display: 'flex', justifyContent: 'center', paddingTop: 80 }}>
          <Result
            status="error"
            title="页面出错了"
            subTitle={error.message || '发生了未预期的渲染异常'}
            extra={
              <Button type="primary" onClick={this.handleReload}>
                重新加载
              </Button>
            }
          />
        </div>
      );
    }
    return this.props.children;
  }
}

export default ErrorBoundary;
