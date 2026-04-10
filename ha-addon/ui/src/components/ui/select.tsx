"use client"

import * as React from "react"

import { cn } from "@/lib/utils"

/**
 * Native HTML <select> with the canonical project styling. Created in C.5
 * so components stop hand-rolling the same Tailwind class string. Uses the
 * native control intentionally — no popover, no Base UI primitive — because
 * the existing usages are short option lists that benefit from native
 * keyboard, screen reader, and mobile picker behavior.
 */
function Select({ className, children, ...props }: React.ComponentProps<"select">) {
  return (
    <select
      data-slot="select"
      className={cn(
        "w-full rounded-lg border border-[var(--border)] bg-[var(--bg)] px-2.5 py-1.5 text-[13px] text-[var(--text)] outline-none focus:border-[var(--accent)] cursor-pointer disabled:cursor-not-allowed disabled:opacity-50",
        className,
      )}
      {...props}
    >
      {children}
    </select>
  )
}

export { Select }
