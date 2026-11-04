import { cn } from '../utils/cn';

interface ButtonProps extends React.ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: 'primary' | 'secondary' | 'ghost';
  size?: 'sm' | 'md' | 'lg';
  children: React.ReactNode;
}

export function Button({
  variant = 'primary',
  size = 'md',
  className,
  children,
  ...props
}: ButtonProps) {
  return (
    <button
      className={cn(
        'relative inline-flex items-center justify-center font-mono font-medium transition-all duration-200 uppercase',
        'focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-mil-cyan/50',
        'disabled:pointer-events-none disabled:opacity-40',
        {
          'bg-mil-cyan/20 hover:bg-mil-cyan/30 text-mil-cyan border border-mil-cyan/40 hover:border-mil-cyan/60 shadow-glow-cyan': variant === 'primary',
          'bg-mil-panel hover:bg-mil-border/30 border border-mil-border text-mil-text hover:text-white': variant === 'secondary',
          'hover:bg-mil-border/20 text-mil-dim hover:text-mil-text': variant === 'ghost',
        },
        {
          'h-8 px-3 text-[10px] rounded-sm': size === 'sm',
          'h-10 px-5 text-xs rounded-sm': size === 'md',
          'h-12 px-7 text-sm rounded-sm': size === 'lg',
        },
        className
      )}
      {...props}
    >
      {children}
    </button>
  );
}
