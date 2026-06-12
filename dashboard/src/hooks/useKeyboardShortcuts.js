import { useEffect } from "react"

export function useKeyboardShortcuts(map, enabled = true) {
  useEffect(() => {
    if (!enabled) return undefined

    const handler = (event) => {
      const tag = document.activeElement?.tagName
      if (
        tag === "INPUT" ||
        tag === "TEXTAREA" ||
        event.metaKey ||
        event.ctrlKey ||
        event.altKey
      ) {
        return
      }

      const key = event.key.toLowerCase()
      const fn = map[key]

      if (fn) {
        event.preventDefault()
        fn()
      }
    }

    window.addEventListener("keydown", handler)
    return () => window.removeEventListener("keydown", handler)
  }, [map, enabled])
}