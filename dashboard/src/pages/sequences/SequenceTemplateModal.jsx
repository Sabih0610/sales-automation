import { useMemo, useState } from "react"
import { ProductBadge, ProductButton, ProductModal } from "../../components/product"
import {
  blankSequenceTemplate,
  sequenceTemplates,
  templateCategories,
} from "./templateData"
import "./templateModal.css"

export default function SequenceTemplateModal({
  onClose,
  onCreateBlank,
  onUseTemplate,
  open,
}) {
  const [selectedCategory, setSelectedCategory] = useState("marketing")
  const [selectedTemplateId, setSelectedTemplateId] = useState("enterprise-intro")

  const categoryTemplates = useMemo(
    () => sequenceTemplates.filter((template) => template.category === selectedCategory),
    [selectedCategory],
  )
  const selectedTemplate =
    categoryTemplates.find((template) => template.id === selectedTemplateId) ||
    categoryTemplates[0] ||
    blankSequenceTemplate

  const changeCategory = (categoryId) => {
    const templates = sequenceTemplates.filter((template) => template.category === categoryId)
    setSelectedCategory(categoryId)
    setSelectedTemplateId(templates[0]?.id || "")
  }

  const createBlank = () => {
    onClose?.()
    onCreateBlank?.(blankSequenceTemplate)
  }

  const useTemplate = () => {
    onClose?.()
    onUseTemplate?.(selectedTemplate)
  }

  return (
    <ProductModal
      className="sequence-template-modal"
      footer={
        <>
          <ProductButton onClick={onClose}>Cancel</ProductButton>
          <ProductButton icon="ti-check" onClick={useTemplate} variant="primary">
            Use Template
          </ProductButton>
        </>
      }
      onClose={onClose}
      open={open}
      subtitle="Choose a pre-built sequence to get started or create a blank sequence."
      title="Select Sequence Template"
    >
      <div className="sequence-template-layout">
        <aside className="sequence-template-rail">
          <button className="blank-template-button" onClick={createBlank} type="button">
            <i className="ti ti-plus" aria-hidden="true" />
            Create Blank
          </button>

          <div className="template-category-list">
            {templateCategories.map((category) => (
              <button
                className={selectedCategory === category.id ? "active" : ""}
                key={category.id}
                onClick={() => changeCategory(category.id)}
                type="button"
              >
                <span>{category.label}</span>
                <strong>{category.count}</strong>
              </button>
            ))}
          </div>
        </aside>

        <section className="template-card-list" aria-label="Sequence templates">
          {categoryTemplates.map((template) => (
            <button
              className={selectedTemplate.id === template.id ? "selected" : ""}
              key={template.id}
              onClick={() => setSelectedTemplateId(template.id)}
              type="button"
            >
              <div>
                <h3>{template.name}</h3>
                <p>{template.description}</p>
              </div>
              <div className="template-card-meta">
                <ProductBadge tone="info">{template.steps.length} steps</ProductBadge>
                {selectedTemplate.id === template.id && (
                  <span className="template-check">
                    <i className="ti ti-check" aria-hidden="true" />
                  </span>
                )}
              </div>
            </button>
          ))}
        </section>

        <section className="template-preview-panel">
          <div className="template-preview-head">
            <span className="template-preview-kicker">Preview</span>
            <h3>{selectedTemplate.name}</h3>
            <p>{selectedTemplate.previewDescription || selectedTemplate.description}</p>
          </div>

          <div className="template-chip-row">
            {(selectedTemplate.metadata || []).map((item) => (
              <span key={item}>{item}</span>
            ))}
          </div>

          <div className="template-preview-section">
            <h4>Sequence steps</h4>
            {selectedTemplate.steps.length > 0 ? (
              <ol className="template-step-list">
                {selectedTemplate.steps.map((step) => (
                  <li key={`${step.day}-${step.title}`}>
                    <span>{step.day}</span>
                    <strong>{step.title}</strong>
                    <em>{step.channel}</em>
                  </li>
                ))}
              </ol>
            ) : (
              <p className="template-empty-copy">Start blank and add each email step manually.</p>
            )}
          </div>

          <div className="template-preview-section">
            <h4>Default Exit Rules</h4>
            <div className="template-exit-rules">
              {(selectedTemplate.exitRules || []).map((rule) => (
                <div key={rule.id}>
                  <strong>{rule.title}</strong>
                  <p>{rule.description}</p>
                </div>
              ))}
            </div>
          </div>
        </section>
      </div>
    </ProductModal>
  )
}
