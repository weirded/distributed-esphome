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

// Auto-dismiss timer per toast
function ToastEntry({ item, onRemove }: { item: ToastItem; onRemove: (id: number) => void }) {
  useEffect(() => {
    const t = setTimeout(() => onRemove(item.id), 4000);
    return () => clearTimeout(t);
  }, [item.id, onRemove]);

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
