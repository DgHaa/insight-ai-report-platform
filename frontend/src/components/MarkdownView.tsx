import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import rehypeHighlight from 'rehype-highlight';

interface Props {
  content?: string;
  /** 追加到 markdown-body 容器上的自定义类名（用于风格作用域） */
  className?: string;
}

/** Markdown → HTML 渲染（GFM + 代码高亮） */
export default function MarkdownView({ content, className }: Props) {
  const cls = className ? `markdown-body ${className}` : 'markdown-body';
  return (
    <div className={cls}>
      <ReactMarkdown remarkPlugins={[remarkGfm]} rehypePlugins={[rehypeHighlight]}>
        {content || ''}
      </ReactMarkdown>
    </div>
  );
}
