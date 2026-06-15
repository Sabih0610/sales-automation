const defaultEmailBody = [
  "Write a concise first-touch email for SAP migration modernization.",
  "Personalize by the lead's role, seniority, company context, and available KB.",
  "Connect their likely responsibility to migration risk reduction, integration reliability, SAP-to-Azure modernization, and Microsoft Fabric analytics where relevant.",
  "Do not invent facts.",
  "Keep under 130 words.",
  "Use a soft 20-minute call CTA.",
  "Do not include a signature.",
].join("\n")

export const defaultBuilderRules = {
  mode: "manual",
  timezone: "Asia/Karachi",
  stop_on_reply: true,
  stop_on_bounce: true,
  stop_on_unsubscribe: true,
  skip_no_email: true,
  skip_weekends: false,
  send_window_start: "09:00",
  send_window_end: "17:00",
  daily_send_limit: 50,
  delay_between_sends_seconds: 60,
  require_approval_for_touch1: true,
  require_approval_for_followups: true,
}

const uid = (prefix) => `${prefix}-${Date.now()}-${Math.random().toString(16).slice(2)}`

export function createEmailStep(number = 1, overrides = {}) {
  const dayLabel = number === 1 ? "Immediate" : `Day ${number === 2 ? 3 : 7}`
  return {
    id: uid(`email-${number}`),
    type: "email",
    number,
    timingLabel: dayLabel,
    title: `Email ${number}`,
    subject: "SAP migration modernization angle",
    body: defaultEmailBody,
    ...overrides,
  }
}

export function createDelayStep(waitDays = 3, overrides = {}) {
  return {
    id: uid("delay"),
    type: "delay",
    waitDays,
    ...overrides,
  }
}

export function createConditionStep(overrides = {}) {
  return {
    id: uid("condition"),
    type: "condition",
    conditions: ["Replied", "Bounced", "Unsubscribed"],
    ...overrides,
  }
}

export function defaultBuilderSteps() {
  return [
    createEmailStep(1, {
      id: "email-1",
      timingLabel: "Immediate",
      subject: "First-touch SAP migration modernization angle",
      body: [
        "Write a concise first-touch email for SAP migration modernization.",
        "Personalize by the lead's title, seniority, company, and available KB.",
        "Connect their likely responsibility to migration risk reduction, integration reliability, SAP-to-Azure modernization, and Microsoft Fabric analytics where relevant.",
        "Do not invent facts.",
        "Keep under 130 words.",
        "Use a soft 20-minute call CTA.",
        "Do not include a signature.",
      ].join("\n"),
    }),
    createDelayStep(3, { id: "delay-1" }),
    createEmailStep(2, {
      id: "email-2",
      timingLabel: "Day 3",
      subject: "What usually slows SAP migration programs down?",
      body: [
        "Hi {{first_name}},",
        "",
        "A common challenge we see is aligning data, integrations, and business continuity before migration work accelerates.",
      ].join("\n"),
    }),
    createConditionStep({ id: "condition-1" }),
    createEmailStep(3, {
      id: "email-3",
      timingLabel: "Day 7",
      subject: "A useful SAP migration planning resource",
      body: [
        "Hi {{first_name}},",
        "",
        "I can share a concise migration planning checklist that helps teams pressure-test scope, risk, and readiness before committing resources.",
      ].join("\n"),
    }),
  ]
}

export function templateToBuilderState(template) {
  if (!template || template.id === "blank-sequence") {
    return {
      name: "Blank Sequence",
      status: "Draft",
      steps: [createEmailStep(1, { id: "email-blank-1", timingLabel: "Immediate" })],
    }
  }

  const sourceSteps = Array.isArray(template.steps) && template.steps.length > 0
    ? template.steps
    : []

  if (!sourceSteps.length) {
    return {
      name: template.name || "Enterprise SAP Intro Sequence",
      status: "Draft",
      steps: defaultBuilderSteps(),
    }
  }

  const steps = []
  sourceSteps.forEach((step, index) => {
    if (index === 1) {
      const previousDay = Number(String(sourceSteps[index - 1].day || "").replace(/\D/g, "")) || 1
      const currentDay = Number(String(step.day || "").replace(/\D/g, "")) || previousDay + 3
      steps.push(createDelayStep(Math.max(1, currentDay - previousDay), {
        id: `delay-template-${index}`,
      }))
    }
    if (index === 2) {
      steps.push(createConditionStep({ id: "condition-template-1" }))
    }
    steps.push(createEmailStep(index + 1, {
      id: `email-template-${index + 1}`,
      timingLabel: index === 0 ? "Immediate" : step.day || `Day ${index * 3}`,
      title: `Email ${index + 1}`,
      subject: `${step.title} angle`,
      body: [
        `Write this step using the "${step.title}" angle.`,
        "Personalize by the lead's title, seniority, company context, and available KB.",
        "Connect the message to the campaign goal without inventing facts.",
        "Keep it concise and do not include a signature.",
      ].join("\n"),
    }))
  })

  return {
    name: template.name || "Enterprise SAP Intro Sequence",
    status: "Draft",
    steps,
  }
}

export function backendSequenceToBuilderState(sequenceData, fallbackName = "Enterprise SAP Intro Sequence") {
  const backendSteps = sequenceData?.steps || sequenceData?.touches || []
  if (!backendSteps.length) {
    return {
      name: sequenceData?.sequence_name || sequenceData?.name || fallbackName,
      status: "Draft",
      steps: defaultBuilderSteps(),
      rules: defaultBuilderRules,
    }
  }

  const steps = []
  backendSteps.forEach((step, index) => {
    const delayValue = Number(step.delay_value ?? step.delay_days ?? 0) || 0
    if (index > 0) steps.push(createDelayStep(delayValue || 3, { id: `delay-backend-${index}` }))
    if (index === 2) steps.push(createConditionStep({ id: "condition-backend-1" }))
    steps.push(createEmailStep(index + 1, {
      id: `email-backend-${index + 1}`,
      timingLabel: index === 0 ? "Immediate" : `Day ${delayValue || index * 3}`,
      subject: step.subject_template || `Email ${index + 1}`,
      body: step.email_body_template || defaultEmailBody,
      title: `Email ${index + 1}`,
    }))
  })

  const backendRules = { ...defaultBuilderRules, ...(sequenceData.rules || {}), skip_weekends: false }

  return {
    name: sequenceData?.sequence_name || sequenceData?.name || fallbackName,
    status: backendRules.mode === "auto" ? "Active" : "Draft",
    steps,
    rules: backendRules,
  }
}

export function builderStepsToSequencePayload(builderSteps, rules = defaultBuilderRules) {
  const emailSteps = []
  let pendingDelay = 0

  builderSteps.forEach((step) => {
    if (step.type === "delay") {
      pendingDelay = Number(step.waitDays || 0) || 0
      return
    }

    if (step.type !== "email") return

    const touchNumber = emailSteps.length + 1
    emailSteps.push({
      touch_number: touchNumber,
      number: touchNumber,
      touch_name: `Email ${touchNumber}`,
      name: `Email ${touchNumber}`,
      is_active: true,
      delay_days: touchNumber === 1 ? 0 : pendingDelay,
      delay_value: touchNumber === 1 ? 0 : pendingDelay,
      delay_unit: "days",
      delay_type: "calendar_days",
      send_time_mode: "same_as_previous",
      fixed_send_time: "",
      subject_template: step.subject || "",
      email_body_template: step.body || "",
    })
    pendingDelay = 0
  })

  return {
    steps: emailSteps,
    touches: emailSteps,
    rules: {
      ...defaultBuilderRules,
      ...rules,
      skip_weekends: false,
    },
  }
}

export function createStepByType(type, nextEmailNumber = 1) {
  if (type === "delay") return createDelayStep(3)
  if (type === "condition") return createConditionStep()
  return createEmailStep(nextEmailNumber, {
    title: `Email ${nextEmailNumber}`,
    timingLabel: nextEmailNumber === 1 ? "Immediate" : `Day ${nextEmailNumber * 3}`,
  })
}
