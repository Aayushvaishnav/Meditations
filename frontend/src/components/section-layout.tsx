import type { ComponentProps } from "react"
import { cn } from "cn"

export type SectionWidth = "workspace" | "reading"

type SectionLayoutProps = ComponentProps<"main"> & {
  width: SectionWidth
}

export function SectionLayout({ width, children, className, ...props }: SectionLayoutProps) {
  return (
    <main {...props} className={cn("flex-1 min-h-0 min-w-0 overflow-y-auto overflow-x-hidden", className)}>
      <div className={cn(
        "@container mx-auto flex w-full min-w-0 flex-col px-4 pt-5 pb-10 sm:px-6 lg:px-8",
        width === "workspace" ? "max-w-[90rem]" : "max-w-[80ch]",
      )}>
        {children}
      </div>
    </main>
  )
}
