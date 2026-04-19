import * as React from "react"
import { Dialog as DialogPrimitive } from "@base-ui/react/dialog"

import { cn } from "@/lib/utils"

// SP.4: right-anchored slide-in panel built on the Dialog primitive.
// Named "Sheet" to match shadcn's nomenclature; when we graduate to a
// full-page /settings route later, we'll swap the consumer's Sheet for
// that route — the settings-content component itself doesn't change.

function Sheet({ ...props }: DialogPrimitive.Root.Props) {
  return <DialogPrimitive.Root data-slot="sheet" {...props} />
}

function SheetTrigger({ ...props }: DialogPrimitive.Trigger.Props) {
  return <DialogPrimitive.Trigger data-slot="sheet-trigger" {...props} />
}

function SheetPortal({ ...props }: DialogPrimitive.Portal.Props) {
  return <DialogPrimitive.Portal data-slot="sheet-portal" {...props} />
}

function SheetClose({ ...props }: DialogPrimitive.Close.Props) {
  return <DialogPrimitive.Close data-slot="sheet-close" {...props} />
}

function SheetOverlay({
  className,
  ...props
}: DialogPrimitive.Backdrop.Props) {
  return (
    <DialogPrimitive.Backdrop
      data-slot="sheet-overlay"
      // #78 / UX_REVIEW §3.2: bumped from /50 to /65 to match
       // Dialog's overlay. Against our dark theme, /50 was barely
       // perceptible — the review correctly flagged that the
       // underlying tab stayed visible and its 1 Hz SWR badges kept
       // flickering in peripheral vision. /65 matches what Restore
       // confirmation already uses, so the "drawer is modal" read is
       // consistent across Sheet and Dialog.
      className={cn("fixed inset-0 z-50 bg-black/65", className)}
      {...props}
    />
  )
}

interface SheetContentProps extends DialogPrimitive.Popup.Props {
  showCloseButton?: boolean
}

function SheetContent({
  className,
  children,
  showCloseButton = true,
  ...props
}: SheetContentProps) {
  return (
    <SheetPortal>
      <SheetOverlay />
      <DialogPrimitive.Popup
        data-slot="sheet-content"
        className={cn(
          "fixed inset-y-0 right-0 z-50 flex h-full w-[min(440px,100vw)] flex-col border-l border-[var(--border)] bg-[var(--surface)] text-[var(--text)] shadow-xl outline-none",
          className
        )}
        {...props}
      >
        {children}
        {showCloseButton && (
          <DialogPrimitive.Close
            data-slot="sheet-close"
            aria-label="Close settings"
            className="absolute top-3 right-3 rounded-md p-1 text-[var(--text-muted)] hover:bg-[var(--border)] hover:text-[var(--text)] cursor-pointer"
          >
            &#x2715;
          </DialogPrimitive.Close>
        )}
      </DialogPrimitive.Popup>
    </SheetPortal>
  )
}

function SheetHeader({ className, ...props }: React.ComponentProps<"div">) {
  return (
    <div
      data-slot="sheet-header"
      className={cn(
        "flex items-center gap-2 border-b border-[var(--border)] bg-[var(--surface2)] px-4 py-3 pr-12",
        className
      )}
      {...props}
    />
  )
}

function SheetTitle({
  className,
  ...props
}: DialogPrimitive.Title.Props) {
  return (
    <DialogPrimitive.Title
      data-slot="sheet-title"
      className={cn("text-sm font-semibold text-[var(--text)]", className)}
      {...props}
    />
  )
}

function SheetDescription({
  className,
  ...props
}: DialogPrimitive.Description.Props) {
  return (
    <DialogPrimitive.Description
      data-slot="sheet-description"
      className={cn("text-xs text-[var(--text-muted)]", className)}
      {...props}
    />
  )
}

function SheetBody({ className, ...props }: React.ComponentProps<"div">) {
  return (
    <div
      data-slot="sheet-body"
      className={cn("flex-1 overflow-y-auto px-4 py-3", className)}
      {...props}
    />
  )
}

export {
  Sheet,
  SheetTrigger,
  SheetClose,
  SheetContent,
  SheetHeader,
  SheetTitle,
  SheetDescription,
  SheetBody,
}
