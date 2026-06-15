import { useMemo, useState } from "react"
import { useNavigate, useParams } from "react-router-dom"
import { ProductButton } from "../../components/product"
import { useCampaignOverview, useCampaignReport, useCampaigns } from "../../queries"
import SequenceCard from "./SequenceCard.jsx"
import SequenceTemplateModal from "./SequenceTemplateModal.jsx"
import { blankSequenceTemplate } from "./templateData"
import "./sequences.css"

const sortOptions = [
  ["lastEdited", "Last edited"],
  ["enrolled", "Enrolled"],
  ["replyRate", "Reply rate"],
]

const decodeFilename = (value = "") => {
  try {
    return decodeURIComponent(value)
  } catch {
    return value
  }
}

export default function CampaignSequencesHome() {
  const { filename: encodedFilename } = useParams()
  const filename = decodeFilename(encodedFilename || "")
  const navigate = useNavigate()

  const [activeTab, setActiveTab] = useState("active")
  const [search, setSearch] = useState("")
  const [sortBy, setSortBy] = useState("lastEdited")
  const [showTemplateModal, setShowTemplateModal] = useState(false)
  const [archivedIds, setArchivedIds] = useState(() => new Set())

  const routeBase = `/campaigns/${encodeURIComponent(filename)}/sequences`

  const { data: campaigns = [] } = useCampaigns()
  const { data: overview = {} } = useCampaignOverview(filename)
  const { data: report = {} } = useCampaignReport(filename, 30)

  const campaign = campaigns.find((item) => item.filename === filename) || null
  const totals = report?.totals || {}
  const statusBreakdown = report?.status_breakdown || {}

  const liveSequence = {
    id: "campaign-sequence",
    name: `${campaign?.name || "Campaign"} Sequence`,
    description: "Live sequence metrics for this campaign based on drafts, sends, and replies.",
    icon: "ti-send",
    iconTone: "primary",
    favorite: true,
    status: Number(overview.active_sequence_steps || 0) > 0 ? "Active" : "Draft",
    lastEdited: "Live data",
    editedBy: "Synced from campaign activity",
    archived: archivedIds.has("campaign-sequence"),
    metrics: {
      enrolled: Number(overview.total_leads || 0),
      active: Number(statusBreakdown.active || 0),
      scheduled: Number(totals.scheduled || 0),
      sent: Number(totals.sent || overview.emails_sent || 0),
      replyRate: `${Number(totals.reply_rate || 0)}%`,
    },
  }

  const sequences = [liveSequence]

  const filteredSequences = useMemo(() => {
    const normalizedSearch = search.trim().toLowerCase()

    const activeRows = sequences.filter((sequence) =>
      activeTab === "archived" ? sequence.archived : !sequence.archived,
    )

    const searchedRows = activeRows.filter((sequence) => {
      if (!normalizedSearch) return true

      return `${sequence.name} ${sequence.description}`
        .toLowerCase()
        .includes(normalizedSearch)
    })

    return [...searchedRows].sort((a, b) => {
      if (sortBy === "enrolled") {
        return b.metrics.enrolled - a.metrics.enrolled
      }

      if (sortBy === "replyRate") {
        return parseFloat(b.metrics.replyRate) - parseFloat(a.metrics.replyRate)
      }

      return new Date(b.lastEdited) - new Date(a.lastEdited)
    })
  }, [activeTab, search, sortBy, sequences])

  const openBlankBuilder = (template = blankSequenceTemplate) => {
    setShowTemplateModal(false)

    navigate(`${routeBase}/blank/builder`, {
      state: {
        blank: true,
        template: {
          ...template,
          icon: "ti-plus",
          iconTone: "primary",
          name: "Blank Sequence",
        },
      },
    })
  }

  const duplicateSequence = (sequence) => {
    navigate(`${routeBase}/${sequence.id}-copy/builder`, {
      state: {
        sequence: {
          ...sequence,
          id: `${sequence.id}-copy`,
          name: `Copy of ${sequence.name}`,
          status: "Draft",
        },
      },
    })
  }

  const toggleArchiveSequence = (sequence) => {
    setArchivedIds((current) => {
      const next = new Set(current)

      if (next.has(sequence.id)) {
        next.delete(sequence.id)
      } else {
        next.add(sequence.id)
      }

      return next
    })
  }

  const openTemplateBuilder = (template) => {
    setShowTemplateModal(false)

    navigate(`${routeBase}/${template.id}/builder`, {
      state: {
        template: {
          ...template,
          icon: "ti-template",
          iconTone: "blue",
        },
      },
    })
  }

  return (
    <>
      <section className="sequences-content-inner">
        <div className="sequences-title-row">
          <div>
            <h1>Email Sequences</h1>
            <p>Create and manage email sequences for this campaign.</p>
          </div>

          <ProductButton
            icon="ti-plus"
            onClick={() => setShowTemplateModal(true)}
            variant="primary"
          >
            New Sequence
          </ProductButton>
        </div>

        <div className="sequences-toolbar">
          <input
            className="search-input"
            onChange={(event) => setSearch(event.target.value)}
            placeholder="Search sequences, steps, or contacts..."
            value={search}
          />

          <div className="sequences-tabs" role="tablist" aria-label="Sequence status">
            {[
              ["active", "Active"],
              ["archived", "Archived"],
            ].map(([value, label]) => (
              <button
                aria-selected={activeTab === value}
                className={activeTab === value ? "active" : ""}
                key={value}
                onClick={() => setActiveTab(value)}
                role="tab"
                type="button"
              >
                {label}
              </button>
            ))}
          </div>

          <label className="sequences-sort">
            <span>Sort</span>

            <select value={sortBy} onChange={(event) => setSortBy(event.target.value)}>
              {sortOptions.map(([value, label]) => (
                <option key={value} value={value}>
                  {label}
                </option>
              ))}
            </select>
          </label>
        </div>

        <div className="sequence-list" aria-live="polite">
          {filteredSequences.map((sequence) => (
            <SequenceCard
              key={sequence.id}
              onArchive={toggleArchiveSequence}
              onDuplicate={duplicateSequence}
              onOpen={(item) =>
                navigate(`${routeBase}/${item.id}/builder`, {
                  state: { sequence: item },
                })
              }
              sequence={sequence}
            />
          ))}
        </div>

        {filteredSequences.length === 0 && (
          <div className="sequences-empty-state">
            <div className="sequences-empty-icon">
              <i className="ti ti-send" aria-hidden="true" />
            </div>

            <h2>{activeTab === "archived" ? "No archived sequences" : "No sequences found"}</h2>

            <p>
              {activeTab === "archived"
                ? "Archived sequences will appear here when older campaign sequences are paused."
                : "Try a different search or create a new sequence for this campaign."}
            </p>

            <ProductButton
              icon="ti-plus"
              onClick={() => setShowTemplateModal(true)}
              variant="primary"
            >
              New Sequence
            </ProductButton>
          </div>
        )}
      </section>

      <SequenceTemplateModal
        onClose={() => setShowTemplateModal(false)}
        onCreateBlank={openBlankBuilder}
        onUseTemplate={openTemplateBuilder}
        open={showTemplateModal}
      />
    </>
  )
}