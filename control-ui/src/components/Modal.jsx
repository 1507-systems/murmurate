/**
 * Modal — Overlay dialog for forms and confirmations.
 *
 * Renders on top of the page with a backdrop. Closes on backdrop click or
 * Escape key. Used for persona creation, config editing, etc.
 */

import { useEffect, useRef } from 'react'

export default function Modal({ open, onClose, title, children }) {
  const overlayRef = useRef(null)

  useEffect(() => {
    if (!open) return

    function handleEscape(e) {
      if (e.key === 'Escape') onClose()
    }

    document.addEventListener('keydown', handleEscape)
    return () => document.removeEventListener('keydown', handleEscape)
  }, [open, onClose])

  if (!open) return null

  return (
    <div
      ref={overlayRef}
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm"
      onClick={(e) => {
        if (e.target === overlayRef.current) onClose()
      }}
    >
      <div className="bg-[#1a1a24] border border-[#2a2a3a] rounded-lg w-full max-w-lg mx-4 shadow-2xl">
        <div className="flex items-center justify-between px-5 py-3.5 border-b border-[#2a2a3a]">
          <h2 className="text-sm font-medium text-white">{title}</h2>
          <button
            onClick={onClose}
            className="text-[#8888a0] hover:text-white transition-colors text-lg leading-none"
            aria-label="Close"
          >
            &times;
          </button>
        </div>
        <div className="p-5">{children}</div>
      </div>
    </div>
  )
}
