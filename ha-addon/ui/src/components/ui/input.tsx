"use client"

import * as React from "react"

import { cn } from "@/lib/utils"

/**
 * Plain HTML input wrapped with the canonical project styling. Created in
 * C.5 so components stop hand-rolling the same Tailwind class string for
 * every text/number field.
 */
function Input({ className, type, ...props }: React.ComponentProps<"input">) {
  return (
    <input
      type={type}
      data-slot="input"
      className={cn(
        "w-full rounded-lg border border-[var(--border)] bg-[var(--bg)] px-2.5 py-1.5 text-[13px] text-[var(--text)] outline-none focus:border-[var(--accent)] disabled:cursor-not-allowed disabled:opacity-50",
        className,
      )}
      {...props}
    />
  )
}

export { Input }
