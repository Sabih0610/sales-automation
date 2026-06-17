import { useEffect, useState } from "react"
import { ProductCard } from "../../components/product"
import { useSequenceMembers, useRemoveSequenceMember } from "../../queries"

function touchLabel(touch, status) {
  const s = (status || "").replace(/_/g, " ")
  if (!touch || touch <= 0) {
    return s ? s.charAt(0).toUpperCase() + s.slice(1) : "Not started"
  }
  return `Touch ${touch} (${s})`
}

export default function SequenceMembersCard({ campaignFilename }) {
  const [search, setSearch] = useState("")
  const [q, setQ] = useState("")

  useEffect(() => {
    const timer = setTimeout(() => setQ(search), 250)
    return () => clearTimeout(timer)
  }, [search])

  const { data, isLoading } = useSequenceMembers(campaignFilename, { q })
  const removeMember = useRemoveSequenceMember(campaignFilename)

  const items = data?.items || []
  const total = data?.total || 0

  const handleRemove = (member) => {
    if (
      !window.confirm(
        `Remove ${member.full_name || "this lead"} from this sequence? Any scheduled email that has not sent yet will be cancelled. This affects this campaign only.`,
      )
    ) {
      return
    }
    removeMember.mutate(member.lead_id)
  }

  return (
    <ProductCard className="builder-side-panel">
      <div className="seq-members-head">
        <h2>People in this sequence</h2>
        <span className="seq-members-count">{total}</span>
      </div>

      <input
        className="seq-members-search"
        onChange={(event) => setSearch(event.target.value)}
        placeholder="Filter by name or email..."
        value={search}
      />

      {isLoading ? (
        <p className="seq-members-muted">Loading...</p>
      ) : items.length === 0 ? (
        <p className="seq-members-muted">
          {q ? "No one matches that search." : "No one is in this sequence yet."}
        </p>
      ) : (
        <div className="seq-members-list">
          {items.map((member) => (
            <div className="seq-member-row" key={member.lead_id}>
              <div className="seq-member-info">
                <strong>{member.full_name || "Unknown lead"}</strong>
                <span>{touchLabel(member.current_touch, member.status)}</span>
                {member.other_campaigns?.length > 0 && (
                  <span
                    className="seq-member-also"
                    title={`Also in: ${member.other_campaigns.join(", ")}`}
                  >
                    Also in: {member.other_campaigns.join(", ")}
                  </span>
                )}
              </div>
              <button
                aria-label="Remove from sequence"
                className="seq-member-remove"
                disabled={removeMember.isPending}
                onClick={() => handleRemove(member)}
                type="button"
              >
                <i className="ti ti-x" aria-hidden="true" />
              </button>
            </div>
          ))}
          {total > items.length && (
            <p className="seq-members-muted">
              Showing first {items.length} of {total}
              {q ? " matches" : ""}.
            </p>
          )}
        </div>
      )}
    </ProductCard>
  )
}
