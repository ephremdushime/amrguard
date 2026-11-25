/**
 * AMRGuard Web Application Canonical Types.
 */

export type CanonicalRole =
  | 'prescriber'
  | 'pharmacist'
  | 'pharmacy_assistant'
  | 'stewardship_officer'
  | 'facility_admin'
  | 'national_analyst'
  | 'platform_operator';

export interface OrderItem {
  id: number;
  antibiotic: string;
  code: string;
  strength: string;
  formulation: string;
  route: string;
  dose: number | string;
  dose_unit?: string;
  frequency_per_day: number | string;
  duration_days: number;
  authorized_quantity: number;
  quantity?: number;
  indication: string;
  is_prn?: boolean;
  prn_reason?: string | null;
  instructions?: string | null;
  conversion_review_required?: boolean;
}

export interface OperationalRx {
  id: number;
  code: string;
  external_id: string;
  status: string;
  prescriber: {
    id: string;
    name: string;
    facility_code?: string;
    facility_name?: string;
  };
  facility: {
    id?: number;
    code: string;
    name: string;
    district?: string;
  };
  patient_reference: string;
  created_at: string;
  expires_at?: string | null;
  allow_external_dispensing?: boolean;
  items: OrderItem[];
}

export interface Pharmacy {
  id: number;
  code: string;
  name: string;
  district: string;
  active: boolean;
  facility_id?: number | null;
  pharmacy_type?: string | null;
}

export interface OperationalBatch {
  id: number;
  pharmacy_id: number;
  pharmacy_name: string;
  pharmacy_code: string;
  antibiotic_id: number;
  antibiotic: string;
  antibiotic_code: string;
  strength: string;
  formulation: string;
  batch_number: string;
  expiry_date: string;
  quantity_available: number;
  source_reference?: string | null;
}

export interface BatchAllocation {
  batch_id: number;
  quantity: number;
}

export interface OperationalTransaction {
  transaction_id: string;
  prescription_id: number;
  prescription_code?: string;
  external_id?: string;
  pharmacy_id: number;
  batch_id: number;
  quantity: number;
  status: string;
  payment_reference?: string | null;
  created_at: string;
}

export interface StewardshipReminderRow {
  id: number;
  prescription_id: number;
  prescription_code: string;
  scheduled_at: string;
  status: string;
  consent_recorded: boolean;
  consent_reference?: string | null;
}

export interface StewardshipReviewRow {
  id: number;
  prescription_id: number;
  prescription_code: string;
  patient_reference: string;
  status: string;
  due_at: string;
  outcome?: string | null;
  reason?: string | null;
  last_transaction_id?: string | null;
}

export interface TraceEvent {
  type: string;
  quantity: number;
  reference?: string | null;
  source: string;
  details: Record<string, unknown>;
  created_at: string;
}

export interface LinkedDispense {
  transaction_id: string;
  prescription_id: number;
  prescription_code: string;
  external_id: string;
  quantity: number;
  status: string;
  created_at: string;
}

export interface TraceResponse {
  batch: {
    id: number;
    batch_number: string;
    antibiotic: string;
    antibiotic_code: string;
    strength: string;
    expiry_date: string;
    current_quantity: number;
    pharmacy: string;
    pharmacy_id: number;
    source_reference?: string | null;
  };
  events: TraceEvent[];
  linked_transactions: LinkedDispense[];
}

export interface OperationsSummary {
  prescriptions: number;
  validated: number;
  blocked: number;
  dispensing_transactions: number;
  units_dispensed: number;
  active_batches: number;
  connected_pharmacies?: number;
  prescriptions_with_dispense?: number;
  prescription_dispense_reconciliation_rate?: number;
  stewardship_reviews_total?: number;
  stewardship_reviews_completed?: number;
  stewardship_review_completion_rate?: number;
  pending_stewardship_reviews?: number;
  aware_breakdown?: WhoAwareBreakdown | null;
}

export interface PrescriptionOrder {
  external_id?: string;
  patient_reference: string;
  antibiotic_code: string;
  generic_name: string;
  strength: string;
  formulation: string;
  route: string;
  dose: number;
  frequency_per_day: number;
  duration_days: number;
  quantity: number;
  indication: string;
  expires_at: string;
  is_prn?: boolean;
}

export interface FacilityMeasure {
  facility_code: string;
  facility_name: string;
  district: string;
  prescriptions: number;
  prescriptions_with_dispense?: number;
  reconciliation_rate: number;
  stewardship_reviews?: number;
  reviews_completed?: number;
  review_completion_rate: number;
}

export interface EvaluatedMetricItem {
  metric_code: string;
  name: string;
  category: string;
  value: number | null;
  unit: string;
  target_benchmark?: string | null;
  benchmark_met: boolean;
  numerator?: number | null;
  denominator?: number | null;
}

export interface WhoAwareBreakdown {
  total_orders: number;
  total_units: number;
  access_count: number;
  watch_count: number;
  reserve_count: number;
  access_percentage: number;
  watch_percentage: number;
  reserve_percentage: number;
  meets_who_access_target: boolean;
  who_benchmark: string;
  cell_suppression_applied: boolean;
}

export interface SuppressedCount {
  value: number | null;
  display: string;
  suppressed: boolean;
}

export interface GovernedMetricsResponse {
  facility_id?: number | null;
  evaluated_at: string;
  metrics: EvaluatedMetricItem[];
  counts: Record<string, SuppressedCount | number>;
  aware_breakdown: WhoAwareBreakdown;
  data_quality_caveats: string[];
}

export interface StewardshipAlertItem {
  id: number;
  alert_id: string;
  prescription_id: number;
  prescription_item_id?: number | null;
  rule_id?: number | null;
  rule_code: string;
  severity: string;
  message: string;
  clinical_evidence?: string | null;
  status: string;
  disposition_outcome?: string | null;
  disposition_reason?: string | null;
  disposition_at?: string | null;
  created_at: string;
}

export interface WhoAwareCatalogItem {
  id: number;
  antibiotic_code: string;
  generic_name: string;
  category: string;
  atc_code?: string | null;
  version: string;
  effective_date: string;
  clinical_notes?: string | null;
}

export interface StewardshipRuleItem {
  id: number;
  rule_code: string;
  title: string;
  description: string;
  category: string;
  severity: string;
  aware_category?: string | null;
  max_duration_days?: number | null;
  requires_specialist_approval: boolean;
  version: number;
  status: string;
  clinical_rationale: string;
}

export interface AIAssistanceResponse {
  scenario: string;
  summary: string;
  clinical_rationale: string;
  recommendations: string[];
  guideline_citations: Array<Record<string, string>>;
  uncertainty_caveats: string[];
  phi_redacted: boolean;
  model_version: string;
  evaluated_at: string;
}

export interface ConsentRecordItem {
  id: number;
  patient_reference: string;
  purpose: string;
  channel: string;
  language: string;
  recipient_phone_masked: string;
  status: string;
  captured_at: string;
  facility_id?: number | null;
  source_reference?: string | null;
  evidence_reference?: string | null;
  policy_version: string;
  withdrawn_at?: string | null;
  withdrawal_reason?: string | null;
}

export interface QuarantineInboxItem {
  id: number;
  source_system: string;
  event_type: string;
  external_id: string;
  quarantine_reason: string;
  unresolved_code?: string | null;
  status: string;
  facility_id?: number | null;
  created_at: string;
  resolved_at?: string | null;
  resolved_by_user_id?: number | null;
  resolution_notes?: string | null;
}

export interface MedicineMappingItem {
  id: number;
  source_system: string;
  source_code: string;
  source_description?: string | null;
  medicine_concept_id: number;
  formulation_id?: number | null;
  approval_status: string;
  created_at: string;
}

export interface OutboxDeadLetterItem {
  id: number;
  destination_system: string;
  event_type: string;
  aggregate_type: string;
  aggregate_id: string;
  payload: string;
  status: string;
  retry_count: number;
  next_attempt_at: string;
  last_attempt_at?: string | null;
  error_message?: string | null;
  created_at: string;
  dispatched_at?: string | null;
}

export interface OutboxDispatchStats {
  processed: number;
  dispatched: number;
  retrying: number;
  dead_letter: number;
}

export interface OfflineDispenseItem {
  id: number;
  bundle_id: string;
  pharmacy_id: number;
  offline_transaction_id: string;
  status: string;
  conflict_reason?: string | null;
  created_at: string;
}

export interface OfflineReconcileResult {
  bundle_id: string;
  status: string;
  conflict_reason?: string | null;
  transaction_id?: string | null;
  reconciled_at?: string | null;
}

export interface EMRConnectorItem {
  connector_code: string;
  name: string;
  system_type: string;
}

export interface AuditEventItem {
  id: number;
  event_type: string;
  entity_type: string;
  entity_id: string;
  source_system: string;
  actor_type?: string | null;
  actor_id?: string | null;
  facility_id?: number | null;
  pharmacy_id?: number | null;
  correlation_id?: string | null;
  outcome?: string | null;
  details: Record<string, unknown>;
  created_at: string;
}

export interface ObservabilityMetrics {
  prescriptions_total: number;
  dispenses_total: number;
  active_batches: number;
  outbox_pending: number;
  outbox_dead_letter: number;
  auth_failures_total: number;
  active_pharmacies: number;
}

export interface DistrictSurveillanceRow {
  district: string;
  total_orders: number;
  total_units: number;
  total_dot: number;
  aware_counts: {
    ACCESS: number | null;
    WATCH: number | null;
    RESERVE: number | null;
    DISCOURAGED: number | null;
  };
  cell_suppression_applied: boolean;
}

export interface NationalSurveillanceExport {
  feed_type: string;
  generated_at: string;
  period: {
    start: string | null;
    end: string | null;
    district_filter: string | null;
  };
  methodology: {
    standard: string;
    minimum_cell_suppression_threshold: number;
    privacy_preserving: boolean;
  };
  national_summary: {
    total_evaluated_orders: number;
    total_units_consumed: number;
    total_estimated_dot: number;
    access_percentage: number;
    watch_percentage: number;
    reserve_percentage: number;
    meets_who_access_benchmark: boolean;
  };
  district_breakdowns: DistrictSurveillanceRow[];
  cell_suppression_applied: boolean;
}

export interface ApiMeta {
  name: string;
  version: string;
  api_version: string;
  integration_mode: string;
  demo_data: boolean;
  standards: string;
  auth_mode: string;
  cross_facility_dispensing_enabled: boolean;
}

// Admin Governance Types
export interface AdminOrganization {
  id: number;
  code: string;
  name: string;
  active: boolean;
  created_at: string;
}

export interface AdminFacility {
  id: number;
  code: string;
  name: string;
  district: string;
  organization_id?: number | null;
  active: boolean;
}

export interface AdminPharmacy {
  id: number;
  code: string;
  name: string;
  district: string;
  organization_id?: number | null;
  facility_id?: number | null;
  pharmacy_type: string;
  active: boolean;
}

export interface AdminPharmacyNetwork {
  id: number;
  code: string;
  name: string;
  active: boolean;
  created_at: string;
  facilities: Array<{
    facility_id: number;
    facility_code: string;
    facility_name: string;
    active: boolean;
  }>;
  pharmacies: Array<{
    pharmacy_id: number;
    pharmacy_code: string;
    pharmacy_name: string;
    allow_all_medicines: boolean;
    active: boolean;
    permitted_antibiotic_codes: string[];
  }>;
}

export interface AdminRole {
  id: number;
  code: string;
  description: string;
}

export interface AdminRoleScope {
  id: number;
  role_code: string;
  scope_type: string;
  organization_id?: number | null;
  facility_id?: number | null;
  pharmacy_id?: number | null;
  active: boolean;
  granted_by_user_id?: number | null;
  created_at: string;
  revoked_at?: string | null;
}

export interface AdminUser {
  id: number;
  username: string;
  display_name: string;
  email?: string | null;
  identity_issuer: string;
  active: boolean;
  failed_login_attempts: number;
  locked_until?: string | null;
  created_at: string;
  scopes: AdminRoleScope[];
}

export interface AdminServiceClientCredential {
  id: number;
  key_prefix: string;
  created_at: string;
  expires_at?: string | null;
  revoked_at?: string | null;
  active: boolean;
}

export interface AdminServiceClient {
  id: number;
  client_code: string;
  name: string;
  partner_type: string;
  active: boolean;
  created_at: string;
  scopes: Array<{
    id: number;
    scope: string;
    facility_id?: number | null;
    pharmacy_id?: number | null;
    active: boolean;
  }>;
  credentials: AdminServiceClientCredential[];
}

export interface AdminServiceKeyIssued {
  client_id: number;
  client_code: string;
  credential_id: number;
  key_prefix: string;
  api_key: string;
  expires_at?: string | null;
  revoked_previous_count: number;
  disclosure_notice: string;
}
