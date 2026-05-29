import sys

sys.path.insert(0, ".")

from src.agents.enrichment_agent import EnrichmentAgent
from src.agents.export_agent import ExportAgent
from src.agents.segment_agent import SegmentAgent
from src.models import Lead, PipelineRun


run = PipelineRun(filters={"test": True})

leads = [
    Lead(
        first_name="Ali",
        last_name="Khan",
        title="CTO",
        company="Systems Ltd",
        location="Karachi",
    ),
    Lead(
        first_name="Sarah",
        last_name="Connor",
        title="Head of Data",
        company="Microsoft",
        location="Seattle",
    ),
    Lead(
        first_name="Usman",
        last_name="Ahmed",
        title="VP Engineering",
        company="Netsol Technologies",
        location="Lahore",
    ),
    Lead(
        first_name="James",
        last_name="Wilson",
        title="CIO",
        company="IBM",
        location="New York",
    ),
    Lead(
        first_name="Fatima",
        last_name="Sheikh",
        title="Data Analytics VP",
        company="Engro Corp",
        location="Karachi",
    ),
]

print(f"Created {len(leads)} mock leads")

enricher = EnrichmentAgent(run, leads)
enricher.on_event(lambda e: print(f"  EVENT: {e.event_type.value} | {e.payload}"))
leads = enricher.execute()
print(f"Enriched. Emails found: {sum(1 for lead in leads if lead.email)}/{len(leads)}")

segmenter = SegmentAgent(run, leads)
leads = segmenter.execute()
print(
    f"Segmented: warm={run.total_warm} cold={run.total_cold} "
    f"no_email={run.total_no_email}"
)

exporter = ExportAgent(run, leads)
files = exporter.execute()
print(f"Exported to: {files}")
