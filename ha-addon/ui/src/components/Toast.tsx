import { useEffect, useRef, useState } from 'react';

export type ToastType = 'info' | 'success' | 'error';

export interface ToastItem {
  id: number;
  message: string;
  type: ToastType;
}

interface ToastProps {
  items: ToastItem[];
  onRemove: (id: number) => void;
}

const DISMISS_MS: Record<ToastType, number> = {
  info: 3000,
  success: 3000,
  error: 5000,
};

function ToastEntry({ item, onRemove }: { item: ToastItem; onRemove: (id: number) => void }) {
  // Store onRemove in a ref so the timer doesn't reset when the parent re-renders
  const onRemoveRef = useRef(onRemove);
  onRemoveRef.current = onRemove;

  useEffect(() => {
    const t = setTimeout(() => onRemoveRef.current(item.id), DISMISS_MS[item.type] ?? 3000);
    return () => clearTimeout(t);
  }, [item.id, item.type]);

  return (
    <div className={`toast ${item.type}`}>
      {item.message}
    </div>
  );
}

export function ToastContainer({ items, onRemove }: ToastProps) {
  return (
    <div id="toast-container">
      {items.map(item => (
        <ToastEntry key={item.id} item={item} onRemove={onRemove} />
      ))}
    </div>
  );
}

let _nextId = 1;

export function useToast() {
  const [items, setItems] = useState<ToastItem[]>([]);
  const counterRef = useRef(_nextId);

  function addToast(message: string, type: ToastType = 'info') {
    const id = counterRef.current++;
    setItems(prev => [...prev, { id, message, type }]);
  }

  function removeToast(id: number) {
    setItems(prev => prev.filter(t => t.id !== id));
  }

  return { items, addToast, removeToast };
}
