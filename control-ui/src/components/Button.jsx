/**
 * Button — Styled button with variant support.
 */

const VARIANTS = {
  primary: 'bg-[#6366f1] hover:bg-[#818cf8] text-white',
  secondary: 'bg-[#2a2a3a] hover:bg-[#3a3a4a] text-[#e0e0e8]',
  danger: 'bg-[#ef4444]/10 hover:bg-[#ef4444]/20 text-[#ef4444]',
  ghost: 'hover:bg-[#2a2a3a] text-[#8888a0] hover:text-[#e0e0e8]',
}

export default function Button({
  children,
  variant = 'primary',
  size = 'md',
  disabled = false,
  onClick,
  className = '',
  ...props
}) {
  const sizeClasses = size === 'sm' ? 'px-3 py-1.5 text-xs' : 'px-4 py-2 text-sm'

  return (
    <button
      onClick={onClick}
      disabled={disabled}
      className={`
        ${VARIANTS[variant] || VARIANTS.primary}
        ${sizeClasses}
        rounded-md font-medium transition-colors
        disabled:opacity-50 disabled:cursor-not-allowed
        ${className}
      `}
      {...props}
    >
      {children}
    </button>
  )
}
