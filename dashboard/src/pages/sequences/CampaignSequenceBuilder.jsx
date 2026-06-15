import { useMemo } from "react"
import { useLocation, useNavigate, useParams } from "react-router-dom"
import { blankSequenceTemplate, sequenceTemplates } from "./templateData"
import SequenceBuilder from "./SequenceBuilder.jsx"

const decodeFilename = (value = "") => {
  try {
    return decodeURIComponent(value)
  } catch {
    return value
  }
}

export default function CampaignSequenceBuilder() {
  const { filename: encodedFilename } = useParams()
  const { sequenceId = "" } = useParams()
  const filename = decodeFilename(encodedFilename || "")
  const navigate = useNavigate()
  const location = useLocation()

  const initialSequence = useMemo(
    () =>
      location.state?.template ||
      location.state?.sequence ||
      (location.state?.blank || sequenceId === "blank" ? blankSequenceTemplate : null) ||
      sequenceTemplates.find((template) => template.id === sequenceId) ||
      null,
    [location.state, sequenceId],
  )

  return (
    <SequenceBuilder
      campaignFilename={filename}
      initialSequence={initialSequence}
      onBack={() => navigate(`/campaigns/${encodeURIComponent(filename)}/sequences`)}
    />
  )
}
