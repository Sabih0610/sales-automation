export default function SequenceDots({ current = 1, total = 3 }) {
  const safeTotal = Math.max(1, Number(total || 1))
  const safeCurrent = Math.max(1, Number(current || 1))

  return (
    <span className="seq-dots" title={`Email ${safeCurrent} of ${safeTotal}`}>
      {Array.from({ length: safeTotal }, (_, index) => {
        const number = index + 1
        const className =
          number < safeCurrent
            ? "dot done"
            : number === safeCurrent
              ? "dot active"
              : "dot"

        return <span className={className} key={number} />
      })}
    </span>
  )
}