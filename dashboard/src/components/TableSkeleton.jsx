export default function TableSkeleton({ rows = 8, cols = 6 }) {
  return (
    <tbody>
      {Array.from({ length: rows }, (_, rowIndex) => (
        <tr key={rowIndex}>
          {Array.from({ length: cols }, (_, colIndex) => (
            <td key={colIndex}>
              <div className="skeleton-bar" />
            </td>
          ))}
        </tr>
      ))}
    </tbody>
  )
}