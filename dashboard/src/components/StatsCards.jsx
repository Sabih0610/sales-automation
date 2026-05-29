const stats = [
  ["total_scraped", "Scraped", "blue"],
  ["total_enriched", "Enriched", "purple"],
  ["total_warm", "Warm", "green"],
  ["total_cold", "Cold", "gray"],
];

function StatsCards({ run }) {
  return (
    <div className="stats-grid">
      {stats.map(([key, label, tone]) => (
        <div className={`stat-card ${tone}`} key={key}>
          <strong>{run?.[key] ?? 0}</strong>
          <span>{label}</span>
        </div>
      ))}
    </div>
  );
}

export default StatsCards;
