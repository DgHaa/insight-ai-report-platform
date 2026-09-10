import { Button } from 'antd';
import { ArrowLeftOutlined } from '@ant-design/icons';
import { useBackNavigation } from '../hooks/useBackNavigation';

interface BackButtonProps {
  /** 无历史记录（直接通过 URL 进入）时的回退路径 */
  fallback: string;
  /** 按钮文案，默认“返回” */
  text?: string;
}

/** 页面统一的“返回”按钮：优先回退上一页，无历史时跳转 fallback 路径。 */
export default function BackButton({ fallback, text = '返回' }: BackButtonProps) {
  const goBack = useBackNavigation(fallback);
  return (
    <Button icon={<ArrowLeftOutlined />} onClick={goBack}>
      {text}
    </Button>
  );
}
