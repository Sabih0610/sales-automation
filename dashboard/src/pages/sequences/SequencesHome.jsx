import { useMemo, useState } from "react"
import { useLocation, useNavigate } from "react-router-dom"
import {
  ProductButton,
  ProductIconBox,
  ProductShell,
} from "../../components/product"
import SequenceCard from "./SequenceCard.jsx"
import SequenceBuilder from "./SequenceBuilder.jsx"
import SequenceTemplateModal from "./SequenceTemplateModal.jsx"
import { blankSequenceTemplate } from "./templateData"
import "./sequences.css"

const mockSequences = [
  {
    id: "enterprise-sap-intro",
    name: "Enterprise SAP Intro Sequence",
    description: "Introduce RC Sales and qualify interest in SAP migration services for enterprises.",
    icon: "ti-send",
    iconTone: "primary",
    favorite: true,
    status: "Active",
    lastEdited: "Jun 13, 2026",
    editedBy: "Edited by Aamir",
    archived: false,
    metrics: {
      enrolled: 0,
      active: 0,
      scheduled: 0,
      sent: 0,
      replyRate: "0%",
    },
  },
  {
    id: "follow-up-nurture",
    name: "Follow-up Nurture Sequence",
    description: "Nurture leads with case studies, insights, and ROI-focused content.",
    icon: "ti-mail",
    iconTone: "blue",
    favorite: false,
    status: "Active",
    lastEdited: "Jun 12, 2026",
    editedBy: "Edited by Sales Team",
    archived: false,
    metrics: {
      enrolled: 0,
      active: 0,
      scheduled: 0,
      sent: 0,
      replyRate: "0%",
    },
  },
  {
    id: "re-engagement",
    name: "Re-engagement Sequence",
    description: "Re-engage cold leads with a value-driven check-in and relevant resources.",
    icon: "ti-refresh",
    iconTone: "warning",
    favorite: false,
    status: "Paused",
    lastEdited: "Jun 10, 2026",
    editedBy: "Edited by Royal Cyber",
    archived: false,
    metrics: {
      enrolled: 0,
      active: 0,
      scheduled: 0,
      sent: 0,
      replyRate: "0%",
    },
  },
]

const sortOptions = [
  ["lastEdited", "Last edited"],
  ["enrolled", "Enrolled"],
  ["replyRate", "Reply rate"],
]

export default function SequencesHome() {
  const navigate = useNavigate()
  const location = useLocation()
  const [activeTab, setActiveTab] = useState("active")
  const [search, setSearch] = useState("")
  const [sortBy, setSortBy] = useState("lastEdited")
  const [showTemplateModal, setShowTemplateModal] = useState(false)

  const sequenceId = location.pathname.replace(/^\/sequences\/?/, "").split("/")[0]
  const selectedSequence =
    location.state?.template ||
    location.state?.sequence ||
    (location.state?.blank ? blankSequenceTemplate : null) ||
    mockSequences.find((sequence) => sequence.id === sequenceId)

  const filteredSequences = useMemo(() => {
    const normalizedSearch = search.trim().toLowerCase()
    const activeRows = mockSequences.filter((sequence) =>
      activeTab === "archived" ? sequence.archived : !sequence.archived,
    )
    const searchedRows = activeRows.filter((sequence) => {
      if (!normalizedSearch) return true
      return `${sequence.name} ${sequence.description}`.toLowerCase().includes(normalizedSearch)
    })

    return [...searchedRows].sort((a, b) => {
      if (sortBy === "enrolled") return b.metrics.enrolled - a.metrics.enrolled
      if (sortBy === "replyRate") return parseFloat(b.metrics.replyRate) - parseFloat(a.metrics.replyRate)
      return new Date(b.lastEdited) - new Date(a.lastEdited)
    })
  }, [activeTab, search, sortBy])

  const openNewSequence = () => setShowTemplateModal(true)
  const openBlankBuilder = (template = blankSequenceTemplate) => {
    setShowTemplateModal(false)
    navigate("/sequences/builder", {
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
  const openTemplateBuilder = (template) => {
    setShowTemplateModal(false)
    navigate(`/sequences/builder-${template.id}`, {
      state: {
        template: {
          ...template,
          icon: "ti-template",
          iconTone: "blue",
        },
      },
    })
  }

  if (sequenceId) {
    return (
      <>
        <SequenceBuilder
          initialSequence={selectedSequence}
          onNewSequence={openNewSequence}
        />
        <SequenceTemplateModal
          onClose={() => setShowTemplateModal(false)}
          onCreateBlank={openBlankBuilder}
          onUseTemplate={openTemplateBuilder}
          open={showTemplateModal}
        />
      </>
    )
  }

  return (
    <ProductShell
      activeItem="Sequences"
      campaignName="SAP Migration for Enterprise"
      onSearchChange={setSearch}
      searchValue={search}
    >
      <section className="sequences-content-inner">
        <div className="sequences-title-row">
          <div>
            <h1>Email Sequences</h1>
            <p>Create and manage email sequences for your SAP Migration for Enterprise campaign.</p>
          </div>
          <ProductButton icon="ti-plus" onClick={openNewSequence} variant="primary">
            New Sequence
          </ProductButton>
        </div>

        <div className="sequences-toolbar">
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
              onOpen={(item) => navigate(`/sequences/${item.id}`, { state: { sequence: item } })}
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
                ? "Archived sequences will appear here when older campaigns are paused."
                : "Try a different search or create a new sequence for this campaign."}
            </p>
            <ProductButton icon="ti-plus" onClick={openNewSequence} variant="primary">
              New Sequence
            </ProductButton>
          </div>
        )}

        <section className="sequences-create-panel">
          <div className="sequences-create-visual">
            <ProductIconBox icon="ti-send" tone="primary" />
          </div>
          <div>
            <h2>Create a new sequence</h2>
            <p>Build automated email journeys that engage leads and drive more replies.</p>
          </div>
          <ProductButton icon="ti-plus" onClick={openNewSequence} variant="primary">
            New Sequence
          </ProductButton>
        </section>
      </section>

      <SequenceTemplateModal
        onClose={() => setShowTemplateModal(false)}
        onCreateBlank={openBlankBuilder}
        onUseTemplate={openTemplateBuilder}
        open={showTemplateModal}
      />
    </ProductShell>
  )
}
