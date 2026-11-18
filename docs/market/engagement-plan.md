# AMRGuard Rwanda stakeholder engagement plan

**Version:** 0.1  
**Date:** 2026-11-18  
**Purpose:** Begin institutional discovery and pilot-partner engagement in parallel with product hardening.

## Positioning

AMRGuard is an antibiotic-specific interoperability and transaction layer intended to complement existing EMRs, pharmacy systems, and supply-chain platforms. It is not a replacement EMR and does not claim live integration with e-Buzima, RMS/eLMIS, or any other institutional system until the relevant system owner has approved the interface and end-to-end tests have passed.

The first engagement objective is not to sell a national deployment. It is to validate the problem, understand the institution's architecture and governance requirements, identify a pilot site, and agree a route to a controlled evaluation.

## Priority stakeholder sequence

| Priority | Stakeholder | Engagement objective | Requested next step |
|---|---|---|---|
| 1 | RBC AMR programme / stewardship leadership | Validate alignment with national AMR priorities, indicators, and facility workflow | Technical discovery meeting and identification of clinical focal person |
| 2 | Ministry of Health digital health / e-Buzima leadership | Confirm interoperability pathway, system ownership, data governance, and procurement route | Architecture review and approved sandbox/specification pathway |
| 3 | Hospital leadership, pharmacy, stewardship committee, and ICT | Validate day-to-day workflow, staffing, integration constraints, and pilot readiness | Site assessment and non-binding letter of interest |
| 4 | Rwanda FDA | Clarify regulatory boundaries and relevant medicine traceability expectations | Regulatory classification / requirements consultation |
| 5 | Data protection and cybersecurity stakeholders | Clarify controller/processor responsibilities, registration, DPIA, security, and hosting requirements | Compliance scoping before any personal data processing |
| 6 | Development partners and AMR funders | Explore financing for a defined, measurable implementation and evaluation | Funder briefing after pilot scope and institutional interest are documented |

## Discovery questions

### AMR programme and clinical stewardship
- Which antibiotic prescribing, dispensing, and stewardship gaps are highest priority?
- Which indicators are currently collected, by whom, and at what frequency?
- What governance process approves antibiotic catalogues, AWaRe mappings, and stewardship rules?
- Which facilities could participate in a controlled evaluation?

### Digital health and interoperability
- Which EMR/HIS platforms are in use at candidate facilities?
- Is there an approved API, FHIR profile, integration engine, or national interoperability layer?
- Who owns the e-Buzima and RMS/eLMIS interface specifications and sandbox credentials?
- What patient identity and prescriber identity references may be shared, and under what legal basis?
- What are the hosting, security, data residency, and audit requirements?

### Hospital and pharmacy operations
- How are antibiotic prescriptions verified at the dispensing point today?
- How are batch numbers and expiry dates recorded and reconciled?
- What happens during internet, power, or source-system downtime?
- Which pharmacy roles may verify and dispense?
- What measurable workflow improvement would justify continued payment?

## Pilot proposal for discussion

Use the previously scoped 3-month, 2–3-facility pilot as a planning hypothesis, not as a commitment. Confirm scope with the institutional partner before finalizing the protocol or budget.

Initial design assumptions:
- 2–3 facilities, subject to partner approval.
- Approximately 40–60 healthcare professionals, subject to workflow mapping.
- Synthetic data for demonstrations and integration development.
- Real patient data only after institutional authorization, privacy/security review, appropriate ethics determination where research is involved, and signed data-processing arrangements.
- Evaluation using RE-AIM, with operational indicators agreed before baseline measurement.

Potential measures include prescription intake success, dispense reconciliation, batch traceability completeness, workflow time, stewardship review completion, SMS delivery performance, patient-reported adherence, and cost per facility. Do not treat SMS delivery as proof of dose ingestion or claim a reduction in AMR without an appropriately designed evaluation.

## Commercial hypothesis

Test, rather than assume, the buyer and budget owner:
- Facility or hospital group subscription for operational software.
- One-time implementation and integration services.
- Multi-facility or national procurement subject to the government's procurement and budget process.
- Development-partner financing for time-limited implementation and independent evaluation.

A regulator or public-health agency may be a technical stakeholder, data user, or convenor without being the purchasing customer. Confirm the actual contracting authority and budget holder during discovery.

## Engagement materials

Prepare a short institutional pack containing:
1. Two-page concept note and problem statement.
2. Product workflow diagram and current capability/limitation matrix.
3. Interoperability architecture and data-flow diagram.
4. Synthetic-data demonstration.
5. Pilot protocol outline, proposed indicators, and budget assumptions.
6. Privacy, security, clinical governance, and risk register.
7. Clear statement of what is implemented, simulated, planned, and dependent on partner approval.

## Immediate 30-day actions

1. Request an RBC AMR/stewardship discovery meeting.
2. Request a separate MoH digital health/e-Buzima architecture discussion.
3. Identify one hospital pharmacy lead and one hospital ICT lead for workflow discovery.
4. Ask each institution for its approved integration, data governance, and security requirements.
5. Revise the pilot scope and budget from stakeholder feedback.
6. Approach funders with documented institutional interest and a defined implementation package.

## Communication guardrails

- Describe the current product as an integration-ready MVP with canonical contracts, not a live government integration.
- Do not claim government endorsement, regulatory approval, clinical validation, or national deployment.
- Do not share real patient information in demos or funder materials.
- Do not send patient reminders until consent, clinical message content, approved destination resolution, and SMS delivery controls are operational.
- Seek a paid pilot or explicit post-pilot procurement pathway; avoid an open-ended unpaid deployment.
