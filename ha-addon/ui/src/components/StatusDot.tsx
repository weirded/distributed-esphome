type Status = 'online' | 'offline' | 'checking' | 'paused' | 'upgrading' | 'archived';

export function StatusDot({ status, label }: { status: Status; label?: string }) {
  const cls = status === 'checking' ? 'dot dot-checking'
    : status === 'upgrading' ? 'dot dot-upgrading'
    : status === 'online' ? 'dot dot-online'
    : status === 'archived' ? 'dot dot-archived'
    : 'dot dot-offline';
  const text = label ?? (
    status === 'checking' ? 'Checking...'
    : status === 'upgrading' ? 'Upgrading...'
    : status === 'online' ? 'Online'
    : status === 'paused' ? 'Paused'
    : status === 'archived' ? 'Archived'
    : 'Offline'
  );
  const style = (status === 'paused' || status === 'archived')
    ? { color: 'var(--text-muted)' }
    : undefined;
  return <><span className={cls}></span><span style={style}>{text}</span></>;
}
