interface DiffLine {
  type: 'same' | 'add' | 'remove';
  text: string;
}

/** 简单的按行 LCS 文本差异 */
function diffLines(oldText: string, newText: string): DiffLine[] {
  const a = (oldText || '').split('\n');
  const b = (newText || '').split('\n');
  const n = a.length;
  const m = b.length;
  const dp: number[][] = Array.from({ length: n + 1 }, () => new Array(m + 1).fill(0));
  for (let i = n - 1; i >= 0; i--) {
    for (let j = m - 1; j >= 0; j--) {
      dp[i][j] = a[i] === b[j] ? dp[i + 1][j + 1] + 1 : Math.max(dp[i + 1][j], dp[i][j + 1]);
    }
  }
  const result: DiffLine[] = [];
  let i = 0;
  let j = 0;
  while (i < n && j < m) {
    if (a[i] === b[j]) {
      result.push({ type: 'same', text: a[i] });
      i++;
      j++;
    } else if (dp[i + 1][j] >= dp[i][j + 1]) {
      result.push({ type: 'remove', text: a[i] });
      i++;
    } else {
      result.push({ type: 'add', text: b[j] });
      j++;
    }
  }
  while (i < n) result.push({ type: 'remove', text: a[i++] });
  while (j < m) result.push({ type: 'add', text: b[j++] });
  return result;
}

interface Props {
  oldText?: string;
  newText?: string;
}

/** 版本对比视图（绿色=新增，红色删除线=移除） */
export default function DiffView({ oldText, newText }: Props) {
  const lines = diffLines(oldText || '', newText || '');
  return (
    <div style={{ fontFamily: 'monospace', fontSize: 13, maxHeight: 480, overflow: 'auto' }}>
      {lines.map((line, idx) => (
        <div
          key={idx}
          className={line.type === 'add' ? 'diff-add' : line.type === 'remove' ? 'diff-remove' : ''}
          style={{ padding: '2px 8px', whiteSpace: 'pre-wrap' }}
        >
          {line.type === 'add' ? '+ ' : line.type === 'remove' ? '- ' : '  '}
          {line.text || ' '}
        </div>
      ))}
    </div>
  );
}
