const options = [
  {
    type: "email",
    icon: "ti-mail",
    title: "Message",
    description: "Send an email message",
  },
  {
    type: "delay",
    icon: "ti-clock",
    title: "Delay",
    description: "Wait for a specific time",
  },
  {
    type: "condition",
    icon: "ti-git-branch",
    title: "Condition",
    description: "Add an if/else rule",
  },
]

export default function AddStepPopover({ onAdd, onClose }) {
  return (
    <div className="add-step-popover">
      {options.map((option) => (
        <button
          key={option.type}
          onClick={() => {
            onAdd(option.type)
            onClose?.()
          }}
          type="button"
        >
          <span>
            <i className={`ti ${option.icon}`} aria-hidden="true" />
          </span>
          <div>
            <strong>{option.title}</strong>
            <small>{option.description}</small>
          </div>
        </button>
      ))}
    </div>
  )
}
