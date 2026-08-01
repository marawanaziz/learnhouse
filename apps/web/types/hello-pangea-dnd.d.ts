import '@hello-pangea/dnd'

// React's Radix-aware CSSProperties accepts Radix custom properties. Add the
// same optional signature to the draggable library's style objects so the two
// structurally compatible types remain assignable under React 19.
declare module '@hello-pangea/dnd' {
  interface DraggingStyle {
    [key: `--radix-${string}`]: string | number | undefined
  }

  interface NotDraggingStyle {
    [key: `--radix-${string}`]: string | number | undefined
  }
}
