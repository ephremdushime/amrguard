/**
 * AMRGuard Web Application Canonical Types.
 */

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
  reconciliation_rate: number;
  review_completion_rate: number;
}
