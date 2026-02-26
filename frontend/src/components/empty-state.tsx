export function EmptyState({
  title,
  description,
  icon,
  action,
}: {
  title: string;
  description: string;
  icon?: React.ReactNode;
  action?: React.ReactNode;
}) {
  return (
    <div className="flex flex-col items-center justify-center py-20 px-6 text-center animate-fade-in">
      <div className="w-16 h-16 rounded-2xl bg-surface-2 border border-border-1 flex items-center justify-center mb-6">
        {icon ?? (
          <svg
            width="24"
            height="24"
            viewBox="0 0 24 24"
            fill="none"
            stroke="currentColor"
            strokeWidth="1.5"
            className="text-text-3"
          >
            <rect x="3" y="3" width="18" height="18" rx="3" />
            <path d="M12 8v8M8 12h8" strokeLinecap="round" />
          </svg>
        )}
      </div>
      <h3 className="text-lg font-medium text-text-1 mb-2">{title}</h3>
      <p className="text-sm text-text-2 max-w-sm mb-8 leading-relaxed">{description}</p>
      {action}
    </div>
  );
}
