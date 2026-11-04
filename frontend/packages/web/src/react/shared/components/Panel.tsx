import { cn } from '../utils/cn';

interface PanelProps {
  children: React.ReactNode;
  className?: string;
  title?: string;
  variant?: 'default' | 'minimal';
}

export function Panel({ children, className, title, variant = 'default' }: PanelProps) {
  if (variant === 'minimal') {
    return (
      <div className={cn('relative', className)}>
        {children}
      </div>
    );
  }

  return (
    <div
      className={cn(
        'relative glass-panel mil-brackets animate-fade-in p-5',
        className
      )}
    >
      {title && (
        <div className="flex items-center gap-2 mb-4">
          <div className="w-0.5 h-4 bg-mil-cyan" />
          <h3 className="mil-label text-[11px]">
            {title}
          </h3>
        </div>
      )}
      {children}
    </div>
  );
}
